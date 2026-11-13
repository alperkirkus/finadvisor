"""Earnings surprise measured from the day the market learned it.

The quarterly backtest dates a quarter by its 10-Q filing, weeks after the
earnings release, and scores it on the next calendar quarter end, by which
time most of the post-announcement drift (Bernard & Thomas 1989) has
happened. Here each surprise is dated by the company's 8-K Item 2.02
(Results of Operations) filing and the return is measured from the close of
the first trading day the news could trade on, for 60 trading days, against
SPY. Pre-registered in plan.md (Phase 9): 3-month IC > 0 with t >= 2 in
2013-2019, on S&P 500 and mid/small members.

    python src/earnings.py fetch [--midsmall]    # older submission pages, daily prices
    python src/earnings.py run [--midsmall] [--holdout]
"""
import bisect
import json
import math
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import backtest as B
import edgar
import strategy as S
import universe as U

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
HOLD_DAYS = 60
MAX_LAG_DAYS = 75          # a release more than this after quarter end is not that quarter's
DEV_LAST_RELEASE = "2019-09-30"   # 60 trading days later still falls inside 2019
HOLDOUT_FIRST_RELEASE = "2020-01-01"


def _sub_pages(cik):
    """Every page of a filer's submission history, older pages cached."""
    main = json.load(open(os.path.join(edgar.CACHE, "sub_%010d.json" % cik)))
    pages = [main["filings"]["recent"]]
    for f in main["filings"].get("files", []):
        if f.get("filingTo", "") < "2012-01-01":
            continue
        path = os.path.join(edgar.CACHE, f["name"])
        if not os.path.exists(path):
            edgar._get("https://data.sec.gov/submissions/" + f["name"], path)
        pages.append(json.load(open(path)))
    return pages


def releases(cik):
    """Sorted (filing date, acceptance UTC time) of 8-K Item 2.02 filings."""
    out = set()
    for p in _sub_pages(cik):
        for form, day, items, acc in zip(p["form"], p["filingDate"], p["items"],
                                         p.get("acceptanceDateTime") or [""] * len(p["form"])):
            if form in ("8-K", "8-K/A") and "2.02" in (items or "").split(","):
                out.add((day, acc or ""))
    return sorted(out)


def periodic_filings(cik):
    """{report period end: first 10-Q/10-K filing date}: when the quarter's
    numbers reached XBRL, the earliest a live system could compute them."""
    out = {}
    for p in _sub_pages(cik):
        for form, day, period in zip(p["form"], p["filingDate"], p["reportDate"]):
            if form in ("10-Q", "10-K") and period:
                if period not in out or day < out[period]:
                    out[period] = day
    return out


def _reaction_index(dates, day, accepted):
    """Index of the first close that could reflect a release.

    Accepted at or after 20:00 UTC (16:00 New York in summer, 15:00 in
    winter -- the conservative side) counts as after the close.
    """
    i = bisect.bisect_left(dates, day)
    if i < len(dates) and dates[i] == day and accepted[11:13] >= "20":
        i += 1
    return i


def events(ticker, rec, spy):
    """One row per quarter whose release could be dated."""
    cik = rec["cik"]
    try:
        facts = edgar.companyfacts(cik)
        rel = releases(cik)
        periodic = periodic_filings(cik)
        px = S.fetch_one(rec.get("symbol") or U.yahoo_symbol(ticker))
    except Exception:
        return []
    if not rel:
        return []
    dates, adj = px["date"], px["adj"]
    spy_at = dict(zip(spy["date"], spy["adj"]))
    ends = sorted(edgar.quarterly_flows(facts, edgar.DURATION["eps_diluted"],
                                        date.today().isoformat()))
    rows = []
    for end in ends:
        lo = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        hi = (date.fromisoformat(end) + timedelta(days=MAX_LAG_DAYS)).isoformat()
        match = [r for r in rel if lo <= r[0] <= hi]
        if not match:
            continue
        day, acc = match[0]
        if not U.is_member(rec["intervals"], day):
            continue
        # Values as first filed: the 10-Q follows the release within weeks,
        # so filings up to the release plus MAX_LAG_DAYS hold the original
        # number without later restatements.
        asof = (date.fromisoformat(day) + timedelta(days=MAX_LAG_DAYS)).isoformat()
        sue = B._surprise(facts, asof, "eps_diluted", target_end=end)
        rev = B._surprise(facts, asof, "revenue", target_end=end)
        if sue is None and rev is None:
            continue
        i = _reaction_index(dates, day, acc)
        j = i + HOLD_DAYS
        if i < 1 or j >= len(dates):
            continue
        d0, d1 = dates[i], dates[j]
        if d0 not in spy_at or d1 not in spy_at:
            continue
        stock = adj[j] / adj[i] - 1
        market = spy_at[d1] / spy_at[d0] - 1
        jump = adj[i] / adj[i - 1] - 1
        row = {"ticker": ticker, "end": end, "release": day, "start": d0,
               "sue": sue, "revenue_surprise": rev,
               "announcement_return": jump, "car": stock - market}
        # The realizable version: from the first close after the 10-Q/10-K
        # is filed (time of day unknown, so the next day), for 60 days.
        filed = periodic.get(end)
        if filed:
            k = bisect.bisect_right(dates, filed)
            if k + HOLD_DAYS < len(dates) and dates[k] in spy_at and dates[k + HOLD_DAYS] in spy_at:
                row["filed"] = filed
                row["car_filed"] = (adj[k + HOLD_DAYS] / adj[k] - 1
                                    - (spy_at[dates[k + HOLD_DAYS]] / spy_at[dates[k]] - 1))
        rows.append(row)
    return rows


