"""The account and not the trade: three studies judged in money.

plan.md, Phases 38 to 40 and "The money criterion". Each is read beside
the universe held and beside the universe held at the rule's own share
invested, with idle money at the 3-month bill rate.

    capital.py issuance            # Phase 38: the every-signal book split by net issuance
    capital.py calm seen | read    # Phase 39: calm members, fully invested under the gate
    capital.py dips seen | read    # Phase 40: SPY after days of many oversold members
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breadth as W           # noqa: E402
import consistent as K        # noqa: E402
import engine as E            # noqa: E402

OUT = os.path.join(E.P.OUT, "capital.json")
DATA = os.path.join(E.P.OUT, "..")
ROWS = {"sp500": "backtest_rows.json", "midsmall": "backtest_rows_midsmall.json"}
MAX_AGE, MIN_MONTH = 200, 6
SPREAD = 0.015
SEEN = ("2006-01-01", "2016-12-31")
DIP_SHARE, DIP_DAYS, SPY_COST = 80, 5, 0.0005


def bills(dates):
    """The 3-month Treasury bill rate as a daily return for each date."""
    rate = {}
    for row in csv.DictReader(open(os.path.join(DATA, "macro", "TB3MS.csv"))):
        rate[row["observation_date"][:7]] = float(row["TB3MS"]) / 100
    return np.array([rate.get(d[:7], 0.0) for d in dates]) / 252


def members_daily(m):
    """The equal-weight members' return of each day (0 on the first)."""
    close = m.bars["close"]
    with np.errstate(all="ignore"):
        daily = close[1:] / close[:-1] - 1
    ok = m.member[:-1] & np.isfinite(daily)
    return np.concatenate([[0.0], np.where(ok, daily, 0).sum(axis=1) / np.maximum(ok.sum(axis=1), 1)])


def curve(daily, bill):
    equity = np.cumprod(1 + daily)
    years = len(daily) / 252
    over = daily - bill
    return {"yearly": float(equity[-1] ** (1 / years) - 1), "volatility": float(daily.std() * np.sqrt(252)),
            "sharpe": float(over.mean() / over.std() * np.sqrt(252)) if over.std() > 0 else 0.0,
            "drawdown": float((equity / np.maximum.accumulate(np.maximum(equity, 1)) - 1).min())}


def money(made, held, universe, bill):
    """The money criterion for a fixed-risk book: the account on the most
    money it ever had in positions with idle money at bills, the universe
    held, and the universe held at the book's own daily share invested."""
    capital = held.max()
    share = held / capital
    return {"capital": float(capital), "invested": float(share.mean()),
            "account": curve((made + (capital - held) * bill) / capital, bill),
            "held": curve(universe, bill),
            "at_same_exposure": curve(share * universe + (1 - share) * bill, bill)}


def money_line(name, s):
    return ("  %-30s yilda %+5.1f%%  dusus %+4.0f%%  Sharpe %5.2f" %
            (name, 100 * s["yearly"], 100 * s["drawdown"], s["sharpe"]))


def company(universe):
    known = {}
    for row in json.load(open(os.path.join(DATA, ROWS[universe]))):
        if row.get("net_issuance") is not None:
            known.setdefault(row["ticker"], []).append((row["asof"], row["net_issuance"]))
    for rows in known.values():
        rows.sort()
    return known


def _age(a, b):
    return (np.datetime64(b) - np.datetime64(a)).astype(int)


