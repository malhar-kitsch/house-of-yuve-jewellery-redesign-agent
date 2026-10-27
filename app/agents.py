"""The two agents: a designer that studies the photo and plans redesigns,
and a renderer that draws each redesign using matching before/after examples."""
import asyncio, base64, io, json, os, shutil
from functools import partial
from pathlib import Path

import httpx
from google import genai
from google.genai import types
from PIL import Image

from app import pricing, usage

from app.paths import DATA, KEPT
TEXT_MODEL = os.getenv("TEXT_MODEL", "gemini-flash-latest")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gemini-3.1-flash-image")
OPENROUTER = "https://openrouter.ai/api/v1"
EXAMPLES_PER_DESIGN = 2

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def load_catalogue():
    pairs = json.loads((DATA / "dataset.json").read_text())["pairs"]
    out = {}
    for p in pairs:
        if p["confidence"].startswith("low") or not p["files"].get("before") or not p["files"].get("after"):
            continue
        folder = DATA / p["folder"]
        out[p["id"]] = {
            "transformation": p["transformation"],
            "style": "traditional",
            "before": folder / p["files"]["before"][0]["file"],
            "after": folder / p["files"]["after"][0]["file"],
        }
    # Designs the team marked "keep" in the app become examples too.
    for meta in sorted({*(DATA / "kept").glob("*/meta.json"), *KEPT.glob("*/meta.json")}):
        m = json.loads(meta.read_text())
        out[m["id"]] = {"transformation": m["transformation"], "style": m["style"],
                        "before": meta.parent / "before_1.jpg", "after": meta.parent / "after_1.png"}
    return out


def keep(run_dir: Path, index: int, kept: bool):
    """Save (or remove) one generated design as a new before/after example."""
    pid = f"kept_{run_dir.name}_{index}"
    folder = KEPT / pid
    if not kept:
        shutil.rmtree(folder, ignore_errors=True)
    else:
        d = json.loads((run_dir / "plan.json").read_text())["designs"][index - 1]
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy(run_dir / "original.jpg", folder / "before_1.jpg")
        shutil.copy(run_dir / d["image"], folder / "after_1.png")
        style = json.loads((run_dir / "plan.json").read_text()).get("style", "modern")
        (folder / "meta.json").write_text(json.dumps(
            {"id": pid, "style": style, "transformation": f"{d['title']}: {d['idea']}"}, indent=2))
    CATALOGUE.clear()
    CATALOGUE.update(load_catalogue())
    return pid


CATALOGUE = load_catalogue()

DESIGNER_PROMPT = """You are a senior Indian jewellery designer at a boutique that upcycles old gold jewellery.
A customer has uploaded a photo of an old piece. We never melt the gold — we reuse the existing elements
(pendants, motifs, chains, bangles, earrings) and rework them: split, re-string, add pearls/beads/stones/enamel,
convert one type of piece into another (e.g. heavy necklace -> bangle, earrings -> pendant), or deconstruct
into lighter, modern, elegant pieces.

Style direction: {style_brief}

Occasion: {occasion}

Customer's wish (may be empty): {wish}

Gold weight: {grams}, {karat}K

What they want to make: {pieces}

GOAL — {goal}

Today's {karat}K gold rate: about ₹{rate:,.0f} per gram.

GOLD BUDGET — use ALL of the customer's gold (plus any new gold the goal allows). If the main new piece needs less gold than the old piece
(e.g. a 20 g necklace becoming 4 g earrings), turn the leftover into matching companion pieces — earrings,
ring, pendant, maang tikka, bracelet, a second lighter chain — or make the main piece fuller, so the split
adds up to roughly the total. Never leave gold unaccounted for.

ADD ELEMENTS — like our reference projects, every design must add at least 2 new materials to make it richer
and more elegant: pearls / rice pearls, gemstone beads (emerald, ruby, coral, onyx), kundan, polki,
lab-grown diamonds, coloured stones, enamel / meenakari, ghungroo drops. Choose ones that suit the style.

Reference transformations we have photos of (id [style]: what happened). Prefer references whose style
matches the style direction; "kept_" ones are past designs our team approved:
{catalogue}

Return JSON only:
{{
  "piece": {{"type": "...", "description": "what you see: motifs, stones, finish, approx size/weight feel",
             "gold_grams": "estimated total gold weight in grams (use the customer's figure if given)",
             "size": "realistic real-world dimensions of each element in cm, judged from what kind of piece it is (e.g. a chandbali earring is ~4-6 cm wide)"}},
  "designs": [
    {{
      "title": "short name",
      "idea": "1-2 sentences for the customer: what becomes what and why it's modern",
      "reuse": "which existing elements are kept and where they go",
      "gold_split": [{{"piece": "e.g. main pendant necklace", "grams": 12}}, {{"piece": "matching earrings", "grams": 5}}],
      "added": ["new materials added, e.g. rice pearls", "lab-grown diamonds"],
      "additions_cost": {{"low": 8000, "high": 15000}},
      "render_prompt": "detailed visual description of the NEW piece(s) for an image model: the main piece AND every companion piece from gold_split, form, layout, the added materials, finish, colours",
      "scale": "real-world size of the new piece and of each reused element in it, in cm (reused elements keep their original size)",
      "examples": ["2 reference ids from the list whose style best fits this design"]
    }}
  ]
}}
"gold_split" grams must add up to the customer's gold PLUS any new gold bought with a top-up.
"additions_cost" is your realistic Indian retail estimate in rupees (numbers only) for the added materials.

Give exactly {n} distinct design(s), all following the style direction, the occasion and the pieces they want. If more than one, at least one should
change the type of piece (e.g. necklace -> bracelet/bangle/ring/earrings) if that is realistic for the gold available."""

