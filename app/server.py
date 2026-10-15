import base64, io, os, secrets, time, uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from app import agents, usage

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


@app.post("/api/redesign")
async def redesign(photo: UploadFile = File(...), wish: str = Form(""), count: int = Form(4),
                   style: str = Form("modern"), engine: str = Form("gemini")):
    if style not in agents.STYLES:
        raise HTTPException(400, "Unknown style")
    if engine != "compare" and engine not in agents.ENGINES:
        raise HTTPException(400, "Unknown image engine")
    try:
        img = Image.open(io.BytesIO(await photo.read())).convert("RGB")
    except Exception:
        raise HTTPException(400, "Could not read that image")
    img.thumbnail((1536, 1536))
    run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    out_dir = OUT / run_id
    out_dir.mkdir()
    img.save(out_dir / "original.jpg", quality=92)
    try:
        plan = await agents.redesign(img, wish, max(1, min(count, 6)), style, engine, out_dir)
    except Exception as e:
        raise HTTPException(502, f"AI error: {str(e)[:400]}")
    # Send images back inline: on Vercel a later request may land on a different server.
    for d in plan["designs"]:
        if d.get("image"):
            d["image_data"] = _jpeg_data_url(out_dir / d["image"])
    return {"run": run_id, **plan, "usage": usage.summary()}


def _jpeg_data_url(path, max_side=1200):
    # Vercel caps responses at ~4.5MB, so send compact JPEGs (full PNG stays on disk).
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


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
