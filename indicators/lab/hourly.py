"""Hourly bars: a system as four parts, every combination (plan.md, Phase 27).

    hourly.py fetch [market]        # one-hour bars, as far back as they are served
    hourly.py grid [market]         # every combination on the search period
    hourly.py top [market]          # what the search found
    hourly.py choose | sealed [market]

Markets: sp100, etf, bist. The daily context of an hourly bar comes from
the daily panel signals.py keeps (panel_live_*), read at the previous
day's close. Everything else is trades.py's simulator on hourly bars: a
"day" there is one bar here.
"""
import itertools
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E            # noqa: E402
import panel as P             # noqa: E402
import trades as T            # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=730d&interval=1h"
UA = "Mozilla/5.0 (FinAdvisor research)"
OUT = os.path.join(P.OUT, "hourly")
MARKETS = {"sp100": ("live_sp500", "", 0.001), "etf": ("live_etf", "", 0.0005),
           "bist": ("live_bist", ".IS", 0.002)}
STAGES = {"discover": ("2023-12-01", "2025-06-30 99"), "validate": ("2025-07-01", "2026-03-31 99"),
          "sealed": ("2026-04-01", "2026-12-31 99")}
SAMPLE = 13
CONTEXT = {"none": "(sample > -1)", "up": "(d_ma_gap200 > 0)",
           "dip_up": "(d_z20 < -1.5) & (d_ma_gap200 > 0)", "near_high": "(d_high_gap250 > -0.05)",
           "oversold": "(d_rsi < 35)"}
TRIGGER = {"break_yesterday": "cross_up(d_prev_high_gap, 0)", "high20h": "(brk20 > 0)",
           "high55h": "(brk55 > 0)", "rsi30": "cross_up(rsi, 30)",
           "mean_reclaim": "cross_up(z20, 0) & (ts_min(z20, 10) < -1.5)",
           "band_reentry": "cross_up(z20, -2)", "volume_thrust": "(rvol > 2) & (ret1 > 0.005)"}
STOPS = [["atr", 1.5], ["atr", 2.5], ["atr", 4], ["low", 5], ["low", 20]]
TARGETS = [None, 1, 2, 3]
TRAILS = [["none", 0], ["low", 10], ["low", 20], ["chandelier", 3]]
HOLDS = (35, 105)
FINALISTS, MIN_TRADES, MIN_CHOICE, KILL = 20, 200, 100, 0.3


def symbols(market):
    if market == "sp100":
        return json.load(open(os.path.join(ROOT, "intraday", "universe.json")))["symbols"]
    return list(P.ETFS) if market == "etf" else list(P.BIST)


def fetch(market):
    suffix = MARKETS[market][1]

    def one(symbol):
        for attempt in range(3):
            try:
                req = urllib.request.Request(URL % (symbol + suffix), headers={"User-Agent": UA})
                res = json.load(urllib.request.urlopen(req, timeout=40))["chart"]["result"][0]
                q = res["indicators"]["quote"][0]
                return symbol, res["timestamp"], q
            except Exception:
                time.sleep(2 * (attempt + 1))
        return symbol, None, None
    with ThreadPoolExecutor(6) as pool:
        got = [g for g in pool.map(one, symbols(market)) if g[1]]
    if len(got) < 0.8 * len(symbols(market)):
        raise SystemExit("%s: yalnizca %d sembol geldi" % (market, len(got)))
    stamps = sorted({t for _, ts, _ in got for t in ts})
    at = {t: i for i, t in enumerate(stamps)}
    fields = {k: np.full((len(stamps), len(got)), np.nan, dtype=np.float32)
              for k in ("open", "high", "low", "close", "volume")}
    for j, (_, ts, q) in enumerate(got):
        rows = [at[t] for t in ts]
        for k in fields:
            fields[k][rows, j] = np.array([np.nan if v is None else v for v in q[k]], dtype=np.float32)
    bad = ~(np.isfinite(fields["close"]) & np.isfinite(fields["open"]) & np.isfinite(fields["high"])
            & np.isfinite(fields["low"]) & (fields["close"] > 0))
    for k in fields:
        fields[k][bad] = np.nan
    dates = np.array([time.strftime("%Y-%m-%d %H:%M", time.gmtime(t)) for t in stamps])
    np.savez(os.path.join(P.OUT, "panel_h_%s.npz" % market), dates=dates,
             labels=np.array([g[0] for g in got]), member=np.isfinite(fields["close"]), **fields)
    print("%s: %d saatlik bar x %d enstruman (%s .. %s)" % (market, len(stamps), len(got), dates[0], dates[-1]))