def issuance(universe, span):
    m = K.market(universe)
    known = company(universe)
    rows, made, held, dates = W.ledger(m, W.RULE, span)
    tagged, by_month = [], {}
    for x in rows:
        seen = [(a, v) for a, v in known.get(x[7], []) if a < x[0]]
        if seen and _age(seen[-1][0], x[0]) <= MAX_AGE:
            tagged.append((x, seen[-1][1]))
            by_month.setdefault(x[0][:7], []).append(seen[-1][1])
    low, high = [], []
    for x, value in tagged:
        values = by_month[x[0][:7]]
        if len(values) < MIN_MONTH:
            continue
        a, b = np.quantile(values, [1 / 3, 2 / 3])
        if value <= a:
            low.append(x)
        elif value >= b:
            high.append(x)
    months = sorted({x[0][:7] for x in low} & {x[0][:7] for x in high})
    diff_r = np.array([np.mean([x[2] for x in low if x[0][:7] == u]) - np.mean([x[2] for x in high if x[0][:7] == u])
                       for u in months])
    diff_net = np.array([np.mean([x[3] for x in low if x[0][:7] == u])
                         - np.mean([x[3] for x in high if x[0][:7] == u]) for u in months])

    def side(group):
        r = np.array([x[2] for x in group])
        return {"trades": len(r), "avg_r": float(r.mean()), "win_rate": float((r > 0).mean()),
                "net": float(np.mean([x[3] for x in group])), "days": float(np.mean([x[4] for x in group])),
                "risk_of_price": float(np.mean([x[5] for x in group]))}

    def t(series):
        return float(series.mean() / series.std(ddof=1) * np.sqrt(len(series)))

    chosen = {(x[7], x[0]) for x in low}
    book = W.ledger(m, W.RULE, span, keep=lambda trade: (trade["instrument"], trade["entry"]) in chosen)
    first = [x[0] for x, _ in tagged]
    inside = np.array([d >= min(first)[:8] + "01" for d in dates])
    universe_daily, bill = members_daily(m), bills(m.dates)
    at = {d: i for i, d in enumerate(m.dates)}
    idx = np.array([at[d] for d in dates])[inside]
    out = {"span": [dates[int(np.argmax(inside))], span[1]], "trades": len(rows), "tagged": len(tagged),
           "low": side(low), "high": side(high), "months": len(months),
           "difference_r": float(diff_r.mean()), "t_r": t(diff_r),
           "difference_net": float(diff_net.mean()), "t_net": t(diff_net),
           "book": W.scorecard(book[0], book[1][inside], book[2][inside], list(np.array(dates)[inside])),
           "money": money(book[1][inside], book[2][inside], universe_daily[idx], bill[idx]),
           "money_all": money(made[inside], held[inside], universe_daily[idx], bill[idx])}
    for key in ("monthly", "by_year"):
        out["book"].pop(key)
    print("%s, %s .. %s: %d islemin %d'inde sirket satiri var" % (universe, out["span"][0], span[1], len(rows), len(tagged)))
    for name, s in (("en az hisse cikaran ucte bir", out["low"]), ("en cok cikaran ucte bir", out["high"])):
        print("  %-30s %5d islem  R %+5.2f  kazanan %%%2.0f  net %+5.1f%%  %3.0f gun  1R = fiyatin %%%.1f'i"
              % (name, s["trades"], s["avg_r"], 100 * s["win_rate"], 100 * s["net"], s["days"],
                 100 * s["risk_of_price"]))
    print("  fark (giris ayina gore, %d ay): %+.2fR (t %.1f), net %+.1f%% (t %.1f)"
          % (len(months), out["difference_r"], out["t_r"], 100 * out["difference_net"], out["t_net"]))
    b, mny = out["book"], out["money"]
    print("  alt ucte bir, kitap olarak: ayda %.1f islem, %+.2fR, ayda %+.1fR, en cok %.0fk$ (ortalama %%%.0f'i yatirimda)"
          % (b["trades_a_month"], b["avg_r"], b["r_a_month"], mny["capital"] / 1e3, 100 * mny["invested"]))
    print(money_line("  kitap (bos para bonoda)", mny["account"]))
    print(money_line("  ayni oranda yatirimla endeks", mny["at_same_exposure"]))
    print(money_line("  butun kitap (Phase 36)", out["money_all"]["account"]))
    print(money_line("  butun kitabin oraninda endeks", out["money_all"]["at_same_exposure"]))
    print(money_line("  uyeleri tutmak", mny["held"]))
    out["killed"] = bool(not (out["difference_r"] >= 0.2 and out["t_r"] >= 2
                              and mny["account"]["yearly"] > mny["at_same_exposure"]["yearly"]))
    return out


def portfolio(m, span, select, leverage=1.0, gated=True, delay=1):
    """Monthly equal-weight holdings as daily returns over the span.

    At each month's last close `select(day)` names the holdings; under the
    gate the account holds them at `leverage` times its value, otherwise
    bills. The new holdings earn from `delay` days after the signal's
    close. Idle money earns the bill rate, borrowed money pays it plus
    SPREAD. Returns the daily returns and the share invested each day."""
    close = m.bars["close"].astype(float)
    with np.errstate(all="ignore"):
        r = np.zeros_like(close)
        r[1:] = close[1:] / close[:-1] - 1
    r[~np.isfinite(r)] = 0.0
    bill, up = bills(m.dates), m.env["market_up"][:, 0] > 0
    days = [i for i, d in enumerate(m.dates) if span[0] <= d <= span[1]]
    first, last = days[0], days[-1]
    w, pending, owed = np.zeros(close.shape[1]), None, 0.0
    daily, share = [], []
    for t in range(first - 1, last + 1):
        if t >= first:
            exposure = w.sum()
            carry = (1 - exposure) * bill[t] if exposure <= 1 else -(exposure - 1) * (bill[t] + SPREAD / 252)
            daily.append(r[t] @ w + carry - owed)
            share.append(exposure)
            owed = 0.0
        if t < last and m.dates[t][:7] != m.dates[t + 1][:7]:
            names = select(t)
            new = np.zeros(close.shape[1])
            if len(names) and (up[t] or not gated):
                new[names] = leverage / len(names)
            pending = (t + delay, new)
        if pending is not None and pending[0] == t:
            owed, w, pending = np.abs(pending[1] - w).sum() * m.cost, pending[1], None
    return np.array(daily), np.array(share)


