"""Long holds: a ten-slot account that buys calm stocks while the market is up.

plan.md, Phase 26. Few trades, held for months, a fixed 15% stop, judged
as an account against accounts that pick at random under the same rules
and against simply holding.

    position.py discover     # 2006-2016, with 500 random accounts
    position.py validate     # 2017-2021, once, only if discovery did not kill it
    position.py scan         # 2006-2016: other stops, limits, exits and selections
    position.py chosen       # the variant taken on from the scan, 2006-2016 and 2017-2021
    position.py sealed       # that variant on 2022-2025, once
    position.py company      # the same account with the company side in the selection
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E            # noqa: E402

OUT = os.path.join(E.P.OUT, "position.json")
SLOTS, STOP, HOLD, COST, RANDOM = 10, 0.15, 250, 0.001, 500


def setting(m):
    """Per day: the equal-weight index and whether it is above its 200-day
    average, month ends, and who may be bought (all members; the calm ones)."""
    close = m.bars["close"]
    with np.errstate(all="ignore"):
        daily = close[1:] / close[:-1] - 1
    ok = m.member[:-1] & np.isfinite(daily)
    mean = np.where(ok, daily, 0).sum(axis=1) / np.maximum(ok.sum(axis=1), 1)
    index = np.concatenate([[1.0], np.cumprod(1 + mean)])
    average = np.full(len(index), np.nan)
    total = np.cumsum(index)
    average[199:] = (total[199:] - np.concatenate([[0], total[:-200]])) / 200
    up = index > average
    month_end = np.array([m.dates[i][:7] != m.dates[i + 1][:7] for i in range(len(m.dates) - 1)]
                         + [False])
    calm = np.zeros(m.member.shape, dtype=bool)
    rng14, above = m.parts["range14"], m.parts["ma_gap200"] > 0
    for t in np.where(month_end)[0]:
        known = m.member[t] & np.isfinite(rng14[t])
        if known.sum() >= 50:
            calm[t] = known & above[t] & (rng14[t] <= np.percentile(rng14[t, known], 20))
    return index, up, month_end, calm


def run(m, stage, pick, up, month_end, stop=STOP, hold=HOLD, trend_exit=False, risk=None, span=None):
    """One account over a stage. `pick(t, held)` gives the columns to buy
    after the close of day t, best first. Returns the daily equity and the
    closed trades as (net result, days). With `trend_exit` a position is
    also sold at the open after a close under its own 200-day average.
    With `risk` a position is sized so that the stop costs that share of
    the account (at most a fifth of it), instead of a tenth of the account."""
    o, low, c = m.bars["open"], m.bars["low"], m.bars["close"]
    under = m.parts["ma_gap200"] < 0
    STOP, HOLD = stop, hold
    first, last = span or E.STAGES[stage]
    days = [i for i, d in enumerate(m.dates) if first <= d <= last]
    cash, held, wanted, curve, trades = 1.0, {}, [], [], []
    for t in days:
        for j, (shares, paid, since, mark) in list(held.items()):
            price = None
            if not np.isfinite(o[t, j]):
                if not np.isfinite(c[t:, j]).any():        # it stopped trading: out at the last price
                    price = mark
            elif (t - since >= HOLD or o[t, j] <= paid * (1 - STOP)
                  or (trend_exit and t - since >= 1 and under[t - 1, j])):
                price = o[t, j]
            elif low[t, j] <= paid * (1 - STOP):
                price = paid * (1 - STOP)
            if price is not None:
                cash += shares * price * (1 - COST)
                trades.append((price * (1 - COST) / (paid * (1 + COST)) - 1, t - since))
                del held[j]
        if wanted:
            equity = cash + sum(s * mk for s, _, _, mk in held.values())
            for j in wanted:
                if len(held) >= SLOTS or j in held or not np.isfinite(o[t, j]):
                    continue
                spend = min(equity / SLOTS if risk is None else min(risk / STOP, 0.2) * equity, cash)
                if spend <= 0:
                    break
                held[j] = (spend / (o[t, j] * (1 + COST)), o[t, j], t, o[t, j])
                cash -= spend
            wanted = []
        for j, (shares, paid, since, mark) in held.items():
            if np.isfinite(c[t, j]):
                held[j] = (shares, paid, since, c[t, j])
        curve.append(cash + sum(s * mk for s, _, _, mk in held.values()))
        if month_end[t] and up[t] and len(held) < SLOTS:
            wanted = pick(t, held)
    for j, (shares, paid, since, mark) in held.items():     # marked, not sold, at the stage's end
        trades.append((mark * (1 - COST) / (paid * (1 + COST)) - 1, days[-1] - since))
    return np.array(curve), trades


def summary(curve, trades=None, STOP=STOP):
    years = len(curve) / 252
    out = {"yearly": float(curve[-1] ** (1 / years) - 1),
           "drawdown": float((curve / np.maximum.accumulate(curve) - 1).min())}
    out["ratio"] = out["yearly"] / -out["drawdown"] if out["drawdown"] < 0 else float("inf")
    if trades:
        net = np.array([t[0] for t in trades])
        r = net / STOP
        won = r > 0
        out.update({"trades": len(net), "per_year": len(net) / years, "win_rate": float(won.mean()),
                    "avg_r": float(r.mean()), "avg_win_r": float(r[won].mean()) if won.any() else 0.0,
                    "avg_loss_r": float(r[~won].mean()) if (~won).any() else 0.0,
                    "net": float(net.mean()), "days": float(np.mean([t[1] for t in trades])),
                    "stopped": float((net <= -STOP + 0.02).mean()), "worst": float(net.min())})
    return out


def line(name, s):
    text = "  %-34s yilda %+6.1f%%  en derin dusus %+5.0f%%  oran %5.2f" % (
        name, 100 * s["yearly"], 100 * s["drawdown"], s["ratio"])
    if "trades" in s:
        text += ("  | %4d islem (yilda %4.1f)  kazanan %%%2.0f  R %+5.2f (kazanc %+5.2f, kayip %+5.2f)  "
                 "%3.0f gun  en kotu %+4.0f%%"
                 % (s["trades"], s["per_year"], 100 * s["win_rate"], s["avg_r"], s["avg_win_r"],
                    s["avg_loss_r"], s["days"], 100 * s["worst"]))
    return text


def study(m, stage):
    index, up, month_end, calm = setting(m)
    rng14 = m.parts["range14"]
    first, last = E.STAGES[stage]
    span = np.array([first <= d <= last for d in m.dates])

    def calmest(t, held):
        cols = np.where(calm[t])[0]
        return [int(j) for j in cols[np.argsort(rng14[t, cols])] if j not in held]

    mine = summary(*run(m, stage, calmest, up, month_end))
    randoms = []
    for seed in range(RANDOM):
        rng = np.random.default_rng(seed)

        def anyone(t, held, rng=rng):
            cols = np.where(m.member[t] & np.isfinite(m.bars["close"][t]))[0]
            return [int(j) for j in rng.permutation(cols) if j not in held]
        randoms.append(summary(*run(m, stage, anyone, up, month_end)))
    hold = index[span] / index[span][0]
    timed, inside = [1.0], False
    days = np.where(span)[0]
    for a, b in zip(days[:-1], days[1:]):
        timed.append(timed[-1] * (index[b] / index[a] if inside else 1.0))
        if month_end[b]:
            inside = bool(up[b])
    out = {"calm": mine, "holding": summary(hold), "timed": summary(np.array(timed)),
           "random": {k: [float(np.percentile([r[k] for r in randoms], q)) for q in (25, 50, 75)]
                      for k in ("yearly", "drawdown", "ratio", "avg_r", "win_rate")},
           "above": float(np.mean([mine["ratio"] > r["ratio"] for r in randoms]))}
    print("%s, %s .. %s" % (m.universe, first, last))
    print(line("sakin hisseler, piyasa yukaridayken", mine))
    print(line("endeksi oldugu gibi tutmak", out["holding"]))
    print(line("endeks, 200 gunlugun ustundeyken", out["timed"]))
    r = out["random"]
    print("  rastgele secen %d hesap (ceyrek / medyan / ceyrek): yillik %+.1f / %+.1f / %+.1f%%, dusus "
          "%+.0f / %+.0f / %+.0f%%, oran %.2f / %.2f / %.2f, islem basi R %+.2f / %+.2f / %+.2f, "
          "kazanan %%%.0f / %.0f / %.0f"
          % ((RANDOM,) + tuple(100 * x for x in r["yearly"]) + tuple(100 * x for x in r["drawdown"])
             + tuple(r["ratio"]) + tuple(r["avg_r"]) + tuple(100 * x for x in r["win_rate"])))
    print("  sakin hesap, rastgele hesaplarin %%%.0f'inden iyi (getiri / dusus oraninda)" % (100 * out["above"]))
    return out


def scan(m):
    """2006-2016 only: the long-hold account with other stops, limits,
    exits and selections, positions sized by risk. Nothing is recorded."""
    index, up, month_end, calm = setting(m)
    rng14, mom, above = m.parts["range14"], m.parts["mom12_1"], m.parts["ma_gap200"] > 0
    order = np.random.default_rng(0).permutation(m.member.shape[1])

    def chooser(kind):
        def pick(t, held):
            if kind == "calm":
                cols = np.where(calm[t])[0]
                cols = cols[np.argsort(rng14[t, cols])]
            elif kind == "calm+momentum":
                cols = np.where(calm[t] & np.isfinite(mom[t]))[0]
                cols = cols[np.argsort(-mom[t, cols])]
            elif kind == "momentum":
                known = m.member[t] & np.isfinite(mom[t])
                cols = np.where(known & above[t] & (mom[t] >= np.percentile(mom[t, known], 80)))[0]
                cols = cols[np.argsort(-mom[t, cols])]
            else:
                cols = np.array([j for j in order if m.member[t, j] and above[t, j]])
            return [int(j) for j in cols if j not in held]
        return pick
    rows = []
    for kind in ("calm", "calm+momentum", "momentum", "any"):
        pick = chooser(kind)
        for stop in (0.06, 0.08, 0.10, 0.12, 0.15, 0.20):
            for hold in (120, 250, 500):
                for trend_exit in (False, True):
                    curve, trades = run(m, "discover", pick, up, month_end, stop, hold, trend_exit, 0.01)
                    s = summary(curve, trades, STOP=stop)
                    rows.append((kind, stop, hold, trend_exit, s))
    print("2006-2016, pozisyon riske gore (%1 risk, en cok %20, en cok 10 pozisyon); 100 $ risk = 1R")
    print("  %-14s %5s %4s %6s | %5s %7s %13s %6s %7s %9s | %7s %6s" % (
        "secim", "stop", "gun", "trend", "islem", "kazanan", "kazanc/kayip", "R", "islem/y", "$/yil", "hesap", "dusus"))
    for kind, stop, hold, trend_exit, s in sorted(rows, key=lambda r: -r[4]["avg_r"] * r[4]["per_year"]):
        print("  %-14s %4.0f%% %4d %6s | %5d %6.0f%% %+5.2f / %+5.2f %+6.2f %7.1f %+9.0f | %+6.1f%% %+5.0f%%"
              % (kind, 100 * stop, hold, "cikis" if trend_exit else "-", s["trades"], 100 * s["win_rate"],
                 s["avg_win_r"], s["avg_loss_r"], s["avg_r"], s["per_year"],
                 100 * s["avg_r"] * s["per_year"], 100 * s["yearly"], 100 * s["drawdown"]))


def chosen(m, stage, stop=0.08, hold=250):
    """The variant taken on from the scan (calmest fifth, 8% stop, 250
    days, sized by risk) on one stage, beside holding and 200 accounts that
    pick at random under the same rules."""
    index, up, month_end, calm = setting(m)
    rng14 = m.parts["range14"]
    first, last = E.STAGES[stage]
    span = np.array([first <= d <= last for d in m.dates])

    def calmest(t, held):
        cols = np.where(calm[t])[0]
        return [int(j) for j in cols[np.argsort(rng14[t, cols])] if j not in held]
    mine = summary(*run(m, stage, calmest, up, month_end, stop, hold, False, 0.01), STOP=stop)
    randoms = []
    for seed in range(200):
        rng = np.random.default_rng(seed)

        def anyone(t, held, rng=rng):
            cols = np.where(m.member[t] & np.isfinite(m.bars["close"][t]))[0]
            return [int(j) for j in rng.permutation(cols) if j not in held]
        randoms.append(summary(*run(m, stage, anyone, up, month_end, stop, hold, False, 0.01), STOP=stop))
    hold_curve = index[span] / index[span][0]
    timed, inside = [1.0], False
    days = np.where(span)[0]
    for a, b in zip(days[:-1], days[1:]):
        timed.append(timed[-1] * (index[b] / index[a] if inside else 1.0))
        if month_end[b]:
            inside = bool(up[b])
    out = {"calm": mine, "holding": summary(hold_curve), "timed": summary(np.array(timed)),
           "random": {k: float(np.median([r[k] for r in randoms]))
                      for k in ("yearly", "drawdown", "avg_r", "win_rate", "per_year")},
           "above_r": float(np.mean([mine["avg_r"] > r["avg_r"] for r in randoms]))}
    print("%s, %s .. %s: en sakin beste bir, stop %%%g, en cok %d gun, islem basi %%1 risk"
          % (m.universe, first, last, 100 * stop, hold))
    print(line("sakin hisseler", mine))
    print("  100 $ riskle: islem basi %+.0f $, yilda %+.0f $ (%.1f islem), kazanan %+.0f $, kaybeden %+.0f $"
          % (100 * mine["avg_r"], 100 * mine["avg_r"] * mine["per_year"], mine["per_year"],
             100 * mine["avg_win_r"], 100 * mine["avg_loss_r"]))
    print(line("endeksi oldugu gibi tutmak", out["holding"]))
    print(line("endeks, 200 gunlugun ustundeyken", out["timed"]))
    r = out["random"]
    print("  rastgele secen 200 hesap (medyan): yillik %+.1f%%, dusus %+.0f%%, islem basi R %+.2f, kazanan "
          "%%%.0f, yilda %.1f islem; sakin hesabin R'si bunlarin %%%.0f'inden yuksek"
          % (100 * r["yearly"], 100 * r["drawdown"], r["avg_r"], 100 * r["win_rate"], r["per_year"],
             100 * out["above_r"]))
    return out


SPANS = {"2013-2016": ("2013-04-01", "2016-12-31"), "2017-2021": ("2017-01-01", "2021-12-31"),
         "2022-2025": ("2022-01-01", "2025-12-31")}
SELECTIONS = ("calm", "calm+investable", "calm+quality", "investable", "top-score")


def company_side(m):
    """Per month end and column: the company side's latest verdict, overall
    score and business score known that day (data/backtest_rows.json)."""
    rows = json.load(open(os.path.join(E.P.OUT, "..", "backtest_rows.json")))
    known = {}
    for r in rows:
        known.setdefault(r["ticker"], []).append((r["asof"], r["verdict"] == "yatirim yapilabilir",
                                                   r.get("overall"), r.get("business_score")))
    for v in known.values():
        v.sort()
    shape = m.member.shape
    good = np.zeros(shape, dtype=bool)
    overall = np.full(shape, np.nan, dtype=np.float32)
    business = np.full(shape, np.nan, dtype=np.float32)
    month_end = [i for i in range(len(m.dates) - 1) if m.dates[i][:7] != m.dates[i + 1][:7]]
    for j, label in enumerate(m.labels):
        mine = known.get(label) or known.get(label.split("-")[0])
        if not mine:
            continue
        k = 0
        for t in month_end:
            while k + 1 < len(mine) and mine[k + 1][0] <= m.dates[t]:
                k += 1
            if mine[k][0] <= m.dates[t] and m.dates[t][:4] <= str(int(mine[k][0][:4]) + 1):
                good[t, j] = mine[k][1]
                overall[t, j] = np.nan if mine[k][2] is None else mine[k][2]
                business[t, j] = np.nan if mine[k][3] is None else mine[k][3]
    return good, overall, business


def with_company(m, periods=("2013-2016", "2017-2021"), selections=SELECTIONS):
    index, up, month_end, calm = setting(m)
    good, overall, business = company_side(m)
    rng14, above = m.parts["range14"], m.parts["ma_gap200"] > 0

    def chooser(kind):
        def pick(t, held):
            if kind == "calm":
                cols = np.where(calm[t])[0]
                cols = cols[np.argsort(rng14[t, cols])]
            elif kind == "calm+investable":
                cols = np.where(calm[t] & good[t])[0]
                cols = cols[np.argsort(rng14[t, cols])]
            elif kind == "calm+quality":
                seen = m.member[t] & np.isfinite(business[t])
                cols = np.where(calm[t] & seen & (business[t] >= np.nanmedian(business[t, seen])))[0] \
                    if seen.sum() >= 50 else np.array([], dtype=int)
                cols = cols[np.argsort(-business[t, cols])]
            elif kind == "investable":
                cols = np.where(m.member[t] & above[t] & good[t] & np.isfinite(overall[t]))[0]
                cols = cols[np.argsort(-overall[t, cols])]
            else:
                seen = m.member[t] & np.isfinite(overall[t])
                cols = np.where(seen & above[t] & (overall[t] >= np.percentile(overall[t, seen], 80)))[0] \
                    if seen.sum() >= 50 else np.array([], dtype=int)
                cols = cols[np.argsort(-overall[t, cols])]
            return [int(j) for j in cols if j not in held]
        return pick
    out = {}
    for period in periods:
        print("S&P 500, %s: stop %%8, en cok 250 gun, islem basi %%1 risk, 10 pozisyon" % period)
        for kind in selections:
            s = summary(*run(m, None, chooser(kind), up, month_end, 0.08, 250, False, 0.01,
                             span=SPANS[period]), STOP=0.08)
            out.setdefault(kind, {})[period] = s
            print(line(kind, s) + ("  100$: yilda %+5.0f $" % (100 * s["avg_r"] * s["per_year"])
                                   if "trades" in s else ""))
    return out


def main(argv):
    stage = argv[1] if len(argv) > 1 else "discover"
    if stage == "company":
        result = json.load(open(OUT)) if os.path.exists(OUT) else {}
        if "company" in result:
            raise SystemExit("sirket tarafi karsilastirmasi zaten okundu")
        out = with_company(E.Market("sp500"))
        base = out["calm"]
        better = [k for k in SELECTIONS[1:]
                  if all(out[k][p].get("trades", 0) >= 30 and out[k][p]["avg_r"] > base[p]["avg_r"]
                         and out[k][p]["win_rate"] > base[p]["win_rate"] for p in ("2013-2016", "2017-2021"))]
        print("  iki donemde de 'calm'i gecenler: %s" % (", ".join(better) or "yok"))
        result["company"] = {"periods": out, "better": better}
        with open(OUT + ".tmp", "w") as fh:
            json.dump(result, fh, indent=1)
            fh.write("\n")
        os.replace(OUT + ".tmp", OUT)
        return None
    if stage == "scan":
        return scan(E.Market("sp500"))
    if stage == "company-sealed":
        result = json.load(open(OUT)) if os.path.exists(OUT) else {}
        if "company_sealed" in result:
            raise SystemExit("2022-2025 bu secim icin zaten okundu")
        out = with_company(E.Market("sp500"), ("2022-2025",), ("calm", "calm+quality"))
        s = out["calm+quality"]["2022-2025"]
        alive = s.get("trades", 0) >= 30 and s["avg_r"] >= 0.7 and s["win_rate"] >= 0.5
        print("  sonuc: %s" % ("aday olarak yasiyor" if alive else "elendi"))
        result["company_sealed"] = {"periods": out, "alive": alive}
        with open(OUT + ".tmp", "w") as fh:
            json.dump(result, fh, indent=1)
            fh.write("\n")
        os.replace(OUT + ".tmp", OUT)
        return None
    if stage == "sealed":
        result = json.load(open(OUT)) if os.path.exists(OUT) else {}
        if not result.get("chosen", {}).get("survived"):
            raise SystemExit("secilen varyant 2017-2021'i gecmedi ya da okunmadi")
        if "sealed" in result:
            raise SystemExit("2022-2025 zaten okundu")
        out = chosen(E.Market("sp500"), "sealed")
        c, t = out["calm"], out["timed"]
        out["survived"] = (c["avg_r"] >= 0.4 and c["win_rate"] >= 0.5
                           and not (t["yearly"] - c["yearly"] > 0.03 and c["drawdown"] <= t["drawdown"]))
        print("  sonuc: %s" % ("yasiyor" if out["survived"] else "elendi"))
        result["sealed"] = out
        with open(OUT + ".tmp", "w") as fh:
            json.dump(result, fh, indent=1)
            fh.write("\n")
        os.replace(OUT + ".tmp", OUT)
        return None
    if stage == "chosen":
        result = json.load(open(OUT)) if os.path.exists(OUT) else {}
        if "chosen" in result:
            raise SystemExit("secilen varyant 2017-2021'de zaten okundu")
        m = E.Market("sp500")
        out = {"discover": chosen(m, "discover"), "validate": chosen(m, "validate")}
        c, t = out["validate"]["calm"], out["validate"]["timed"]
        out["survived"] = (c["avg_r"] >= 0.5 and c["win_rate"] >= 0.5
                           and not (t["yearly"] - c["yearly"] > 0.03 and c["drawdown"] <= t["drawdown"]))
        print("  sonuc: %s" % ("yasiyor" if out["survived"] else "elendi"))
        result["chosen"] = out
        with open(OUT + ".tmp", "w") as fh:
            json.dump(result, fh, indent=1)
            fh.write("\n")
        os.replace(OUT + ".tmp", OUT)
        return None
    if stage not in ("discover", "validate"):
        raise SystemExit("bu asamada yalnizca discover ve validate okunur")
    result = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if stage in result:
        raise SystemExit("%s zaten okundu" % stage)
    if stage == "validate" and not result.get("discover", {}).get("survived"):
        raise SystemExit("kesif asamasinda elendi ya da henuz calismadi")
    m = E.Market("sp500")
    out = study(m, stage)
    if stage == "discover":
        out["survived"] = out["above"] > 0.75
        print("  sonuc: %s" % ("yasiyor, 2017-2021 okunabilir" if out["survived"] else "elendi"))
    else:
        c, t = out["calm"], out["timed"]
        out["survived"] = (c["avg_r"] >= 0.3 and c["win_rate"] >= 0.5
                           and not (t["yearly"] - c["yearly"] > 0.03 and c["drawdown"] <= t["drawdown"]))
        print("  sonuc: %s" % ("yasiyor" if out["survived"] else "elendi"))
    result[stage] = out
    with open(OUT + ".tmp", "w") as fh:
        json.dump(result, fh, indent=1)
        fh.write("\n")
    os.replace(OUT + ".tmp", OUT)


if __name__ == "__main__":
    main(sys.argv)
