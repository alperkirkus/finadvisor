"""Consistency over the whole of 2006-2025: four blocks, every rule beside its placebo.

plan.md, Phase 29. A variant of the core is kept only if in each of four
five-year blocks it has enough trades, a positive R per trade and more
than the same exit and stop entered at random.

    consistent.py           # S&P 500: the scan, and the variants that are consistent
"""
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E            # noqa: E402
import stops as X             # noqa: E402
import trades as T            # noqa: E402

OUT = os.path.join(E.P.OUT, "consistent.json")
BLOCKS = [("2006-01-01", "2010-12-31"), ("2011-01-01", "2015-12-31"),
          ("2016-01-01", "2020-12-31"), ("2021-01-01", "2025-12-31")]
MIN_TRADES = 100
DIP = "(ma_cross > 0) & (ma_gap200 > 0) & (rsi < 40)"
RECLAIM = "cross_up(ma_gap200, 0) & (squeeze < 1)"
WINNER = "(mom12_1 > 0.2) & (rsi < 35) & (range_ratio < 1.2)"
ENTRIES = {"trend_dip": DIP, "reclaim_200": RECLAIM, "winner_dip": WINNER,
           "any": "(%s) | (%s) | (%s)" % (DIP, RECLAIM, WINNER),
           "trend_dip+market": "(%s) & (market_up > 0)" % DIP,
           "any+market": "((%s) | (%s) | (%s)) & (market_up > 0)" % (DIP, RECLAIM, WINNER)}
EXITS = {"under_200": "(ma_gap200 < -0.02)", "rsi_60": "(rsi > 60)", "none": None}
LIMITS = (60, 120, 250)
STOPS = [["atr", 2], ["atr", 2.5], ["atr", 3], ["atr", 4], ["pct", 0.05], ["pct", 0.08], ["pct", 0.10]]
TRAILS = [["none", 0], ["chandelier", 3], ["low", 20]]
TARGETS = [None, 2, 3]


GATE = " & (market_up > 0)"
TREND = "(ma_cross > 0) & (ma_gap200 > 0)"
CALM = " & (rank(range14) < 0.4)"
STRONG = " & (mom12_1 > 0.1)"
B_ENTRIES = {"rsi40": TREND + " & (rsi < 40)" + GATE, "rsi35": TREND + " & (rsi < 35)" + GATE,
             "rsi30": TREND + " & (rsi < 30)" + GATE,
             "rsi40+calm": TREND + " & (rsi < 40)" + CALM + GATE,
             "rsi40+strong": TREND + " & (rsi < 40)" + STRONG + GATE,
             "rsi40+calm+strong": TREND + " & (rsi < 40)" + CALM + STRONG + GATE,
             "rsi35+calm": TREND + " & (rsi < 35)" + CALM + GATE,
             "any": "((%s) | (%s) | (%s))" % (DIP, RECLAIM, WINNER) + GATE}
B_EXITS = {"none": None, "under_200": "(ma_gap200 < -0.02)"}
B_LIMITS = (120, 250)
B_SPECS = [{"initial": s, "target_r": tg, "target_part": part, "breakeven_r": be}
           for s in ([["pct", x] for x in (0.06, 0.08, 0.10, 0.12, 0.15)] + [["atr", x] for x in (3, 4, 5)])
           for tg, part in ((2, 1), (2.5, 1), (3, 1), (4, 1), (5, 1), (2, 0.5), (3, 0.5))
           for be in (None, 1, 2)]
MIN_WIN, MIN_WIN_BLOCK = 0.45, 0.40


def market(universe="sp500"):
    m = E.Market(universe)
    shape = m.member.shape
    m.env["sample"] = np.broadcast_to(
        (np.arange(shape[0]) % 11 == 0).astype(np.float32)[:, None], shape).copy()
    known = m.member & np.isfinite(m.parts["ma_gap200"])
    share = (known & (m.parts["ma_gap200"] > 0)).sum(axis=1) / np.maximum(known.sum(axis=1), 1)
    m.env["market_up"] = np.broadcast_to((share > 0.5).astype(np.float32)[:, None], shape).copy()
    return m


