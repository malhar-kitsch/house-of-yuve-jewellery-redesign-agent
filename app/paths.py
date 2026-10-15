"""Where things live. On Vercel only /tmp is writable (and it is wiped between cold starts)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WRITABLE = Path("/tmp/hoy") if os.getenv("VERCEL") else ROOT
OUT = WRITABLE / "outputs"
KEPT = WRITABLE / "data" / "kept"
USAGE_FILE = WRITABLE / "data" / "usage.json"
for p in (OUT, KEPT):
    p.mkdir(parents=True, exist_ok=True)