def load(market):
    """The hourly market, with the daily context of each bar added to what a
    formula may name: d_ma_gap200, d_z20, d_rsi, d_high_gap250,
    d_prev_high_gap (the hourly close against yesterday's high), `sample`."""
    daily_name, _, cost = MARKETS[market]
    E.UNIVERSES["h_" + market] = ("panel_h_%s.npz" % market, cost)
    E.UNIVERSES[daily_name] = ("panel_%s.npz" % daily_name, cost)
    m, d = E.Market("h_" + market), E.Market(daily_name)
    column = {label: j for j, label in enumerate(d.labels)}
    days = np.array([s[:10] for s in m.dates])
    before = np.searchsorted(np.array(d.dates), days) - 1          # the last daily bar before that day
    ok = before >= 0
    shape = m.member.shape
    extra = {k: np.full(shape, np.nan, dtype=np.float32)
             for k in ("d_ma_gap200", "d_z20", "d_rsi", "d_high_gap250", "d_prev_high_gap")}
    for j, label in enumerate(m.labels):
        if label not in column:
            continue
        dj = column[label]
        for k, src in (("d_ma_gap200", "ma_gap200"), ("d_z20", "z20"), ("d_rsi", "rsi"),
                       ("d_high_gap250", "high_gap250")):
            extra[k][ok, j] = d.parts[src][before[ok], dj]
    # Yesterday's high is taken from the hourly bars themselves: the daily
    # panel is adjusted for dividends and the hourly bars are not.
    starts = np.concatenate([[0], np.where(days[1:] != days[:-1])[0] + 1])
    day_of = np.repeat(np.arange(len(starts)), np.diff(np.concatenate([starts, [len(days)]])))
    highest = np.fmax.reduceat(m.bars["high"], starts, axis=0)
    with np.errstate(all="ignore"):
        extra["d_prev_high_gap"][day_of > 0] = (m.bars["close"][day_of > 0]
                                                / highest[day_of[day_of > 0] - 1] - 1)
    extra["sample"] = np.broadcast_to(
        (np.arange(shape[0]) % SAMPLE == 0).astype(np.float32)[:, None], shape).copy()
    m.env.update(extra)
    return m


def policies():
    specs = [{"initial": s, "trail": tr, "target_r": tg, "rule_exit": False}
             for s, tg, tr in itertools.product(STOPS, TARGETS, TRAILS)]
    return specs, np.array([T.policy({"stop": s}) for s in specs])


def sums(m, entry, hold, rows, stage):
    first, last = STAGES[stage]
    p = T.prepare(m, {"entry": entry, "exit": None, "max_days": hold}, first, last)
    o, h, low, c, atr, lows = p["bars"]
    return T._grid(o, h, low, c, atr, lows, p["leave"], p["dist"], p["sig_j"], p["sig_t"], p["ends"],
                   p["hold"], rows, T.drift(m, first, last), m.cost)


def score(m, stage, only=None):
    """{(context, trigger, policy index, hold): figures}, each with its
    placebo's R. `only` limits it to those keys."""
    specs, rows = policies()
    years = sum(STAGES[stage][0] <= d <= STAGES[stage][1] for d in m.dates) / (
        len(m.dates) / ((time.mktime(time.strptime(m.dates[-1], "%Y-%m-%d %H:%M"))
                         - time.mktime(time.strptime(m.dates[0], "%Y-%m-%d %H:%M"))) / 31557600))
    out = {}
    for context, hold in itertools.product(CONTEXT, HOLDS):
        wanted = None if only is None else {k for k in only if k[0] == context and k[3] == hold}
        if wanted is not None and not wanted:
            continue
        placebo = sums(m, "%s & (sample > 0)" % CONTEXT[context], hold, rows, stage)
        for trigger in TRIGGER:
            if wanted is not None and not any(k[1] == trigger for k in wanted):
                continue
            s = sums(m, "%s & %s" % (CONTEXT[context], TRIGGER[trigger]), hold, rows, stage)
            for q in range(len(rows)):
                key = (context, trigger, q, hold)
                if wanted is not None and key not in wanted:
                    continue
                n, pn = s[q, 0], placebo[q, 0]
                if n < 1:
                    continue
                wins = s[q, 24]
                out[key] = {"trades": int(n), "per_year": n / years, "win_rate": wins / n,
                            "avg_r": s[q, 6] / n, "avg_win_r": s[q, 8] / max(wins, 1),
                            "avg_loss_r": s[q, 9] / max(n - wins, 1), "net": s[q, 2] / n,
                            "risk": s[q, 21] / n, "bars": s[q, 5] / n, "stopped": s[q, 13] / n,
                            "placebo_r": placebo[q, 6] / pn if pn >= 30 else None,
                            "placebo_trades": int(pn)}
    return out


def name(key, specs):
    context, trigger, q, hold = key
    s = specs[q]
    return "%-9s %-15s stop %-9s hedef %-4s iz %-13s %3d bar" % (
        context, trigger, "%s %g" % tuple(s["initial"]), s["target_r"] or "-",
        "%s %g" % tuple(s["trail"]) if s["trail"][0] != "none" else "-", hold)


