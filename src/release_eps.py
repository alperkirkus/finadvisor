"""Can the quarter's EPS be read from the earnings release itself?

The surprise measured from the release date has a drift (earnings.py), but
the EPS it uses comes from XBRL, which arrives with the 10-Q weeks later.
This tests whether the 8-K Item 2.02 press release gives the same number
on the day. Pre-registered in plan.md (Phase 13): a random sample of
release events, EPS extracted by release_extract.py, compared with the EPS
first filed in XBRL.

    python src/release_eps.py sample [--dev]   # draw the events, with their XBRL EPS
    <edgartools venv>/python -I src/release_extract.py data/release_sample.json
    python src/release_eps.py report [--dev]

`--dev` draws a small separate set (other seed) for building the extractor,
so the test sample is parsed once, by a parser that never saw it.
"""
import json
import os
import random
import sys
from collections import Counter
from datetime import date, timedelta

import backtest as B
import earnings as E
import edgar
import universe as U

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
SEED, SIZE = 20261113, 400
DEV_SEED, DEV_SIZE = 1, 30
TOLERANCE = 0.01
MIN_COVERAGE, MIN_MATCH = 0.80, 0.95


def _path(dev, kind="sample"):
    return os.path.join(DATA, "release_%s%s.json" % (kind, "_dev" if dev else ""))


def _accession(cik, day):
    """Accession number of the Item 2.02 8-K filed on `day`."""
    for p in E._sub_pages(cik):
        for form, filed, items, acc in zip(p["form"], p["filingDate"], p["items"],
                                           p["accessionNumber"]):
            if form in ("8-K", "8-K/A") and filed == day and "2.02" in (items or "").split(","):
                return acc
    return None


def _reference(facts, end, release):
    """(diluted EPS of the quarter as first filed, whether XBRL reports that
    quarter directly rather than as year minus nine months)."""
    asof = (date.fromisoformat(release) + timedelta(days=E.MAX_LAG_DAYS)).isoformat()
    chain = edgar.DURATION["eps_diluted"]
    value = edgar.quarterly_flows(facts, chain, asof).get(end)
    lo, hi = edgar.QUARTER_DAYS
    direct = any(e == end and lo <= edgar._days(s, e) <= hi
                 for s, e in edgar._periods(facts, chain, asof))
    return value, direct


def sample(dev=False):
    events = json.load(open(os.path.join(DATA, "earnings_events.json")))
    pool = sorted((r for r in events if r.get("sue") is not None
                   and "2013-01-01" <= r["release"] <= "2025-12-31"),
                  key=lambda r: (r["ticker"], r["end"]))
    if len(pool) < SIZE:
        raise ValueError("only %d usable events in earnings_events.json" % len(pool))
    rng = random.Random(DEV_SEED if dev else SEED)
    drawn = rng.sample(pool, DEV_SIZE if dev else SIZE)
    if dev:
        test = {(r["ticker"], r["end"]) for r in random.Random(SEED).sample(pool, SIZE)}
        drawn = [r for r in drawn if (r["ticker"], r["end"]) not in test]
    uni, _ = U.backtest_universe()
    rows = []
    for r in drawn:
        cik = uni[r["ticker"]]["cik"]
        value, direct = _reference(edgar.companyfacts(cik), r["end"], r["release"])
        rows.append({"ticker": r["ticker"], "cik": cik, "end": r["end"],
                     "release": r["release"], "accession": _accession(cik, r["release"]),
                     "eps_xbrl": value, "direct": direct, "sue": r["sue"], "car": r["car"]})
    json.dump(rows, open(_path(dev), "w"), indent=1)
    print("%d olay yazildi: %s (%d dogrudan raporlanan ceyrek)"
          % (len(rows), _path(dev), sum(r["direct"] for r in rows)))


def report(dev=False):
    rows = json.load(open(_path(dev)))
    got = {(r["ticker"], r["end"]): r for r in json.load(open(_path(dev, "extract")))}
    if len(got) < len(rows):
        raise ValueError("extraction covers %d of %d events" % (len(got), len(rows)))
    out = {}
    for name, keep in (("direct", True), ("fourth_quarter", False)):
        group = [r for r in rows if r["direct"] is keep and r["eps_xbrl"] is not None]
        found = [(r, got[(r["ticker"], r["end"])]) for r in group]
        extracted = [(r, g) for r, g in found if g.get("eps") is not None]
        equal = [(r, g) for r, g in extracted if abs(g["eps"] - r["eps_xbrl"]) <= TOLERANCE]
        out[name] = {"events": len(group), "extracted": len(extracted), "equal": len(equal),
                     "coverage": len(extracted) / len(group) if group else None,
                     "match": len(equal) / len(extracted) if extracted else None,
                     "status": dict(Counter(g.get("status") for _, g in found))}
        print("%-15s %3d olay | EPS cikarildi %3d (%s) | XBRL ile esit %3d (%s)"
              % (name, len(group), len(extracted),
                 "-" if not group else "%.0f%%" % (100 * len(extracted) / len(group)),
                 len(equal), "-" if not extracted else "%.0f%%" % (100 * len(equal) / len(extracted))))
        print("    durumlar: %s" % out[name]["status"])
        for r, g in extracted:
            if abs(g["eps"] - r["eps_xbrl"]) > TOLERANCE:
                print("    farkli: %-5s %s  bulten %s  XBRL %s  (%s)"
                      % (r["ticker"], r["end"], g["eps"], r["eps_xbrl"], g.get("label")))
    d = out["direct"]
    passed = (d["coverage"] is not None and d["match"] is not None
              and d["coverage"] >= MIN_COVERAGE and d["match"] >= MIN_MATCH)
    out["criterion"] = {"min_coverage": MIN_COVERAGE, "min_match": MIN_MATCH, "passed": passed}
    print("Olcut (kapsam >= %%%d ve esitlik >= %%%d, dogrudan raporlanan ceyrekler): %s"
          % (MIN_COVERAGE * 100, MIN_MATCH * 100, "GECTI" if passed else "KALDI"))
    # Selection check: is the surprise's relation to the drift the same on
    # the events the parser could read as on the ones it could not?
    for label, keep in (("cikarilan", True), ("cikarilamayan", False)):
        pairs = [(r["sue"], r["car"]) for r in rows
                 if (got[(r["ticker"], r["end"])].get("eps") is not None) is keep
                 and r["car"] is not None]
        ic = B.rank_ic(pairs) if len(pairs) >= 20 else None
        out["ic_" + ("extracted" if keep else "missed")] = {"events": len(pairs), "rank_ic": ic}
        print("  SUE-CAR sira korelasyonu, %s: %s (n=%d)"
              % (label, "-" if ic is None else "%+.3f" % ic, len(pairs)))
    if not dev:
        json.dump(out, open(os.path.join(DATA, "release_summary.json"), "w"), indent=1)
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"sample": sample, "report": report}[cmd]("--dev" in sys.argv)
