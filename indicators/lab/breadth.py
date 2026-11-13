"""Every signal of one rule at a fixed sum at risk: the owner's scorecard.

plan.md, Phase 36. Ten slots take a random tenth of a rule's signals;
this takes all of them through `trades.simulate` (one position per
instrument at a time), puts the same sum at risk on each, marks the
positions every day and asks what R a month that is and what capital it
needs.

    breadth.py seen    # S&P 500 2006-2016, against the red team's figures
    breadth.py read    # S&P 500 2017-2025 and S&P 400/600 2011-2025
    breadth.py table   # every system with a stop on the same scorecard
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import book as B              # noqa: E402
import consistent as K        # noqa: E402
import engine as E            # noqa: E402
import stops as X             # noqa: E402
import trades as T            # noqa: E402

OUT = os.path.join(E.P.OUT, "breadth.json")
RISK = 100.0
GATE = "(market_up > 0) & "
RULE = {"id": "trend_hold_all", "entry": GATE + B.STATE, "exit": "(ma_cross < 0)",
        "stop_atr": 5, "max_days": 500}
PLACEBOS = {"uptrend, any range": GATE + "(ma_cross > 0) & (ma_gap200 > 0)",
            "50d over 200d only": GATE + "(ma_cross > 0)"}
WIDE_STOP = 0.15
DIP = GATE + "(ma_cross > 0) & (ma_gap200 > 0) & (rsi < 40)"
NAMED = [{"id": "profile_a", "entry": DIP, "exit": "(ma_gap200 < -0.02)", "stop_atr": 2, "max_days": 250},
         {"id": "profile_b", "entry": DIP + " & (rank(range14) < 0.4)", "exit": None,
          "stop": {"initial": ["atr", 5], "target_r": 4}, "max_days": 250},
         RULE]
MIN_TRADES = 100


def ledger(m, system, span, continuous=True, risk=RISK, keep=None):
    """The trades entered in the span and the account's days.

    Each trade buys risk / (stop distance as a share of price) of the
    stock. `continuous` counts entries up to the span's last day and values
    a position still open then at that day's close; otherwise the simulator
    drops the entries of the last `max_days`. Returns the trades as (entry
    date, exit date, R, net, days, risk as a share of price, reason,
    instrument) and, for the span's days, the money made and the money in
    positions. `keep(trade)` leaves a trade out when it returns False."""
    index = {d: i for i, d in enumerate(m.dates)}
    days = [i for i, d in enumerate(m.dates) if span[0] <= d <= span[1]]
    first, last = days[0], days[-1]
    close = m.bars["close"]
    made, held, rows = np.zeros(len(m.dates)), np.zeros(len(m.dates)), []
    for t in T.simulate(m, system, span[0], span[1], live=continuous):
        if t["entry"] is None or not t["risk"] or (keep is not None and not keep(t)):
            continue
        a, b, j = index[t["entry"]], index[t["exit"]], t["column"]
        if a > last:
            continue
        cut = b > last
        b = min(b, last)
        path = close[a:b + 1, j].astype(float)
        for k in np.where(~np.isfinite(path))[0]:
            path[k] = path[k - 1] if k else t["entry_price"]
        if not cut:
            path[-1] = t["exit_price"]
        path = np.concatenate([[t["entry_price"]], path])
        size = risk / t["risk"]
        made[a:b + 1] += size * np.diff(path) / t["entry_price"]
        made[a] -= size * m.cost
        made[b] -= size * m.cost
        held[a:b + 1] += size
        net = path[-1] / t["entry_price"] - 1 - 2 * m.cost
        rows.append((t["entry"], m.dates[b], net / t["risk"], net, b - a + 1, t["risk"],
                     "open" if cut else t["reason"], t["instrument"]))
    return rows, made[first:last + 1], held[first:last + 1], [m.dates[i] for i in days]


def holding(m, span):
    """The equal-weight members over the span: yearly return and drawdown."""
    close = m.bars["close"]
    inside = np.array([span[0] <= d <= span[1] for d in m.dates])
    with np.errstate(all="ignore"):
        daily = close[1:] / close[:-1] - 1
    ok = m.member[:-1] & np.isfinite(daily) & inside[1:, None]
    index = np.cumprod(1 + (np.where(ok, daily, 0).sum(axis=1) / np.maximum(ok.sum(axis=1), 1))[inside[1:]])
    return {"yearly": float(index[-1] ** (252 / len(index)) - 1),
            "drawdown": float((index / np.maximum.accumulate(index) - 1).min())}


def scorecard(rows, made, held, dates, risk=RISK):
    r = np.array([x[2] for x in rows])
    won = r > 0
    streak = longest = 0
    for x in sorted(rows, key=lambda x: (x[1], x[0])):
        streak = streak + 1 if x[2] <= 0 else 0
        longest = max(longest, streak)
    months = np.array([d[:7] for d in dates])
    names = sorted(set(months))
    monthly = np.array([made[months == u].sum() for u in names]) / risk
    entered = np.array([x[0][:7] for x in rows])
    per_month = np.array([(entered == u).sum() for u in names])
    twelve = np.convolve(monthly, np.ones(12), "valid") if len(monthly) >= 12 else monthly.sum(keepdims=True)
    years = len(dates) / 252
    total = np.cumsum(made)
    by_year = {}
    for x in rows:
        by_year.setdefault(x[0][:4], []).append(x[2])
    out = {"trades": len(r), "trades_a_month": float(len(r) / len(names)),
           "trades_a_month_median": float(np.median(per_month)),
           "avg_r": float(r.mean()), "win_rate": float(won.mean()),
           "avg_win_r": float(r[won].mean()), "avg_loss_r": float(r[~won].mean()),
           "worst_r": float(r.min()), "best_r": float(r.max()), "longest_losing_run": longest,
           "days": float(np.mean([x[4] for x in rows])),
           "risk_of_price": float(np.mean([x[5] for x in rows])),
           "wide_stops": float(np.mean([x[5] > WIDE_STOP for x in rows])),
           "open_at_end": float(np.mean([x[6] == "open" for x in rows])),
           "stopped": float(np.mean([x[6] == "stop" for x in rows])),
           "r_a_month": float(monthly.mean()), "r_a_month_median": float(np.median(monthly)),
           "worst_month_r": float(monthly.min()), "months_positive": float((monthly > 0).mean()),
           "worst_twelve_months_r": float(twelve.min()), "r_a_year": float(total[-1] / risk / years),
           "drawdown_r": float((total - np.maximum.accumulate(total)).min() / risk),
           "invested_max": float(held.max()), "invested_p95": float(np.percentile(held, 95)),
           "invested_mean": float(held.mean()),
           "by_year": {y: {"trades": len(v), "avg_r": float(np.mean(v)),
                           "win_rate": float(np.mean(np.array(v) > 0))} for y, v in sorted(by_year.items())},
           "monthly": {u: float(v) for u, v in zip(names, monthly)}}
    for name in ("max", "p95"):
        capital = out["invested_" + name]
        equity = capital + total
        out["account_" + name] = {
            "capital_per_r": capital / risk, "r_of_account": risk / capital,
            "yearly_simple": float(total[-1] / years / capital),
            "drawdown_of_capital": float((total - np.maximum.accumulate(np.maximum(total, 0))).min() / capital),
            "yearly_growth": float((equity[-1] / capital) ** (1 / years) - 1),
            "drawdown": float((equity / np.maximum.accumulate(np.maximum(equity, capital)) - 1).min())}
    return out


def line(name, s):
    a = s["account_max"]
    return ("  %-22s %5d islem (ayda %4.1f)  R %+5.2f  kazanan %%%2.0f (%+5.2f / %+5.2f)  %3.0f gun  "
            "ust uste kayip %2d | ayda %+5.1fR (medyan %+5.1f, en kotu %+4.0f, arti ay %%%2.0f)\n"
            "  %-22s 1R = fiyatin %%%4.1f'i; pozisyonlardaki para en cok %4.0fk$ (%%95: %4.0fk$) = 1R hesabin "
            "%%%.3f'i | o paraya gore yilda %+5.1f%%, dusus %+4.0f%% (%+.0fR); buyuyen hesap yilda %+5.1f%%, "
            "dusus %+4.0f%%"
            % (name, s["trades"], s["trades_a_month"], s["avg_r"], 100 * s["win_rate"], s["avg_win_r"],
               s["avg_loss_r"], s["days"], s["longest_losing_run"], s["r_a_month"], s["r_a_month_median"],
               s["worst_month_r"], 100 * s["months_positive"], "", 100 * s["risk_of_price"],
               s["invested_max"] / 1e3, s["invested_p95"] / 1e3, 100 * a["r_of_account"],
               100 * a["yearly_simple"], 100 * a["drawdown_of_capital"], s["drawdown_r"],
               100 * a["yearly_growth"], 100 * a["drawdown"]))


def study(universe, span, continuous=True, placebos=True, later=True):
    m = K.market(universe)
    out = {"span": list(span), "continuous": continuous, "cost": m.cost,
           "rule": scorecard(*ledger(m, RULE, span, continuous)), "holding": holding(m, span)}
    print("%s, %s .. %s (%s; her sinyale %d$ risk, gunluk degerleme, tarafi %%%.2f)"
          % (universe, span[0], span[1], "kesintisiz" if continuous else "son 500 gunun girisleri yok",
             RISK, 100 * m.cost))
    print(line("kural (sakin trend)", out["rule"]))
    if placebos:
        out["placebo"] = {}
        for name, entry in PLACEBOS.items():
            out["placebo"][name] = scorecard(*ledger(m, {**RULE, "id": name, "entry": entry}, span, continuous))
            print(line(name, out["placebo"][name]))
    print("  uyeleri esit agirlik tutmak: yilda %+.1f%%, dusus %+.0f%%"
          % (100 * out["holding"]["yearly"], 100 * out["holding"]["drawdown"]))
    print("  giris yilina gore: " + "  ".join(
        "%s %+.2fR/%d" % (y[2:], v["avg_r"], v["trades"]) for y, v in out["rule"]["by_year"].items()))
    out["killed"] = bool(out["rule"]["avg_r"] < 0.4 or out["rule"]["win_rate"] < 0.40)
    after = (str(int(span[1][:4]) + 1) + "-01-01", m.dates[-1])
    if later and continuous and after[0] <= after[1]:
        rows, made, held, dates = ledger(m, RULE, (span[0], after[1]))
        late = np.array([d >= after[0] for d in dates])
        entered = [x[2] for x in rows if x[0] >= after[0]]
        out["after"] = {"span": list(after), "r": float(made[late].sum() / RISK), "entered": len(entered),
                        "entered_avg_r": float(np.mean(entered)) if entered else None}
        print("  ayri: %s .. %s arasinda %+.0fR (o donemde acilan %d islem, simdiye kadar ortalama %s)"
              % (after[0], after[1], out["after"]["r"], len(entered),
                 "%+.2fR" % np.mean(entered) if entered else "-"))
    return out


def table(universe, span):
    """Every system that has a stop, on the owner's scorecard."""
    m = K.market(universe)
    rows, without = [], 0
    for system in X.systems() + NAMED:
        if not (system.get("stop_atr") or (system.get("stop") or {}).get("initial")):
            without += 1
            continue
        led = ledger(m, system, span)
        if len(led[0]) < MIN_TRADES:
            continue
        s = scorecard(*led)
        rows.append({"id": system["id"], **{k: s[k] for k in (
            "trades", "trades_a_month", "avg_r", "win_rate", "avg_win_r", "avg_loss_r", "days",
            "longest_losing_run", "r_a_month", "worst_month_r", "months_positive", "risk_of_price",
            "invested_max", "drawdown_r")}, "account": s["account_max"]})
    rows.sort(key=lambda x: -x["r_a_month"])
    print("%s, %s .. %s: her sinyale %d$ risk, gunluk degerleme (stopu olmayan %d sistem disarida)"
          % (universe, span[0], span[1], RISK, without))
    print("  %-24s %6s %6s %6s %5s %12s %5s %7s %7s %8s %6s %5s"
          % ("sistem", "islem", "ayda", "R", "kzn%", "kzn/kyp R", "gun", "ayda R", "1R=%fyt", "para k$", "yil%", "dusus"))
    for x in rows:
        print("  %-24s %6d %6.1f %+6.2f %5.0f %+6.2f/%+5.2f %5.0f %+7.1f %7.1f %8.0f %+6.1f %+5.0f"
              % (x["id"][:24], x["trades"], x["trades_a_month"], x["avg_r"], 100 * x["win_rate"],
                 x["avg_win_r"], x["avg_loss_r"], x["days"], x["r_a_month"], 100 * x["risk_of_price"],
                 x["invested_max"] / 1e3, 100 * x["account"]["yearly_growth"], 100 * x["account"]["drawdown"]))
    return {"span": list(span), "holding": holding(m, span), "rows": rows}


def main(argv):
    what = argv[1] if len(argv) > 1 else ""
    saved = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if what == "seen":
        saved["seen_block"] = study("sp500", ("2006-01-01", "2016-12-31"), continuous=False, placebos=False)
        saved["seen"] = study("sp500", ("2006-01-01", "2016-12-31"), later=False)
    elif what == "read":
        saved["sp500"] = study("sp500", ("2017-01-01", "2025-12-31"))
        saved["midsmall"] = study("midsmall", ("2011-01-01", "2025-12-31"))
    elif what == "table":
        saved["table_sp500"] = table("sp500", ("2017-01-01", "2025-12-31"))
    else:
        raise SystemExit(__doc__)
    with open(OUT, "w") as f:
        json.dump(saved, f, indent=1)


if __name__ == "__main__":
    main(sys.argv)