STYLES = {
    "modern": {
        "brief": "MODERN & MINIMAL. Lightweight, wearable every day or to the office. Clean lines, negative space, "
                 "deconstructed single motifs, asymmetry, fine chains, cuffs, ear climbers, stackable rings, sleek "
                 "pendants. Additions stay delicate but present: lab-grown diamond accents, a few pearls, one coloured "
                 "stone, a fine bead strand, enamel detail. Avoid heavy bridal looks, layered haars and dense kundan.",
        "render": "Use the reference pairs ONLY to see how old elements were reused and for photo quality. The new "
                  "piece must look modern, minimal and light — NOT heavy or bridal like the references. Photograph it "
                  "on a plain light neutral background or a simple modern stand.",
    },
    "traditional": {
        "brief": "TRADITIONAL & HERITAGE. Festive and bridal: kundan, polki, temple work, meenakari, pearls, emerald/"
                 "ruby bead strands, statement chokers and haars, matching earrings — like the reference projects.",
        "render": "Match the AFTER images' style, level of craftsmanship and their photography (clean studio product "
                  "shot, soft light, dark teal velvet bust or plain neutral background).",
    },
}

RENDER_PROMPT = """You are rendering a jewellery redesign for an upcycling studio.

The images above are reference pairs from real projects: each BEFORE was reworked into its AFTER.
{style_render}

The LAST image is the customer's actual old piece. Redesign THAT piece — keep its recognisable motifs,
gold tone and stones so the customer can see their own jewellery was reused, not replaced.

New design: {title}
{render_prompt}

Pieces to show together as one set (all made from the customer's gold): {pieces}
New materials that MUST be clearly visible: {added}

TRUE SCALE — very important: {scale}
Reused elements must keep their original real-world size. Small pieces (e.g. an earring reused as a pendant)
must look small relative to the chain/strands, the bust or the wrist — never enlarge them.
Arrange the set like a studio set photo: main piece on its display, companion pieces beside it.
Display it so the size is obvious: necklaces and chokers on a neck bust, bracelets/bangles on a wrist form or
bangle stand, earrings on an earring stand, rings on a ring cone.

Framing: the ENTIRE piece must be fully visible with clear empty margin on every side — nothing cropped at
the edges. One photorealistic product photo of the new set only. No text, no labels, no people, no borders,
no collage or inset images."""


def explain(e: Exception) -> str:
    """Turn an API error into a plain reason the team can act on."""
    msg = str(e)
    low = msg.lower()
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    gemini = "openrouter" not in low
    if code == 402 or any(w in low for w in ("insufficient credits", "credits are depleted", "prepayment",
                                              "billing", "key limit exceeded", "limit exceeded")):
        return ("Out of credits on " + ("Gemini — top up in Google AI Studio billing." if gemini
                else "OpenRouter — add credits or raise the key limit on openrouter.ai.") + f" ({msg[:150]})")
    if code == 429 or "resource_exhausted" in low or "quota" in low or "rate limit" in low:
        return ("Usage limit hit on " + ("Gemini" if gemini else "OpenRouter") +
                " — either credits/quota are used up or too many requests at once. Wait a minute and retry; "
                f"if it keeps happening, check credits. ({msg[:150]})")
    if code in (401, 403) or "api key" in low or "unauthorized" in low:
        return f"API key problem — the key is missing, wrong or disabled. ({msg[:150]})"
    return msg[:300]


