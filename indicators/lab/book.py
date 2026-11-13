"""An account that holds a book of positions, marked every day.

plan.md, Phase 32. Unlike stops.account, which books closed trades, this
walks the days: what is held, what is stopped, what the rule says to
sell, what may be bought with the cash there is. One fill model, the
same as trades.py's: bought at the next open, an open under the stop is
sold at the open, a low under it at the stop, a rule exit at the next open.

    book.py seen       # 2006-2016, against the strategist's exploratory figures
    book.py read       # 2017-2025 and S&P 400/600 2011-2025, once
    book.py wide       # Phase 33: the dip model as 80 small positions
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import consistent as K        # noqa: E402
import engine as E            # noqa: E402
import trades as T            # noqa: E402

OUT = os.path.join(E.P.OUT, "book.json")
STATE = "(ma_cross > 0) & (ma_gap200 > 0) & (rank(range14) < 0.4)"
SEEDS, RANDOM = 20, 200


def run(m, span, wants, leave, seed, slots=10, risk=0.01, cap=0.10, stop_atr=5.0, hold=500,
        target_r=None, gated=True, log=None):
    """One account over a span. `wants[t, j]`: may be bought after the close
    of day t; `leave[t, j]`: to be sold at the next open. Free slots are
    filled in a random order drawn from `seed`. With `risk` None every
    position is `cap` of the account. Returns the daily equity and the
    trades as (entry date, R, net, days); `log` collects (entry day, exit
    day, share of the account spent) per position."""
    o, h, low, c = (m.bars[k] for k in ("open", "high", "low", "close"))
    atr = m.parts["range14"] * c
    gate = m.env["market_up"][:, 0] > 0 if gated else np.ones(len(m.dates), dtype=bool)
    rng = np.random.default_rng(seed)
    days = [i for i, d in enumerate(m.dates) if span[0] <= d <= span[1]]
    cash, held, wanted, curve, trades = 1.0, {}, [], [], []
    for t in days:
        for j in list(held):
            shares, paid, since, mark, stop, target, due, unit, part = held[j]
            price = None
            if not np.isfinite(o[t, j]):
                if not np.isfinite(c[t:, j]).any():
                    price = mark
            elif due or t - since >= hold or o[t, j] <= stop:
                price = o[t, j]
            elif low[t, j] <= stop:
                price = stop
            elif target is not None and h[t, j] >= target:
                price = max(target, o[t, j])
            if price is not None:
                cash += shares * price * (1 - m.cost)
                net = price * (1 - m.cost) / (paid * (1 + m.cost)) - 1
                trades.append((m.dates[since], net / unit, net, t - since))
                if log is not None:
                    log.append((since, t, part))
                del held[j]
        if wanted:
            equity = cash + sum(v[0] * v[3] for v in held.values())
            for j in wanted:
                if len(held) >= slots:
                    break
                size = atr[t - 1, j] * stop_atr
                if j in held or not np.isfinite(o[t, j]) or not size > 0.001 * o[t, j]:
                    continue
                unit = size / o[t, j]
                spend = min((cap if risk is None else min(risk / unit, cap)) * equity, cash)
                if spend <= 0:
                    break
                held[j] = (spend / (o[t, j] * (1 + m.cost)), o[t, j], t, o[t, j], o[t, j] - size,
                           None if target_r is None else o[t, j] + target_r * size, False, unit,
                           spend / equity)
                cash -= spend
            wanted = []
        for j in held:
            v = held[j]
            mark = c[t, j] if np.isfinite(c[t, j]) else v[3]
            held[j] = v[:3] + (mark,) + v[4:6] + (bool(v[6] or leave[t, j]),) + v[7:]
        curve.append(cash + sum(v[0] * v[3] for v in held.values()))
        if gate[t] and len(held) < slots:
            cols = np.where(wants[t])[0]
            wanted = [int(j) for j in rng.permutation(cols) if j not in held]
    for j, v in held.items():
        net = v[3] * (1 - m.cost) / (v[1] * (1 + m.cost)) - 1
        trades.append((m.dates[v[2]], net / v[7], net, days[-1] - v[2]))
    return np.array(curve), trades


def summary(curve, trades):
    years = len(curve) / 252
    r = np.array([t[1] for t in trades])
    won = r > 0
    by_exit, run_, longest = sorted(trades, key=lambda t: (t[0], t[3])), 0, 0
    for t in by_exit:
        run_ = run_ + 1 if t[1] <= 0 else 0
        longest = max(longest, run_)
    out = {"yearly": float(curve[-1] ** (1 / years) - 1),
           "drawdown": float((curve / np.maximum.accumulate(curve) - 1).min()),
           "trades": len(r), "per_year": len(r) / years, "win_rate": float(won.mean()),
           "avg_r": float(r.mean()), "avg_win_r": float(r[won].mean()) if won.any() else 0.0,
           "avg_loss_r": float(r[~won].mean()) if (~won).any() else 0.0,
           "days": float(np.mean([t[3] for t in trades])), "longest_losing_run": longest,
           "worst_r": float(r.min()), "best_r": float(r.max())}
    out["ratio"] = out["yearly"] / -out["drawdown"] if out["drawdown"] < 0 else float("inf")
    return out


def mean(rows, keys=("yearly", "drawdown", "ratio", "avg_r", "win_rate", "avg_win_r", "avg_loss_r",
                     "per_year", "days", "longest_losing_run")):
    return {k: float(np.mean([r[k] for r in rows])) for k in keys}


def line(name, s):
    return ("  %-36s yilda %+5.1f%%  dusus %+4.0f%%  oran %4.2f | yilda %4.1f islem  kazanan %%%2.0f  "
            "R %+5.2f (%+5.2f / %+5.2f)  %3.0f gun  ust uste kayip %2.0f"
            % (name, 100 * s["yearly"], 100 * s["drawdown"], s["ratio"], s["per_year"],
               100 * s["win_rate"], s["avg_r"], s["avg_win_r"], s["avg_loss_r"], s["days"],
               s["longest_losing_run"]))


def study(universe, span):
    m = K.market(universe)
    wants = T.flags(m, STATE) & m.member
    leave = T.flags(m, "(ma_cross < 0)")
    never = np.zeros(m.member.shape, dtype=bool)
    anyone = m.member & np.isfinite(m.bars["close"])
    book, by_year = [], {}
    for seed in range(SEEDS):
        curve, trades = run(m, span, wants, leave, seed)
        book.append(summary(curve, trades))
        for t in trades:
            by_year.setdefault(t[0][:4], []).append(t[1])
    target = [summary(*run(m, span, wants, never, seed, hold=250, target_r=4)) for seed in range(SEEDS)]
    random = [summary(*run(m, span, anyone, leave, seed)) for seed in range(RANDOM)]
    close = m.bars["close"]
    inside = np.array([span[0] <= d <= span[1] for d in m.dates])
    with np.errstate(all="ignore"):
        daily = close[1:] / close[:-1] - 1
    ok = m.member[:-1] & np.isfinite(daily) & inside[1:, None]
    index = np.cumprod(1 + (np.where(ok, daily, 0).sum(axis=1) / np.maximum(ok.sum(axis=1), 1))[inside[1:]])
    holding = {"yearly": float(index[-1] ** (252 / len(index)) - 1),
               "drawdown": float((index / np.maximum.accumulate(index) - 1).min())}
    mine, other = mean(book), mean(target)
    ratios = np.array([r["ratio"] for r in random])
    out = {"book": mine, "book_range": {k: [float(min(r[k] for r in book)), float(max(r[k] for r in book))]
                                        for k in ("yearly", "drawdown", "avg_r", "win_rate")},
           "target4": other, "random": mean(random),
           "random_ratio_p75": float(np.percentile(ratios, 75)),
           "above_random": float((mine["ratio"] > ratios).mean()), "holding": holding,
           "by_year": {y: float(np.mean(v)) for y, v in sorted(by_year.items())}}
    print("%s, %s .. %s (10 pozisyon, islem basi %%1 risk, gunluk degerleme)" % ((universe,) + span))
    print(line("trend bitene kadar tut (20 cekilis)", mine))
    print("     cekilisler arasi: yillik %+.1f..%+.1f%%, dusus %+.0f..%+.0f%%, R %+.2f..%+.2f, kazanan %%%.0f..%.0f"
          % (100 * out["book_range"]["yearly"][0], 100 * out["book_range"]["yearly"][1],
             100 * out["book_range"]["drawdown"][0], 100 * out["book_range"]["drawdown"][1],
             out["book_range"]["avg_r"][0], out["book_range"]["avg_r"][1],
             100 * out["book_range"]["win_rate"][0], 100 * out["book_range"]["win_rate"][1]))
    print(line("ayni hisseler, hedef 4R / 250 gun", other))
    print(line("rastgele uye, ayni kurallar (200)", out["random"]))
    print("  endeksi tutmak: yilda %+.1f%%, dusus %+.0f%% | kitabin getiri/dusus orani rastgele hesaplarin "
          "%%%.0f'inden iyi (75. yuzdelik %.2f)"
          % (100 * holding["yearly"], 100 * holding["drawdown"], 100 * out["above_random"],
             out["random_ratio_p75"]))
    print("  giris yilina gore R: " + "  ".join("%s %+.2f" % (y[2:], v) for y, v in out["by_year"].items()))
    out["killed"] = bool(mine["avg_r"] < 0.4 or mine["win_rate"] < 0.40 or mine["ratio"] <= other["ratio"]
                         or mine["ratio"] <= out["random_ratio_p75"])
    return out


def spy_instead(m, log, span):
    """The same purchases, made in SPY instead: bought at SPY's open on the
    entry day for the same share of the account, sold at its open on the
    exit day; 0.05% a side. Returns the daily equity."""
    p = E.P.load("panel_etf.npz")
    at = {str(d): i for i, d in enumerate(p["dates"])}
    j = [str(x) for x in p["labels"]].index("SPY")
    o = np.array([p["open"][at[d], j] if d in at else np.nan for d in m.dates])
    c = np.array([p["close"][at[d], j] if d in at else np.nan for d in m.dates])
    for series in (o, c):
        for i in range(1, len(series)):
            if not np.isfinite(series[i]):
                series[i] = series[i - 1]
    days = [i for i, d in enumerate(m.dates) if span[0] <= d <= span[1]]
    buys, sells = {}, {}
    for k, (a, b, part) in enumerate(log):
        buys.setdefault(a, []).append((k, part))
        sells.setdefault(b, []).append(k)
    cash, held, curve, mark = 1.0, {}, [], {}
    for t in days:
        for k in sells.get(t, []):
            if k in held:
                cash += held.pop(k) * o[t] * (1 - 0.0005)
        equity = cash + sum(s * c[t - 1] for s in held.values())
        for k, part in buys.get(t, []):
            spend = min(part * equity, cash)
            if spend > 0:
                held[k] = spend / (o[t] * (1 + 0.0005))
                cash -= spend
        curve.append(cash + sum(s * c[t] for s in held.values()))
    return np.array(curve)


def wide(span):
    """Phase 33: the stored dip model as an account of many small positions."""
    import combine as C2
    m = K.market("sp500")
    stored = C2.load_result("sp500")
    model = stored["models"]["dip"]
    entry, _ = C2.take(m, model, model["variants"][stored["choice"]["dip"]])
    leave = T.flags(m, "(z20 > 0)")
    kw = {"risk": None, "stop_atr": 2.5, "hold": 15, "gated": False}
    mine, logs = [], []
    for seed in range(SEEDS):
        log = []
        mine.append(summary(*run(m, span, entry, leave, seed, slots=80, cap=0.0125, log=log, **kw)))
        logs.append(log)
    few = [summary(*run(m, span, entry, leave, seed, slots=5, cap=0.20, **kw)) for seed in range(SEEDS)]
    inside = np.array([span[0] <= d <= span[1] for d in m.dates])
    random = []
    for seed in range(RANDOM):
        rng = np.random.default_rng(1000 + seed)
        fake = np.zeros(entry.shape, dtype=bool)
        for t in np.where(entry.any(axis=1) & inside)[0]:
            cols = np.where(m.member[t])[0]
            fake[t, rng.choice(cols, min(int(entry[t].sum()), len(cols)), replace=False)] = True
        random.append(summary(*run(m, span, fake, leave, seed, slots=80, cap=0.0125, **kw)))
    spy = []
    for log in logs[:5]:
        curve = spy_instead(m, log, span)
        spy.append({"yearly": float(curve[-1] ** (252 / len(curve)) - 1),
                    "drawdown": float((curve / np.maximum.accumulate(curve) - 1).min())})
    a, f, r = mean(mine), mean(few), mean(random)
    p90 = float(np.percentile([x["yearly"] for x in random], 90))
    spy_year = float(np.mean([x["yearly"] for x in spy]))
    print("sp500, %s .. %s: dipten alis modeli, genis hesap (gunluk degerleme)" % span)
    print(line("80 pozisyon x %1,25 (20 cekilis)", a))
    print(line("5 pozisyon x %20", f))
    print(line("ayni gunlerde rastgele uye, 80 x %1,25", r))
    print("  rastgele hesaplarin 90. yuzdeligi yilda %+.1f%% | ayni gunlerde ayni tutarda SPY: yilda %+.1f%%, "
          "dusus %+.0f%%" % (100 * p90, 100 * spy_year, 100 * np.mean([x["drawdown"] for x in spy])))
    killed = bool(a["yearly"] < 0.03 or a["yearly"] < p90 or a["yearly"] < spy_year or a["drawdown"] < -0.20)
    print("  sonuc: %s" % ("elendi" if killed else "ayakta"))
    return {"wide": a, "few": f, "random": r, "random_p90": p90, "spy": spy_year, "killed": killed}


def main(argv):
    result = json.load(open(OUT)) if os.path.exists(OUT) else {}
    command = argv[1] if len(argv) > 1 else "seen"
    if command == "wide":
        if "wide" in result:
            raise SystemExit("genis hesap zaten okundu")
        result["wide"] = {"2017-2021": wide(("2017-01-01", "2021-12-31")),
                          "2022-2025": wide(("2022-01-01", "2025-12-31"))}
    elif command == "seen":
        result["seen"] = study("sp500", ("2006-01-01", "2016-12-31"))
    elif command == "read":
        if "read" in result:
            raise SystemExit("2017-2025 ve orta/kucuk bu kural icin zaten okundu")
        result["read"] = {"sp500": study("sp500", ("2017-01-01", "2025-12-31")),
                          "midsmall": study("midsmall", ("2011-01-01", "2025-12-31"))}
        for u, s in result["read"].items():
            print("  %s: %s" % (u, "elendi" if s["killed"] else "ayakta"))
    else:
        raise SystemExit("bilinmeyen komut: %s" % command)
    with open(OUT + ".tmp", "w") as fh:
        json.dump(result, fh, indent=1)
        fh.write("\n")
    os.replace(OUT + ".tmp", OUT)


if __name__ == "__main__":
    main(sys.argv)
