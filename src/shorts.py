"""Short interest: do heavily shorted stocks lag?

Short sellers are, on average, informed: stocks with a large short position
relative to their trading volume ("days to cover") have lagged in the
academic record (Hong, Li, Ni, Scheinkman & Wang 2016; Asquith, Pathak &
Ritter 2005). FINRA publishes consolidated short interest twice a month for
free; the history starts in 2018. The test is fixed in plan.md (Phase 10).

    python src/shorts.py fetch           # one mid-month settlement per month
    python src/shorts.py run [--midsmall]
"""
import bisect
import json
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

import backtest as B
import edgar
import strategy as S
import universe as U

DIR = os.path.join(os.path.dirname(__file__), "..", "data", "shorts")
API = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
FIRST_MONTH = "2018-01"
PUBLICATION_LAG_DAYS = 14
HORIZONS = {1: 21, 3: 63}


def _post(body, headers_only=False):
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("record-total") or 0)
        return total if headers_only else (total, json.loads(r.read() or b"[]"))


def _settlement(month):
    """The mid-month settlement date of `month`, or None."""
    y, m = map(int, month.split("-"))
    for day in (15, 14, 13, 12, 16, 11, 10, 17, 18):
        d = date(y, m, day).isoformat()
        flt = [{"compareType": "EQUAL", "fieldName": "settlementDate", "fieldValue": d}]
        if _post({"limit": 1, "compareFilters": flt}, headers_only=True):
            return d
    return None


def _symbol(code):
    return code.replace(".", "-").replace("/", "-").upper()


def fetch_month(month):
    os.makedirs(DIR, exist_ok=True)
    done = [n for n in os.listdir(DIR) if n.startswith(month)]
    if done:
        return os.path.join(DIR, done[0])
    d = _settlement(month)
    if d is None:
        return None
    flt = [{"compareType": "EQUAL", "fieldName": "settlementDate", "fieldValue": d}]
    out, offset = {}, 0
    while True:
        total, rows = _post({"limit": 5000, "offset": offset, "compareFilters": flt,
                             "fields": ["symbolCode", "currentShortPositionQuantity",
                                        "averageDailyVolumeQuantity"]})
        for r in rows:
            out[_symbol(r["symbolCode"])] = [r.get("currentShortPositionQuantity"),
                                             r.get("averageDailyVolumeQuantity")]
        offset += 5000
        if offset >= total or not rows:
            break
    path = os.path.join(DIR, "%s.json" % d)
    json.dump(out, open(path, "w"))
    return path


def months(first=FIRST_MONTH, last=None):
    last = last or date.today().strftime("%Y-%m")
    out, m = [], first
    while m <= last:
        out.append(m)
        m = B.add_months(m, 1)
    return out


def load():
    if not os.path.isdir(DIR):
        return {}
    return {n[:10]: json.load(open(os.path.join(DIR, n)))
            for n in sorted(os.listdir(DIR)) if n.endswith(".json")}


def days_to_cover(rec):
    short, adv = rec
    if short is None or not adv or adv <= 0:
        return None
    return short / adv


def _universe(midsmall):
    if midsmall:
        uni, _, _ = U.midsmall_universe(start="2018-01-01")
        return {U.yahoo_symbol(t): (r["intervals"], r["cik"]) for t, r in uni.items()}
    # Daily volume and FINRA's file are keyed by a live symbol; members read
    # from the outside price file have neither.
    uni, _ = U.backtest_universe(start="2018-01-01", outside=False)
    return {r["symbol"]: (r["intervals"], r["cik"]) for r in uni.values()}


