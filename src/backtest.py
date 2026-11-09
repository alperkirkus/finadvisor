"""Does the signal actually predict anything?

The verdict thresholds in `verdict.py` are chosen from the literature, not
measured on this data. This module measures them: it rebuilds each company's
evidence package as it stood on a past date with the same builder the product
uses (`report.build`), values it with point-in-time market inputs, scores it
with `verdict.assess`, and compares the score with the return that followed.
The number tested is the number the screen orders by (`ranking.overall_score`).

Two biases are removed by construction and one is not.

Removed: lookahead, because a signal may only use filings whose `filed` date
precedes the decision date, and prices, share counts, rates and betas no later
than that month; and restatement, because a revision is itself a later filing
and so is invisible to an earlier as-of date.

Not removed: survivorship. The universe is companies that exist today, which
tilts every bucket's return upward. The comparison between names on the same
date is still meaningful -- the bias applies to all of them -- but absolute
return levels are optimistic.

The headline statistic is the cross-sectional information coefficient: the
rank correlation between signal and forward return across the names of one
date, averaged over dates. Pooling every date into one correlation lets a
good or bad year for the whole market masquerade as signal.

Dates are split into a development window and a holdout. Every decision about
weights or signals is made on the development window; the holdout is printed
only on request, and every request is logged.
"""
import argparse
import csv
import io
import json
import math
import os
import subprocess
import time
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

import edgar
import report
import valuation as V
import verdict as VD

UA = "Mozilla/5.0 (FinAdvisor research)"
PRICE_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
             "%s?range=20y&interval=1mo&events=split")
BENCHMARK = "%5EGSPC"
DATA = os.path.join(os.path.dirname(__file__), "..", "data")
CACHE = os.path.join(DATA, "prices")
MACRO = os.path.join(DATA, "macro")
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
FRENCH = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FRENCH_FILES = {"ff5": "F-F_Research_Data_5_Factors_2x3_CSV.zip",
                "mom": "F-F_Momentum_Factor_CSV.zip"}
HOLDOUT_LOG = os.path.join(DATA, "holdout_log.json")

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
HORIZONS = (1, 3, 6, 12)
DEV_END = "2019-12"          # last month whose return belongs to development
HOLDOUT_START = "2020-01"
MIN_CROSS_SECTION = 20       # fewer names than this and a date's IC is noise
QUINTILES = 5

SIGNALS = ["overall", "business_score", "quality", "safety",
           "earnings_quality", "valuation", "accrual_ratio", "f_score",
           "fcf_yield", "roic"]
PILLAR_KEYS = {"Kalite": "quality", "Güvenlik": "safety",
               "Kâr kalitesi": "earnings_quality", "Değerleme": "valuation"}


# --------------------------------------------------------------------------
# Data


def prices(symbol, need_raw=False):
    """Monthly closes as {YYYY-MM: close}, cached on disk.

    `closes` are dividend- and split-adjusted (total return); `raw` are
    split-adjusted only, which is what a market value needs -- a dividend
    adjustment lowers every past price and would understate past market caps.
    A cache written before `raw` existed is refetched when `raw` is needed.
    """
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, symbol.replace("%5E", "_") + ".json")
    if os.path.exists(path):
        payload = _legacy(json.load(open(path)))
        if not need_raw or payload.get("raw"):
            return payload
    req = urllib.request.Request(PRICE_URL % symbol, headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())
    result = d["chart"]["result"][0]
    quote_close = result["indicators"]["quote"][0]["close"]
    closes = (result["indicators"]["adjclose"][0]["adjclose"]
              if "adjclose" in result["indicators"] else quote_close)
    out, raw = {}, {}
    for stamp, close, plain in zip(result["timestamp"], closes, quote_close):
        month = time.strftime("%Y-%m", time.gmtime(stamp))
        if close is not None and close > 0:
            out[month] = close
        if plain is not None and plain > 0:
            raw[month] = plain
    # Splits are kept alongside the prices. The closes are split-adjusted but
    # a filing's share count is not, so anything that multiplies the two --
    # a historical market value -- needs the split history to put them on the
    # same basis.
    splits = []
    for row in (result.get("events", {}).get("splits") or {}).values():
        splits.append({"date": time.strftime("%Y-%m-%d", time.gmtime(row["date"])),
                       "factor": row["numerator"] / row["denominator"]})
    payload = {"closes": out, "raw": raw,
               "splits": sorted(splits, key=lambda s: s["date"])}
    json.dump(payload, open(path, "w"))
    return payload


