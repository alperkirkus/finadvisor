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
import insider
import report
import universe as U
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
HORIZONS = (1, 3, 6, 12, 24, 36)
DEV_END = "2019-12"          # last month whose return belongs to development
HOLDOUT_START = "2020-01"
MIN_CROSS_SECTION = 20       # fewer names than this and a date's IC is noise
QUINTILES = 5

SIGNALS = ["overall", "business_score", "quality", "safety",
           "earnings_quality", "valuation", "accrual_ratio", "f_score",
           "fcf_yield", "roic",
           "gross_profitability", "asset_growth", "net_issuance", "momentum",
           "earnings_yield", "multifactor", "sue", "revenue_surprise",
           "volatility", "upside", "dcf_upside", "vd_upside",
           "insider_buyers_6m", "insider_npr_12m"]

# Candidate signals from the literature, each with the sign its source
# predicts. The composite averages their within-sector percentiles with
# equal weight; nothing here is fitted to this data.
LITERATURE_SIGNS = {
    "gross_profitability": +1,   # Novy-Marx (2013)
    "asset_growth": -1,          # Cooper, Gulen & Schill (2008)
    "net_issuance": -1,          # Pontiff & Woodgate (2008)
    "momentum": +1,              # Jegadeesh & Titman (1993), 12-1 months
    "earnings_yield": +1,        # Basu (1977)
    "accrual_ratio": -1,         # Sloan (1996)
}
MIN_COMPONENTS = 3
PILLAR_KEYS = {"Kalite": "quality", "Güvenlik": "safety",
               "Kâr kalitesi": "earnings_quality", "Değerleme": "valuation"}


# --------------------------------------------------------------------------
# Data


def prices(symbol, need_raw=False, max_age_days=None):
    """Monthly closes as {YYYY-MM: close}, cached on disk.

    `closes` are dividend- and split-adjusted (total return); `raw` are
    split-adjusted only, which is what a market value needs -- a dividend
    adjustment lowers every past price and would understate past market caps.
    A cache written before `raw` existed is refetched when `raw` is needed,
    and one older than `max_age_days` is refetched when that is given (live
    valuation); the backtest leaves it None so a run never changes its data
    midway.
    """
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, symbol.replace("%5E", "_") + ".json")
    if os.path.exists(path):
        payload = _legacy(json.load(open(path)))
        fresh = (max_age_days is None or
                 time.time() - os.path.getmtime(path) <= max_age_days * 86400)
        if fresh and (not need_raw or payload.get("raw")):
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
    """Latest share count filed by `asof`, with its period end."""
    counts = edgar.share_counts(facts, asof)
    if not counts:
        return None, None
    end = max(counts)
    return counts[end], end


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


def signal(ticker, facts, asof, payload, bench, rf_series, skips, cik=None):
    """The score the product would have shown on `asof`, plus what followed.

    Returns None and counts the reason in `skips` when the date cannot be
    scored; a skipped date is never filled with a substitute value.
    """
    import ranking

    try:
        pkg = report.build(ticker, quarters=40, asof=asof, facts=facts, cik=cik)
    except ValueError:
        skips["no usable period"] += 1
        return None
    if pkg["periods_available"] < 12 or pkg["data_coverage"] < 0.75:
        skips["thin data"] += 1
        return None
    if pkg["stale_days"] > VD.STALE_DAYS:
        skips["stale package"] += 1
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
    ni = m.get("net_income_ttm")
    earnings_yield = ni / (raw[month] * shares) if shares and ni is not None else None
    gm, turnover = m.get("gross_margin"), m.get("asset_turnover")
    gross_profitability = gm * turnover if gm is not None and turnover else None
    start, prior = add_months(month, -12), add_months(month, -1)
    momentum = (closes[prior] / closes[start] - 1
                if prior in closes and start in closes else None)

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
            "volatility": (V.trailing_volatility(closes, month) or {}).get("annualized"),
            "business_score": a["business_score"],
            **{k: pillars.get(k) for k in PILLAR_KEYS.values()},
            "valuation_error": val_error,
            "f_score": (pkg["scores"].get("piotroski") or {}).get("score"),
            "accrual_ratio": m.get("accrual_ratio"),
            "roic": m.get("roic"),
            "fcf_yield": fcf_yield,
            "gross_profitability": gross_profitability,
            "asset_growth": _asset_growth(facts, asof),
            "net_issuance": edgar.net_issuance(facts, asof, payload["splits"]),
            "momentum": momentum,
            "earnings_yield": earnings_yield,
            "upside": (val or {}).get("upside_to_fair"),
            "fair_value_method": ("bank" if (val or {}).get("bank") else
                                  "reversion" if (val or {}).get("reversion") else
                                  "dcf" if (val or {}).get("upside_to_fair") is not None
                                  else None),
            "revenue_growth": m.get("revenue_growth_yoy"),
            "fcf_margin_trend": (pkg["trends"].get("fcf_margin") or {}).get("direction"),
            "revenue_trend": (pkg["trends"].get("revenue_ttm") or {}).get("direction"),
            "dcf_upside": (val or {}).get("dcf_upside"),
            "vd_upside": (round(val["value_driver"]["fair"] / raw[month] - 1, 4)
                          if (val or {}).get("value_driver") else None),
            **_insider(cik, asof),
            "sue": _surprise(facts, asof, "eps_diluted"),
            "revenue_surprise": _surprise(facts, asof, "revenue"),
            "forward": forward,
            "benchmark_forward": bench_forward}


