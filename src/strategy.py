"""Portfolio backtest of price, trend and market-regime signals, alone and
combined with the business-quality filter.

The verdict alone does not rank returns. This module tests whether adding
what prices and volume say -- trend (200-day average), momentum (12-1
months), nearness to the 52-week high -- and a market-regime switch (S&P 500
above its 200-day average) turns the system into rules worth following. The
rules are fixed in plan.md before the first run; the output is a portfolio
history (return, volatility, Sharpe, worst drawdown, turnover, costs), not a
correlation, compared with SPY and with an equal-weight portfolio of the
same members.

Price-only rules need no filings, so they are tested from 2006, a window
this project has never looked at and one that contains 2008.

    python src/strategy.py fetch      # daily prices for every member since 2004
    python src/strategy.py run        # backtest and report
"""
import csv
import json
import math
import os
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import universe as U

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
DAILY = os.path.join(DATA, "daily")
UA = "Mozilla/5.0 (FinAdvisor research)"
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
       "?period1=1072915200&period2=%d&interval=1d")
INDEX, ETF = "%5EGSPC", "SPY"
START, END = "2006-01", "2025-12"
TOP_N = 50
COST = 0.001              # 10 bp per side, on traded weight
SMA_DAYS, YEAR, MONTH = 200, 252, 21
WINDOWS = [("2006-2012", "2006-01", "2012-12"), ("2013-2019", "2013-01", "2019-12"),
           ("2020-2025", "2020-01", "2025-12")]


# --------------------------------------------------------------------------
# Data


def _path(symbol):
    return os.path.join(DAILY, symbol.replace("%5E", "_") + ".json")


def fetch_one(symbol):
    """Daily adjusted close and volume since 2004 as parallel lists."""
    path = _path(symbol)
    if os.path.exists(path):
        return json.load(open(path))
    req = urllib.request.Request(URL % (symbol, int(time.time())), headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=60).read())["chart"]["result"][0]
    ind = d["indicators"]
    adj = (ind.get("adjclose") or [{}])[0].get("adjclose") or ind["quote"][0]["close"]
    vol = ind["quote"][0].get("volume") or [None] * len(adj)
    out = {"date": [], "adj": [], "vol": []}
    for t, a, v in zip(d["timestamp"], adj, vol):
        if a is None or a <= 0:
            continue
        out["date"].append(time.strftime("%Y-%m-%d", time.gmtime(t)))
        out["adj"].append(a)
        out["vol"].append(v or 0)
    if len(out["date"]) < 50:
        raise ValueError("too little history for %s" % symbol)
    os.makedirs(DAILY, exist_ok=True)
    tmp = path + ".part"
    json.dump(out, open(tmp, "w"))
    os.replace(tmp, path)
    return out


def members_since(start="2005-01-01", end="2025-12-31"):
    """{yahoo_symbol: intervals} for S&P 500 members at any point in the window."""
    out = {}
    for t, iv in U.membership().items():
        if any(s <= end and (e is None or e >= start) for s, e in iv):
            out.setdefault(U.yahoo_symbol(t), []).extend(iv)
    return out


def fetch_all(workers=4):
    os.makedirs(DAILY, exist_ok=True)
    symbols = sorted(members_since()) + [INDEX, ETF]
    failed = {}

    def one(sym):
        try:
            fetch_one(sym)
            return sym, None
        except Exception as exc:
            return sym, str(exc)[:80]
    with ThreadPoolExecutor(workers) as pool:
        for i, (sym, err) in enumerate(pool.map(one, symbols), 1):
            if err:
                failed[sym] = err
            if i % 100 == 0:
                print("  %d/%d (%d yok)" % (i, len(symbols), len(failed)), flush=True)
    return len(symbols), failed


def tbill_monthly():
    """{YYYY-MM: monthly T-bill return} from FRED TB3MS (percent a year)."""
    path = os.path.join(DATA, "macro", "TB3MS.csv")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        body = urllib.request.urlopen("https://fred.stlouisfed.org/graph/fredgraph.csv?id=TB3MS",
                                      timeout=60).read()
        open(path, "wb").write(body)
    out = {}
    for row in csv.reader(open(path)):
        try:
            out[row[0][:7]] = float(row[1]) / 100 / 12
        except (ValueError, IndexError):
            continue
    return out