def calm_names(m, share=0.4):
    quiet, close = m.parts["range14"], m.bars["close"]

    def select(t):
        known = m.member[t] & np.isfinite(quiet[t])
        if not known.any():
            return np.array([], dtype=int)
        return np.where(known & np.isfinite(close[t]) & (quiet[t] <= np.quantile(quiet[t][known], share)))[0]
    return select


def all_names(m):
    return lambda t: np.where(m.member[t] & np.isfinite(m.bars["close"][t]))[0]


def calm(universe, span, delays=(1,)):
    m = K.market(universe)
    days = [i for i, d in enumerate(m.dates) if span[0] <= d <= span[1]]
    bill = bills(m.dates)[days[0]:days[-1] + 1]
    year = np.array([m.dates[i][:4] for i in days])
    out = {"span": list(span), "cost": m.cost}
    print("%s, %s .. %s (aylik, esit agirlik, masraf %%%.2f, bos para bonoda, borc bono + %%%.1f)"
          % (universe, span[0], span[1], 100 * m.cost, 100 * SPREAD))
    for delay in delays:
        rows = {}
        for name, select, leverage, gated in (
                ("sakin 2/5, kapi, 1.5x", calm_names(m), 1.5, True), ("sakin 2/5, kapi, 1x", calm_names(m), 1.0, True),
                ("tum uyeler, kapi, 1.5x", all_names(m), 1.5, True), ("tum uyeler, kapi, 1x", all_names(m), 1.0, True),
                ("sakin 2/5, hep, 1.5x", calm_names(m), 1.5, False), ("sakin 2/5, hep, 1x", calm_names(m), 1.0, False),
                ("uyeleri tutmak", all_names(m), 1.0, False)):
            daily, share = portfolio(m, span, select, leverage, gated, delay)
            rows[name] = {**curve(daily, bill), "invested": float(share.mean()),
                          "by_year": {y: float(np.prod(1 + daily[year == y]) - 1) for y in sorted(set(year))}}
            print(money_line(("%s%s" % (name, "" if delay else " (sinyal gunu)")), rows[name])
                  + "  oynaklik %%%4.1f  ortalama yatirim %.2f" % (100 * rows[name]["volatility"], rows[name]["invested"]))
        out["delay_%d" % delay] = rows
    rule, hold = out["delay_%d" % delays[-1]]["sakin 2/5, kapi, 1.5x"], out["delay_%d" % delays[-1]]["uyeleri tutmak"]
    print("  yillara gore (1.5x / tutmak): " + "  ".join(
        "%s %+.0f/%+.0f" % (y[2:], 100 * v, 100 * hold["by_year"][y]) for y, v in rule["by_year"].items()))
    out["killed"] = bool(rule["yearly"] < hold["yearly"] - 0.01 or rule["drawdown"] < hold["drawdown"])
    return out