def line(key, f, specs):
    own = f["avg_r"] - f["placebo_r"] if f["placebo_r"] is not None else float("nan")
    return ("  %s | %5d islem (yilda %5.0f) kazanan %%%2.0f  R %+5.2f (%+5.2f / %+5.2f)  plasebo %s  "
            "kendi payi %+5.2f  1R=%%%.2f  %4.0f bar  100$: yilda %+7.0f $"
            % (name(key, specs), f["trades"], f["per_year"], 100 * f["win_rate"], f["avg_r"],
               f["avg_win_r"], f["avg_loss_r"],
               "%+5.2f" % f["placebo_r"] if f["placebo_r"] is not None else "  -  ", own,
               100 * f["risk"], f["bars"], 100 * f["avg_r"] * f["per_year"]))


def result_path(market):
    return os.path.join(OUT, "result_%s.json" % market)


def load_result(market):
    return json.load(open(result_path(market))) if os.path.exists(result_path(market)) else {}


def save_result(market, result):
    os.makedirs(OUT, exist_ok=True)
    with open(result_path(market) + ".tmp", "w") as fh:
        json.dump(result, fh, indent=1)
        fh.write("\n")
    os.replace(result_path(market) + ".tmp", result_path(market))


def above(f):
    return f["placebo_r"] is not None and f["avg_r"] > f["placebo_r"]


def grid(market):
    result = load_result(market)
    if "finalists" in result:
        raise SystemExit("%s: arama zaten yapildi" % market)
    m = load(market)
    specs, _ = policies()
    found = score(m, "discover")
    fit = {k: f for k, f in found.items() if f["trades"] >= MIN_TRADES and above(f)}
    best = sorted(fit, key=lambda k: -fit[k]["avg_r"])[:FINALISTS]
    rs = np.array([f["avg_r"] for f in found.values() if f["trades"] >= MIN_TRADES])
    print("%s, arama donemi (.. 2025-06-30): %d kombinasyon, %d tanesi en az %d islemli; bunlarin R'si: "
          "medyan %+.2f, %%90 %+.2f, en yuksek %+.2f; plasebosunu gecen %d"
          % (market, len(found), len(rs), MIN_TRADES, np.median(rs), np.percentile(rs, 90), rs.max(),
             len(fit)))
    for k in best:
        print(line(k, fit[k], specs))
    result["search"] = {"combinations": len(found), "enough": int(len(rs)), "above_placebo": len(fit),
                        "median_r": float(np.median(rs)), "p90_r": float(np.percentile(rs, 90))}
    result["finalists"] = [{"key": list(k), "discover": fit[k]} for k in best]
    save_result(market, result)


def choose(market):
    result = load_result(market)
    if "finalists" not in result:
        raise SystemExit("%s: once `hourly.py grid`" % market)
    if "choice" in result:
        raise SystemExit("%s: secim zaten yapildi" % market)
    m = load(market)
    specs, _ = policies()
    keys = [tuple(f["key"]) for f in result["finalists"]]
    found = score(m, "validate", only=set(keys))
    print("%s, secim donemi (2025-07 .. 2026-03):" % market)
    best = None
    for f in result["finalists"]:
        k = tuple(f["key"])
        f["validate"] = found.get(k)
        if f["validate"] is None:
            continue
        print(line(k, f["validate"], specs))
        v = f["validate"]
        if v["trades"] >= MIN_CHOICE and above(v) and (best is None or v["avg_r"] > best["validate"]["avg_r"]):
            best = f
    if best is None or best["validate"]["avg_r"] < KILL:
        result["choice"] = None
        print("  secilen yok: en iyi aday +%.1fR esigini gecemedi; bu piyasada saatlik sistem yok" % KILL)
    else:
        result["choice"] = best["key"]
        print("  secilen: " + name(tuple(best["key"]), specs))
    save_result(market, result)


def sealed(market):
    result = load_result(market)
    if not result.get("choice"):
        raise SystemExit("%s: secilen sistem yok" % market)
    if "sealed" in result:
        raise SystemExit("%s: son donem zaten okundu" % market)
    m = load(market)
    specs, _ = policies()
    k = tuple(result["choice"])
    found = score(m, "sealed", only={k})
    result["sealed"] = found.get(k)
    print("%s, son donem (2026-04 ..):" % market)
    print(line(k, found[k], specs) if k in found else "  islem yok")
    save_result(market, result)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "top"
    for market in sys.argv[2:] or list(MARKETS):
        if market not in MARKETS:
            raise SystemExit("bilinmeyen piyasa: %s" % market)
        {"fetch": fetch, "grid": grid, "choose": choose, "sealed": sealed}[command](market)