def _legacy(payload):
    """Accepts both the old bare-closes cache and the new payload shape."""
    if isinstance(payload, dict) and "closes" in payload:
        return payload
    return {"closes": payload, "splits": []}


def risk_free_series():
    """10-year Treasury yield at each month end, {YYYY-MM: decimal}. FRED DGS10."""
    os.makedirs(MACRO, exist_ok=True)
    path = os.path.join(MACRO, "DGS10.csv")
    if not os.path.exists(path):
        # FRED stalls requests carrying a browser-like User-Agent; the
        # library default is answered at once.
        _download(FRED_URL, path, user_agent=None)
    out = {}
    with open(path) as fh:
        for row in csv.reader(fh):
            if len(row) != 2 or row[1] in ("", "."):
                continue
            try:
                value = float(row[1])
            except ValueError:
                continue          # header line
            if not math.isfinite(value):
                continue
            out[row[0][:7]] = value / 100     # rows are ascending: last wins
    if not out:
        raise ValueError("DGS10 cache at %s has no usable rows" % path)
    return out


def factors():
    """Fama-French five factors plus momentum, monthly, in decimals.

    {YYYY-MM: {"Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF", "Mom"}}. Only
    months present in both files are returned.
    """
    os.makedirs(MACRO, exist_ok=True)
    tables = {}
    for key, name in FRENCH_FILES.items():
        path = os.path.join(MACRO, name)
        if not os.path.exists(path):
            _download(FRENCH + name, path)
        with zipfile.ZipFile(path) as zf:
            text = zf.read(zf.namelist()[0]).decode("latin-1")
        tables[key] = _french_monthly(text)
    out = {}
    for month, row in tables["ff5"].items():
        if month in tables["mom"]:
            out[month] = {**row, **tables["mom"][month]}
    if not out:
        raise ValueError("factor files parsed to zero shared months")
    return out


def _download(url, path, user_agent=UA):
    """Writes only a complete response, so a failed fetch leaves no stub file."""
    headers = {"User-Agent": user_agent} if user_agent else {}
    body = urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                  timeout=60).read()
    if not body:
        raise ValueError("empty response from %s" % url)
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(body)
    os.replace(tmp, path)


def _french_monthly(text):
    """The monthly block of a Ken French CSV: the first table, rows YYYYMM."""
    out, header = {}, None
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(",")]
        if header is None:
            if len(cells) > 1 and cells[0] == "" and cells[1]:
                header = cells[1:]
            continue
        if not cells[0]:
            if out:
                break             # the annual block follows a blank line
            continue
        if not (len(cells[0]) == 6 and cells[0].isdigit()):
            if out:
                break
            continue
        values = [float(c) / 100 for c in cells[1:len(header) + 1]]
        out["%s-%s" % (cells[0][:4], cells[0][4:])] = dict(zip(header, values))
    return out


def shares_at(facts, asof):
    """Cover-page share count filed by `asof`, with its period end."""
    node = facts["facts"].get("dei", {}).get("EntityCommonStockSharesOutstanding")
    if not node:
        return None, None
    rows = [e for e in node["units"].get("shares", [])
            if e.get("form") in ("10-K", "10-Q") and e.get("filed", "9999") <= asof]
    if not rows:
        return None, None
    row = max(rows, key=lambda e: e["end"])
    return row["val"], row["end"]


def add_months(month, n):
    year, mon = int(month[:4]), int(month[5:7]) + n
    year += (mon - 1) // 12
    mon = (mon - 1) % 12 + 1
    return "%04d-%02d" % (year, mon)