def _insider(cik, asof):
    trades = _WORKER.get("insider")
    if trades is None or cik is None or str(cik) not in _WORKER["insider_covered"]:
        return {"insider_buyers_6m": None, "insider_npr_12m": None}
    return insider.signal(trades.get(str(cik)), asof)


def _days_between(a, b):
    from datetime import date
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _asset_growth(facts, asof):
    """Total assets against four quarters earlier, from filings by `asof`."""
    series = edgar.instant_series(facts, edgar.INSTANT["assets"], asof)
    dates = sorted(d for d, v in series.items() if v)
    if len(dates) < 2:
        return None
    now = dates[-1]
    earlier = [d for d in dates if 330 <= _days_between(d, now) <= 400]
    if not earlier:
        return None
    return series[now] / series[earlier[-1]] - 1


def _surprise(facts, asof, concept, history=8, min_history=6):
    """Standardized unexpected value under a seasonal random walk.

    (latest quarter - same quarter a year earlier) divided by the standard
    deviation of that year-over-year change over the preceding quarters
    (Foster, Olsen & Shevlin 1984; Bernard & Thomas 1989 for earnings,
    Jegadeesh & Livnat 2006 for revenue). Only quarters filed by `asof`
    are used, and a latest quarter older than five months is stale news
    and gets no value.
    """
    q = edgar.quarterly_flows(facts, edgar.DURATION[concept], asof)
    ends = sorted(q)
    if not ends or _days_between(ends[-1], asof) > 150:
        return None

    def year_ago(end):
        cands = [e for e in ends if 350 <= _days_between(e, end) <= 380]
        return cands[-1] if cands else None

    changes = []
    for end in ends:
        prior = year_ago(end)
        if prior is not None:
            changes.append((end, q[end] - q[prior]))
    if len(changes) < min_history + 1 or changes[-1][0] != ends[-1]:
        return None
    latest = changes[-1][1]
    past = [c for _, c in changes[-(history + 1):-1]]
    if len(past) < min_history:
        return None
    mean = sum(past) / len(past)
    sd = math.sqrt(sum((c - mean) ** 2 for c in past) / (len(past) - 1))
    if not sd or not math.isfinite(sd):
        return None
    value = latest / sd
    return value if math.isfinite(value) else None