def run(uni):
    spy = S.fetch_one(S.ETF)
    with ThreadPoolExecutor(6) as pool:
        parts = list(pool.map(lambda kv: events(kv[0], kv[1], spy), sorted(uni.items())))
    return [r for p in parts for r in p]


def ic_by_quarter(rows, key, first, last, ret="car"):
    by_q = defaultdict(list)
    for r in rows:
        if first <= r["release"] <= last and r.get(key) is not None and r.get(ret) is not None:
            q = r["release"][:4] + "Q%d" % ((int(r["release"][5:7]) - 1) // 3 + 1)
            by_q[q].append((r[key], r[ret]))
    ics = [B.rank_ic(p) for _, p in sorted(by_q.items())]
    ics = [x for x in ics if x is not None]
    nw = B.newey_west(ics, 1)
    if not nw:
        return {"insufficient": True, "quarters": len(ics)}
    return {"mean_ic": round(nw["mean"], 4), "nw_t": round(nw["t"], 2),
            "quarters": len(ics),
            "events": sum(len(p) for p in by_q.values()),
            "positive_share": round(sum(x > 0 for x in ics) / len(ics), 3)}


def quintiles(rows, key, first, last, ret="car"):
    by_q = defaultdict(list)
    for r in rows:
        if first <= r["release"] <= last and r.get(key) is not None and r.get(ret) is not None:
            by_q[r["release"][:7]].append(r)
    buckets = defaultdict(list)
    for group in by_q.values():
        if len(group) < B.MIN_CROSS_SECTION:
            continue
        qs = B._quintile_of([r[key] for r in group])
        per = defaultdict(list)
        for q, r in zip(qs, group):
            per[q].append(r[ret])
        for q, v in per.items():
            buckets[q].append(sum(v) / len(v))
    return [round(sum(buckets[q]) / len(buckets[q]), 4) if buckets[q] else None
            for q in range(B.QUINTILES)]


def _universe(midsmall):
    if midsmall:
        uni, _, _ = U.midsmall_universe()
    else:
        uni, _ = U.backtest_universe()
    return uni


def fetch(uni):
    U._sec_contact()
    sec, yahoo = U._RateLimit(8), U._RateLimit(4)

    def one(item):
        ticker, rec = item
        try:
            main = os.path.join(edgar.CACHE, "sub_%010d.json" % rec["cik"])
            if not os.path.exists(main):
                sec.wait()
                edgar.profile(rec["cik"])
            for f in json.load(open(main))["filings"].get("files", []):
                path = os.path.join(edgar.CACHE, f["name"])
                if f.get("filingTo", "") >= "2012-01-01" and not os.path.exists(path):
                    sec.wait()
                    edgar._get("https://data.sec.gov/submissions/" + f["name"], path)
            if not os.path.exists(S._path(U.yahoo_symbol(ticker))):
                yahoo.wait()
                S.fetch_one(U.yahoo_symbol(ticker))
        except Exception as exc:
            return ticker, str(exc)
        return ticker, None

    with ThreadPoolExecutor(6) as pool:
        failed = {t: e for t, e in pool.map(one, sorted(uni.items())) if e}
    print("%d sirket, %d hata" % (len(uni), len(failed)))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    mid = "--midsmall" in sys.argv
    uni = _universe(mid)
    if cmd == "fetch":
        fetch(uni)
        sys.exit()
    rows = run(uni)
    suffix = "_midsmall" if mid else ""
    json.dump(rows, open(os.path.join(DATA, "earnings_events%s.json" % suffix), "w"))
    windows = [("dev", "2013-01-01", DEV_LAST_RELEASE)]
    if "--holdout" in sys.argv:
        print("HOLDOUT acildi (kayitli bakis #%d)" % B._log_holdout_look())
        windows.append(("holdout", HOLDOUT_FIRST_RELEASE, "2026-12-31"))
    out = {}
    print("%s: %d olay" % ("mid/small" if mid else "S&P 500", len(rows)))
    for name, a, b in windows:
        for key in ("sue", "revenue_surprise", "announcement_return"):
            s = ic_by_quarter(rows, key, a, b)
            q = quintiles(rows, key, a, b)
            out.setdefault(name, {})[key] = {**s, "quintile_car": q}
            if key == "sue":
                sf = ic_by_quarter(rows, key, a, b, "car_filed")
                qf = quintiles(rows, key, a, b, "car_filed")
                out[name]["sue_from_filing"] = {**sf, "quintile_car": qf}
                print("  %-8s %-20s IC %s  Q1..Q5 CAR %s" % (
                    name, "sue (10-Q'dan)",
                    "-" if sf.get("insufficient") else "%+.3f (t %.1f, %d olay)"
                    % (sf["mean_ic"], sf["nw_t"], sf["events"]),
                    ["%+.1f%%" % (x * 100) if x is not None else "-" for x in qf]))
            print("  %-8s %-20s IC %s  Q1..Q5 CAR %s" % (
                name, key,
                "-" if s.get("insufficient") else "%+.3f (t %.1f, %d ceyrek, %d olay)"
                % (s["mean_ic"], s["nw_t"], s["quarters"], s["events"]),
                ["%+.1f%%" % (x * 100) if x is not None else "-" for x in q]))
    json.dump(out, open(os.path.join(DATA, "earnings_summary%s.json" % suffix), "w"), indent=1)
