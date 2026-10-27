import base64, io, json, os, re, secrets, time, uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from app import agents, history, pricing, usage

from app.paths import OUT

app = FastAPI()
PASSWORD = os.getenv("APP_PASSWORD")


@app.middleware("http")
async def require_password(request: Request, call_next):
    """Browser login prompt when APP_PASSWORD is set (any username)."""
    if PASSWORD:
        ok = False
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            try:
                ok = secrets.compare_digest(base64.b64decode(auth[6:]).decode().split(":", 1)[1], PASSWORD)
            except Exception:
                pass
        if not ok:
            return Response("Password required", 401, {"WWW-Authenticate": 'Basic realm="House of Yuve"'})
    return await call_next(request)


def _read_photo(data: bytes):
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(400, "Could not read that image")
    img.thumbnail((1536, 1536))
    return img


@app.post("/api/weigh")
async def weigh(photo: UploadFile = File(...)):
    """Estimate the gold weight from the photo as soon as it is added."""
    try:
        return await agents.weigh(_read_photo(await photo.read()))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Couldn't estimate the weight: {agents.explain(e)}")


@app.post("/api/redesign")
async def redesign(photo: UploadFile = File(...), wish: str = Form(""), count: int = Form(4),
                   style: str = Form("modern"), engine: str = Form("gemini"), grams: float = Form(0),
                   karat: str = Form("22"), goal: str = Form("own"), topup: float = Form(0), pieces: str = Form(""),
                   set_size: str = Form("any"), occasion: str = Form(""), rate24: float = Form(0),
                   grams_estimated: bool = Form(False), grams_low: float = Form(0), grams_high: float = Form(0)):
    if style not in agents.STYLES:
        raise HTTPException(400, "Unknown style")
    if engine != "compare" and engine not in agents.ENGINES:
        raise HTTPException(400, "Unknown image engine")
    img = _read_photo(await photo.read())
    if karat not in pricing.PURITY:
        karat = "22"
    if not rate24:
        try:
            rate24 = (await pricing.rate_24k())["rate"]
        except Exception:
            rate24 = 0  # no live rate: designs still work, just without prices
    brief = {"karat": karat, "goal": goal, "topup": max(topup, 0) if goal == "topup" else 0,
             "pieces": [x for x in pieces.split(",") if x in agents.PIECES], "set_size": set_size,
             "occasion": occasion, "rate24": rate24, "rate": pricing.per_gram(rate24, karat),
             "grams_estimated": grams_estimated and grams > 0,
             "grams_range": (grams_low, grams_high) if grams_estimated and 0 < grams_low <= grams <= grams_high else None}
    run_id = time.strftime("%Y%m%d-%H%M%S-", time.gmtime()) + uuid.uuid4().hex[:4]
    out_dir = OUT / run_id
    out_dir.mkdir()
    img.save(out_dir / "original.jpg", quality=92)
    try:
        plan = await agents.redesign(img, wish, max(1, min(count, 6)), style, engine, out_dir, max(grams, 0), brief)
    except Exception as e:
        raise HTTPException(502, f"Couldn't create designs: {agents.explain(e)}")
    # Send images back inline: on Vercel a later request may land on a different server.
    files = {"original.jpg": _jpeg(out_dir / "original.jpg"), "thumb.jpg": _jpeg(out_dir / "original.jpg", 360)}
    for i, d in enumerate(plan["designs"], 1):
        if d.get("image"):
            files[f"design_{i}.jpg"] = _jpeg(out_dir / d["image"])
            d["saved_image"] = f"design_{i}.jpg"
    inputs = {"wish": wish, "style": style, "engine": engine, "grams": grams, "grams_estimated": brief["grams_estimated"],
              **{k: brief[k] for k in ("karat", "goal", "topup", "pieces", "set_size", "occasion", "rate24")}}
    run = {"run": run_id, "inputs": inputs, **plan}
    try:
        await history.save_run(run_id, files, run)
    except Exception as e:
        run["history_error"] = f"Not saved to history: {str(e)[:150]}"
    for d in run["designs"]:
        if d.get("saved_image"):
            d["image_data"] = "data:image/jpeg;base64," + base64.b64encode(files[d["saved_image"]]).decode()
    return {**run, "usage": usage.summary()}


def _jpeg(path, max_side=1200):
    # Vercel caps responses at ~4.5MB, so send compact JPEGs (full PNG stays on disk).
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


RUN_ID = re.compile(r"^[\w-]+$")


@app.get("/api/history")
async def list_history():
    try:
        return await history.list_runs()
    except Exception as e:
        raise HTTPException(502, f"Couldn't load history: {str(e)[:150]}")


@app.get("/api/history/{run}")
async def get_run(run: str):
    data = await history.get(f"runs/{run}/run.json") if RUN_ID.match(run) else None
    if not data:
        raise HTTPException(404, "That run wasn't found")
    return json.loads(data)


@app.get("/api/history/{run}/{name}")
async def history_image(run: str, name: str):
    ok = RUN_ID.match(run) and re.match(r"^(original|thumb|design_\d+)\.jpg$", name)
    data = await history.get(f"runs/{run}/{name}") if ok else None
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@app.post("/api/keep")
def keep(run: str = Form(...), index: int = Form(...), kept: bool = Form(True)):
    run_dir = (OUT / run).resolve()
    if OUT not in run_dir.parents or not (run_dir / "plan.json").exists():
        raise HTTPException(404)
    try:
        pid = agents.keep(run_dir, index, kept)
    except (IndexError, KeyError):
        raise HTTPException(400, "No image for that design")
    return {"id": pid, "kept": kept, "examples": len(agents.CATALOGUE)}


@app.get("/api/gold-rate")
async def gold_rate():
    try:
        return await pricing.rate_24k()
    except Exception:
        raise HTTPException(502, "Couldn't fetch today's gold rate — type it in instead")


@app.get("/api/usage")
def get_usage():
    return usage.summary()


@app.get("/outputs/{run}/{name}")
def output_file(run: str, name: str):
    p = (OUT / run / name).resolve()
    if OUT not in p.parents or not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/examples/{pair_id}/{which}")
def example_file(pair_id: str, which: str):
    ex = agents.CATALOGUE.get(pair_id)
    if not ex or which not in ("before", "after"):
        raise HTTPException(404)
    return FileResponse(ex[which])


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