def add_composite(rows):
    """Equal-weight average of the literature signals' within-sector percentiles.

    Percentiles are taken among the same date's names in the same sector
    bucket (or the whole date when the bucket has fewer than five), each
    flipped to the sign its source predicts. A row needs at least
    MIN_COMPONENTS signals; otherwise it gets no composite rather than one
    built from a single input.
    """
    by_month = defaultdict(list)
    for r in rows:
        by_month[r["month"]].append(r)
    for group in by_month.values():
        pct = defaultdict(dict)
        for key, sign in LITERATURE_SIGNS.items():
            have = [r for r in group if r.get(key) is not None]
            sectors = defaultdict(list)
            for r in have:
                sectors[r["sector"]].append(r)
            for members in sectors.values():
                pool = members if len(members) >= 5 else have
                if len(pool) < 2:
                    continue
                ranks = _avg_ranks([r[key] for r in pool])
                index = {id(r): rank for r, rank in zip(pool, ranks)}
                for r in members:
                    p = index[id(r)] / (len(pool) - 1)
                    pct[id(r)][key] = p if sign > 0 else 1 - p
        for r in group:
            parts = pct.get(id(r), {})
            r["multifactor"] = (sum(parts.values()) / len(parts)
                                if len(parts) >= MIN_COMPONENTS else None)


def legacy_universe():
    """The original 53 names, scored on every date (no membership filter)."""
    out = {}
    for ticker in UNIVERSE:
        try:
            out[ticker] = {"cik": edgar.resolve_cik(ticker)[0], "intervals": None}
        except KeyError:
            pass
    return out


_WORKER = {}


def _init_worker(start, end, universe_name="sp500"):
    # Insider trades are optional input: without the file, or for an issuer
    # the file was not built for, the insider columns stay None rather than
    # reading as "no insider bought".
    path = os.path.join(DATA, "insider", "trades_%s.json" % universe_name)
    if os.path.exists(path):
        payload = json.load(open(path))
        _WORKER["insider"] = payload["trades"]
        _WORKER["insider_covered"] = set(payload["covered"])
    else:
        _WORKER["insider"], _WORKER["insider_covered"] = None, set()
    _WORKER["bench"] = prices(BENCHMARK)["closes"]
    _WORKER["rf"] = risk_free_series()
    _WORKER["dates"] = quarter_ends(start, end)


def _score_ticker(item):
    """All as-of rows for one ticker; runs in a worker process."""
    ticker, rec = item
    skips = Counter()
    try:
        facts = edgar.companyfacts(rec["cik"])
        payload = prices(U.yahoo_symbol(ticker), need_raw=True)
    except Exception as exc:
        skips["ticker unavailable"] += 1
        return ticker, [], skips, "%s" % exc
    rows = []
    for asof in _WORKER["dates"]:
        if rec["intervals"] is not None and not U.is_member(rec["intervals"], asof):
            continue
        try:
            row = signal(ticker, facts, asof, payload, _WORKER["bench"],
                         _WORKER["rf"], skips, cik=rec["cik"])
        except Exception as exc:
            skips["error: %s" % type(exc).__name__] += 1
            continue
        if row:
            rows.append(row)
    return ticker, rows, skips, None


def run(universe, start=2013, end=2025, workers=None, universe_name="sp500"):
    """Scores every ticker of `universe` ({ticker: {cik, intervals}})."""
    from multiprocessing import Pool
    rows, skips, unavailable = [], Counter(), {}
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with Pool(workers, initializer=_init_worker,
              initargs=(start, end, universe_name)) as pool:
        for i, (ticker, got, sk, err) in enumerate(
                pool.imap_unordered(_score_ticker, sorted(universe.items())), 1):
            rows.extend(got)
            skips.update(sk)
            if err:
                unavailable[ticker] = err
            if i % 50 == 0 or i == len(universe):
                print("  %d/%d sirket, %d gozlem" % (i, len(universe), len(rows)))
    rows.sort(key=lambda r: (r["asof"], r["ticker"]))
    add_composite(rows)
    _add_excess(rows)
    return rows, dict(skips), unavailable


def membership_coverage(rows, start=2013, end=2025):
    """How many index members each date had, and how many were scored.

    The gap is the survivorship this backtest cannot close: members with no
    CIK, no price history or too little data on that date.
    """
    members = U.membership()
    scored = Counter(r["asof"] for r in rows)
    per_date = []
    for asof in quarter_ends(start, end):
        n = sum(1 for iv in members.values() if U.is_member(iv, asof))
        per_date.append((asof, n, scored.get(asof, 0)))
    avg_m = sum(n for _, n, _ in per_date) / len(per_date)
    avg_s = sum(s for _, _, s in per_date) / len(per_date)
    return {"avg_members": round(avg_m, 1), "avg_scored": round(avg_s, 1),
            "scored_share": round(avg_s / avg_m, 3) if avg_m else None,
            "first": per_date[0], "last": per_date[-1]}


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


