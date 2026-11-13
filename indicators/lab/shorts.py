"""The short side: every system as its mirror image (plan.md, Phase 31).

A short on a price series is a long on its inverse. The panel is inverted
(open and close to 1/price, high and low exchanged), the systems and the
simulator run on it unchanged, and each trade's result is converted back
to what a short made: (entry - exit) / entry, less costs and a borrow fee.

    shorts.py            # S&P 500, 2006-2025, four blocks
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E            # noqa: E402
import panel as P             # noqa: E402
import stops as X             # noqa: E402
import trades as T            # noqa: E402

BLOCKS = [("2006-01-01", "2010-12-31"), ("2011-01-01", "2015-12-31"),
          ("2016-01-01", "2020-12-31"), ("2021-01-01", "2025-12-31")]
BORROW = 0.01                 # a year, on the value sold short
OUT = os.path.join(P.OUT, "shorts.json")


def mirror(universe="sp500"):
    """The universe with every price inverted, as a market of its own."""
    name, cost = E.UNIVERSES[universe]
    p = P.load(name)
    with np.errstate(all="ignore"):
        q = {"open": 100 / p["open"], "close": 100 / p["close"], "high": 100 / p["low"],
             "low": 100 / p["high"], "volume": p["volume"]}
    path = os.path.join(P.OUT, "panel_mirror_%s.npz" % universe)
    np.savez(path, dates=p["dates"], labels=p["labels"], member=p["member"],
             **{k: v.astype(np.float32) for k, v in q.items()})
    E.UNIVERSES["mirror_" + universe] = ("panel_mirror_%s.npz" % universe, cost)
    m = E.Market("mirror_" + universe)
    m.env["sample"] = np.broadcast_to(
        (np.arange(m.member.shape[0]) % 11 == 0).astype(np.float32)[:, None], m.member.shape).copy()
    return m


def as_short(m, trades):
    """The trades of a long on the inverted series, as the shorts they are:
    (R, net result, days) per trade."""
    out = []
    for t in trades:
        gross = t["gross"] / (1 + t["gross"])                # (entry - exit) / entry
        risk = t["risk"] / (1 - t["risk"])                   # (stop - entry) / entry
        net = gross - 2 * m.cost - BORROW * t["days"] / 252
        out.append((net / risk, net, t["days"]))
    return out


def figures(rows):
    if len(rows) < 30:
        return None
    r = np.array([x[0] for x in rows])
    return {"n": len(rows), "r": float(r.mean()), "win": float((r > 0).mean()),
            "win_r": float(r[r > 0].mean()) if (r > 0).any() else 0.0,
            "loss_r": float(r[r <= 0].mean()) if (r <= 0).any() else 0.0,
            "net": float(np.mean([x[1] for x in rows])), "days": float(np.mean([x[2] for x in rows]))}


def main():
    m = mirror()
    whole = ("2006-01-01", "2025-12-31")
    rows, placebo = [], {}
    for s in X.systems():
        base = {"id": s["id"], "entry": s["entry"], "exit": s.get("exit"), "max_days": s["max_days"],
                "stop_atr": 2.5}
        key = (s.get("exit"), s["max_days"])
        if key not in placebo:
            random = {**base, "entry": "(sample > 0)"}
            placebo[key] = [figures(as_short(m, T.simulate(m, random, *b))) for b in BLOCKS + [whole]]
        mine = [figures(as_short(m, T.simulate(m, base, *b))) for b in BLOCKS + [whole]]
        if mine[4]:
            rows.append({"id": s["id"], "blocks": mine[:4], "whole": mine[4], "placebo": placebo[key]})
    rows.sort(key=lambda x: -x["whole"]["r"])
    print("S&P 500, 2006-2025, acigA satis: her sistemin ayna goruntusu, stop girisin 2,5 ATR ustu")
    print("  %-34s %7s %4s %13s %7s %6s | %-27s | %s" % (
        "sistem (aynasi)", "islem", "kzn", "kazanc/kayip", "R", "net", "R: 06-10 11-15 16-20 21-25",
        "rastgele acigA satis R"))
    for x in rows:
        w, p = x["whole"], x["placebo"][4]
        print("  %-34s %7d %3.0f%% %+5.2f / %+5.2f %+7.2f %+5.2f%% | %-27s | %+5.2f" % (
            x["id"][:34], w["n"], 100 * w["win"], w["win_r"], w["loss_r"], w["r"], 100 * w["net"],
            " ".join("%+5.2f" % b["r"] if b else "  -  " for b in x["blocks"]), p["r"] if p else float("nan")))
    positive = sum(x["whole"]["r"] > 0 for x in rows)
    every = sum(all(b and b["r"] > 0 for b in x["blocks"]) for x in rows)
    beat = sum(all(b and p and b["r"] > p["r"] for b, p in zip(x["blocks"], x["placebo"][:4])) for x in rows)
    both = sum(all(b and p and b["r"] > 0 and b["r"] > p["r"] for b, p in zip(x["blocks"], x["placebo"][:4]))
               for x in rows)
    print("%d sistem; 20 yilda islem basi arti olan %d; dort blogun hepsinde arti %d; dort blogun hepsinde "
          "rastgele acigA satisi gecen %d; ikisi birden %d" % (len(rows), positive, every, beat, both))
    with open(OUT + ".tmp", "w") as fh:
        json.dump({"rows": rows, "positive": positive, "every_block": every, "above_placebo": beat,
                   "both": both}, fh)
        fh.write("\n")
    os.replace(OUT + ".tmp", OUT)


if __name__ == "__main__":
    main()
