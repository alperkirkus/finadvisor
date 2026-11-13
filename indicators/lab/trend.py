"""Trends across asset classes held as one portfolio of weights.

plan.md, Phase 37. The 36 ETFs of panel_etf.npz. At each month's last
close every ETF with a year of history gets +1, 0 or -1 from the signs of
its 252- and 63-day returns, is sized by the inverse of its volatility,
and the whole is scaled to a target volatility. Traded at a later close.
A portfolio of weights has no stop, so it does not go through
`trades.py`; the one fill here is the close, `delay` days after the
signal.

    trend.py cash     # fetch the 13-week Treasury bill rate into data/
    trend.py seen     # 2006-2016, against the red team's figures
    trend.py read     # 2017-2025, once
"""
import json
import os
import sys
import time
import urllib.request

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import panel as P             # noqa: E402

OUT = os.path.join(P.OUT, "trend.json")
CASH = os.path.join(P.OUT, "cash.json")
COST, BORROW, SPREAD = 0.0005, 0.005, 0.015
TARGET, GROSS = 0.10, 2.0
RANDOM = 40
CLASSES = {"bonds and credit": "HYG IEF LQD TIP TLT", "commodities and gold": "DBC GLD SLV UNG USO",
           "currencies": "FXE FXY UUP", "property": "VNQ"}


def fetch_cash():
    """Yahoo's ^IRX: the 13-week Treasury bill's yield, percent a year, by day."""
    req = urllib.request.Request(P.YAHOO % ("%5EIRX", P.FROM_2004, int(time.time())),
                                 headers={"User-Agent": "Mozilla/5.0 (FinAdvisor research)"})
    result = json.loads(urllib.request.urlopen(req, timeout=60).read())["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    rates = {time.strftime("%Y-%m-%d", time.gmtime(t)): c
             for t, c in zip(result["timestamp"], closes) if c is not None and -1 < c < 20}
    with open(CASH, "w") as f:
        json.dump(rates, f)
    by_year = {}
    for d, c in rates.items():
        by_year.setdefault(d[:4], []).append(c)
    print("%d gun (%s .. %s); yil ortalamasi: %s" % (len(rates), min(rates), max(rates), "  ".join(
        "%s %%%.1f" % (y[2:], np.mean(v)) for y, v in sorted(by_year.items()))))


def load(last=None):
    """The panel up to `last` and what the rule reads from it. Nothing
    after `last` is touched."""
    p = P.load("panel_etf.npz")
    dates = np.array([str(d) for d in p["dates"]])
    keep = dates <= (last or dates[-1])
    dates = dates[keep]
    o, h, low, c = (p[k][keep].astype(float) for k in ("open", "high", "low", "close"))
    days, count = c.shape
    ret = np.full(c.shape, np.nan)
    ret[1:] = c[1:] / c[:-1] - 1

    def rolling(x, n, how):
        out = np.full(x.shape, np.nan)
        for t in range(n, days):
            out[t] = how(x[t - n + 1:t + 1], axis=0)
        return out

    def momentum(n):
        out = np.full(c.shape, np.nan)
        out[n:] = c[n:] / c[:-n] - 1
        return out

    before = np.roll(c, 1, axis=0)
    true_range = np.maximum(h - low, np.maximum(abs(h - before), abs(low - before)))
    true_range[0] = np.nan
    rate = np.zeros(days)
    if os.path.exists(CASH):
        known = json.load(open(CASH))
        level = 0.0
        for t, d in enumerate(dates):
            rate[t] = level / 100 / 252          # yesterday's yield is earned today
            level = known.get(d, level)
    return {"dates": dates, "labels": [str(x) for x in p["labels"]], "ret": ret,
            "vol": rolling(ret, 60, np.std) * np.sqrt(252), "m12": momentum(252), "m3": momentum(63),
            "atr": rolling(true_range, 14, np.mean) / c, "rate": rate,
            "month_end": {i for i in range(days - 1) if dates[i][:7] != dates[i + 1][:7]}}