def sums(m, entry, leave, limit, rows, span):
    p = T.prepare(m, {"entry": entry, "exit": leave, "max_days": limit}, *span)
    o, h, low, c, atr, lows = p["bars"]
    return T._grid(o, h, low, c, atr, lows, p["leave"], p["dist"], p["sig_j"], p["sig_t"], p["ends"],
                   p["hold"], rows, T.drift(m, *span), m.cost)


def scan(m, ENTRIES=ENTRIES, EXITS=EXITS, LIMITS=LIMITS, specs=None):
    specs = specs or [{"initial": s, "trail": tr, "target_r": tg} for s, tr, tg in
                      itertools.product(STOPS, TRAILS, TARGETS)]
    rows = np.array([T.policy({"stop": s}) for s in specs])
    out = []
    for leave, limit in itertools.product(EXITS, LIMITS):
        base = [sums(m, "(sample > 0)", EXITS[leave], limit, rows, b) for b in BLOCKS]
        for entry in ENTRIES:
            mine = [sums(m, ENTRIES[entry], EXITS[leave], limit, rows, b) for b in BLOCKS]
            for q in range(len(rows)):
                n = np.array([s[q, 0] for s in mine])
                r = np.array([s[q, 6] / max(s[q, 0], 1) for s in mine])
                wins = np.array([s[q, 24] for s in mine])
                pr = np.array([s[q, 6] / max(s[q, 0], 1) for s in base])
                total = sum(s[q] for s in mine)
                out.append({"entry": entry, "exit": leave, "limit": limit, "stop": specs[q],
                            "trades": n.tolist(), "r": r.tolist(), "placebo": pr.tolist(),
                            "win": (wins / np.maximum(n, 1)).tolist(),
                            "whole": {"trades": int(n.sum()), "r": float(total[6] / max(total[0], 1)),
                                      "win": float(total[24] / max(total[0], 1)),
                                      "win_r": float(total[8] / max(total[24], 1)),
                                      "loss_r": float(total[9] / max(total[0] - total[24], 1)),
                                      "days": float(total[5] / max(total[0], 1)),
                                      "risk": float(total[21] / max(total[0], 1))},
                            "consistent": bool((n >= MIN_TRADES).all() and (r > 0).all() and (r > pr).all())})
    return out


def name(v):
    s = v["stop"]
    stop = ("%g ATR" % s["initial"][1]) if s["initial"][0] == "atr" else "%%%g" % (100 * s["initial"][1])
    if "trail" in s:
        return "%-17s cikis %-9s %3dg stop %-8s iz %-12s hedef %-2s" % (
            v["entry"], v["exit"], v["limit"], stop,
            "-" if s["trail"][0] == "none" else "%s %g" % tuple(s["trail"]), s["target_r"] or "-")
    return "%-17s cikis %-9s %3dg stop %-7s hedef %sR%s basabas %s" % (
        v["entry"], v["exit"], v["limit"], stop, ("%g" % s["target_r"]),
        " (yarisi)" if s["target_part"] < 1 else "         ", ("+%gR" % s["breakeven_r"]) if s["breakeven_r"] else "-  ")