def _img(path_or_bytes):
    return Image.open(path_or_bytes).convert("RGB")


OCCASIONS = {
    "everyday": "Everyday wear — light, comfortable, durable, nothing that snags.",
    "casual": "Casual outings and small get-togethers — easy to wear but a little dressier than daily wear.",
    "festive": "Festivals, parties and family functions — noticeable, with some colour and sparkle.",
    "ceremonial": "Weddings and ceremonies — rich, statement pieces with matching companions.",
}
PIECES = ["necklace", "choker", "long haar", "earrings", "bangles", "bracelet", "ring", "pendant", "maang tikka"]
SET_SIZES = {
    "any": "Designer's choice of how many pieces.",
    "single": "One single piece.",
    "set": "One matching set (e.g. necklace + earrings).",
    "multi": "Several separate pieces or sets, splitting the gold between them.",
}


def goal_text(goal, topup, karat, rate):
    if goal == "topup" and topup:
        return (f"TOP-UP. The customer will add up to ₹{topup:,.0f} on top of their old gold. Spend it on new "
                f"{karat}K gold (about {topup / rate:.1f} g if it all went on gold), richer additions and making, so "
                "the result is bigger or fuller than their gold alone allows — e.g. a small set becomes a full necklace "
                "set. Keep new gold + additions + ~12% making within the top-up.")
    if goal == "idea":
        return ("THEIR OWN IDEA. The customer has something specific in mind (see their wish) — follow it closely and "
                "make every design a variation of that idea. If it needs more gold than they have, add the new gold to "
                "gold_split and say so in the idea.")
    return "OWN GOLD ONLY. No new gold — the gold_split must add up to their gold. Keep additions modest in cost."