def quarter_ends(start_year, end_year):
    out = []
    for year in range(start_year, end_year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            out.append("%04d-%02d-%02d" % (year, month, day))
    return out


# --------------------------------------------------------------------------
# One observation


def signal(ticker, facts, asof, payload, bench, rf_series, skips):
    """The score the product would have shown on `asof`, plus what followed.

    Returns None and counts the reason in `skips` when the date cannot be
    scored; a skipped date is never filled with a substitute value.
    """
    import ranking

    try:
        pkg = report.build(ticker, quarters=40, asof=asof, facts=facts)
    except ValueError:
        skips["no usable period"] += 1
        return None
    if pkg["periods_available"] < 12 or pkg["data_coverage"] < 0.75:
        skips["thin data"] += 1
        return None

    month = asof[:7]
    closes, raw = payload["closes"], payload.get("raw") or {}
    if month not in closes or month not in raw:
        skips["no price at as-of"] += 1
        return None

    shares, shares_end = shares_at(facts, asof)
    if shares:
        # Prices are split-adjusted to today; the filed count is not.
        for sp in payload["splits"]:
            if sp["date"] > shares_end:
                shares *= sp["factor"]

    val, val_error = None, None
    rf = rf_series.get(month)
    b = V.beta_asof(closes, bench, asof)
    if not shares:
        val_error = "no share count"
    elif rf is None:
        val_error = "no risk-free rate"
    elif b is None:
        val_error = "beta needs 36 months"
    else:
        market = {"asof": asof, "price": raw[month], "shares": shares,
                  "risk_free": rf, "beta": b}
        try:
            val = V.value(pkg, market)
        except Exception as exc:
            val_error = "valuation: %s" % exc

    a = VD.assess(pkg, val)
    pillars = {PILLAR_KEYS[p["name"]]: p["score"] for p in a["pillars"]
               if p["name"] in PILLAR_KEYS}

    m = pkg["latest_metrics"]
    fcf = m.get("fcf_ttm")
    fcf_yield = (fcf / (raw[month] * shares)
                 if shares and fcf and fcf > 0 else None)

    forward, bench_forward = {}, {}
    for h in HORIZONS:
        exit_month = add_months(month, h)
        if exit_month in closes:
            forward[h] = closes[exit_month] / closes[month] - 1
        if exit_month in bench and month in bench:
            bench_forward[h] = bench[exit_month] / bench[month] - 1

    return {"ticker": ticker, "asof": asof, "month": month,
            "sector": pkg["company"]["sector_bucket"],
            "period_used": pkg["as_of"],
            "verdict": a["verdict"],
            "overall": ranking.overall_score(a["business_score"],
                                             pillars.get("valuation")),
            "business_score": a["business_score"],
            **{k: pillars.get(k) for k in PILLAR_KEYS.values()},
            "valuation_error": val_error,
            "f_score": (pkg["scores"].get("piotroski") or {}).get("score"),
            "accrual_ratio": m.get("accrual_ratio"),
            "roic": m.get("roic"),
            "fcf_yield": fcf_yield,
            "forward": forward,
            "benchmark_forward": bench_forward}


def run(universe=None, start=2013, end=2025):
    universe = universe or UNIVERSE
    bench = prices(BENCHMARK)["closes"]
    rf_series = risk_free_series()
    dates = quarter_ends(start, end)
    rows, skips = [], Counter()

    for ticker in universe:
        try:
            cik, _ = edgar.resolve_cik(ticker)
            facts = edgar.companyfacts(cik)
            payload = prices(ticker, need_raw=True)
        except Exception as exc:
            print("  %s atlandi: %s" % (ticker, exc))
            skips["ticker unavailable"] += 1
            continue
        count = 0
        for asof in dates:
            try:
                row = signal(ticker, facts, asof, payload, bench, rf_series, skips)
            except Exception as exc:
                skips["error: %s" % type(exc).__name__] += 1
                continue
            if row:
                rows.append(row)
                count += 1
        print("  %-6s %d gozlem" % (ticker, count))

    _add_excess(rows)
    return rows, dict(skips)


def _add_excess(rows):
    """Forward return over the equal-weight mean of the same date's names.

    The cap-weighted S&P 500 is the wrong yardstick for an equal-weight set
    of mega caps: the gap between them is a size tilt, not a signal.
    """
    by_month = defaultdict(list)
    for r in rows:
        by_month[r["month"]].append(r)
    for group in by_month.values():
        for h in HORIZONS:
            vals = [r["forward"][h] for r in group if h in r["forward"]]
            if not vals:
                continue
            mean = sum(vals) / len(vals)
            for r in group:
                if h in r["forward"]:
                    r.setdefault("excess", {})[h] = r["forward"][h] - mean


def segment(month, h):
    """dev, holdout, or embargo: a dev observation's return must end by DEV_END."""
    if month >= HOLDOUT_START:
        return "holdout"
    if add_months(month, h) <= DEV_END:
        return "dev"
    return "embargo"


# --------------------------------------------------------------------------
# Statistics


def _avg_ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def _pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if not sxx or not syy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def rank_ic(pairs):
    """Spearman with average ranks for ties (F-Score is mostly ties)."""
    if len(pairs) < MIN_CROSS_SECTION:
        return None
    return _pearson(_avg_ranks([x for x, _ in pairs]),
                    _avg_ranks([y for _, y in pairs]))


def newey_west(series, lag):
    """Mean, its HAC standard error and t for an autocorrelated series."""
    n = len(series)
    if n < 8:
        return None
    mean = sum(series) / n
    dev = [x - mean for x in series]
    var = sum(d * d for d in dev) / n
    for l in range(1, lag + 1):
        cov = sum(dev[t] * dev[t - l] for t in range(l, n)) / n
        var += 2 * (1 - l / (lag + 1)) * cov
    se = math.sqrt(max(var, 0) / n)
    return {"mean": mean, "se": se, "t": mean / se if se else None, "n": n}


def _lag(h):
    """Quarterly as-of dates: an h-month return overlaps ceil(h/3)-1 neighbours."""
    return max(0, math.ceil(h / 3) - 1)


def _cross_sections(rows, key, h, seg):
    by_month = defaultdict(list)
    for r in rows:
        if segment(r["month"], h) != seg:
            continue
        x, y = r.get(key), (r.get("excess") or {}).get(h)
        if x is None or y is None:
            continue
        by_month[r["month"]].append((x, y))
    return dict(sorted(by_month.items()))


def ic_stats(rows, key, h, seg):
    sections = _cross_sections(rows, key, h, seg)
    ics, skipped = [], 0
    for month, pairs in sections.items():
        ic = rank_ic(pairs)
        if ic is None:
            skipped += 1
            continue
        ics.append(ic)
    nw = newey_west(ics, _lag(h))
    if not nw:
        return {"dates": len(ics), "skipped_dates": skipped, "insufficient": True}
    sd = math.sqrt(sum((x - nw["mean"]) ** 2 for x in ics) / (len(ics) - 1))
    return {"mean_ic": round(nw["mean"], 4),
            "ic_sd": round(sd, 4),
            "ic_ir": round(nw["mean"] / sd, 3) if sd else None,
            "positive_share": round(sum(1 for x in ics if x > 0) / len(ics), 3),
            "nw_se": round(nw["se"], 4),
            "nw_t": round(nw["t"], 2) if nw["t"] is not None else None,
            # Two-sided 5%, 80% power: 1.96 + 0.84 standard errors.
            "min_detectable_ic": round(2.80 * nw["se"], 4),
            "dates": len(ics), "skipped_dates": skipped,
            "avg_names": round(sum(len(p) for p in sections.values())
                               / max(1, len(sections)), 1)}


def quintile_stats(rows, key, h, seg):
    sections = _cross_sections(rows, key, h, seg)
    buckets = defaultdict(list)
    spreads = []
    for pairs in sections.values():
        if len(pairs) < MIN_CROSS_SECTION:
            continue
        pairs = sorted(pairs, key=lambda p: p[0])
        n = len(pairs)
        groups = defaultdict(list)
        for i, (_, y) in enumerate(pairs):
            groups[i * QUINTILES // n].append(y)
        means = {q: sum(v) / len(v) for q, v in groups.items()}
        for q, v in means.items():
            buckets[q].append(v)
        spreads.append(means[QUINTILES - 1] - means[0])
    nw = newey_west(spreads, _lag(h))
    if not nw:
        return {"insufficient": True, "dates": len(spreads)}
    return {"quintile_mean_excess": [round(sum(buckets[q]) / len(buckets[q]), 4)
                                     for q in range(QUINTILES)],
            "top_minus_bottom": round(nw["mean"], 4),
            "nw_t": round(nw["t"], 2) if nw["t"] is not None else None,
            "dates": len(spreads)}


def long_short_monthly(rows, key, payloads, hold=3):
    """Monthly top-minus-bottom quintile returns, formed each quarter end.

    Each quarter's portfolio is held for the `hold` months that follow, so the
    monthly series does not overlap and a plain regression is valid.
    """
    by_month = defaultdict(list)
    for r in rows:
        if r.get(key) is not None:
            by_month[r["month"]].append(r)
    out = {}
    for month, group in sorted(by_month.items()):
        if len(group) < MIN_CROSS_SECTION:
            continue
        group = sorted(group, key=lambda r: r[key])
        n = len(group)
        top = [r["ticker"] for i, r in enumerate(group) if i * QUINTILES // n == QUINTILES - 1]
        bottom = [r["ticker"] for i, r in enumerate(group) if i * QUINTILES // n == 0]
        for step in range(1, hold + 1):
            m1, m0 = add_months(month, step), add_months(month, step - 1)
            legs = []
            for names in (top, bottom):
                rets = [payloads[t]["closes"][m1] / payloads[t]["closes"][m0] - 1
                        for t in names
                        if m1 in payloads[t]["closes"] and m0 in payloads[t]["closes"]]
                legs.append(sum(rets) / len(rets) if rets else None)
            if None not in legs:
                out[m1] = legs[0] - legs[1]
    return out


def _solve(a, b):
    """Gauss-Jordan; returns (solution, inverse) of a small dense system."""
    n = len(a)
    m = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] + [b[i]]
         for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None, None
        m[col], m[pivot] = m[pivot], m[col]
        p = m[col][col]
        m[col] = [v / p for v in m[col]]
        for r in range(n):
            if r != col and m[r][col]:
                f = m[r][col]
                m[r] = [v - f * w for v, w in zip(m[r], m[col])]
    return [row[-1] for row in m], [row[n:2 * n] for row in m]


FACTOR_NAMES = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]


def factor_regression(series, ff):
    """OLS of a monthly long-short return on FF5 + momentum."""
    months = [m for m in sorted(series) if m in ff]
    n, k = len(months), len(FACTOR_NAMES) + 1
    if n < 24:
        return {"insufficient": True, "months": n}
    X = [[1.0] + [ff[m][f] for f in FACTOR_NAMES] for m in months]
    y = [series[m] for m in months]
    xtx = [[sum(X[t][i] * X[t][j] for t in range(n)) for j in range(k)]
           for i in range(k)]
    xty = [sum(X[t][i] * y[t] for t in range(n)) for i in range(k)]
    beta, inv = _solve(xtx, xty)
    if beta is None:
        return {"insufficient": True, "months": n, "reason": "singular"}
    resid = [y[t] - sum(beta[i] * X[t][i] for i in range(k)) for t in range(n)]
    s2 = sum(e * e for e in resid) / (n - k)
    se = [math.sqrt(max(inv[i][i] * s2, 0)) for i in range(k)]
    names = ["alpha"] + FACTOR_NAMES
    mean_y = sum(y) / n
    ss_tot = sum((v - mean_y) ** 2 for v in y)
    return {"months": n,
            "raw_mean_monthly": round(mean_y, 5),
            "alpha_monthly": round(beta[0], 5),
            "alpha_annual": round(beta[0] * 12, 4),
            "alpha_t": round(beta[0] / se[0], 2) if se[0] else None,
            "loadings": {names[i]: {"beta": round(beta[i], 3),
                                    "t": round(beta[i] / se[i], 2) if se[i] else None}
                         for i in range(1, k)},
            "r2": round(1 - sum(e * e for e in resid) / ss_tot, 3) if ss_tot else None}


# --------------------------------------------------------------------------
# Legacy statistics, kept so old and new runs can be compared. These pool
# December observations of every year and measure 12-month excess over the
# S&P 500, exactly as before; `verdict.py` reads their cohorts.


def _legacy_rows(rows):
    out = []
    for r in rows:
        if not r["asof"].endswith("-12-31"):
            continue
        f, b = r["forward"].get(HOLD_MONTHS), r["benchmark_forward"].get(HOLD_MONTHS)
        if f is None or b is None:
            continue
        out.append({**r, "excess_return": f - b})
    return out


def spearman(rows, key):
    """Pooled rank correlation (legacy definition)."""
    sel = [(r[key], r["excess_return"]) for r in rows if r.get(key) is not None]
    if len(sel) < 50:
        return None
    rho = _pearson(_avg_ranks([x for x, _ in sel]), _avg_ranks([y for _, y in sel]))
    return round(rho, 4) if rho is not None else None


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


LEGACY_COHORTS = [
    (lambda r: (r.get("business_score") or 0) >= 70, "İşletme skoru >= 70"),
    (lambda r: r.get("business_score") is not None and r["business_score"] < 50,
     "İşletme skoru < 50"),
    (lambda r: (r.get("accrual_ratio") or 0) < -0.06, "Tahakkuk < -%6"),
    (lambda r: (r.get("accrual_ratio") or -1) > -0.02, "Tahakkuk > -%2"),
    (lambda r: (r.get("f_score") or 0) >= 7, "F-Score >= 7"),
    (lambda r: (r.get("f_score") or 9) <= 5, "F-Score <= 5"),
    (lambda r: r.get("fcf_yield") is not None and r["fcf_yield"] < 0.02,
     "FCF getirisi < %2"),
    (lambda r: r.get("fcf_yield") is not None and r["fcf_yield"] >= 0.05,
     "FCF getirisi >= %5"),
]


# --------------------------------------------------------------------------
# Summary


def summarise(rows, skips, payloads, ff, segments=("dev",)):
    import statistics as st
    legacy = _legacy_rows(rows)
    baseline = st.mean(r["excess_return"] for r in legacy)
    out = {
        "observations": len(rows),
        "independent_observations": len(legacy),
        "companies": len({r["ticker"] for r in rows}),
        "span": [min(r["asof"] for r in rows), max(r["asof"] for r in rows)],
        "skipped": skips,
        "valuation_coverage": round(sum(1 for r in rows if r["valuation"] is not None)
                                    / len(rows), 3),
        "valuation_errors": dict(Counter(r["valuation_error"] for r in rows
                                         if r["valuation_error"])),
        "universe_mean_excess": round(baseline, 4),
        "rank_correlations": {k: spearman(legacy, k) for k in SIGNALS},
        "cohorts": [cohort(legacy, p, n, baseline) for p, n in LEGACY_COHORTS],
        "split": {"dev": "as-of months whose return ends by %s" % DEV_END,
                  "holdout": "as-of months from %s" % HOLDOUT_START,
                  "embargo": "dev-era months whose return reaches into the holdout",
                  "reported": list(segments)},
        "ic": {}, "quintiles": {}, "factor": {},
        "biases": [
            "Survivorship: evren bugun mevcut sirketlerden olusuyor; mutlak "
            "getiriler yukari sapmali, ayni tarihteki karsilastirma gecerli.",
            "Tek rejim: 2013-2025 ABD buyuk sermayeli boga piyasasi.",
            "Kucuk kesit: tarih basina yaklasik 50 sirket; min_detectable_ic "
            "bu evrenin olcebilecegi en kucuk etkiyi gosterir.",
            "Islem maliyeti ve pozisyon buyuklugu modellenmedi.",
            "Legacy kohortlar butun yillari (holdout dahil) havuzluyor; "
            "karar icin ic/quintiles/factor bolumlerinin dev kismi kullanilir.",
        ],
    }
    for seg in segments:
        out["ic"][seg] = {str(h): {k: ic_stats(rows, k, h, seg) for k in SIGNALS}
                          for h in HORIZONS}
        out["quintiles"][seg] = {str(h): {k: quintile_stats(rows, k, h, seg)
                                          for k in SIGNALS}
                                 for h in (3, HOLD_MONTHS)}
    for key in ("overall", "accrual_ratio"):
        series = long_short_monthly(rows, key, payloads)
        for seg in segments:
            if seg == "dev":
                part = {m: v for m, v in series.items() if m <= DEV_END}
            else:
                part = {m: v for m, v in series.items() if m >= HOLDOUT_START}
            out["factor"].setdefault(seg, {})[key] = factor_regression(part, ff)
    return out


def _log_holdout_look():
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, cwd=os.path.dirname(__file__)).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"],
                                    capture_output=True, text=True,
                                    cwd=os.path.dirname(__file__)).stdout.strip())
    except OSError:
        sha, dirty = None, None
    log = json.load(open(HOLDOUT_LOG)) if os.path.exists(HOLDOUT_LOG) else []
    log.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "git_sha": sha, "dirty": dirty})
    json.dump(log, open(HOLDOUT_LOG, "w"), indent=1)
    return len(log)


