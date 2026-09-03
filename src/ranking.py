"""Ranks a universe with the same algorithm the single-company view uses.

Nothing here re-scores or re-weights: it calls `verdict.assess` per company
and orders the results. A screen that ranked by a different rule than the one
it explains would be a second, hidden model.
"""
import json
import os
import time

import backtest
import edgar
import report
import valuation as valuation_mod
import verdict as verdict_mod

OUTPUT = os.path.join(os.path.dirname(__file__), "..", "data", "ranking.json")

# Verdicts a screen should surface, best first. A blocked company is never
# promoted regardless of how it scores elsewhere.
ORDER = {
    "yatirim yapilabilir": 0,
    "ucuz ama sorunlu": 1,
    "kosullu": 2,
    "iyi sirket, pahali fiyat": 3,
    "fiyatlanamaz": 4,
    "fiyat verisi yok": 5,
    "degerlendirilemez": 6,
    "yatirim yapilamaz": 7,
}


def cached_universe():
    """Tickers whose filings are already on disk -- no download to rank them."""
    ciks = set()
    for name in os.listdir(os.path.join(edgar.CACHE)):
        if name.startswith("facts_") and name.endswith(".json"):
            ciks.add(int(name[len("facts_"):-len(".json")]))
    table = json.load(open(os.path.join(edgar.CACHE, "tickers.json")))
    out = []
    for row in table.values():
        if row["cik_str"] in ciks:
            out.append(row["ticker"])
            ciks.discard(row["cik_str"])
    return out


def score(ticker):
    pkg = report.build(ticker, quarters=40)
    try:
        val = valuation_mod.value(pkg)
    except Exception:
        val = None
    a = verdict_mod.assess(pkg, val)
    pillars = {p["name"]: p["score"] for p in a["pillars"]}
    business = a["business_score"]
    price_score = pillars.get("Değerleme")

    # Quality carries more than price, but a screen that ignored price would
    # just list the largest good companies at any valuation.
    if business is None:
        overall = None
    elif price_score is None:
        overall = round(business * 0.75, 1)
    else:
        overall = round(business * 0.6 + price_score * 0.4, 1)

    # A large model-versus-market gap is exactly what the single-company view
    # warns about, so the screen must not promote a company on the strength
    # of one without saying so.
    divergence = (val or {}).get("divergence") or {}
    reversion = (val or {}).get("reversion") or {}

    return {
        "ticker": ticker,
        "name": pkg["company"]["name"],
        "industry": pkg["company"]["industry"],
        "verdict": a["verdict"],
        "rationale": a["rationale"],
        "business_score": business,
        "valuation_score": price_score,
        "overall": overall,
        "pillars": pillars,
        "price": (val or {}).get("quote", {}).get("price"),
        "fair_value": ((val or {}).get("fair_value") or {}).get("base"),
        "upside": (val or {}).get("upside_to_fair"),
        "divergence": divergence.get("level"),
        "window_quality": reversion.get("window_quality"),
        "coverage": pkg["data_coverage"],
    }


def build(universe=None, verbose=True):
    universe = universe or cached_universe()
    rows, failed = [], []
    for ticker in universe:
        try:
            rows.append(score(ticker))
        except Exception as exc:
            failed.append((ticker, str(exc)))
            if verbose:
                print("  %-6s atlandi: %s" % (ticker, exc))
            continue
        if verbose:
            r = rows[-1]
            print("  %-6s %-26s %s" % (r["ticker"], r["verdict"], r["overall"]))

    # Companies whose valuation rests on a suspect number rank below equally
    # scored peers whose does not, rather than being filtered out: the number
    # may be right, and hiding it would be its own distortion.
    rows.sort(key=lambda r: (ORDER.get(r["verdict"], 9),
                             1 if r.get("divergence") == "yuksek" else 0,
                             -(r["overall"] or 0)))
    payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "universe_size": len(rows), "failed": failed, "rows": rows}
    json.dump(payload, open(OUTPUT, "w"), ensure_ascii=False, indent=1)
    return payload


def load():
    if not os.path.exists(OUTPUT):
        return None
    return json.load(open(OUTPUT))


if __name__ == "__main__":
    p = build()
    print("\n%d sirket siralandi, %d atlandi" % (len(p["rows"]), len(p["failed"])))
    print("\nEn iyi 10:")
    print("  %-6s %-26s %7s %7s %7s  %s" % ("TICK", "sonuc", "genel", "isletme", "deger", "yukselis"))
    for r in p["rows"][:10]:
        print("  %-6s %-26s %7s %7s %7s  %s"
              % (r["ticker"], r["verdict"], r["overall"], r["business_score"],
                 r["valuation_score"],
                 ("%+.0f%%" % (r["upside"] * 100)) if r["upside"] is not None else "-"))
