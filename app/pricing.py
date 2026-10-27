"""Today's gold rate and rough price estimates for the customer's gold and each redesign."""
import os, re, time

import httpx

# Share of pure gold in each karat.
PURITY = {"24": 1.0, "22": 0.916, "18": 0.75, "14": 0.585}
# Backup only: international spot price -> Indian rate (duty, GST, local premium).
INDIA_PREMIUM = float(os.getenv("GOLD_INDIA_PREMIUM", "1.17"))
# Labour for reworking, as a share of the gold value in the new piece.
MAKING = (0.08, 0.15)
OZ = 31.1035
_cache = {"at": 0, "rate": None}


async def rate_24k():
    """Today's 24K rate in ₹ per gram (GOLD_RATE_24K overrides the live feed). Cached for an hour."""
    if os.getenv("GOLD_RATE_24K"):
        return {"rate": float(os.environ["GOLD_RATE_24K"]), "source": "fixed rate"}
    if not _cache["rate"] or time.time() - _cache["at"] > 3600:
        try:
            rate, source = await _goodreturns(), "GoodReturns, Mumbai"
        except Exception:
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.get("https://api.gold-api.com/price/XAU/INR")
            rate, source = round(r.json()["price"] / OZ * INDIA_PREMIUM), "world price + Indian premium"
        _cache.update(at=time.time(), rate=rate, source=source)
    return {"rate": _cache["rate"], "source": _cache["source"]}


async def _goodreturns():
    """Indian market 24K rate per gram from the Mumbai row of goodreturns.in."""
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Mozilla/5.0"}) as http:
        html = (await http.get("https://www.goodreturns.in/gold-rates/")).text
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&#x20b9;", "₹")
    rate = float(re.search(r"Mumbai ₹([\d,]+) ₹[\d,]+ ₹[\d,]+", text).group(1).replace(",", ""))
    if not 3000 < rate < 100000:
        raise ValueError(f"odd rate {rate}")
    return rate


def per_gram(rate24, karat):
    return rate24 * PURITY.get(karat, PURITY["22"])


def old_gold(grams, karat, rate24, estimated):
    """Value of the customer's gold. A guessed weight gets a wider range."""
    value = grams * per_gram(rate24, karat)
    spread = 0.2 if estimated else 0.05
    return {"grams": grams, "karat": karat, "value": round(value),
            "low": round(value * (1 - spread)), "high": round(value * (1 + spread))}


def design_cost(d, old_grams, karat, rate24):
    """Rough cost of one redesign: gold + new gold + additions + making, minus the customer's own gold."""
    total_g = sum(_num(g.get("grams")) for g in d.get("gold_split", []))
    new_g = max(0.0, total_g - old_grams)
    gram = per_gram(rate24, karat)
    gold = total_g * gram
    extra_gold = new_g * gram
    add = d.get("additions_cost") or {}
    add_low, add_high = _num(add.get("low")), _num(add.get("high"))
    make_low, make_high = gold * MAKING[0], gold * MAKING[1]
    low = extra_gold + add_low + make_low
    high = extra_gold + add_high + make_high
    return {"total_grams": round(total_g, 1), "new_gold_grams": round(new_g, 1), "new_gold": round(extra_gold),
            "additions": [round(add_low), round(add_high)], "making": [round(make_low), round(make_high)],
            "pay": [round(low), round(high)], "piece_value": [round(gold + add_low + make_low), round(gold + add_high + make_high)]}


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("₹", "").split()[0])
    except (ValueError, IndexError):
        return 0.0
