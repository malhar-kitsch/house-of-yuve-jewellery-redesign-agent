"""The two agents: a designer that studies the photo and plans redesigns,
and a renderer that draws each redesign using matching before/after examples."""
import asyncio, base64, io, json, os, shutil
from functools import partial
from pathlib import Path

import httpx
from google import genai
from google.genai import types
from PIL import Image

from app import usage

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KEPT = DATA / "kept"
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
    for meta in sorted(KEPT.glob("*/meta.json")):
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

Customer's wish (may be empty): {wish}

Reference transformations we have photos of (id [style]: what happened). Prefer references whose style
matches the style direction; "kept_" ones are past designs our team approved:
{catalogue}

Return JSON only:
{{
  "piece": {{"type": "...", "description": "what you see: motifs, stones, finish, approx size/weight feel",
             "size": "realistic real-world dimensions of each element in cm, judged from what kind of piece it is (e.g. a chandbali earring is ~4-6 cm wide)"}},
  "designs": [
    {{
      "title": "short name",
      "idea": "1-2 sentences for the customer: what becomes what and why it's modern",
      "reuse": "which existing elements are kept and where they go",
      "render_prompt": "detailed visual description of the NEW piece for an image model: form, layout, materials added, finish, colours",
      "scale": "real-world size of the new piece and of each reused element in it, in cm (reused elements keep their original size)",
      "examples": ["2 reference ids from the list whose style best fits this design"]
    }}
  ]
}}
Give exactly {n} distinct design(s), all following the style direction. If more than one, at least one should
change the type of piece (e.g. necklace -> bracelet/bangle/ring/earrings) if that is realistic for the gold available."""

STYLES = {
    "modern": {
        "brief": "MODERN & MINIMAL. Lightweight, wearable every day or to the office. Clean lines, negative space, "
                 "deconstructed single motifs, asymmetry, fine chains, cuffs, ear climbers, stackable rings, sleek "
                 "pendants. Add little: maybe one stone, a few pearls or a matte/brushed finish. Avoid heavy bridal "
                 "looks, layered haars, dense kundan and lots of beads.",
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

TRUE SCALE — very important: {scale}
Reused elements must keep their original real-world size. Small pieces (e.g. an earring reused as a pendant)
must look small relative to the chain/strands, the bust or the wrist — never enlarge them.
Display it so the size is obvious: necklaces and chokers on a neck bust, bracelets/bangles on a wrist form or
bangle stand, earrings on an earring stand, rings on a ring cone.

Framing: the ENTIRE piece must be fully visible with clear empty margin on every side — nothing cropped at
the edges. One photorealistic product photo of the new piece only. No text, no labels, no people, no borders,
no collage or inset images."""


def _img(path_or_bytes):
    return Image.open(path_or_bytes).convert("RGB")


async def design(photo: Image.Image, wish: str, n: int, style: str):
    catalogue = "\n".join(f"- {k} [{v['style']}]: {v['transformation']}" for k, v in CATALOGUE.items())
    prompt = DESIGNER_PROMPT.format(style_brief=STYLES[style]["brief"], wish=wish or "(none)", catalogue=catalogue, n=n)
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
    return RENDER_PROMPT.format(style_render=STYLES[style]["render"], title=d["title"],
                                render_prompt=d["render_prompt"], scale=d.get("scale", ""))


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
    for part in resp.candidates[0].content.parts:
        if part.inline_data:
            out_path.write_bytes(part.inline_data.data)
            return out_path.name
    raise RuntimeError("Model returned no image")


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
    body = r.json()
    if r.status_code != 200 or not body.get("data"):
        raise RuntimeError(body.get("error", {}).get("message", f"HTTP {r.status_code}"))
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


async def redesign(photo: Image.Image, wish: str, n: int, style: str, engine: str, out_dir: Path):
    plan = await design(photo, wish, n, style)
    plan["style"] = style
    engines = COMPARE if engine == "compare" else [engine]
    # One card per (design, engine) so each render can be compared and kept on its own.
    cards = [{**d, "engine": e, "engine_name": ENGINES[e][0]} for d in plan["designs"][:n] for e in engines]
    results = await asyncio.gather(
        *(ENGINES[c["engine"]][1](photo.copy(), c, style, out_dir / f"design_{i}.png") for i, c in enumerate(cards, 1)),
        return_exceptions=True,
    )
    for c, r in zip(cards, results):
        if isinstance(r, Exception):
            c["error"] = str(r)[:300]
        else:
            c["image"] = r
    plan["designs"] = cards
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=2))
    return plan