def profile_b(m):
    found = scan(m, B_ENTRIES, B_EXITS, B_LIMITS, B_SPECS)
    ok = [v for v in found if v["consistent"] and v["whole"]["win"] >= MIN_WIN
          and min(v["win"]) >= MIN_WIN_BLOCK]
    ok.sort(key=lambda v: -min(v["r"]))
    print("S&P 500, 2006-2025, profil B: %d varyanttan %d tanesi tutarli; bunlarin %d tanesi kazanan "
          "tabanini da sagliyor" % (len(found), sum(v["consistent"] for v in found), len(ok)))
    print("  %-72s | %-27s | %-19s | %6s %4s %13s %6s %4s %6s" % (
        "varyant", "R: 06-10 11-15 16-20 21-25", "kazanan % (blok)", "islem", "kzn", "kazanc/kayip", "R", "gun",
        "1R"))
    for v in ok[:30]:
        w = v["whole"]
        print("  %s | %s | %s | %6d %3.0f%% %+5.2f / %+5.2f %+6.2f %4.0f %5.1f%%" % (
            name(v), " ".join("%+5.2f" % x for x in v["r"]), " ".join("%3.0f" % (100 * x) for x in v["win"]),
            w["trades"], 100 * w["win"], w["win_r"], w["loss_r"], w["r"], w["days"], 100 * w["risk"]))
    with open(os.path.join(E.P.OUT, "consistent_b.json") + ".tmp", "w") as fh:
        json.dump({"variants": len(found), "kept": len(ok), "top": ok[:100]}, fh)
        fh.write("\n")
    os.replace(os.path.join(E.P.OUT, "consistent_b.json") + ".tmp", os.path.join(E.P.OUT, "consistent_b.json"))
    print("hesap (10 pozisyon, islem basi %1 risk), ilk 5:")
    for v in ok[:5]:
        system = {"id": "x", "entry": B_ENTRIES[v["entry"]], "exit": B_EXITS[v["exit"]],
                  "max_days": v["limit"], "stop": v["stop"]}
        text = []
        for span in BLOCKS + [("2006-01-01", "2025-12-31")]:
            tr = T.simulate(m, system, *span)
            for t in tr:
                t["weight"] = min(T.RISK / t["risk"], T.CAP)
            a = X.account(m, tr, span=span, seeds=5, slots=10)
            text.append("%+5.1f%%/%+3.0f%% (%2.0f islem/y)" % (100 * a["yearly"], 100 * a["drawdown"],
                                                              a["trades_per_year"]))
        print("  %s | %s | tum donem %s" % (name(v), "  ".join(text[:4]), text[4]))


def main():
    m = market()
    found = scan(m)
    ok = [v for v in found if v["consistent"]]
    ok.sort(key=lambda v: -min(v["r"]))
    print("S&P 500, 2006-2025, dort blok: %d varyanttan %d tanesi tutarli (her blokta arti ve plasebosunun "
          "ustunde)" % (len(found), len(ok)))
    print("  %-78s | %-27s | %-27s | %7s %4s %13s %6s %6s" % (
        "varyant", "R: 06-10 11-15 16-20 21-25", "plasebo", "islem", "kzn", "kazanc/kayip", "R", "gun"))
    for v in ok[:25]:
        w = v["whole"]
        print("  %s | %s | %s | %7d %3.0f%% %+5.2f / %+5.2f %+6.2f %5.0f" % (
            name(v), " ".join("%+5.2f" % x for x in v["r"]), " ".join("%+5.2f" % x for x in v["placebo"]),
            w["trades"], 100 * w["win"], w["win_r"], w["loss_r"], w["r"], w["days"]))
    with open(OUT + ".tmp", "w") as fh:
        json.dump({"variants": len(found), "consistent": len(ok), "top": ok[:100]}, fh)
        fh.write("\n")
    os.replace(OUT + ".tmp", OUT)
    print("hesap (10 pozisyon, islem basi %1 risk), ilk 5 tutarli varyant:")
    for v in ok[:5]:
        system = {"id": "x", "entry": ENTRIES[v["entry"]], "exit": EXITS[v["exit"]], "max_days": v["limit"],
                  "stop": v["stop"]}
        text = []
        for span in BLOCKS + [("2006-01-01", "2025-12-31")]:
            tr = T.simulate(m, system, *span)
            for t in tr:
                t["weight"] = min(T.RISK / t["risk"], T.CAP)
            a = X.account(m, tr, span=span, seeds=5, slots=10)
            text.append("%+5.1f%%/%+3.0f%%" % (100 * a["yearly"], 100 * a["drawdown"]))
        print("  %s | yillik/dusus: %s | tum donem %s" % (name(v), "  ".join(text[:4]), text[4]))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "b":
        profile_b(market())
    else:
        main()
