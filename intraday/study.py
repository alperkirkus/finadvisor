"""Scores the pre-registered intraday signals. See README.md for the rules;
nothing here chooses a parameter.

    python intraday/study.py            # design set (bars through 2026-11-12)
    python intraday/study.py --test     # the one logged reading of the test set
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import backtest as B          # noqa: E402
import multitest as M         # noqa: E402

import bars as BARS           # noqa: E402

TIMEFRAMES = [("5m", 1), ("15m", 3), ("1h", 12)]
COST = 0.0002                 # per unit of position changed
DESIGN_END = "2026-11-12"
TEST_SESSIONS = 60
MIN_SYMBOLS = 50              # a day with fewer symbols is not averaged
LOOKS = os.path.join(BARS.ROOT, "data", "intraday", "looks.json")


def _ema(values, n):
    k, out, e = 2 / (n + 1), [], None
    for v in values:
        e = v if e is None else e + k * (v - e)
        out.append(e)
    return out


def trend(b):
    close = [x["c"] for x in b]
    macd = [f - s for f, s in zip(_ema(close, 12), _ema(close, 26))]
    line = _ema(macd, 9)
    return [None if i < 34 else (macd[i] - line[i]) / close[i] for i in range(len(b))]


def reversion(b):
    out = []
    for i in range(len(b)):
        if i < 19:
            out.append(None)
            continue
        window = [x["c"] for x in b[i - 19:i + 1]]
        mean = sum(window) / 20
        sd = math.sqrt(sum((x - mean) ** 2 for x in window) / 20)
        out.append(-(b[i]["c"] - mean) / (2 * sd) if sd else None)
    return out


def breakout(b):
    out = []
    for i in range(len(b)):
        if i < 20:
            out.append(None)
            continue
        high = max(x["h"] for x in b[i - 20:i])
        low = min(x["l"] for x in b[i - 20:i])
        out.append(1.0 if b[i]["c"] > high else -1.0 if b[i]["c"] < low else 0.0)
    return out


def volume(b):
    out = []
    for i in range(len(b)):
        if i < 20:
            out.append(None)
            continue
        usual = sum(x["v"] for x in b[i - 20:i]) / 20
        if not usual:
            out.append(None)
            continue
        move = b[i]["c"] - b[i]["o"]
        out.append((1 if move > 0 else -1 if move < 0 else 0)
                   * max(0.0, b[i]["v"] / usual - 1))
    return out


SIGNALS = {"trend": trend, "reversion": reversion, "breakout": breakout, "volume": volume}


def score(symbol, every):
    """{signal: {day: (gross, net, turnover)}} for one symbol and timeframe."""
    days = BARS.sessions(BARS.load(symbol), every)
    flat = [bar for _, session in days for bar in session]
    values = {name: fn(flat) for name, fn in SIGNALS.items()}
    out = {name: {} for name in SIGNALS}
    start = 0
    for day, session in days:
        end = start + len(session)
        for name, series in values.items():
            gross = cost = held = 0.0
            for t in range(start, end - 2):
                s = series[t]
                position = 0.0 if not s else 1.0 if s > 0 else -1.0
                gross += position * (flat[t + 2]["o"] / flat[t + 1]["o"] - 1)
                cost += abs(position - held)
                held = position
            cost += abs(held)
            out[name][day] = (gross, gross - COST * cost, cost)
        start = end
    return out


def run(first, last):
    symbols = BARS.universe()
    results = []
    for label, every in TIMEFRAMES:
        per_symbol = [score(s, every) for s in symbols]
        for name in SIGNALS:
            by_day = {}
            for one in per_symbol:
                for day, triple in one[name].items():
                    if first <= day <= last:
                        by_day.setdefault(day, []).append(triple)
            days = sorted(d for d, v in by_day.items() if len(v) >= MIN_SYMBOLS)
            mean = lambda k: [sum(x[k] for x in by_day[d]) / len(by_day[d]) for d in days]
            gross, net, turnover = mean(0), mean(1), mean(2)
            g, n = B.newey_west(gross, 1), B.newey_west(net, 1)
            if not g or not n:
                results.append({"timeframe": label, "signal": name, "days": len(days),
                                "insufficient": True})
                continue
            sd = math.sqrt(sum((x - n["mean"]) ** 2 for x in net) / (len(net) - 1))
            results.append({
                "timeframe": label, "signal": name, "days": len(days),
                "gross_bp": g["mean"] * 1e4, "gross_t": g["t"],
                "net_bp": n["mean"] * 1e4, "net_t": n["t"],
                "net_sharpe": n["mean"] / sd * math.sqrt(252) if sd else None,
                "turnover": sum(turnover) / len(turnover)})
    return results


def report(results, title):
    scored = [r for r in results if not r.get("insufficient")]
    line = M.t_of(M.ALPHA / max(1, len(results)))
    print("%s -- %d test, Bonferroni cizgisi |t| >= %.2f" % (title, len(results), line))
    print("  %-4s %-10s %4s %9s %7s %9s %7s %8s %9s  %s"
          % ("tf", "sinyal", "gun", "brut bp", "t", "net bp", "t", "Sharpe", "devir/gun", "sonuc"))
    for r in results:
        if r.get("insufficient"):
            print("  %-4s %-10s %4d  yetersiz gun" % (r["timeframe"], r["signal"], r["days"]))
            continue
        verdict = ("bilgi + islem" if abs(r["gross_t"]) >= line and r["net_bp"] > 0 and r["net_t"] >= 2
                   else "bilgi var, maliyeti karsilamiyor" if abs(r["gross_t"]) >= line
                   else "-")
        print("  %-4s %-10s %4d %+9.2f %+7.2f %+9.2f %+7.2f %+8.2f %9.1f  %s"
              % (r["timeframe"], r["signal"], r["days"], r["gross_bp"], r["gross_t"],
                 r["net_bp"], r["net_t"], r["net_sharpe"] or 0, r["turnover"], verdict))
    return scored


if __name__ == "__main__":
    if "--test" in sys.argv:
        days = sorted({BARS.day(t) for s in BARS.universe() for t in BARS.load(s)["t"]
                       if BARS.day(t) > DESIGN_END})
        if len(days) < TEST_SESSIONS:
            raise SystemExit("Test seti %d seans; %d olmadan okunmaz." % (len(days), TEST_SESSIONS))
        looks = json.load(open(LOOKS)) if os.path.exists(LOOKS) else []
        looks.append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "first": days[0], "last": days[-1], "sessions": len(days)})
        json.dump(looks, open(LOOKS, "w"), indent=1)
        print("Test seti okunuyor (kayitli bakis #%d)" % len(looks))
        results = run(days[0], days[-1])
        report(results, "TEST SETI %s .. %s" % (days[0], days[-1]))
        name = "study_test.json"
    else:
        results = run("0000-00-00", DESIGN_END)
        report(results, "TASARIM SETI (.. %s; hicbir seye karar vermez)" % DESIGN_END)
        name = "study_design.json"
    json.dump(results, open(os.path.join(BARS.ROOT, "data", "intraday", name), "w"), indent=1)
