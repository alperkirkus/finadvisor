"""Forward record of the turn-of-quarter effect.

The indicator lab found one thing it could not test: in 2006-2025 the
companies that had fallen most over a quarter did better in the month after
a half-year end, and the ones that had risen most did worse after any
quarter end, with nothing of the kind at ordinary month ends -- what funds
selling their losers and holding their winners into a reporting date would
leave behind. It was found by looking at the whole period, so no part of
that period can confirm it. This writes the rule down once and scores it on
quarter ends that come after.

    python src/calendar_test.py record     # freeze any quarter end not yet recorded
    python src/calendar_test.py report     # what the flagged companies did next

The weekly snapshot job runs `record`, so a quarter end is frozen in the
first week after it. The rules, fixed on 2026-11-13 (plan.md, Phase 21):

- `losers`: bottom quarter of the screen's members by 60-day return, on the
  last trading day of June and December. Expected to beat the members over
  the next 20 trading days.
- `winners`: top fifth by 60-day return, on the last trading day of every
  quarter. Expected to trail.
- `tax_loss`: down more than 10% over 250 days, on the last trading day of
  December. Expected to beat.
- `control`: the `losers` rule on the last trading day of March and
  September, where the old data showed nothing. Expected to do neither.

Entry is the next day's open, exit the close 20 trading days after the
quarter end. Quarter ends of 2026 before the rule was written are recorded
too and marked `backfilled`: the rule had not seen them, but they are not
the future.
"""
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import ranking
import valuation as V

DATA = os.path.join(os.path.dirname(__file__), "..", "tracking")
FIXED_ON = "2026-11-13"
FIRST = "2026-03"             # earlier quarter ends were seen when the effect was found
HOLD = 20
CALENDAR = "SPY"
EXPECT = {"losers": 1, "winners": -1, "tax_loss": 1, "control": 0}


def bars(symbol):
    """(dates, opens, closes) of the last two years, ascending."""
    req = urllib.request.Request(V.DAILY_URL % symbol, headers={"User-Agent": V.UA})
    result = json.loads(urllib.request.urlopen(req, timeout=30).read())["chart"]["result"][0]
    q = result["indicators"]["quote"][0]
    rows = [(time.strftime("%Y-%m-%d", time.gmtime(t)), o, c)
            for t, o, c in zip(result["timestamp"], q["open"], q["close"])
            if o is not None and c is not None and c > 0 and o > 0]
    return [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]


def quarter_ends(dates):
    """Last trading day of each finished quarter, from FIRST on."""
    last = {}
    for d in dates:
        last[d[:7]] = d
    months = sorted(last)
    return [last[m] for m in months[:-1]            # the latest month is not over
            if m[5:7] in ("03", "06", "09", "12") and m >= FIRST]


def _path(day):
    return os.path.join(DATA, "calendar_%s.json" % day)


def flags(day, series):
    """{rule: [symbols]} and each member's entry price, as of the close of `day`."""
    measured = {}
    for symbol, (dates, opens, closes) in series.items():
        if day not in dates:
            continue
        i = dates.index(day)
        if i < 250 or i + 1 >= len(dates):
            continue
        measured[symbol] = {"ret60": closes[i] / closes[i - 60] - 1,
                            "ret250": closes[i] / closes[i - 250] - 1,
                            "entry": opens[i + 1]}
    if len(measured) < 100:
        return None, measured
    order = sorted(measured, key=lambda s: measured[s]["ret60"])
    n, month = len(order), day[5:7]
    bottom, top = order[:n // 4], order[n - n // 5:]
    rules = {"winners": top}
    if month in ("06", "12"):
        rules["losers"] = bottom
    else:
        rules["control"] = bottom
    if month == "12":
        rules["tax_loss"] = [s for s in order if measured[s]["ret250"] < -0.10]
    return rules, measured


def load_series(symbols):
    def one(symbol):
        try:
            return symbol, bars(symbol)
        except Exception:
            return symbol, None
    with ThreadPoolExecutor(4) as pool:
        return {s: b for s, b in pool.map(one, symbols) if b}


def record():
    """Freezes every quarter end that has no record yet. Returns their dates."""
    os.makedirs(DATA, exist_ok=True)
    calendar = bars(CALENDAR)[0]
    todo = [d for d in quarter_ends(calendar) if not os.path.exists(_path(d))]
    if not todo:
        return []
    series = load_series(sorted(ranking.screen_universe()))
    written = []
    for day in todo:
        rules, measured = flags(day, series)
        if rules is None:
            print("%s: yalnizca %d sirket olculebildi, kayit alinmadi" % (day, len(measured)))
            continue
        json.dump({"quarter_end": day, "rule_fixed_on": FIXED_ON,
                   "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "backfilled": day < FIXED_ON, "hold_days": HOLD,
                   "rules": rules, "members": measured},
                  open(_path(day), "w"), indent=1)
        written.append(day)
    return written


def report():
    names = sorted(n for n in os.listdir(DATA)
                   if n.startswith("calendar_") and n.endswith(".json")) if os.path.isdir(DATA) else []
    if not names:
        print("Kayit yok: python src/calendar_test.py record")
        return []
    records = [json.load(open(os.path.join(DATA, n))) for n in names]
    series = load_series(sorted({s for r in records for s in r["members"]}))
    out = []
    for r in records:
        day, returns = r["quarter_end"], {}
        for symbol, m in r["members"].items():
            if symbol not in series or day not in series[symbol][0]:
                continue
            dates, _, closes = series[symbol]
            i = dates.index(day) + r["hold_days"]
            if i < len(dates):
                returns[symbol] = closes[i] / m["entry"] - 1
        if len(returns) < 100:
            print("%s%s: %d gun dolmadi" % (day, " (geriye dogru)" if r["backfilled"] else "",
                                             r["hold_days"]))
            continue
        base = sum(returns.values()) / len(returns)
        print("%s%s: %d sirket, ortalama %+.1f%%" % (day, " (geriye dogru)" if r["backfilled"] else "",
                                                      len(returns), base * 100))
        for rule, symbols in sorted(r["rules"].items()):
            got = [returns[s] for s in symbols if s in returns]
            if not got:
                continue
            excess = sum(got) / len(got) - base
            want = EXPECT[rule]
            print("  %-9s n=%-3d fark %+5.2f%%  beklenen %s  %s"
                  % (rule, len(got), excess * 100, {1: "+", -1: "-", 0: "0"}[want],
                     "" if not want else "tuttu" if excess * want > 0 else "tutmadi"))
            out.append({"quarter_end": day, "rule": rule, "n": len(got), "excess": excess,
                        "backfilled": r["backfilled"]})
    for rule in sorted(EXPECT):
        got = [x["excess"] for x in out if x["rule"] == rule]
        if got:
            print("%-9s %d ceyrek sonu, ortalama fark %+.2f%% (beklenen %s)"
                  % (rule, len(got), 100 * sum(got) / len(got),
                     {1: "+", -1: "-", 0: "0"}[EXPECT[rule]]))
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "record":
        done = record()
        print("Kaydedilen ceyrek sonu: %s" % (", ".join(done) or "yok"))
    else:
        report()
