"""Forward tracking: what the screen said, and what the prices did next.

The backtest's holdout has been used, so no further change can be validated
on past data without fooling ourselves. The one clean test left is the
future. `snapshot` freezes the current screen with its prices; `report`
reprices every frozen snapshot today and compares each verdict group, and
the top ten, with the average name of that same snapshot and with the
S&P 500. Nothing here is fitted or tuned; it only records and compares.

    python src/tracking.py snapshot     # freeze today's screen
    python src/tracking.py snapshot --weekly    # only if this week has none
    python src/tracking.py report       # how every snapshot has done since

A week without a snapshot cannot be made up later, so the weekly form is
meant for a scheduler: scripts/snapshot.plist runs it every Monday morning
(or at the next wake after it), when the prices are Friday's close. Weekly
snapshots overlap almost entirely -- fifty-two of them are not fifty-two
tests of a twelve-month return -- but they show how often a verdict changes
from one week to the next, and no single day's prices decide the record.
"""
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import ranking
import valuation as V

# Snapshots are a record, not a cache: they cannot be regenerated, so they
# live in the repository (tracking/), not under the ignored data/ folder.
DATA = os.path.join(os.path.dirname(__file__), "..", "tracking")
INDEX = "%5EGSPC"     # URL-encoded ^GSPC


def _quote(symbol):
    try:
        return V.quote(symbol)["price"]
    except Exception:
        return None


def snapshot(rebuild=False):
    """Writes data/tracking/snapshot_<date>.json from the current screen.

    The screen is rebuilt first when `rebuild` is set or when ranking.json
    is more than a day old, so a snapshot never freezes stale prices.
    """
    os.makedirs(DATA, exist_ok=True)
    screen = ranking.load()
    stale = (screen is None or time.time() - os.path.getmtime(ranking.OUTPUT) > 86400)
    if rebuild or stale:
        screen = ranking.build(verbose=False)
    day = time.strftime("%Y-%m-%d")
    rows = [{k: r.get(k) for k in ("ticker", "verdict", "overall", "business_score",
                                   "valuation_score", "price", "fair_value", "upside",
                                   "divergence")}
            for r in screen["rows"] if r.get("price")]
    payload = {"date": day, "screen_generated_at": screen["generated_at"],
               "index_level": _quote(INDEX), "rows": rows,
               "top10": [r["ticker"] for r in screen["rows"][:10]]}
    path = os.path.join(DATA, "snapshot_%s.json" % day)
    json.dump(payload, open(path, "w"), indent=1, ensure_ascii=False)
    return path, len(rows)


def week_covered(day=None):
    """Is there already a snapshot dated in the ISO week of `day` (today)?"""
    week = date.fromisoformat(day or time.strftime("%Y-%m-%d")).isocalendar()[:2]
    return os.path.isdir(DATA) and any(
        date.fromisoformat(n[9:19]).isocalendar()[:2] == week
        for n in os.listdir(DATA) if n.startswith("snapshot_") and n.endswith(".json"))


def _snapshots():
    if not os.path.isdir(DATA):
        return []
    names = sorted(n for n in os.listdir(DATA)
                   if n.startswith("snapshot_") and n.endswith(".json"))
    return [json.load(open(os.path.join(DATA, n))) for n in names]


def report(workers=6):
    """Reprices every snapshot today and compares the groups."""
    snaps = _snapshots()
    if not snaps:
        return []
    tickers = sorted({r["ticker"] for s in snaps for r in s["rows"]})
    with ThreadPoolExecutor(workers) as pool:
        now = dict(zip(tickers, pool.map(_quote, tickers)))
    index_now = _quote(INDEX)
    out = []
    for s in snaps:
        rets = {}
        for r in s["rows"]:
            p = now.get(r["ticker"])
            if p and r["price"]:
                rets[r["ticker"]] = p / r["price"] - 1
        if not rets:
            continue
        avg = sum(rets.values()) / len(rets)
        groups = defaultdict(list)
        for r in s["rows"]:
            if r["ticker"] in rets:
                groups[r["verdict"]].append(rets[r["ticker"]])
        top = [rets[t] for t in s["top10"] if t in rets]
        index_ret = (index_now / s["index_level"] - 1
                     if index_now and s.get("index_level") else None)
        out.append({
            "date": s["date"], "names": len(rets), "screen_average": avg,
            "index": index_ret,
            "top10": sum(top) / len(top) if top else None,
            "groups": {k: {"n": len(v), "mean": sum(v) / len(v),
                           "vs_average": sum(v) / len(v) - avg}
                       for k, v in groups.items()},
        })
    return out


def _print(rows):
    if not rows:
        print("Henuz anlik goruntu yok: python src/tracking.py snapshot")
        return
    for r in rows:
        print("\n%s anlik goruntusu, %d sirket, bugune kadar:" % (r["date"], r["names"]))
        print("  ekran ortalamasi %+6.1f%%   S&P 500 %s   ilk 10 %s"
              % (r["screen_average"] * 100,
                 "%+6.1f%%" % (r["index"] * 100) if r["index"] is not None else "   -",
                 "%+6.1f%%" % (r["top10"] * 100) if r["top10"] is not None else "   -"))
        for k, g in sorted(r["groups"].items(), key=lambda kv: -kv[1]["mean"]):
            print("  %-26s n=%-4d %+6.1f%%  (ortalamaya gore %+5.1f puan)"
                  % (k, g["n"], g["mean"] * 100, g["vs_average"] * 100))
    print("\nBirkac ay dolmadan farklar gurultudur; anlam kazanmasi icin "
          "en az 6-12 aylik veri ve birden cok anlik goruntu gerekir.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "snapshot":
        # A quarter end is frozen in the first week after it, whether or not
        # this week already has a snapshot (calendar_test.py).
        import calendar_test
        done = calendar_test.record()
        if done:
            print("Ceyrek sonu kaydedildi: %s" % ", ".join(done))
    if cmd == "snapshot" and "--weekly" in sys.argv and week_covered():
        print("Bu haftanin anlik goruntusu zaten var; yenisi alinmadi.")
    elif cmd == "snapshot":
        path, n = snapshot(rebuild="--rebuild" in sys.argv)
        print("%d sirket kaydedildi: %s" % (n, path))
    else:
        _print(report())
