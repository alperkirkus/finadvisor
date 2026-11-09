"""Ranks a universe with the same algorithm the single-company view uses.

Nothing here re-scores or re-weights: it calls `verdict.assess` per company
and orders the results. A screen that ranked by a different rule than the one
it explains would be a second, hidden model.
"""
import json
import os
import time

import backtest
import report
import valuation as valuation_mod
import verdict as verdict_mod

OUTPUT = os.path.join(os.path.dirname(__file__), "..", "data", "ranking.json")

# Verdicts a screen should surface, best first. A blocked company is never
# promoted regardless of how it scores elsewhere.
ORDER = {
    "yatirim yapilabilir": 0,
    "kosullu": 1,
    "iyi sirket, pahali fiyat": 2,
    "ucuz ama sorunlu": 3,      # the value-trap bucket: weak business, cheap price
    "fiyatlanamaz": 4,
    "fiyat verisi yok": 5,
    "degerlendirilemez": 6,
    "yatirim yapilamaz": 7,
}


# The screen ranks today's S&P 500 members. It used to rank "whatever
# filings are cached", which silently grew when the backtest prefetched
# history; an explicit index keeps its scope deliberate.


def overall_score(business, price_score):
    """The number the screen orders by; the backtest scores the same one."""
    # Quality carries more than price, but a screen that ignored price would
    # just list the largest good companies at any valuation.
    if business is None:
        return None
    if price_score is None:
        return round(business * 0.75, 1)
    return round(business * 0.6 + price_score * 0.4, 1)


def screen_universe():
    """Today's S&P 500 members as {yahoo_symbol: cik}, from the Wikipedia
    constituents table (CIK included, so delisted-from-the-SEC-map names
    still resolve)."""
    import universe as U
    U._sec_contact()        # a member whose filings are not cached is fetched
    wiki = U.wikipedia_ciks()
    return {U.yahoo_symbol(t): U.resolve(t, wiki) for t in wiki}


def score(ticker, cik=None):
    pkg = report.build(ticker, quarters=40, cik=cik)
    try:
        val = valuation_mod.value(pkg)
    except Exception:
        val = None
    a = verdict_mod.assess(pkg, val)
    pillars = {p["name"]: p["score"] for p in a["pillars"]}
    business = a["business_score"]
    price_score = pillars.get("Değerleme")
    overall = overall_score(business, price_score)

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


def build(universe=None, verbose=True, workers=4):
    """Scores every company of the screen, `workers` at a time.

    `universe` is {ticker: cik or None}; by default today's S&P 500.
    """
    from concurrent.futures import ThreadPoolExecutor
    universe = universe or screen_universe()
    if isinstance(universe, (list, tuple)):
        universe = {t: None for t in universe}
    rows, failed = [], []

    def one(item):
        ticker, cik = item
        try:
            return ticker, score(ticker, cik), None
        except Exception as exc:
            return ticker, None, str(exc)

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(one, sorted(universe.items())))
    for ticker, row, err in results:
        if err:
            failed.append((ticker, err))
            if verbose:
                print("  %-6s atlandi: %s" % (ticker, err))
            continue
        rows.append(row)
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