def trend(d, t, ok, rng):
    return (np.sign(d["m12"][t, ok]) + np.sign(d["m3"][t, ok])) / 2


def always_long(d, t, ok, rng):
    return np.ones(ok.sum())


def random_sign(d, t, ok, rng):
    return rng.choice([-1, 0, 1], ok.sum())


def run(d, signal, span, delay=1, financed=True, lead=True, seed=None, cost=COST):
    """One portfolio over a span. With `lead` the first signal is the last
    close before the span, otherwise the first month end inside it (the
    red team's start). `financed`: idle money earns the bill rate, money
    borrowed for long positions over the account pays it plus SPREAD, short
    sales earn nothing. Returns the daily returns, the bill rate of those
    days, the weights at each day's end and at its start (what earned the
    day's gain), and each ETF's contribution by day."""
    dates, ret = d["dates"], d["ret"]
    days, count = ret.shape
    inside = np.where((dates >= span[0]) & (dates <= span[1]))[0]
    first, last = inside[0], inside[-1]
    rng = np.random.default_rng(seed)
    w, pending = np.zeros(count), None
    daily, weights, parts, start = [], np.zeros((days, count)), np.zeros((days, count)), np.zeros((days, count))
    for t in range(first - 1 if lead else first, last + 1):
        r = np.nan_to_num(ret[t])
        part = w * r - np.maximum(-w, 0) * BORROW / 252
        made = part.sum()
        start[t] = w
        if financed:
            idle = 1 - w[w > 0].sum()
            made += idle * d["rate"][t] if idle >= 0 else idle * (d["rate"][t] + SPREAD / 252)
        w = w * (1 + r) / (1 + (w * r).sum())
        paid = 0.0
        if pending is not None and pending[0] == t:
            paid, w, pending = abs(pending[1] - w).sum() * cost, pending[1], None
        if t in d["month_end"] and t + delay <= last:
            ok = np.isfinite(d["m12"][t]) & np.isfinite(d["vol"][t]) & (d["vol"][t] > 0)
            s = np.zeros(count)
            s[ok] = signal(d, t, ok, rng)
            raw = np.zeros(count)
            raw[ok] = s[ok] / d["vol"][t, ok]
            raw /= max(ok.sum(), 1)
            sigma = np.std(np.nan_to_num(ret[t - 119:t + 1]) @ raw) * np.sqrt(252)
            new = raw * (TARGET / sigma if sigma > 0 else 0)
            gross = abs(new).sum()
            if gross > GROSS:
                new *= GROSS / gross
            if delay == 0:
                paid, w = paid + abs(new - w).sum() * cost, new
            else:
                pending = (t + delay, new)
        weights[t], parts[t] = w, part
        if t >= first:
            daily.append(made - paid)
    return {"daily": np.array(daily), "rate": d["rate"][first:last + 1] if financed else np.zeros(len(daily)),
            "weights": weights[first:last + 1], "start": start[first:last + 1],
            "parts": parts[first:last + 1], "dates": dates[first:last + 1]}


def summary(x):
    daily, over = x["daily"], x["daily"] - x["rate"]
    equity = np.cumprod(1 + daily)
    years = len(daily) / 252
    year = np.array([d[:4] for d in x["dates"]])
    w = x["weights"]
    out = {"yearly": float(equity[-1] ** (1 / years) - 1), "volatility": float(daily.std() * np.sqrt(252)),
           "sharpe": float(over.mean() / over.std() * np.sqrt(252)),
           "over_cash": float(over.mean() * 252),
           "drawdown": float((equity / np.maximum.accumulate(np.maximum(equity, 1)) - 1).min()),
           "gross": float(abs(w).sum(axis=1).mean()), "long": float(np.maximum(w, 0).sum(axis=1).mean()),
           "short": float(np.maximum(-w, 0).sum(axis=1).mean()),
           "long_side": float(np.where(x["start"] > 0, x["parts"], 0).sum()),
           "short_side": float(np.where(x["start"] < 0, x["parts"], 0).sum()),
           "by_year": {y: float(np.prod(1 + daily[year == y]) - 1) for y in sorted(set(year))}}
    out["ratio"] = out["yearly"] / -out["drawdown"] if out["drawdown"] < 0 else float("inf")
    return out


