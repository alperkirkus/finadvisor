"""Does the signal actually predict anything?

The verdict thresholds in `verdict.py` are chosen from the literature, not
measured on this data. This module measures them: it reconstructs each
company's evidence package as it stood on a past date, scores it, and
compares the score against the return that followed.

Two biases are removed by construction and one is not.

Removed: lookahead, because a signal may only use filings whose `filed` date
precedes the decision date; and restatement, because a revision is itself a
later filing and so is invisible to an earlier as-of date.

Not removed: survivorship. The universe is companies that exist today, which
tilts every bucket's return upward. The comparison between buckets is still
meaningful -- the bias applies to all of them -- but the absolute return
levels are optimistic and are reported as excess over the index for that
reason.
"""
import json
import os
import time
import urllib.request
from datetime import date, timedelta

import edgar
import metrics as M
import report
import verdict as V

UA = "Mozilla/5.0 (FinAdvisor research)"
PRICE_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
             "%s?range=20y&interval=1mo&events=split")
BENCHMARK = "%5EGSPC"
CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "prices")

UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ORCL", "CRM",
    "ADBE", "INTC", "CSCO", "IBM", "QCOM", "TXN",
    "JPM", "BAC", "WFC", "GS", "AXP",
    "JNJ", "PFE", "MRK", "ABBV", "LLY", "UNH", "BMY", "GILD",
    "KO", "PEP", "PG", "WMT", "COST", "MCD", "SBUX", "NKE", "HD", "TGT",
    "XOM", "CVX", "COP", "NEE", "DUK",
    "CAT", "GE", "BA", "HON", "UPS", "F",
    "T", "VZ", "DIS", "WBA",
]

HOLD_MONTHS = 12


