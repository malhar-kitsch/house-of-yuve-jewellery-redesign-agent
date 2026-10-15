"""Running spend per provider, kept in data/usage.json.
Gemini is estimated from token counts (prices below, USD per 1M tokens — check
https://ai.google.dev/gemini-api/docs/pricing). OpenRouter reports the exact cost of each call."""
import json, threading

from app.paths import USAGE_FILE as FILE

ALERTS = {"gemini": 4.0, "openrouter": 8.0}  # ≈ ₹350 of ₹500 prepaid; $8 of the $10 key cap

# (input, output) per 1M tokens. Image output tokens are priced higher than text.
PRICES = {
    "text": (0.50, 3.00),
    "gemini-3.1-flash-image": (0.50, 60.00),
    "gemini-2.5-flash-image": (0.30, 30.00),
    "gemini-3-pro-image": (2.00, 120.00),
}

_lock = threading.Lock()


def _load():
    u = json.loads(FILE.read_text()) if FILE.exists() else {}
    if "usd" in u and "gemini" not in u:  # older single-provider format
        u = {"gemini": u["usd"], "images": u.get("images", 0)}
    return {"gemini": 0.0, "openrouter": 0.0, "images": 0, **u}


def _add(provider, cost, images=0):
    with _lock:
        u = _load()
        before = u[provider]
        u[provider] = round(u[provider] + cost, 4)
        u["images"] += images
        FILE.write_text(json.dumps(u, indent=2))
        if before < ALERTS[provider] <= u[provider]:
            print(f"\n*** {provider} spend has crossed ${ALERTS[provider]:.0f} (now ${u[provider]:.2f}) ***\n")


def _cost(price, meta):
    if not meta:
        return 0.0
    tin = meta.prompt_token_count or 0
    tout = (meta.candidates_token_count or 0) + (getattr(meta, "thoughts_token_count", 0) or 0)
    return (tin * price[0] + tout * price[1]) / 1e6


def record_text(model, meta):
    _add("gemini", _cost(PRICES["text"], meta))


def record_image(model, meta):
    _add("gemini", _cost(PRICES.get(model, PRICES["gemini-3-pro-image"]), meta), images=1)


def record_openrouter(cost):
    _add("openrouter", cost or 0.0, images=1)


def summary():
    u = _load()
    over = [p for p, limit in ALERTS.items() if u[p] >= limit]
    return {**u, "alerts": ALERTS, "over": over}
