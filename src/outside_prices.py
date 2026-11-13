"""Price histories for index members Yahoo no longer serves, from the outside
dataset crosscheck.py reads, so the verdict backtest can score companies
that were later acquired or failed.

Not on the product path and not stdlib-only (duckdb), and its output stays
under data/, which is not in the repository: the dataset has no licence.

    python src/outside_prices.py ciks                    # project environment
    /tmp/xcheck/bin/python -I src/outside_prices.py prices <dataset directory>

`ciks` settles which SEC filer each unresolved member was: the name match
survivorship.py made when it was unique, otherwise the one candidate that
filed a 10-K or 10-Q around the end of the membership; it downloads that
filer's XBRL facts and drops a member that has none. `prices` then looks,
for each, for the dataset label whose membership interval is the same one
(both ends within five days) and writes

    data/prices/OUT.<label>.json    monthly closes in backtest.prices' shape
    data/universe/outside.json      {ticker: {cik, symbol, label, interval}}

A company's last price is carried for three years past its last trading
month in `closes` only, so a holder is taken to sit in cash at the takeover
or the last quote; `raw`, which prices the company itself, is not carried.
"""
import json
import os
import sys
import time
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edgar                  # noqa: E402
import universe as U          # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CIKS = os.path.join(DATA, "universe", "outside_ciks.json")
EDGE_DAYS = 5
CARRY_MONTHS = 36


def _filed_around(cik, end):
    """Did the filer put out a 10-K or 10-Q in the three years to a year
    past `end`?"""
    path = os.path.join(edgar.CACHE, "sub_%010d.json" % cik)
    if not os.path.exists(path):
        time.sleep(0.15)
        edgar._get("https://data.sec.gov/submissions/CIK%010d.json" % cik, path)
    recent = json.load(open(path))["filings"]["recent"]
    lo = (date.fromisoformat(end) - timedelta(days=3 * 365)).isoformat()
    hi = (date.fromisoformat(end) + timedelta(days=365)).isoformat()
    return any(form in ("10-K", "10-Q") and lo <= day <= hi
               for form, day in zip(recent["form"], recent["filingDate"]))


def ciks():
    U._sec_contact()
    _, unresolved = U.backtest_universe(outside=False)
    names = json.load(open(os.path.join(DATA, "survivorship", "map.json")))
    fja = U.membership()
    out, why = {}, defaultdict(list)
    for ticker in unresolved:
        rec = names.get(U.yahoo_symbol(ticker)) or {}
        end = max((e for _, e in fja[ticker] if e), default=None)
        cik = rec.get("cik")
        if not cik and rec.get("cik_candidates") and end:
            try:
                live = [c for c in rec["cik_candidates"] if _filed_around(c, end)]
            except Exception as exc:
                why["SEC lookup failed: %s" % type(exc).__name__].append(ticker)
                continue
            cik = live[0] if len(live) == 1 else None
            if not cik:
                why["%d candidates filed then" % len(live)].append(ticker)
                continue
        if not cik:
            why["no filer found by name"].append(ticker)
            continue
        try:
            if not os.path.exists(os.path.join(edgar.CACHE, "facts_%010d.json" % cik)):
                time.sleep(0.15)
            edgar.companyfacts(cik)
            edgar.profile(cik)
        except Exception as exc:
            why["no XBRL facts (%s)" % type(exc).__name__].append(ticker)
            continue
        out[ticker] = cik
    json.dump(out, open(CIKS, "w"), indent=1)
    print("%d of %d unresolved members have a filer with XBRL facts" % (len(out), len(unresolved)))
    for reason, tickers in sorted(why.items(), key=lambda kv: -len(kv[1])):
        print("  %-32s %3d  %s" % (reason, len(tickers), " ".join(sorted(tickers))[:140]))


def _gap(a, b):
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _add_months(month, n):
    y, m = int(month[:4]), int(month[5:7]) + n
    return "%04d-%02d" % (y + (m - 1) // 12, (m - 1) % 12 + 1)


def labels(c):
    out = defaultdict(list)
    day = lambda t: t.strftime("%Y-%m-%d") if t else None
    for label, start, end in c.execute(
            'select ticker, start, "end" - interval 1 day from read_parquet($1)',
            [os.path.join(THEIRS, "membership_intervals.parquet")]).fetchall():
        out[label].append((day(start), day(end)))
    return out


def match(interval, theirs):
    """The one dataset label holding this membership interval, or None."""
    start, end = interval
    hits = [label for label, spans in theirs.items() for s, e in spans
            if e is not None and end is not None and _gap(e, end) <= EDGE_DAYS
            and (_gap(s, start) <= EDGE_DAYS or start <= "1996-01-02" >= s)]
    return hits[0] if len(hits) == 1 else None


def payload(c, label):
    """Monthly payload on the split basis of the label's last day."""
    rows = c.execute("""select strftime(date, '%Y-%m-%d'), close, adj_close, stock_splits, source
                        from read_parquet($1) where ticker = $2 order by date""",
                     [os.path.join(THEIRS, "prices.parquet"), label]).fetchall()
    if len(rows) < 250:
        return None
    splits = [{"date": d, "factor": f} for d, _, _, f, _ in rows if f and f > 0 and f != 1]
    closes, raw = {}, {}
    for d, close, adj, _, source in rows:
        later = 1.0
        if not source.startswith("yahoo"):      # as traded: put on the final basis
            for s in splits:
                if s["date"] > d:
                    later *= s["factor"]
        if adj and adj > 0:
            closes[d[:7]] = adj
        if close and close > 0:
            raw[d[:7]] = close / later
    last = max(closes)
    for n in range(1, CARRY_MONTHS + 1):
        closes[_add_months(last, n)] = closes[last]
    return {"closes": closes, "raw": raw, "splits": splits, "last_traded": last}


def prices():
    import duckdb
    c = duckdb.connect()
    theirs = labels(c)
    known = json.load(open(CIKS))
    fja = U.membership()
    out, why = {}, defaultdict(list)
    for ticker in sorted(known):
        spans = [iv for iv in fja[ticker] if iv[1] and iv[1] >= "2013-01-01"]
        if len(spans) != 1:
            why["no single closed interval"].append(ticker)
            continue
        label = match(spans[0], theirs)
        if label is None:
            why["no label with that interval"].append(ticker)
            continue
        cik = known[ticker]
        p = payload(c, label)
        if p is None:
            why["too little price history"].append(ticker)
            continue
        symbol = "OUT." + label
        json.dump(p, open(os.path.join(DATA, "prices", symbol + ".json"), "w"))
        out[ticker] = {"cik": cik, "symbol": symbol, "label": label,
                       "interval": list(spans[0]), "last_traded": p["last_traded"]}
    json.dump(out, open(os.path.join(DATA, "universe", "outside.json"), "w"), indent=1)
    print("%d of %d members with a filer also have a price history" % (len(out), len(known)))
    for reason, tickers in sorted(why.items(), key=lambda kv: -len(kv[1])):
        print("  %-30s %3d  %s" % (reason, len(tickers), " ".join(sorted(tickers))[:150]))


if __name__ == "__main__":
    if sys.argv[1] == "ciks":
        ciks()
    else:
        THEIRS = sys.argv[2]
        prices()