def _cross_sections(rows, key, h, seg, with_sector=False):
    by_month = defaultdict(list)
    for r in rows:
        if segment(r["month"], h) != seg:
            continue
        x, y = r.get(key), (r.get("excess") or {}).get(h)
        if x is None or y is None:
            continue
        by_month[r["month"]].append((x, y, r["sector"]) if with_sector else (x, y))
    return dict(sorted(by_month.items()))


def sector_neutral_ic(triples):
    """Rank IC after removing each sector's mean rank from signal and return.

    What is left is whether the signal orders names *within* their sector;
    a signal that only sorts banks below software firms scores zero here.
    """
    if len(triples) < MIN_CROSS_SECTION:
        return None
    rx = _avg_ranks([t[0] for t in triples])
    ry = _avg_ranks([t[1] for t in triples])
    groups = defaultdict(list)
    for i, t in enumerate(triples):
        groups[t[2]].append(i)
    xs, ys = [], []
    for idx in groups.values():
        if len(idx) < 2:
            continue
        mx = sum(rx[i] for i in idx) / len(idx)
        my = sum(ry[i] for i in idx) / len(idx)
        xs.extend(rx[i] - mx for i in idx)
        ys.extend(ry[i] - my for i in idx)
    if len(xs) < MIN_CROSS_SECTION:
        return None
    return _pearson(xs, ys)


def ic_stats(rows, key, h, seg, neutral=False):
    sections = _cross_sections(rows, key, h, seg, with_sector=neutral)
    ics, skipped = [], 0
    for month, pairs in sections.items():
        ic = sector_neutral_ic(pairs) if neutral else rank_ic(pairs)
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


def _quintile_of(values):
    """Quintile index per value from average ranks, so tied values share a
    bucket and the result does not depend on row order."""
    n = len(values)
    return [min(QUINTILES - 1, int(r * QUINTILES / n)) for r in _avg_ranks(values)]


def _auc(scores, labels):
    """P(score of a non-event > score of an event), ties counted half."""
    ranks = _avg_ranks(scores)
    n1 = sum(labels)
    n0 = len(labels) - n1
    if n0 == 0 or n1 == 0:
        return None
    r0 = sum(r + 1 for r, lab in zip(ranks, labels) if not lab)
    return (r0 - n0 * (n0 + 1) / 2) / (n0 * n1)