# --------------------------------------------------------------------------
# Signals


class Series:
    """One symbol's daily history with lookups by date."""

    def __init__(self, d):
        self.date, self.adj, self.vol = d["date"], d["adj"], d["vol"]
        self.pos = {x: i for i, x in enumerate(self.date)}

    def at_or_before(self, day):
        """Index of the last trading day on or before `day`."""
        lo, hi = 0, len(self.date) - 1
        if not self.date or self.date[0] > day:
            return None
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.date[mid] <= day:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def features(self, i):
        if i is None or i < YEAR:
            return None
        p = self.adj[i]
        sma = sum(self.adj[i - SMA_DAYS + 1:i + 1]) / SMA_DAYS
        mom = self.adj[i - MONTH] / self.adj[i - YEAR] - 1
        high = p / max(self.adj[i - YEAR + 1:i + 1])
        return {"trend": p > sma, "mom": mom, "high": high}


def month_ends(spy):
    """Last trading day of every month in the window, from SPY's calendar."""
    last = {}
    for d in spy.date:
        last[d[:7]] = d
    return [last[m] for m in sorted(last) if START <= m <= END]


def _rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    for r, i in enumerate(order):
        out[i] = r / max(1, len(values) - 1)
    return out


def quality_rows():
    """{yahoo_symbol: [(asof, row)]} from the S&P 500 verdict backtest."""
    path = os.path.join(DATA, "backtest_rows.json")
    out = defaultdict(list)
    if not os.path.exists(path):
        return out
    for r in json.load(open(path)):
        out[U.yahoo_symbol(r["ticker"])].append((r["asof"], r))
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return out


def passes_quality(rows, day):
    """Latest verdict row filed by `day` and no older than about four months."""
    cands = [r for asof, r in rows if asof <= day]
    if not cands:
        return None
    r = cands[-1]
    if (datetime.fromisoformat(day) - datetime.fromisoformat(r["asof"])).days > 125:
        return None
    return ((r.get("business_score") or 0) >= 60 and r.get("verdict") != "yatirim yapilamaz"
            and (r.get("volatility") is None or r["volatility"] < 0.35))


# --------------------------------------------------------------------------
# Backtest


def run():
    members = members_since()
    series = {}
    for sym in list(members) + [INDEX, ETF]:
        if os.path.exists(_path(sym)):
            series[sym] = Series(json.load(open(_path(sym))))
    spy, idx = series[ETF], series[INDEX]
    rf = tbill_monthly()
    quality = quality_rows()
    ends = month_ends(spy)

    strategies = ["A", "A_no_regime", "B", "EW", "SPY"]
    rets = {s: [] for s in strategies}
    held = {s: {} for s in ("A", "A_no_regime", "B")}
    turnover = {s: 0.0 for s in held}
    counts = defaultdict(list)

    for d0, d1 in zip(ends, ends[1:]):
        month = d1[:7]
        tb = rf.get(d0[:7], 0.0)
        ii = idx.at_or_before(d0)
        regime_on = idx.features(ii)["trend"] if ii is not None and idx.features(ii) else True

        universe, nxt = [], {}
        for sym, iv in members.items():
            s = series.get(sym)
            if s is None or not U.is_member(iv, d0):
                continue
            i0, i1 = s.at_or_before(d0), s.at_or_before(d1)
            if i0 is None or i1 is None or s.date[i0][:7] != d0[:7]:
                continue
            f = s.features(i0)
            if f is None:
                continue
            nxt[sym] = s.adj[i1] / s.adj[i0] - 1
            universe.append((sym, f))
        if not universe:
            continue

        ew = sum(nxt[s] for s, _ in universe) / len(universe)
        i0, i1 = spy.at_or_before(d0), spy.at_or_before(d1)
        rets["EW"].append((month, ew, tb))
        rets["SPY"].append((month, spy.adj[i1] / spy.adj[i0] - 1, tb))

        up = [(s, f) for s, f in universe if f["trend"]]
        score = {}
        if up:
            rm, rh = _rank([f["mom"] for _, f in up]), _rank([f["high"] for _, f in up])
            score = {s: (a + b) / 2 for (s, _), a, b in zip(up, rm, rh)}
        ranked = sorted(score, key=lambda s: -score[s])

        picks = {
            "A_no_regime": ranked[:TOP_N],
            "A": ranked[:TOP_N] if regime_on else [],
            "B": ([s for s in ranked if passes_quality(quality.get(s, []), d0)][:TOP_N]
                  if regime_on and d0 >= "2013-01-01" else None),
        }
        for name, names in picks.items():
            if names is None:
                continue
            w_new = {s: 1 / len(names) for s in names} if names else {}
            w_old = held[name]
            traded = sum(abs(w_new.get(k, 0) - w_old.get(k, 0)) for k in set(w_new) | set(w_old))
            cost = COST * traded
            turnover[name] += traded / 2
            gross = sum(w * nxt[s] for s, w in w_new.items()) if w_new else tb
            rets[name].append((month, gross - cost, tb))
            held[name] = w_new
            counts[name].append(len(names))
    return rets, turnover, counts