async def design(photo: Image.Image, wish: str, n: int, style: str, grams: float = 0, brief: dict | None = None):
    b = brief or {}
    karat, rate = b.get("karat", "22"), b.get("rate", 0)
    catalogue = "\n".join(f"- {k} [{v['style']}]: {v['transformation']}" for k, v in CATALOGUE.items())
    pieces = ", ".join(b.get("pieces") or []) or "designer's choice"
    prompt = DESIGNER_PROMPT.format(style_brief=STYLES[style]["brief"], wish=wish or "(none)", catalogue=catalogue, n=n,
                                    grams=f"{grams:g} g (given by the customer)" if grams else "not given — estimate it from the photo",
                                    karat=karat, rate=rate, occasion=OCCASIONS.get(b.get("occasion"), "not given"),
                                    pieces=f"{pieces}. {SET_SIZES.get(b.get('set_size'), SET_SIZES['any'])}",
                                    goal=goal_text(b.get("goal"), b.get("topup", 0), karat, rate))
    resp = await client.aio.models.generate_content(
        model=TEXT_MODEL,
        contents=[photo, prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    usage.record_text(TEXT_MODEL, resp.usage_metadata)
    plan = json.loads(resp.text)
    for d in plan["designs"]:
        d["examples"] = [e for e in d.get("examples", []) if e in CATALOGUE][:EXAMPLES_PER_DESIGN] \
            or list(CATALOGUE)[:EXAMPLES_PER_DESIGN]
    return plan


def _render_prompt(d, style):
    pieces = "; ".join(f"{g.get('piece')} (~{g.get('grams')} g)" for g in d.get("gold_split", [])) or d["title"]
    return RENDER_PROMPT.format(style_render=STYLES[style]["render"], title=d["title"],
                                render_prompt=d["render_prompt"], scale=d.get("scale", ""),
                                pieces=pieces, added=", ".join(d.get("added", [])) or "pearls or stones that suit the design")


async def render_gemini(photo: Image.Image, d: dict, style: str, out_path: Path):
    contents = []
    for i, ex in enumerate(d["examples"], 1):
        contents += [f"Reference {i} BEFORE:", _img(CATALOGUE[ex]["before"]),
                     f"Reference {i} AFTER:", _img(CATALOGUE[ex]["after"])]
    contents += ["Customer's old piece:", photo, _render_prompt(d, style)]
    resp = await client.aio.models.generate_content(
        model=IMAGE_MODEL, contents=contents,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"],
                                           image_config=types.ImageConfig(aspect_ratio="4:5")),
    )
    usage.record_image(IMAGE_MODEL, resp.usage_metadata)
    cand = (resp.candidates or [None])[0]
    for part in (cand.content.parts if cand and cand.content and cand.content.parts else []):
        if part.inline_data:
            out_path.write_bytes(part.inline_data.data)
            return out_path.name
    reason = getattr(cand, "finish_reason", None) or getattr(resp.prompt_feedback, "block_reason", None)
    said = " ".join(p.text for p in (cand.content.parts if cand and cand.content and cand.content.parts else []) if p.text)
    raise RuntimeError(f"Gemini returned no image (reason: {reason or 'not given'})" + (f" — it said: {said[:200]}" if said else ""))


def _data_url(img: Image.Image):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def render_openrouter(model: str, extra: dict, photo: Image.Image, d: dict, style: str, out_path: Path):
    refs, order = [], []
    for i, ex in enumerate(d["examples"], 1):
        refs += [_img(CATALOGUE[ex]["before"]), _img(CATALOGUE[ex]["after"])]
        order += [f"Reference {i} BEFORE", f"Reference {i} AFTER"]
    refs.append(photo)
    order.append("Customer's old piece")
    for r in refs:
        r.thumbnail((1024, 1024))
    prompt = "Input images, in order: " + "; ".join(f"image {i}: {o}" for i, o in enumerate(order, 1)) \
             + ".\n\n" + _render_prompt(d, style)
    async with httpx.AsyncClient(timeout=300) as http:
        r = await http.post(f"{OPENROUTER}/images", headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                            json={"model": model, "prompt": prompt, "aspect_ratio": "3:4", **extra,
                                  "input_references": [{"type": "image_url", "image_url": {"url": _data_url(x)}}
                                                       for x in refs]})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200 or not body.get("data"):
        err = RuntimeError(f"OpenRouter ({model}): " + str(body.get("error", {}).get("message")
                           or f"no image returned, HTTP {r.status_code}"))
        err.code = r.status_code
        raise err
    usage.record_openrouter(body.get("usage", {}).get("cost", 0))
    out_path.write_bytes(base64.b64decode(body["data"][0]["b64_json"]))
    return out_path.name


# Image engines the page can pick from.
ENGINES = {
    "gemini": ("Gemini (Nano Banana 2)", render_gemini),
    "gpt": ("OpenAI GPT Image 2", partial(render_openrouter, "openai/gpt-image-2", {"quality": "medium"})),
    "gpt-high": ("OpenAI GPT Image 2 · high", partial(render_openrouter, "openai/gpt-image-2", {"quality": "high"})),
    "flux": ("FLUX.2 Pro", partial(render_openrouter, "black-forest-labs/flux.2-pro", {})),
}
COMPARE = ["gemini", "gpt", "flux"]


async def redesign(photo: Image.Image, wish: str, n: int, style: str, engine: str, out_dir: Path, grams: float = 0,
                   brief: dict | None = None):
    b = brief or {}
    plan = await design(photo, wish, n, style, grams, b)
    plan["style"] = style
    # Price everything from today's rate; a weight we only guessed from the photo gets a wider range.
    old_g = grams or pricing._num(plan["piece"].get("gold_grams"))
    karat, rate = b.get("karat", "22"), b.get("rate", 0)
    if rate and old_g:
        plan["estimate"] = {"rate24": b["rate24"], "gram_rate": round(rate), "topup": b.get("topup", 0),
                            **pricing.old_gold(old_g, karat, b["rate24"], estimated=not grams)}
        for d in plan["designs"]:
            d["cost"] = pricing.design_cost(d, old_g, karat, b["rate24"])
    engines = COMPARE if engine == "compare" else [engine]
    # One card per (design, engine) so each render can be compared and kept on its own.
    cards = [{**d, "engine": e, "engine_name": ENGINES[e][0]} for d in plan["designs"][:n] for e in engines]
    results = await asyncio.gather(
        *(ENGINES[c["engine"]][1](photo.copy(), c, style, out_dir / f"design_{i}.png") for i, c in enumerate(cards, 1)),
        return_exceptions=True,
    )
    for c, r in zip(cards, results):
        if isinstance(r, Exception):
            c["error"] = explain(r)
        else:
            c["image"] = r
    plan["designs"] = cards
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=2))
    return plan
