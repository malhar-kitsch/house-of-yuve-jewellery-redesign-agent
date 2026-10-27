"""Saved past runs (photo, choices, designs, prices). Uses the private Vercel Blob store when
BLOB_READ_WRITE_TOKEN is set, so history survives across servers; otherwise a local folder."""
import asyncio, json, os

import httpx

from app.paths import WRITABLE

API = "https://vercel.com/api/blob"
LOCAL = WRITABLE / "history"


def _token():
    return os.getenv("BLOB_READ_WRITE_TOKEN")


def _headers(**extra):
    return {"authorization": f"Bearer {_token()}", "x-api-version": "13", **extra}


async def put(path: str, data: bytes, content_type: str):
    if not _token():
        f = LOCAL / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        return
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.put(f"{API}/?pathname={path}", content=data, headers=_headers(**{
            "x-vercel-blob-access": "private", "x-add-random-suffix": "0", "x-allow-overwrite": "1",
            "x-content-type": content_type}))
        r.raise_for_status()


async def get(path: str) -> bytes | None:
    if not _token():
        f = (LOCAL / path).resolve()
        return f.read_bytes() if LOCAL.resolve() in f.parents and f.exists() else None
    store = _token().split("_")[3]
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.get(f"https://{store}.private.blob.vercel-storage.com/{path}", headers=_headers())
    return r.content if r.status_code == 200 else None


async def _names(prefix: str):
    if not _token():
        return [f"{prefix}{f.name}" for f in (LOCAL / prefix).glob("*")]
    names, cursor = [], None
    async with httpx.AsyncClient(timeout=60) as http:
        while True:
            r = await http.get(API, params={"prefix": prefix, "limit": 1000, **({"cursor": cursor} if cursor else {})},
                               headers=_headers())
            r.raise_for_status()
            body = r.json()
            names += [b["pathname"] for b in body["blobs"]]
            if not body.get("hasMore"):
                return names
            cursor = body["cursor"]


async def save_run(run_id: str, files: dict, run: dict):
    """files: {name: jpeg bytes}. run: everything needed to show the run again."""
    await asyncio.gather(*(put(f"runs/{run_id}/{n}", b, "image/jpeg") for n, b in files.items()))
    await put(f"runs/{run_id}/run.json", json.dumps(run).encode(), "application/json")
    est = run.get("estimate") or {}
    summary = {"run": run_id, "piece": run["piece"].get("type"), "inputs": run.get("inputs", {}),
               "designs": len(run["designs"]), "gold_value": [est.get("low"), est.get("high")] if est else None}
    await put(f"index/{run_id}.json", json.dumps(summary).encode(), "application/json")


async def list_runs(limit=40):
    names = sorted(await _names("index/"), reverse=True)[:limit]  # run ids start with the date
    found = await asyncio.gather(*(get(n) for n in names))
    return [json.loads(b) for b in found if b]