def prices(symbol):
    """Monthly adjusted closes as {YYYY-MM: close}, cached on disk."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, symbol.replace("%5E", "_") + ".json")
    if os.path.exists(path):
        return _legacy(json.load(open(path)))
    req = urllib.request.Request(PRICE_URL % symbol, headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())
    result = d["chart"]["result"][0]
    closes = (result["indicators"]["adjclose"][0]["adjclose"]
              if "adjclose" in result["indicators"]
              else result["indicators"]["quote"][0]["close"])
    out = {}
    for stamp, close in zip(result["timestamp"], closes):
        if close is None:
            continue
        out[time.strftime("%Y-%m", time.gmtime(stamp))] = close
    # Splits are kept alongside the prices. The closes are split-adjusted but
    # a filing's share count is not, so anything that multiplies the two --
    # a historical market value -- needs the split history to put them on the
    # same basis.
    splits = []
    for row in (result.get("events", {}).get("splits") or {}).values():
        splits.append({"date": time.strftime("%Y-%m-%d", time.gmtime(row["date"])),
                       "factor": row["numerator"] / row["denominator"]})
    payload = {"closes": out, "splits": sorted(splits, key=lambda s: s["date"])}
    json.dump(payload, open(path, "w"))
    return payload


def _legacy(payload):
    """Accepts both the old bare-closes cache and the new payload shape."""
    if isinstance(payload, dict) and "closes" in payload:
        return payload
    return {"closes": payload, "splits": []}


def price_at(series, when):
    """Close for the month of `when`, or the most recent month before it."""
    key = when.strftime("%Y-%m")
    if key in series:
        return series[key]
    earlier = [k for k in series if k <= key]
    return series[max(earlier)] if earlier else None


def shares_at(facts, asof):
    node = facts["facts"].get("dei", {}).get("EntityCommonStockSharesOutstanding")
    if not node:
        return None
    rows = [e for e in node["units"].get("shares", [])
            if e.get("form") in ("10-K", "10-Q") and e.get("filed", "9999") <= asof]
    return max(rows, key=lambda e: e["end"])["val"] if rows else None


def signal(ticker, facts, sector, asof, price_series):
    """The score a user would have seen on `asof`, plus what followed."""
    panel = edgar.panel(facts, asof)
    usable = [d for d in sorted(panel)
              if "assets" in panel[d] and "revenue" in panel[d]]
    if len(usable) < 12:
        return None
    latest = usable[-1]
    analysis = M.analyze(panel, latest, sector)
    if analysis["coverage"] < 0.75:
        return None

    # A minimal package -- enough for the business pillars, which need no price.
    pkg = {"company": {"ticker": ticker, "sector_bucket": sector},
           "latest_metrics": analysis["metrics"],
           "scores": analysis["scores"],
           "trends": _trends(panel, sector, usable),
           "periods_available": len(panel),
           "data_coverage": analysis["coverage"],
           "data_gaps": analysis["missing"],
           "not_applicable_for_sector": analysis["not_applicable"],
           "equity_negative": analysis["notes"].get("equity_negative", False),
           "equity_thin": analysis["notes"].get("equity_thin", False)}

    pillars = {p["name"]: p["score"] for p in
               (V.quality(pkg, None), V.safety(pkg, None), V.earnings_quality(pkg))}
    scored = [v for v in pillars.values() if v is not None]
    if not scored:
        return None
    business = min(sum(scored) / len(scored), min(scored) + 20)

    asof_date = date(*map(int, asof.split("-")))
    entry = price_at(price_series, asof_date)
    exit_price = price_at(price_series, asof_date + timedelta(days=30 * HOLD_MONTHS))
    if not entry or not exit_price:
        return None

    shares = shares_at(facts, asof)
    fcf = analysis["metrics"].get("fcf_ttm")
    fcf_yield = (fcf / (entry * shares)) if (shares and fcf and fcf > 0) else None

    return {"ticker": ticker, "asof": asof, "sector": sector,
            "period_used": latest,
            "business_score": round(business, 1),
            "quality": pillars.get("Kalite"),
            "safety": pillars.get("Güvenlik"),
            "earnings_quality": pillars.get("Kâr kalitesi"),
            "f_score": (analysis["scores"].get("piotroski") or {}).get("score"),
            "accrual_ratio": analysis["metrics"].get("accrual_ratio"),
            "roic": analysis["metrics"].get("roic"),
            "fcf_yield": fcf_yield,
            "forward_return": exit_price / entry - 1}


def _trends(panel, sector, usable):
    """Only the trend keys the pillars read, computed point-in-time."""
    keys = ["roic", "operating_margin", "fcf_margin"]
    out = {}
    window = usable[-12:]
    for key in keys:
        series = []
        for d in window:
            snap = M.snapshot(panel, d)
            if snap.get(key) is not None:
                series.append((d, snap[key]))
        if len(series) >= 8:
            label, before, recent = report._direction([v for _, v in series], key)
            out[key] = {"series": series, "direction": label,
                        "prior_4q_avg": before, "recent_4q_avg": recent}
    return out


def quarter_ends(start_year, end_year):
    out = []
    for year in range(start_year, end_year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            out.append("%04d-%02d-%02d" % (year, month, day))
    return out


def run(universe=None, start=2013, end=2025):
    universe = universe or UNIVERSE
    bench = prices(BENCHMARK)["closes"]
    dates = quarter_ends(start, end)
    rows, skipped = [], 0

    for ticker in universe:
        try:
            cik, _ = edgar.resolve_cik(ticker)
            facts = edgar.companyfacts(cik)
            sector = edgar.sector(edgar.profile(cik)["sic"])
            series = prices(ticker)["closes"]
        except Exception as exc:
            print("  %s atlandi: %s" % (ticker, exc))
            continue
        for asof in dates:
            try:
                row = signal(ticker, facts, sector, asof, series)
            except Exception:
                row = None
            if not row:
                skipped += 1
                continue
            asof_date = date(*map(int, asof.split("-")))
            b0 = price_at(bench, asof_date)
            b1 = price_at(bench, asof_date + timedelta(days=30 * HOLD_MONTHS))
            row["benchmark_return"] = (b1 / b0 - 1) if b0 and b1 else None
            if row["benchmark_return"] is None:
                skipped += 1
                continue
            row["excess_return"] = row["forward_return"] - row["benchmark_return"]
            rows.append(row)
        print("  %-6s %d gozlem" % (ticker, sum(1 for r in rows if r["ticker"] == ticker)))

    return rows, skipped


def buckets(rows, key, edges):
    """Groups observations by a signal value and reports forward excess return."""
    out = []
    for lo, hi in zip(edges, edges[1:]):
        sel = [r for r in rows
               if r.get(key) is not None and lo <= r[key] < hi]
        if not sel:
            continue
        excess = sorted(r["excess_return"] for r in sel)
        n = len(excess)
        out.append({
            "range": "%.2f - %.2f" % (lo, hi),
            "n": n,
            "mean_excess": round(sum(excess) / n, 4),
            "median_excess": round(excess[n // 2], 4),
            "win_rate": round(sum(1 for e in excess if e > 0) / n, 3),
        })
    return out


def spearman(rows, key):
    """Rank correlation between a signal and the forward excess return.

    This is the question that matters for a scoring product: does a higher
    score correspond to a higher return? A rho near zero means the score
    orders nothing, whatever its bucket averages look like.
    """
    sel = [(r[key], r["excess_return"]) for r in rows if r.get(key) is not None]
    n = len(sel)
    if n < 50:
        return None
    def ranks(vals):
        order = sorted(range(n), key=lambda i: vals[i])
        out = [0] * n
        for pos, i in enumerate(order):
            out[i] = pos
        return out
    a = ranks([x for x, _ in sel])
    b = ranks([y for _, y in sel])
    d2 = sum((x - y) ** 2 for x, y in zip(a, b))
    return round(1 - 6 * d2 / (n * (n * n - 1)), 4)


def cohort(rows, predicate, name, baseline):
    import statistics as st
    sel = [r for r in rows if predicate(r)]
    if len(sel) < 25:
        return {"name": name, "n": len(sel), "insufficient": True}
    ex = sorted(r["excess_return"] for r in sel)
    n = len(ex)
    mean = st.mean(ex)
    sd = st.stdev(ex)
    return {"name": name, "n": n,
            "mean_excess": round(mean, 4),
            "vs_universe": round(mean - baseline, 4),
            "median_excess": round(ex[n // 2], 4),
            "win_rate": round(sum(1 for e in ex if e > 0) / n, 3),
            "t_stat": round(mean / (sd / n ** 0.5), 2)}


def independent(rows):
    """One observation per company per year.

    A 12-month forward return sampled quarterly overlaps three times over,
    so the quarterly panel massively overstates how much independent
    evidence there is. Restricting to one date a year does not fix the
    cross-sectional correlation within a year, but it removes the worst of
    the double counting.
    """
    return [r for r in rows if r["asof"].endswith("-12-31")]


def summarise(rows):
    import statistics as st
    ind = independent(rows)
    baseline = st.mean(r["excess_return"] for r in ind)
    tests = [
        (lambda r: r["business_score"] >= 70, "İşletme skoru >= 70"),
        (lambda r: r["business_score"] < 50, "İşletme skoru < 50"),
        (lambda r: (r.get("accrual_ratio") or 0) < -0.06, "Tahakkuk < -%6"),
        (lambda r: (r.get("accrual_ratio") or -1) > -0.02, "Tahakkuk > -%2"),
        (lambda r: (r.get("f_score") or 0) >= 7, "F-Score >= 7"),
        (lambda r: (r.get("f_score") or 9) <= 5, "F-Score <= 5"),
        (lambda r: r.get("fcf_yield") is not None and r["fcf_yield"] < 0.02,
         "FCF getirisi < %2"),
        (lambda r: r.get("fcf_yield") is not None and r["fcf_yield"] >= 0.05,
         "FCF getirisi >= %5"),
    ]
    return {
        "observations": len(rows),
        "independent_observations": len(ind),
        "companies": len({r["ticker"] for r in rows}),
        "span": [min(r["asof"] for r in rows), max(r["asof"] for r in rows)],
        "universe_mean_excess": round(baseline, 4),
        "rank_correlations": {k: spearman(ind, k) for k in
                              ("business_score", "quality", "safety",
                               "earnings_quality", "f_score", "fcf_yield",
                               "accrual_ratio", "roic")},
        "cohorts": [cohort(ind, p, n, baseline) for p, n in tests],
        "biases": [
            "Survivorship: evren bugun mevcut sirketlerden olusuyor, bu yuzden "
            "her kovanin getirisi yukari sapmali. Kovalar arasi karsilastirma "
            "gecerli, mutlak seviyeler degil.",
            "Tek rejim: 2013-2025 ABD buyuk sermayeli boga piyasasi.",
            "Ayni yil icindeki gozlemler kesitsel olarak korelasyonlu, bu "
            "yuzden t degerleri hala iyimser.",
            "Islem maliyeti, pozisyon buyuklugu ve temettu yeniden yatirimi "
            "modellenmedi (fiyatlar duzeltilmis kapanis).",
        ],
    }


if __name__ == "__main__":
    import statistics as st

    rows, skipped = run()
    json.dump(rows, open(os.path.join(CACHE, "..", "backtest_rows.json"), "w"))
    s = summarise(rows)

    print("\n%d gozlem / %d bagimsiz / %d sirket / %s -> %s"
          % (s["observations"], s["independent_observations"], s["companies"],
             *s["span"]))
    print("evren ortalama fazla getirisi: %+.2f%%\n"
          % (s["universe_mean_excess"] * 100))

    print("Siralama gucu (Spearman rho, bagimsiz gozlemler):")
    for key, rho in s["rank_correlations"].items():
        mark = "" if rho is None or abs(rho) < 0.08 else "  <- anlamli yon"
        print("  %-18s %s%s" % (key, rho, mark))

    print("\nKohortlar:")
    for c in s["cohorts"]:
        if c.get("insufficient"):
            print("  %-24s n=%-4d yetersiz" % (c["name"], c["n"]))
            continue
        print("  %-24s n=%-4d ort %+6.2f%% (evrene gore %+6.2f%%) "
              "medyan %+6.2f%% kazanma %3.0f%% t=%+.2f"
              % (c["name"], c["n"], c["mean_excess"] * 100, c["vs_universe"] * 100,
                 c["median_excess"] * 100, c["win_rate"] * 100, c["t_stat"]))

    print("\nYanliliklar:")
    for b in s["biases"]:
        print("  - %s" % b)