def positions(d, x, cost=COST):
    """The portfolio in the owner's unit. A position is a run of same-sign
    weight in one ETF; 1R is its entry weight times 3 ATR, as a share of
    the account. Returns (entry date, R, days, 1R as a share of the account)."""
    at = {day: i for i, day in enumerate(d["dates"])}
    w, parts, rows = x["weights"], x["parts"], []
    sign = np.sign(w)
    for j in range(w.shape[1]):
        t = 0
        while t < len(w):
            if sign[t, j] == 0:
                t += 1
                continue
            s = t
            while t < len(w) and sign[t, j] == sign[s, j]:
                t += 1
            risk = abs(w[s, j]) * 3 * d["atr"][at[x["dates"][s]], j]
            if risk > 0:
                made = parts[s + 1:t + 1, j].sum() - 2 * cost * abs(w[s, j])
                rows.append((x["dates"][s], made / risk, t - s, risk))
    return rows


def in_r(d, x):
    rows = positions(d, x)
    r = np.array([v[1] for v in rows])
    months = len({day[:7] for day in x["dates"]})
    streak = longest = 0
    for v in sorted(rows):
        streak = streak + 1 if v[1] <= 0 else 0
        longest = max(longest, streak)
    return {"positions": len(r), "a_month": len(r) / months, "avg_r": float(r.mean()),
            "win_rate": float((r > 0).mean()), "avg_win_r": float(r[r > 0].mean()),
            "avg_loss_r": float(r[r <= 0].mean()), "r_a_month": float(r.sum() / months),
            "days": float(np.mean([v[2] for v in rows])), "longest_losing_run": longest,
            "r_of_account": float(np.mean([v[3] for v in rows]))}


def held(d, span, label=None):
    """SPY, or the eligible ETFs in equal weight rebalanced daily, with no interest."""
    inside = (d["dates"] >= span[0]) & (d["dates"] <= span[1])
    ret = d["ret"][inside]
    daily = np.nan_to_num(ret[:, d["labels"].index(label)]) if label else np.nanmean(ret, axis=1)
    nothing = np.zeros((len(daily), 1))
    return summary({"daily": daily, "rate": d["rate"][inside], "weights": nothing, "start": nothing,
                    "parts": nothing, "dates": d["dates"][inside]})


def line(name, s):
    return ("  %-40s yilda %+5.1f%%  oynaklik %%%4.1f  nakit ustu %+5.1f%%  Sharpe %5.2f  dusus %+5.1f%%  "
            "getiri/dusus %4.2f | brut %.2f (uzun %.2f, kisa %.2f)"
            % (name, 100 * s["yearly"], 100 * s["volatility"], 100 * s["over_cash"], s["sharpe"],
               100 * s["drawdown"], s["ratio"], s["gross"], s["long"], s["short"]))


def by_class(d, x):
    named = {label for names in CLASSES.values() for label in names.split()}
    groups = {"equity": [label for label in d["labels"] if label not in named],
              **{k: v.split() for k, v in CLASSES.items()}}
    total = x["parts"].sum(axis=0)
    return {k: float(sum(total[d["labels"].index(label)] for label in v)) for k, v in groups.items()}


