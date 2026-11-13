"""Candlestick patterns and cycle indicators as entries (plan.md, Phase 34).

Every TA-Lib pattern's bullish reading and three Hilbert-cycle entries, as
long entries with one exit for all (stop 2.5 ATR, out after 10 days), each
beside its fair placebo: random members bought on the same days in the
same numbers.

    patterns.py          # S&P 500, 2006-2025, scored continuously
"""
import json
import os
import sys

import numpy as np
import talib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E            # noqa: E402
import trades as T            # noqa: E402

OUT = os.path.join(E.P.OUT, "patterns.json")
SPAN = ("2006-01-01", "2025-12-31")
BLOCKS = ("2006", "2011", "2016", "2021", "2026")
MIN_TRADES = 300


def entries(m):
    """{name: date x instrument flags}, read at the close."""
    names = talib.get_function_groups()["Pattern Recognition"]
    shape = m.member.shape
    out = {n: np.zeros(shape, dtype=bool) for n in names + ["HT_SINE_UP", "HT_TREND_ON", "HT_LINE_UP"]}
    for j in range(shape[1]):
        ok = np.where(np.isfinite(m.bars["close"][:, j]))[0]
        if len(ok) < 300:
            continue
        a, b = ok[0], ok[-1] + 1
        cols = []
        for k in ("open", "high", "low", "close"):
            x = m.bars[k][a:b, j].astype(np.float64)
            gaps = ~np.isfinite(x)
            if gaps.any():
                idx = np.where(gaps, 0, np.arange(len(x)))
                np.maximum.accumulate(idx, out=idx)
                x = x[idx]
            cols.append(x)
        o, h, low, c = cols
        for n in names:
            out[n][a:b, j] = getattr(talib, n)(o, h, low, c) > 0
        with np.errstate(all="ignore"):
            sine, lead = talib.HT_SINE(c)
            mode = talib.HT_TRENDMODE(c)
            trend = talib.HT_TRENDLINE(c)
        out["HT_SINE_UP"][a + 1:b, j] = (sine[1:] > lead[1:]) & (sine[:-1] <= lead[:-1])
        out["HT_TREND_ON"][a + 1:b, j] = (mode[1:] == 1) & (mode[:-1] == 0)
        out["HT_LINE_UP"][a + 1:b, j] = (c[1:] > trend[1:]) & (c[:-1] <= trend[:-1])
    return {n: f & m.member for n, f in out.items()}


def by_block(trades):
    """R per trade over the span and by five-year block of the entry date."""
    r = np.array([t["r"] for t in trades])
    year = np.array([t["entry"][:4] for t in trades])
    blocks = []
    for lo, hi in zip(BLOCKS[:-1], BLOCKS[1:]):
        pick = (year >= lo) & (year < hi)
        blocks.append(float(r[pick].mean()) if pick.sum() >= 30 else None)
    return {"trades": len(r), "r": float(r.mean()), "win": float((r > 0).mean()), "blocks": blocks}


def main():
    m = E.Market("sp500")
    rng = np.random.default_rng(0)
    rows = []
    for name, flags in entries(m).items():
        system = {"id": name, "entry": flags, "exit": None, "max_days": 10, "stop_atr": 2.5}
        mine = T.simulate(m, system, *SPAN)
        if len(mine) < MIN_TRADES:
            rows.append({"name": name, "trades": len(mine), "skipped": True})
            continue
        fake = np.zeros(flags.shape, dtype=bool)
        for t in np.where(flags.any(axis=1))[0]:
            cols = np.where(m.member[t])[0]
            fake[t, rng.choice(cols, min(int(flags[t].sum()), len(cols)), replace=False)] = True
        a, p = by_block(mine), by_block(T.simulate(m, {**system, "entry": fake}, *SPAN))
        own = [None if x is None or y is None else x - y for x, y in zip(a["blocks"], p["blocks"])]
        rows.append({"name": name, **a, "placebo": p["r"], "own": a["r"] - p["r"], "own_blocks": own,
                     "all_blocks": all(x is not None and x > 0 for x in own)})
    scored = sorted([r for r in rows if not r.get("skipped")], key=lambda r: -r["own"])
    print("S&P 500, 2006-2025: %d giris; %d tanesi en az %d islemli" % (len(rows), len(scored), MIN_TRADES))
    print("  %-22s %7s %4s %7s %8s %8s | %s" % ("giris", "islem", "kzn", "R", "rastgele", "kendi",
                                                "kendi payi: 06-10 11-15 16-20 21-25"))
    for r in scored:
        print("  %-22s %7d %3.0f%% %+7.2f %+8.2f %+8.2f | %s %s" % (
            r["name"], r["trades"], 100 * r["win"], r["r"], r["placebo"], r["own"],
            " ".join("  -  " if x is None else "%+5.2f" % x for x in r["own_blocks"]),
            "<- dort blokta da arti" if r["all_blocks"] else ""))
    kept = [r["name"] for r in scored if r["all_blocks"]]
    print("dort blogun hepsinde rastgele girisi gecen: %d / %d (sansla beklenen yaklasik %d)"
          % (len(kept), len(scored), round(len(scored) / 16)))
    with open(OUT + ".tmp", "w") as fh:
        json.dump({"rows": rows, "kept": kept}, fh)
        fh.write("\n")
    os.replace(OUT + ".tmp", OUT)


if __name__ == "__main__":
    main()