def _print(s):
    print("\n%d gozlem / %d legacy bagimsiz / %d sirket / %s -> %s"
          % (s["observations"], s["independent_observations"], s["companies"],
             *s["span"]))
    print("degerleme kapsami: %.0f%%  atlananlar: %s"
          % (s["valuation_coverage"] * 100, s["skipped"]))
    if s["valuation_errors"]:
        print("degerleme hatalari: %s" % s["valuation_errors"])

    for seg in s["split"]["reported"]:
        print("\n=== %s ===" % seg.upper())
        print("Kesitsel IC (esit agirlikli evrene gore fazla getiri):")
        print("  %-17s %s" % ("sinyal", "  ".join("%14s" % ("%day ic (t)" % h)
                                                  for h in HORIZONS)))
        for k in SIGNALS:
            cells = []
            for h in HORIZONS:
                c = s["ic"][seg][str(h)][k]
                cells.append("%14s" % ("-" if c.get("insufficient") else
                                       "%+.3f (%+.1f)" % (c["mean_ic"], c["nw_t"] or 0)))
            print("  %-17s %s" % (k, "  ".join(cells)))
        c = s["ic"][seg][str(HOLD_MONTHS)]["overall"]
        if not c.get("insufficient"):
            print("  12ay overall: %d tarih, tarih basina %.0f sirket, "
                  "tespit edilebilir min IC %.3f"
                  % (c["dates"], c["avg_names"], c["min_detectable_ic"]))

        print("\nBeslik dilimler, 12 ay (Q1 dusuk sinyal -> Q5 yuksek):")
        for k in SIGNALS:
            q = s["quintiles"][seg][str(HOLD_MONTHS)][k]
            if q.get("insufficient"):
                continue
            print("  %-17s %s  Q5-Q1 %+6.2f%% t=%+.2f"
                  % (k, " ".join("%+6.2f%%" % (v * 100)
                                 for v in q["quintile_mean_excess"]),
                     q["top_minus_bottom"] * 100, q["nw_t"] or 0))

        print("\nFaktor regresyonu (aylik Q5-Q1, FF5 + momentum):")
        for key, reg in s["factor"][seg].items():
            if reg.get("insufficient"):
                print("  %-14s yetersiz (%d ay)" % (key, reg["months"]))
                continue
            loads = " ".join("%s %+.2f" % (n, v["beta"]) for n, v in reg["loadings"].items())
            print("  %-14s ham %+.2f%%/ay  alpha %+.2f%%/ay t=%+.2f  R2 %.2f  [%s]"
                  % (key, reg["raw_mean_monthly"] * 100, reg["alpha_monthly"] * 100,
                     reg["alpha_t"] or 0, reg["r2"] or 0, loads))

    print("\nLegacy (Aralik, 12 ay, S&P'ye gore, butun yillar):")
    for key, rho in s["rank_correlations"].items():
        print("  %-17s %s" % (key, rho))
    for c in s["cohorts"]:
        if c.get("insufficient"):
            print("  %-24s n=%-4d yetersiz" % (c["name"], c["n"]))
            continue
        print("  %-24s n=%-4d ort %+6.2f%% (evrene gore %+6.2f%%) kazanma %3.0f%% t=%+.2f"
              % (c["name"], c["n"], c["mean_excess"] * 100, c["vs_universe"] * 100,
                 c["win_rate"] * 100, c["t_stat"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true",
                    help="also report the holdout window (logged)")
    args = ap.parse_args()

    rows, skips = run()
    if not rows:
        raise SystemExit("hic gozlem uretilmedi: %s" % skips)
    json.dump(rows, open(os.path.join(DATA, "backtest_rows.json"), "w"))
    payloads = {t: prices(t) for t in {r["ticker"] for r in rows}}
    segments = ("dev",)
    if args.holdout:
        n = _log_holdout_look()
        print("\nHOLDOUT acildi (kayitli bakis #%d)" % n)
        segments = ("dev", "holdout")
    s = summarise(rows, skips, payloads, factors(), segments)
    json.dump(s, open(os.path.join(DATA, "backtest_summary.json"), "w"),
              indent=1, ensure_ascii=False)
    _print(s)