def observations(midsmall, last_settlement="2025-12-31"):
    uni = _universe(midsmall)
    data = {d: v for d, v in load().items() if d <= last_settlement}
    px = {}
    for sym in uni:
        if os.path.exists(S._path(sym)):
            px[sym] = json.load(open(S._path(sym)))
    shares_cache = {}
    rows = []
    for d, table in sorted(data.items()):
        start_day = (date.fromisoformat(d) + timedelta(days=PUBLICATION_LAG_DAYS)).isoformat()
        for sym, (iv, cik) in uni.items():
            rec = table.get(sym)
            p = px.get(sym)
            if rec is None or p is None or not U.is_member(iv, d):
                continue
            i = bisect.bisect_left(p["date"], start_day)
            if i >= len(p["date"]) or (date.fromisoformat(p["date"][i]) -
                                       date.fromisoformat(start_day)).days > 7:
                continue
            fwd = {}
            for h, n in HORIZONS.items():
                if i + n < len(p["date"]):
                    fwd[h] = p["adj"][i + n] / p["adj"][i] - 1
            if not fwd:
                continue
            ratio = None
            try:
                if cik not in shares_cache:
                    shares_cache[cik] = edgar.companyfacts(cik)
                sh, _, _ = B.shares_at(shares_cache[cik], d)
                if sh and rec[0] is not None:
                    ratio = rec[0] / sh
            except Exception:
                pass
            rows.append({"date": d, "symbol": sym, "dtc": days_to_cover(rec),
                         "short_ratio": ratio, "forward": fwd})
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)
    for group in by_date.values():
        for h in HORIZONS:
            vals = [r["forward"][h] for r in group if h in r["forward"]]
            if vals:
                mean = sum(vals) / len(vals)
                for r in group:
                    if h in r["forward"]:
                        r.setdefault("excess", {})[h] = r["forward"][h] - mean
    return rows


def ic(rows, key, h):
    by_date = defaultdict(list)
    for r in rows:
        x, y = r.get(key), (r.get("excess") or {}).get(h)
        if x is not None and y is not None:
            by_date[r["date"]].append((x, y))
    ics = [B.rank_ic(p) for _, p in sorted(by_date.items())]
    ics = [x for x in ics if x is not None]
    nw = B.newey_west(ics, {1: 0, 3: 2}[h])
    if not nw:
        return {"insufficient": True}
    return {"mean_ic": round(nw["mean"], 4), "nw_t": round(nw["t"], 2), "dates": len(ics),
            "avg_names": round(sum(len(p) for p in by_date.values()) / max(1, len(by_date)))}


def quintiles(rows, key, h):
    by_date = defaultdict(list)
    for r in rows:
        if r.get(key) is not None and h in (r.get("excess") or {}):
            by_date[r["date"]].append(r)
    buckets = defaultdict(list)
    for group in by_date.values():
        if len(group) < B.MIN_CROSS_SECTION:
            continue
        per = defaultdict(list)
        for q, r in zip(B._quintile_of([r[key] for r in group]), group):
            per[q].append(r["excess"][h])
        for q, v in per.items():
            buckets[q].append(sum(v) / len(v))
    return [round(sum(buckets[q]) / len(buckets[q]), 4) if buckets[q] else None
            for q in range(B.QUINTILES)]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "fetch":
        for m in months():
            p = fetch_month(m)
            print(m, os.path.basename(p) if p else "-", flush=True)
        sys.exit()
    mid = "--midsmall" in sys.argv
    rows = observations(mid)
    print("%s: %d gozlem" % ("mid/small" if mid else "S&P 500", len(rows)))
    out = {}
    for key in ("dtc", "short_ratio"):
        for h in HORIZONS:
            s = ic(rows, key, h)
            q = quintiles(rows, key, h)
            out["%s_%dm" % (key, h)] = {**s, "quintiles": q}
            print("  %-12s %dm IC %s  Q1..Q5 %s" % (
                key, h, "-" if s.get("insufficient") else "%+.3f (t %.1f, %d tarih, ~%d sirket)"
                % (s["mean_ic"], s["nw_t"], s["dates"], s["avg_names"]),
                ["%+.2f%%" % (x * 100) if x is not None else "-" for x in q]))
    json.dump(out, open(os.path.join(DIR, "..", "shorts_summary%s.json"
                                     % ("_midsmall" if mid else "")), "w"), indent=1)