def dips(span):
    m = K.market("sp500")
    p = E.P.load("panel_etf.npz")
    etf_dates, labels = [str(d) for d in p["dates"]], [str(x) for x in p["labels"]]
    o, c = (p[k][:, labels.index("SPY")].astype(float) for k in ("open", "close"))
    z = m.parts["z20"]
    known = m.member & np.isfinite(z)
    share = (known & (z < -2)).sum(axis=1) / np.maximum(known.sum(axis=1), 1)
    up = m.env["market_up"][:, 0] > 0
    at = {d: i for i, d in enumerate(etf_dates)}
    seen = [i for i, d in enumerate(m.dates) if SEEN[0] <= d <= SEEN[1] and d in at]
    threshold = float(np.percentile(share[seen], DIP_SHARE))
    days = [i for i, d in enumerate(m.dates) if span[0] <= d <= span[1] and d in at]
    last = at[m.dates[days[-1]]]
    forward, trigger, month = [], [], []
    for i in days:
        e = at[m.dates[i]]
        if e + DIP_DAYS > last:
            continue
        forward.append(c[e + DIP_DAYS] / o[e + 1] - 1 - 2 * SPY_COST)
        trigger.append(bool(share[i] >= threshold and up[i]))
        month.append(m.dates[i][:7])
    forward, trigger, month = np.array(forward), np.array(trigger), np.array(month)
    extra = forward[trigger] - forward.mean()
    monthly = np.array([extra[month[trigger] == u].mean() for u in sorted(set(month[trigger]))])
    sums = np.array([extra[month[trigger] == u].sum() for u in sorted(set(month[trigger]))])
    by_year = {}
    for u, v in zip(month[trigger], forward[trigger]):
        by_year.setdefault(u[:4], []).append(v)
    first, bill = at[m.dates[days[0]]], bills(etf_dates)
    inside, entered = np.zeros(len(etf_dates), dtype=bool), np.zeros(len(etf_dates), dtype=bool)
    for i, flag in zip([i for i in days if at[m.dates[i]] + DIP_DAYS <= last], trigger):
        if flag:
            e = at[m.dates[i]]
            inside[e + 1:e + DIP_DAYS + 1] = True
    daily, spy = [], []
    for t in range(first, last + 1):
        held = c[t] / c[t - 1] - 1
        spy.append(held)
        if not inside[t]:
            daily.append(bill[t])
            continue
        made = c[t] / o[t] - 1 - SPY_COST if not inside[t - 1] else held
        entered[t] = not inside[t - 1]
        daily.append(made - (SPY_COST if t == last or not inside[t + 1] else 0.0))
    daily, spy, bill = np.array(daily), np.array(spy), bill[first:last + 1]
    out = {"span": list(span), "threshold": threshold, "days": int(len(forward)), "triggers": int(trigger.sum()),
           "windows": int(entered.sum()), "all_days": float(forward.mean()),
           "trigger_days": float(forward[trigger].mean()), "win_rate": float((forward[trigger] > 0).mean()),
           "months": int(len(monthly)), "extra": float(monthly.mean()),
           "t": float(monthly.mean() / monthly.std(ddof=1) * np.sqrt(len(monthly))),
           "difference": float(extra.mean()),
           "t_difference": float(sums.mean() / sums.std(ddof=1) * np.sqrt(len(sums))),
           "by_year": {y: float(np.mean(v)) for y, v in sorted(by_year.items())},
           "in_spy": float(inside[first:last + 1].mean()),
           "account": curve(daily, bill), "bills": curve(bill, bill), "spy": curve(spy, bill)}
    out["at_same_exposure"] = curve(out["in_spy"] * spy + (1 - out["in_spy"]) * bill, bill)
    print("%s .. %s: esik %%%.1f (2006-2016'nin %d. yuzdeligi), kapi acik; SPY ertesi acilista alinir, %d gun sonra kapanista satilir"
          % (span[0], span[1], 100 * threshold, DIP_SHARE, DIP_DAYS))
    print("  tetik gunleri %d (%d ayri pencere, %d ay): %+.2f%%, kazanan %%%.0f | tum gunler %+.2f%% | "
          "fark gun agirlikli %+.2f%% (t %.1f), ay agirlikli %+.2f%% (t %.1f)"
          % (out["triggers"], out["windows"], out["months"], 100 * out["trigger_days"], 100 * out["win_rate"],
             100 * out["all_days"], 100 * out["difference"], out["t_difference"], 100 * out["extra"], out["t"]))
    print("  yillara gore: " + "  ".join("%s %+.1f%%" % (y[2:], 100 * v) for y, v in out["by_year"].items()))
    print(money_line("pencerede SPY, digerinde bono", out["account"]) + "  (gunlerin %%%.0f'i SPY'da)" % (100 * out["in_spy"]))
    print(money_line("ayni oranda surekli SPY + bono", out["at_same_exposure"]))
    print(money_line("yalniz bono", out["bills"]))
    print(money_line("SPY tutmak", out["spy"]))
    # The criterion as coded before the read: the month-weighted excess. The
    # account earns the day-weighted one, whose t is `t_difference`.
    out["killed"] = bool(not (out["extra"] >= 0.002 and out["t"] >= 2))
    return out


def main(argv):
    what, stage = (argv + ["", ""])[1:3]
    saved = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if what == "issuance":
        saved["issuance_sp500"] = issuance("sp500", ("2017-01-01", "2025-12-31"))
        saved["issuance_midsmall"] = issuance("midsmall", ("2011-01-01", "2025-12-31"))
    elif what == "calm" and stage == "seen":
        saved["calm_seen"] = calm("sp500", SEEN, delays=(0, 1))
    elif what == "calm" and stage == "read":
        saved["calm_sp500"] = calm("sp500", ("2017-01-01", "2025-12-31"))
        saved["calm_midsmall"] = calm("midsmall", ("2011-01-01", "2025-12-31"))
    elif what == "dips" and stage == "seen":
        saved["dips_seen"] = dips(SEEN)
    elif what == "dips" and stage == "read":
        saved["dips"] = dips(("2017-01-01", "2025-12-31"))
    else:
        raise SystemExit(__doc__)
    with open(OUT, "w") as f:
        json.dump(saved, f, indent=1)


if __name__ == "__main__":
    main(sys.argv)