def stats(series, start, end):
    rows = [(m, r, tb) for m, r, tb in series if start <= m <= end]
    if len(rows) < 12:
        return None
    level, peak, mdd = 1.0, 1.0, 0.0
    for _, r, _ in rows:
        level *= 1 + r
        peak = max(peak, level)
        mdd = min(mdd, level / peak - 1)
    years = len(rows) / 12
    ex = [r - tb for _, r, tb in rows]
    mean = sum(ex) / len(ex)
    sd = math.sqrt(sum((x - mean) ** 2 for x in ex) / (len(ex) - 1))
    vol = math.sqrt(sum((r - sum(x for _, x, _ in rows) / len(rows)) ** 2
                        for _, r, _ in rows) / (len(rows) - 1)) * math.sqrt(12)
    return {"cagr": level ** (1 / years) - 1, "vol": vol,
            "sharpe": mean / sd * math.sqrt(12) if sd else None, "maxdd": mdd,
            "months": len(rows)}


def report(rets, turnover, counts):
    names = {"A": "A: trend+momentum+rejim", "A_no_regime": "A, rejim filtresiz",
             "B": "B: A + kalite/risk filtresi", "EW": "Esit agirlikli evren",
             "SPY": "SPY (S&P 500)"}
    out = {}
    for label, a, b in WINDOWS + [("2006-2025", "2006-01", "2025-12")]:
        print("\n== %s ==" % label)
        print("  %-30s %8s %8s %7s %9s" % ("strateji", "CAGR", "oynak.", "Sharpe", "max dusus"))
        out[label] = {}
        for k in ("A", "B", "A_no_regime", "EW", "SPY"):
            st = stats(rets[k], a, b)
            out[label][k] = st
            if st:
                print("  %-30s %+7.1f%% %7.1f%% %7.2f %+8.1f%%"
                      % (names[k], st["cagr"] * 100, st["vol"] * 100,
                         st["sharpe"] or 0, st["maxdd"] * 100))
    for k in ("A", "A_no_regime", "B"):
        months = max(1, len(rets[k]))
        avg = sum(counts[k]) / max(1, len(counts[k]))
        print("\n%s: yillik devir %.0f%%, ortalama hisse sayisi %.0f"
              % (names[k], turnover[k] / months * 12 * 100, avg))
    json.dump(out, open(os.path.join(DATA, "strategy_summary.json"), "w"), indent=1)
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "fetch":
        n, failed = fetch_all()
        print("%d sembol, %d indirilemedi" % (n, len(failed)))
        json.dump(failed, open(os.path.join(DAILY, "failed.json"), "w"), indent=1)
    else:
        report(*run())