def study(d, span, lead=True):
    x = run(d, trend, span, lead=lead)
    out = {"span": list(span), "trend": summary(x), "in_r": in_r(d, x), "by_class": by_class(d, x),
           "always_long": summary(run(d, always_long, span, lead=lead)),
           "at_signal_close": summary(run(d, trend, span, delay=0, lead=lead)),
           "twice_the_cost": summary(run(d, trend, span, lead=lead, cost=2 * COST)),
           "spy": held(d, span, "SPY"), "equal_weight": held(d, span)}
    random = [summary(run(d, random_sign, span, lead=lead, seed=seed)) for seed in range(RANDOM)]
    out["random"] = {"sharpe_median": float(np.median([r["sharpe"] for r in random])),
                     "sharpe_p95": float(np.percentile([r["sharpe"] for r in random], 95)),
                     "yearly_median": float(np.median([r["yearly"] for r in random]))}
    print("%s .. %s (faizli hesap: bos para bono faizi alir, borc faiz + %%%.1f oder; islem bir gun sonra)"
          % (span[0], span[1], 100 * SPREAD))
    print(line("trend portfoyu (uzun/kisa)", out["trend"]))
    print(line("  ayni, sinyal gunu kapanisinda", out["at_signal_close"]))
    print(line("  ayni, iki kat masraf", out["twice_the_cost"]))
    print(line("plasebo: hep uzun, ayni boyutlama", out["always_long"]))
    print(line("SPY tutmak", out["spy"]))
    print(line("36 ETF esit agirlik", out["equal_weight"]))
    print("  rastgele yonler (%d): Sharpe medyan %.2f, %%95 %.2f; yillik medyan %+.1f%%"
          % (RANDOM, out["random"]["sharpe_median"], out["random"]["sharpe_p95"],
             100 * out["random"]["yearly_median"]))
    print("  yillara gore: " + "  ".join("%s %+.0f%%" % (y[2:], 100 * v) for y, v in out["trend"]["by_year"].items()))
    print("  uzun taraf %+.0f%%, kisa taraf %+.0f%% (gunluk kazanc toplami); sinifa gore: %s"
          % (100 * out["trend"]["long_side"], 100 * out["trend"]["short_side"],
             "  ".join("%s %+.0f%%" % (k, 100 * v) for k, v in out["by_class"].items())))
    r = out["in_r"]
    print("  R cinsinden: %d pozisyon (ayda %.1f), %+.2fR, kazanan %%%.0f (%+.2f / %+.2f), ayda %+.1fR, %.0f gun, "
          "ust uste kayip %d; 1R = hesabin %%%.2f'i"
          % (r["positions"], r["a_month"], r["avg_r"], 100 * r["win_rate"], r["avg_win_r"], r["avg_loss_r"],
             r["r_a_month"], r["days"], r["longest_losing_run"], 100 * r["r_of_account"]))
    t, a = out["trend"], out["always_long"]
    out["killed"] = bool(t["sharpe"] < 0.4 or t["ratio"] <= a["ratio"] or t["drawdown"] < -0.20)
    return out


def main(argv):
    what = argv[1] if len(argv) > 1 else ""
    saved = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if what == "cash":
        return fetch_cash()
    if what == "seen":
        d = load("2016-12-31")
        span = ("2006-01-01", "2016-12-31")
        print("kirmizi takimin hesabi (faizsiz), 2006-2016:")
        for name, delay in (("sinyal gunu kapanisinda", 0), ("bir gun sonra", 1)):
            print(line(name, summary(run(d, trend, span, delay=delay, financed=False, lead=False))))
        print(line("hep uzun", summary(run(d, always_long, span, delay=0, financed=False, lead=False))))
        saved["seen"] = study(d, span, lead=False)
    elif what == "read":
        d = load()
        saved["read"] = study(d, ("2017-01-01", "2025-12-31"))
        after = ("2026-01-01", str(d["dates"][-1]))
        x = summary(run(d, trend, ("2017-01-01", after[1])))
        saved["after"] = {"span": list(after), "return": x["by_year"].get("2026")}
        print("  ayri: %s .. %s trend portfoyu %+.1f%%" % (after[0], after[1], 100 * x["by_year"]["2026"]))
    else:
        raise SystemExit(__doc__)
    with open(OUT, "w") as f:
        json.dump(saved, f, indent=1)


if __name__ == "__main__":
    main(sys.argv)
