"""The measured fall rates behind the product's risk read: by quintile of
the daily range and half of momentum, as ranked among the index members of
each quarter end. Frequencies only; nothing is fitted (plan.md, Phase 18).

    <research venv>/python -I indicators/risk_table.py <dataset directory>

Writes data/risk_table.json, which src/verdict.py reads. It also checks
that the product's own arithmetic for the daily range (src/valuation.py, no
TA-Lib) gives what TA-Lib gives, since the table is built with one and the
product reads a company with the other.

The momentum halves are tabulated and not used: inside a range quintile
they differ by a point or less, and not in one direction.
"""
import json
import os
import sys
import warnings
from datetime import date

import numpy as np
import talib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map as IM              # noqa: E402
import test as T              # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import valuation as V         # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "risk_table.json")
QUINTILES = 5


def main(theirs):
    warnings.simplefilter("ignore")
    rows, worst = {}, 0.0
    for label, dates, bars, spans in IM.companies(theirs):
        picks = [(m, i) for m, i in sorted(T.quarter_ends(dates).items())
                 if i >= IM.MIN_HISTORY and any(s <= dates[i] and (e is None or dates[i] < e)
                                                for s, e in spans)]
        if not picks:
            continue
        close = bars["close"]
        spread = talib.SMA(talib.ATR(bars["high"], bars["low"], close, V.RANGE_DAYS) / close,
                           V.RANGE_SMOOTH)
        momentum = talib.MACDFIX(close)[0] / close
        ordinals = np.array([date.fromisoformat(d).toordinal() for d in dates])
        for m, i in picks:
            if not (np.isfinite(spread[i]) and np.isfinite(momentum[i])):
                continue
            rows.setdefault(m, []).append((spread[i], momentum[i],
                                           T.forward(dates, ordinals, close, i, 365)))
        # The product's arithmetic on the last two years of the same bars.
        if len(close) >= 504:
            cut = {k: bars[k][-504:].tolist() for k in ("high", "low", "close")}
            mine = V.daily_range(cut["high"], cut["low"], cut["close"])
            if mine is not None and np.isfinite(spread[-1]) and spread[-1]:
                worst = max(worst, abs(mine - spread[-1]) / spread[-1])
    if len(rows) < 60:
        raise ValueError("only %d quarter ends in %s" % (len(rows), theirs))

    cells, per_window = {}, {}
    total = fell_total = 0
    for m, obs in sorted(rows.items()):
        spread, momentum, fwd = (np.array([o[k] for o in obs]) for k in range(3))
        order = spread.argsort().argsort()
        quintile = np.minimum(order * QUINTILES // len(obs), QUINTILES - 1) + 1
        low = momentum < np.median(momentum)
        fell = fwd < T.FALL
        window = next(name for name, a, b in T.WINDOWS if a <= m <= b)
        total += len(obs)
        fell_total += int(fell.sum())
        for q in range(1, QUINTILES + 1):
            for key, mask in (("q%d" % q, quintile == q),
                              ("q%d_low" % q, (quintile == q) & low),
                              ("q%d_high" % q, (quintile == q) & ~low)):
                c = cells.setdefault(key, [0, 0])
                c[0] += int(mask.sum())
                c[1] += int((mask & fell).sum())
                w = per_window.setdefault(key, {}).setdefault(window, [0, 0])
                w[0] += int(mask.sum())
                w[1] += int((mask & fell).sum())
    table = {"period": "2006–2025", "quarter_ends": len(rows), "horizon_months": 12,
             "fall": T.FALL, "universe_rate": fell_total / total, "universe_n": total,
             "range_days": V.RANGE_DAYS, "smooth_days": V.RANGE_SMOOTH,
             "cells": {k: {"n": n, "fall_25": f / n,
                           "windows": {w: (b / a if a else None) for w, (a, b) in per_window[k].items()}}
                       for k, (n, f) in cells.items()}}
    json.dump(table, open(OUT, "w"), indent=1, ensure_ascii=False)

    if worst > 1e-6:
        raise ValueError("the product's daily range differs from TA-Lib's by %.2e" % worst)
    print("urun aritmetigi ile TA-Lib arasindaki en buyuk goreli fark: %.2e" % worst)
    print("%d ceyrek sonu, %d gozlem, evrende dusus orani %.1f%%"
          % (len(rows), total, 100 * table["universe_rate"]))
    print("  %-8s %7s %8s   %s   | momentum zayif / guclu" % ("dilim", "n", "dusus", "pencereler"))
    for q in range(1, QUINTILES + 1):
        c = table["cells"]["q%d" % q]
        print("  q%d       %7d %7.1f%%   %s   | %5.1f%% / %5.1f%%"
              % (q, c["n"], 100 * c["fall_25"],
                 "  ".join("%4.1f%%" % (100 * c["windows"][w]) for w, _, _ in T.WINDOWS),
                 100 * table["cells"]["q%d_low" % q]["fall_25"],
                 100 * table["cells"]["q%d_high" % q]["fall_25"]))


if __name__ == "__main__":
    main(sys.argv[1])