def crash_stats(rows, key, seg, h=HOLD_MONTHS):
    """Does a higher signal mean fewer blow-ups?

    Two events per date: the bottom decile of that date's excess return
    (relative), and a 12-month fall of more than 25% (absolute). AUC above
    0.5 means higher-signal names were less likely to have one. Dates with
    fewer than three events are skipped.
    """
    out = {}
    for name in ("bottom_decile", "fall_25"):
        aucs = []
        by_month = defaultdict(list)
        for r in rows:
            if segment(r["month"], h) != seg or r.get(key) is None:
                continue
            ex, fwd = (r.get("excess") or {}).get(h), r["forward"].get(h)
            if ex is None or fwd is None:
                continue
            by_month[r["month"]].append((r[key], ex, fwd))
        for group in by_month.values():
            if len(group) < MIN_CROSS_SECTION:
                continue
            if name == "bottom_decile":
                cut = sorted(g[1] for g in group)[len(group) // 10]
                labels = [g[1] < cut for g in group]
            else:
                labels = [g[2] < -0.25 for g in group]
            if sum(labels) < 3:
                continue
            auc = _auc([g[0] for g in group], labels)
            if auc is not None:
                aucs.append(auc - 0.5)
        nw = newey_west(aucs, _lag(h))
        out[name] = ({"auc": round(0.5 + nw["mean"], 3),
                      "nw_t": round(nw["t"], 2) if nw["t"] is not None else None,
                      "dates": nw["n"]} if nw else {"insufficient": True,
                                                     "dates": len(aucs)})
    return out


def fair_value_table(rows):
    """Outcomes after each fair-value upside band, at 1, 2 and 3 years, per
    valuation method -- the bank P/B model and the cash-flow reversion model
    behave too differently to share one record.

    Descriptive base rates for the product, so every as-of date with a
    complete forward window is used (2013 onward, including the 2020+
    window the v2 holdout test already opened). Hit rate: the price moved at
    least as far as the target implied, in the target's direction.
    """
    methods = {}
    for method in ("bank", "reversion"):
        methods[method] = _fair_value_bands(
            [r for r in rows if r.get("fair_value_method") == method])
    months = [r["month"] for r in rows if r.get("upside") is not None]
    # What the average member returned in a year, averaged over dates: the
    # yardstick a target's annualised return has to beat to be worth having.
    by_month = defaultdict(list)
    for r in rows:
        if r["forward"].get(12) is not None:
            by_month[r["month"]].append(r["forward"][12])
    yearly = [sum(v) / len(v) for v in by_month.values() if v]
    return {"period": "%s–%s" % (min(months)[:4], max(months)[:4]) if months else None,
            "universe_annual_return": round(sum(yearly) / len(yearly), 4) if yearly else None,
            "methods": methods}


def _fair_value_bands(rows):
    out = {}
    for lo, hi, name in VD.UPSIDE_BANDS:
        cells = {}
        for h in VD.FV_HORIZONS:
            sel = [r for r in rows if r.get("upside") is not None
                   and lo <= r["upside"] < hi and h in r["forward"]
                   and h in (r.get("excess") or {})]
            if len(sel) < 50:
                continue
            by_month = defaultdict(list)
            for r in sel:
                by_month[r["month"]].append(r["excess"][h])
            nw = newey_west([sum(v) / len(v) for v in by_month.values()], _lag(h))
            hit = [(r["forward"][h] >= r["upside"]) if r["upside"] >= 0
                   else (r["forward"][h] <= r["upside"]) for r in sel]
            raw = sorted(r["forward"][h] for r in sel)
            cells[str(h)] = {"n": len(sel),
                             "hit_rate": round(sum(hit) / len(hit), 3),
                             "mean_excess": round(nw["mean"], 4) if nw else None,
                             "t": round(nw["t"], 2) if nw and nw["t"] is not None else None,
                             "median_return": round(raw[len(raw) // 2], 4)}
        out[name] = cells
    return out


def crash_table(rows, h=HOLD_MONTHS):
    """Development-window base rates of a >25% fall, per risk cell."""
    cells = defaultdict(list)
    dev = [r for r in rows if segment(r["month"], h) == "dev"
           and r["forward"].get(h) is not None]
    for r in dev:
        key = VD.risk_cell(r.get("volatility"))
        if key:
            cells[key].append(r["forward"][h] < -0.25)
    total = [r["forward"][h] < -0.25 for r in dev]
    return {"segment": "dev", "horizon_months": h,
            "high_volatility": VD.HIGH_VOLATILITY,
            "universe_rate": round(sum(total) / len(total), 4) if total else None,
            "universe_n": len(total),
            "cells": {k: {"n": len(v), "fall_25": round(sum(v) / len(v), 4)}
                      for k, v in sorted(cells.items())}}


def quintile_stats(rows, key, h, seg):
    sections = _cross_sections(rows, key, h, seg)
    buckets = defaultdict(list)
    spreads = []
    for pairs in sections.values():
        if len(pairs) < MIN_CROSS_SECTION:
            continue
        groups = defaultdict(list)
        for q, (_, y) in zip(_quintile_of([x for x, _ in pairs]), pairs):
            groups[q].append(y)
        if 0 not in groups or QUINTILES - 1 not in groups:
            continue
        means = {q: sum(v) / len(v) for q, v in groups.items()}
        for q, v in means.items():
            buckets[q].append(v)
        spreads.append(means[QUINTILES - 1] - means[0])
    nw = newey_west(spreads, _lag(h))
    if not nw:
        return {"insufficient": True, "dates": len(spreads)}
    return {"quintile_mean_excess": [round(sum(buckets[q]) / len(buckets[q]), 4)
                                     if buckets[q] else None
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
        qs = _quintile_of([r[key] for r in group])
        top = [r["ticker"] for q, r in zip(qs, group) if q == QUINTILES - 1]
        bottom = [r["ticker"] for q, r in zip(qs, group) if q == 0]
        if not top or not bottom:
            continue
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
            "Survivorship: sonradan satin alinan veya borsadan cikan uyelerin "
            "cogunun CIK'i veya fiyati yok; mutlak getiriler yukari sapmali, "
            "ayni tarihteki karsilastirma daha az etkilenir.",
            "Tek rejim: 2013-2025 ABD buyuk sermayeli boga piyasasi.",
            "Kesit boyutu sinirli: min_detectable_ic bu evrenin "
            "olcebilecegi en kucuk etkiyi gosterir.",
            "Islem maliyeti ve pozisyon buyuklugu modellenmedi.",
            "Legacy kohortlar butun yillari (holdout dahil) havuzluyor; "
            "karar icin ic/quintiles/factor bolumlerinin dev kismi kullanilir.",
        ],
    }
    out["crash_table"] = crash_table(rows)
    out["fair_value_table"] = fair_value_table(rows)
    out["ic_sector_neutral"] = {}
    out["crash"] = {}
    for seg in segments:
        out["crash"][seg] = {k: crash_stats(rows, k, seg) for k in SIGNALS}
        out["ic"][seg] = {str(h): {k: ic_stats(rows, k, h, seg) for k in SIGNALS}
                          for h in HORIZONS}
        out["ic_sector_neutral"][seg] = {
            str(h): {k: ic_stats(rows, k, h, seg, neutral=True) for k in SIGNALS}
            for h in (3, HOLD_MONTHS)}
        out["quintiles"][seg] = {str(h): {k: quintile_stats(rows, k, h, seg)
                                          for k in SIGNALS}
                                 for h in (3, HOLD_MONTHS)}
    for key in ("overall", "accrual_ratio", "multifactor", "gross_profitability",
                "asset_growth", "net_issuance", "earnings_yield", "sue",
                "revenue_surprise"):
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
    u = s.get("universe") or {}
    if u.get("membership"):
        m = u["membership"]
        print("endeks uyeligi: tarih basina ort %.0f uye, %.0f skorlandi (%.0f%%); "
              "%d uye CIK yok, %d fiyat/veri yok"
              % (m["avg_members"], m["avg_scored"], m["scored_share"] * 100,
                 u["unresolved_cik"], len(u["unavailable"])))

    for seg in s["split"]["reported"]:
        print("\n=== %s ===" % seg.upper())
        print("Kesitsel IC (esit agirlikli evrene gore fazla getiri):")
        print("  %-20s %s" % ("sinyal", "  ".join("%14s" % ("%day ic (t)" % h)
                                                  for h in HORIZONS)))
        for k in SIGNALS:
            cells = []
            for h in HORIZONS:
                c = s["ic"][seg][str(h)][k]
                cells.append("%14s" % ("-" if c.get("insufficient") else
                                       "%+.3f (%+.1f)" % (c["mean_ic"], c["nw_t"] or 0)))
            print("  %-20s %s" % (k, "  ".join(cells)))
        c = s["ic"][seg][str(HOLD_MONTHS)]["overall"]
        if not c.get("insufficient"):
            print("  12ay overall: %d tarih, tarih basina %.0f sirket, "
                  "tespit edilebilir min IC %.3f"
                  % (c["dates"], c["avg_names"], c["min_detectable_ic"]))

        print("\nSektor-notr IC (sektor ici siralama):")
        print("  %-20s %16s %16s" % ("sinyal", "3ay ic (t)", "12ay ic (t)"))
        for k in SIGNALS:
            cells = []
            for h in (3, HOLD_MONTHS):
                c = s["ic_sector_neutral"][seg][str(h)][k]
                cells.append("%16s" % ("-" if c.get("insufficient") else
                                       "%+.3f (%+.1f)" % (c["mean_ic"], c["nw_t"] or 0)))
            print("  %-20s %s" % (k, " ".join(cells)))

        print("\nCokus riski, 12 ay (AUC>0.5: yuksek sinyal = daha az cokus):")
        print("  %-20s %18s %18s" % ("sinyal", "alt %10 (t)", "-%25 dusus (t)"))
        for k in SIGNALS:
            c = s["crash"][seg][k]
            cells = ["%18s" % ("-" if c[n].get("insufficient") else
                               "%.3f (%+.1f)" % (c[n]["auc"], c[n]["nw_t"] or 0))
                     for n in ("bottom_decile", "fall_25")]
            print("  %-20s %s" % (k, " ".join(cells)))

        print("\nBeslik dilimler, 12 ay (Q1 dusuk sinyal -> Q5 yuksek):")
        for k in SIGNALS:
            q = s["quintiles"][seg][str(HOLD_MONTHS)][k]
            if q.get("insufficient"):
                continue
            print("  %-20s %s  Q5-Q1 %+6.2f%% t=%+.2f"
                  % (k, " ".join("%+6.2f%%" % (v * 100) if v is not None else "      -"
                                 for v in q["quintile_mean_excess"]),
                     q["top_minus_bottom"] * 100, q["nw_t"] or 0))

        print("\nFaktor regresyonu (aylik Q5-Q1, FF5 + momentum):")
        for key, reg in s["factor"][seg].items():
            if reg.get("insufficient"):
                print("  %-20s yetersiz (%d ay)" % (key, reg["months"]))
                continue
            loads = " ".join("%s %+.2f" % (n, v["beta"]) for n, v in reg["loadings"].items())
            print("  %-20s ham %+.2f%%/ay  alpha %+.2f%%/ay t=%+.2f  R2 %.2f  [%s]"
                  % (key, reg["raw_mean_monthly"] * 100, reg["alpha_monthly"] * 100,
                     reg["alpha_t"] or 0, reg["r2"] or 0, loads))

    print("\nLegacy (Aralik, 12 ay, S&P'ye gore, butun yillar):")
    for key, rho in s["rank_correlations"].items():
        print("  %-20s %s" % (key, rho))
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
    ap.add_argument("--universe", choices=("sp500", "midsmall", "legacy"),
                    default="sp500",
                    help="point-in-time S&P 500 members, S&P 400/600 members, "
                         "or the original 53 names")
    args = ap.parse_args()

    if args.universe == "legacy":
        uni, unresolved = legacy_universe(), []
    elif args.universe == "midsmall":
        uni, unresolved, _ = U.midsmall_universe()
    else:
        uni, unresolved = U.backtest_universe()
    print("%s evreni: %d sirket (%d CIK cozulemedi)"
          % (args.universe, len(uni), len(unresolved)))
    rows, skips, unavailable = run(uni, universe_name=args.universe)
    if not rows:
        raise SystemExit("hic gozlem uretilmedi: %s" % skips)
    # The product reads backtest_summary.json for its evidence lines, and
    # that evidence is about S&P 500 members; other universes write to their
    # own files so a research run never changes what the verdict cites.
    suffix = "" if args.universe == "sp500" else "_" + args.universe
    json.dump(rows, open(os.path.join(DATA, "backtest_rows%s.json" % suffix), "w"))
    payloads = {t: prices(U.yahoo_symbol(t)) for t in {r["ticker"] for r in rows}}
    segments = ("dev",)
    if args.holdout:
        n = _log_holdout_look()
        print("\nHOLDOUT acildi (kayitli bakis #%d)" % n)
        segments = ("dev", "holdout")
    s = summarise(rows, skips, payloads, factors(), segments)
    s["universe"] = {"name": args.universe, "companies": len(uni),
                     "unresolved_cik": len(unresolved),
                     "unavailable": unavailable}
    if args.universe == "sp500":
        s["universe"]["membership"] = membership_coverage(rows)
    json.dump(s, open(os.path.join(DATA, "backtest_summary%s.json" % suffix), "w"),
              indent=1, ensure_ascii=False)
    _print(s)
