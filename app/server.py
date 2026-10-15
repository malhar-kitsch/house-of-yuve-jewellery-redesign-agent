import io, time, uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from app import agents, usage

OUT = agents.ROOT / "outputs"
OUT.mkdir(exist_ok=True)
app = FastAPI()


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
        raise HTTPException(502, f"Gemini error: {str(e)[:400]}")
    return {"run": run_id, **plan, "usage": usage.summary()}


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
