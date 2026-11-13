"""Trading systems as they are traded: an entry rule, an exit rule, a stop.

engine.py scores a signal by what happened a fixed number of days later,
against the other companies. A system on a chart is something else: it
gets in on one rule and out on another, on one instrument, and is judged
by its trades. This simulates that, trade by trade, and keeps every trade.

    trades.py discover <systems.json> [--universe sp500|midsmall|etf|bist]
    trades.py validate | sealed | ledger    [--universe ...]
    trades.py seen | product                [--universe ...]   # the product's list, see below
    trades.py show <system id> <instrument> [--universe ...]   # its trades, one by one

A system is {"id", "entry", "exit", "stop_atr", "max_days", "rationale"}:
`entry` and `exit` are true/false formulas over the components (engine.py
catalog), read at the close; a position opens at the next open and closes
at the open after `exit` turns true, or at the stop (`stop_atr` average
true ranges under the entry price, hit during a day), or after `max_days`.
Long only, one position per instrument, no pyramiding.

Instead of `stop_atr` a system may carry `stop`, a policy: an initial
stop, a trailing stop, a move to break-even, a target, a stall limit, and
whether its own exit rule is kept (see policy()). The walk is by day: the
stop for a day is fixed from the days before it; an open at or under the
stop leaves at the open, a low at or under it leaves at the stop; stop and
target inside one bar count as the stop. A trade's risk is its entry price
minus the stop of the entry day, and its result in R is the net result
over that risk. stops.py is where a policy is chosen.

What counts. The first number is the one asked for: the average profit of
a trade after costs. On its own it flatters: in a rising market a purchase
made on any rule is profitable on average, and in lira almost any purchase
is. So beside it stands what the same instrument returned over a holding
period of the same length on an average day of the stage, and the
difference is the system's own contribution, the `edge`. A system passes a
stage when its trades make money after costs AND its edge is positive with
a t (by month of entry) of at least 3 in discovery, 2 after. The stages
and the ledger are engine.py's.

The product shows more than the lab confirms, and says so (plan.md, Phase
23). `seen` scores every discovered system once on the validation years;
a system is "shown" for a market when profit per trade and edge are both
positive in discovery and in validation, with no t asked. `product` reads
the shown systems once on the sealed years; one that loses there stays in
the list, marked. signals.py turns the list into today's signals.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E            # noqa: E402

try:
    from numba import njit, prange
except ImportError:                      # the product runs without numba, only slower
    prange = range

    def njit(*args, **kwargs):
        return args[0] if args and callable(args[0]) else (lambda f: f)

MAX_DAYS_LIMIT = 120
JOURNAL = os.path.join(E.P.OUT, "journals")
LOWS = (3, 5, 10, 20)                    # the lowest-low windows a stop may stand on
RISK, CAP = 0.01, 0.20                   # sizing: 1% of the account at risk, no position over a fifth
MIN_STOP_ATR = 0.5                       # a level stop is never closer to the entry than this
MIN_RISK = 0.001                         # nor is any stop closer than this share of the price
INITIAL = {"none": 0, "atr": 1, "pct": 2, "low": 3, "expr": 4}
TRAIL = {"none": 0, "chandelier": 1, "low": 2, "pct": 3}
REASONS = ("skip", "stop", "target", "exit", "stall", "time", "end", "open")
STATS = ("n", "wins", "net", "net2", "base", "days", "r", "r2", "win_r", "loss_r", "sized",
         "sized2", "sized_net", "stops", "gaps", "targets", "exits", "stalls", "times", "worst",
         "worst_r", "risk", "skipped", "weight", "wins_r", "sized_days")


def flags(m, expr):
    with np.errstate(all="ignore"):
        value = eval(E.compile_formula(expr, m.env), {"__builtins__": {}}, m.env)
    return np.broadcast_to(np.asarray(value), m.member.shape) == True     # noqa: E712


def number(m, expr):
    with np.errstate(all="ignore"):
        value = eval(E.compile_formula(expr, m.env), {"__builtins__": {}}, m.env)
    return np.ascontiguousarray(np.broadcast_to(np.asarray(value, dtype=np.float64), m.member.shape))


# ------------------------------------------------------------------ the walk
#
# A stop policy is a row of nine numbers: initial kind and size, trailing
# kind and size, the R at which the stop goes to break-even, the target in
# R, the part sold at the target, whether the system's exit rule is kept,
# and the stall limit in days. policy() builds it from a system.

@njit(cache=True)
def _first_stop(cfg, price, unit, level_initial, level_trail, distance, close):
    """The stop in force on the entry day, or NaN when the policy has none."""
    floor = price - MIN_STOP_ATR * unit
    ik, tk = cfg[0], cfg[2]
    if ik == 1:
        return price - cfg[1] * unit
    if ik == 2:
        return price * (1.0 - cfg[1])
    if ik == 3:
        return level_initial if level_initial < floor else floor
    if ik == 4:
        level = close * (1.0 - distance)
        return level if level < floor else floor
    if tk == 1:
        return price - cfg[3] * unit
    if tk == 2:
        return level_trail if level_trail < floor else floor
    if tk == 3:
        return price * (1.0 - cfg[3])
    return np.nan


@njit(cache=True)
def _trade(o, h, low, c, atr, lows, leave, dist, j, t, end, hold, live_end, cfg):
    """One trade from the signal at the close of day t on column j.

    Returns (exit day, exit price, reason, initial stop, gross result, the
    stop for the next day, exit due, gapped, highest high, lowest low,
    part sold at the target)."""
    a = t + 1
    price = o[a, j]
    ik, tk, tx = cfg[0], cfg[2], cfg[3]
    be, tgt, part, use_exit, stall = cfg[4], cfg[5], cfg[6], cfg[7] > 0, cfg[8]
    distance = dist[t, j] if ik == 4 else 0.0
    if ik == 4 and not distance > 0:
        return a, np.nan, 0, np.nan, 0.0, np.nan, 0, 0, np.nan, np.nan, 0.0
    stop = _first_stop(cfg, price, atr[t, j], lows[int(cfg[1]), t, j] if ik == 3 else np.nan,
                       lows[int(tx), t, j] if tk == 2 else np.nan, distance, c[t, j])
    has = stop == stop
    # A stop within a thousandth of the price is a quote that has not moved
    # (ATR near zero), not a stop: its R would be meaningless. No trade.
    if has and not price - stop > MIN_RISK * price:
        return a, np.nan, 0, np.nan, 0.0, np.nan, 0, 0, np.nan, np.nan, 0.0
    first, risk = stop, price - stop
    target = price + tgt * risk if tgt > 0 else np.inf
    last_day = a + hold - 1
    high, low_seen, high_close = price, price, price
    left, banked, to_entry, pending = 1.0, 0.0, False, 0
    d = a
    while True:
        od, hd, ld, cd = o[d, j], h[d, j], low[d, j], c[d, j]
        if pending != 0 and od == od:
            return d, od, pending, first, banked + left * (od / price - 1.0), stop, 0, 0, high, \
                low_seen, 1.0 - left
        if has:
            if d > a and od <= stop:
                return d, od, 1, first, banked + left * (od / price - 1.0), stop, 0, \
                    1 if od < stop else 0, high, min(low_seen, od), 1.0 - left
            if ld <= stop:
                return d, stop, 1, first, banked + left * (stop / price - 1.0), stop, 0, 0, high, \
                    min(low_seen, ld), 1.0 - left
        if target < np.inf:
            fill = np.nan
            if d > a and od >= target:
                fill = od
            elif hd >= target:
                fill = target
            if fill == fill:
                if part >= 1.0:
                    return d, fill, 2, first, fill / price - 1.0, stop, 0, 0, max(high, hd), \
                        min(low_seen, ld), 1.0
                banked += part * (fill / price - 1.0)
                left -= part
                target = np.inf
                to_entry = True
        if hd > high:
            high = hd
        if ld < low_seen:
            low_seen = ld
        if cd > high_close:
            high_close = cd
        due = 0
        if pending != 0:
            due = pending
        elif use_exit and leave[d, j]:
            due = 3
        elif stall > 0 and d - a + 1 >= stall and cd < price:
            due = 4
        elif d >= last_day:
            due = 5
        if has:
            level = stop
            if tk == 1:
                level = high - tx * atr[d, j]
            elif tk == 2:
                level = lows[int(tx), d, j]
            elif tk == 3:
                level = high_close * (1.0 - tx)
            if level > stop:
                stop = level
            if (to_entry or (be > 0 and high >= price + be * risk)) and price > stop:
                stop = price
        if d == end:
            return d, cd, 7 if end == live_end else 6, first, banked + left * (cd / price - 1.0), \
                stop, 1 if due != 0 else 0, 0, high, low_seen, 1.0 - left
        pending = due
        d += 1


@njit(cache=True)
def _list(o, h, low, c, atr, lows, leave, dist, sig_j, sig_t, ends, hold, live_end, cfg):
    """Every trade of one policy: which signal, and what _trade returned."""
    n = len(sig_t)
    whole = np.empty((n, 5), dtype=np.int64)
    real = np.empty((n, 7), dtype=np.float64)
    count, free, column = 0, 0, -1
    for k in range(n):
        j, t = sig_j[k], sig_t[k]
        if j != column:
            column, free = j, 0
        if t < free:
            continue
        day, price, reason, first, gross, stop, due, gapped, high, low_seen, sold = _trade(
            o, h, low, c, atr, lows, leave, dist, j, t, ends[j], hold, live_end, cfg)
        if reason == 0:
            continue
        free = day if reason != 7 else day + 1
        whole[count, 0], whole[count, 1], whole[count, 2] = k, day, reason
        whole[count, 3], whole[count, 4] = due, gapped
        real[count, 0], real[count, 1], real[count, 2], real[count, 3] = price, first, gross, stop
        real[count, 4], real[count, 5], real[count, 6] = high, low_seen, sold
        count += 1
    return whole[:count], real[:count]


@njit(cache=True)
def _each(o, h, low, c, atr, lows, leave, dist, sig_j, sig_t, ends, hold, cfg):
    """Every signal traded on its own, whether or not the instrument is
    already held: (gross result, initial stop, days) per signal, NaN where
    there is no trade. For judging entries, not for a record."""
    out = np.full((len(sig_t), 3), np.nan)
    for k in range(len(sig_t)):
        j, t = sig_j[k], sig_t[k]
        day, price, reason, first, gross, stop, due, gapped, high, low_seen, sold = _trade(
            o, h, low, c, atr, lows, leave, dist, j, t, ends[j], hold, -1, cfg)
        if reason != 0:
            out[k, 0], out[k, 1], out[k, 2] = gross, first, max(day - t - 1, 1)
    return out


@njit(cache=True, parallel=True)
def _grid(o, h, low, c, atr, lows, leave, dist, sig_j, sig_t, ends, hold, cfgs, per_day, cost):
    """The sums of STATS for every policy in `cfgs`, on one system's signals."""
    out = np.zeros((len(cfgs), 26), dtype=np.float64)
    n = len(sig_t)
    for q in prange(len(cfgs)):
        cfg, s = cfgs[q], out[q]
        free, column = 0, -1
        for k in range(n):
            j, t = sig_j[k], sig_t[k]
            if j != column:
                column, free = j, 0
            if t < free:
                continue
            day, price, reason, first, gross, stop, due, gapped, high, low_seen, sold = _trade(
                o, h, low, c, atr, lows, leave, dist, j, t, ends[j], hold, -1, cfg)
            if reason == 0:
                s[22] += 1
                continue
            free = day
            days = max(day - t - 1, 1)
            net = gross - 2 * cost
            base = (1.0 + per_day[j]) ** days - 1.0
            weight = CAP
            if first == first:
                risk = (o[t + 1, j] - first) / o[t + 1, j]
                weight = min(RISK / risk, CAP)
                r = net / risk
                s[6] += r
                s[7] += r * r
                s[21] += risk
                if r > 0:
                    s[8] += r
                    s[24] += 1
                else:
                    s[9] += r
                if r < s[20]:
                    s[20] = r
            sized = (net - base) * weight
            s[0] += 1
            s[1] += 1 if net > 0 else 0
            s[2] += net
            s[3] += net * net
            s[4] += base
            s[5] += days
            s[10] += sized
            s[11] += sized * sized
            s[12] += net * weight
            s[13] += 1 if reason == 1 else 0
            s[14] += gapped
            s[15] += 1 if reason == 2 else 0
            s[16] += 1 if reason == 3 else 0
            s[17] += 1 if reason == 4 else 0
            s[18] += 1 if reason >= 5 else 0
            if net < s[19]:
                s[19] = net
            s[23] += weight
            s[25] += weight * days
    return out


def policy(system):
    """The stop policy of a system as the row _trade reads.

    A system carries either `stop_atr` (a number of ATRs under the entry,
    or null) or `stop`: {"initial": [kind, size], "trail": [kind, size],
    "breakeven_r", "target_r", "target_part", "rule_exit", "stall_days",
    "bail"}. Kinds: initial none | atr | pct | low | expr, trail none |
    chandelier | low | pct. `low` takes a window from LOWS; `expr` takes a
    formula for the stop's distance under the signal close, as a share of
    it. `bail` is one more exit rule, read at the close like `exit`."""
    spec = system.get("stop")
    if spec is None:
        x = system.get("stop_atr")
        spec = {"initial": ["atr", x]} if x else {}
    unknown = set(spec) - {"initial", "trail", "breakeven_r", "target_r", "target_part", "rule_exit",
                           "stall_days", "bail"}
    if unknown:
        raise ValueError("unknown stop fields: %s" % sorted(unknown))
    row = np.zeros(9, dtype=np.float64)
    for at, kinds, field in ((0, INITIAL, "initial"), (2, TRAIL, "trail")):
        kind, size = spec.get(field) or ("none", 0)
        if kind not in kinds:
            raise ValueError("unknown %s stop: %s" % (field, kind))
        row[at] = kinds[kind]
        if kind == "low":
            if size not in LOWS:
                raise ValueError("a low stop needs a window from %s, not %s" % (LOWS, size))
            row[at + 1] = LOWS.index(size)
        elif kind not in ("none", "expr"):
            if not (isinstance(size, (int, float)) and math.isfinite(size) and size > 0):
                raise ValueError("%s stop %s needs a positive size, not %r" % (field, kind, size))
            row[at + 1] = size
    row[4] = spec.get("breakeven_r") or 0
    row[5] = spec.get("target_r") or 0
    row[6] = spec.get("target_part") or 1
    row[7] = 1 if spec.get("rule_exit", True) or spec.get("bail") else 0
    row[8] = spec.get("stall_days") or 0
    if (row[4] or row[5]) and not (row[0] or row[2]):
        raise ValueError("a target or a break-even move in R needs a stop")
    if not (row[4] >= 0 and row[5] >= 0 and 0 < row[6] <= 1 and row[8] >= 0):
        raise ValueError("stop policy out of range: %s" % spec)
    return row


def arrays(m):
    """The bars as _trade wants them, kept on the market."""
    if not hasattr(m, "walk"):
        o, h, low, c = (np.ascontiguousarray(m.bars[k], dtype=np.float64)
                        for k in ("open", "high", "low", "close"))
        atr = np.ascontiguousarray(m.parts["range14"] * m.bars["close"], dtype=np.float64)
        lows = np.empty((len(LOWS),) + low.shape, dtype=np.float64)
        running = low.copy()
        for n in range(1, max(LOWS) + 1):
            if n > 1:
                running[n - 1:] = np.fmin(running[n - 1:], low[:-(n - 1)])
            if n in LOWS:
                lows[LOWS.index(n)] = running
        finite = np.isfinite(c)
        ends = np.where(finite.any(axis=0), len(c) - 1 - finite[::-1].argmax(axis=0), -1)
        m.walk = (o, h, low, c, atr, lows, ends.astype(np.int64))
    return m.walk


def prepare(m, system, first, last, live=False):
    """What the walk needs for one system: its signals, exits and limits."""
    o, h, low, c, atr, lows, ends = arrays(m)
    hold = int(system["max_days"])
    spec = system.get("stop") or {}
    # `entry` is a formula, or the signals themselves (combine.py builds them).
    entry = system["entry"] if isinstance(system["entry"], np.ndarray) else flags(m, system["entry"])
    leave = flags(m, system["exit"]) if system.get("exit") else np.zeros(m.member.shape, dtype=bool)
    if spec.get("bail"):                 # read even when the system's own exit is dropped
        leave = (leave if spec.get("rule_exit", True) else np.zeros_like(leave)) | flags(m, spec["bail"])
    initial = spec.get("initial") or ("none", 0)
    dist = number(m, initial[1]) if initial[0] == "expr" else np.zeros((1, 1))
    window = np.array([first <= d <= last for d in m.dates])
    # The last `hold` days of the window give no entries, so a trade opened
    # in one stage is over before the next begins.
    if not live:
        window[np.where(window)[0][-hold:]] = False
    ok = entry & m.member & window[:, None]
    jj, tt = np.nonzero(ok.T)
    nxt = np.minimum(tt + 1, len(c) - 1)
    keep = (tt + 1 <= ends[jj]) & np.isfinite(atr[tt, jj]) & np.isfinite(o[nxt, jj])
    return {"bars": (o, h, low, c, atr, lows), "leave": np.ascontiguousarray(leave), "dist": dist,
            "sig_j": jj[keep].astype(np.int64), "sig_t": tt[keep].astype(np.int64), "ends": ends,
            "hold": hold, "ok": ok}


def simulate(m, system, first, last, live=False):
    """Every trade whose entry signal falls in [first, last]: a list of dicts.

    `live` reads up to the panel's last bar as today: a position not yet
    closed has reason "open" (valued at the last close, `closing` when its
    exit is due at the next open, `stop_now` the stop for the next day),
    and a signal on the last bar of an instrument with no position, whose
    entry is still ahead, has reason "pending"."""
    p = prepare(m, system, first, last, live)
    o, h, low, c, atr, lows = p["bars"]
    cfg, dates, n_days = policy(system), m.dates, len(m.dates)
    whole, real = _list(o, h, low, c, atr, lows, p["leave"], p["dist"], p["sig_j"], p["sig_t"],
                        p["ends"], p["hold"], n_days - 1 if live else -1, cfg)
    trades, in_position = [], set()
    for (k, day, reason, due, gapped), (exit_price, stop, gross, stop_now, high, low_seen, sold) \
            in zip(whole.tolist(), real.tolist()):
        j, t = int(p["sig_j"][k]), int(p["sig_t"][k])
        price = float(o[t + 1, j])
        risk = (price - stop) / price if stop == stop else None
        net = gross - 2 * m.cost
        if reason == 7:
            in_position.add(j)
        trades.append({"instrument": m.labels[j], "column": j, "signal": dates[t],
                       "entry": dates[t + 1], "entry_price": price, "exit": dates[day],
                       "exit_price": exit_price, "reason": REASONS[reason],
                       "days": int(day - t - 1) or 1, "gross": gross, "net": net,
                       "closing": bool(due) and reason == 7, "stop": stop if risk else None,
                       "stop_now": stop_now if risk and reason == 7 else None,
                       "risk": risk, "r": net / risk if risk else None, "gapped": bool(gapped),
                       "sold_at_target": sold, "high": high, "low": low_seen})
    if live:
        t = n_days - 1
        for j in np.where(p["ok"][t] & (p["ends"] == t) & np.isfinite(atr[t]))[0].tolist():
            if j in in_position:
                continue
            close = float(c[t, j])
            distance = float(p["dist"][t, j]) if cfg[0] == 4 else 0.0
            if cfg[0] == 4 and not distance > 0:
                continue
            stop = float(_first_stop(cfg, close, atr[t, j],
                                     lows[int(cfg[1]), t, j] if cfg[0] == 3 else np.nan,
                                     lows[int(cfg[3]), t, j] if cfg[2] == 2 else np.nan,
                                     distance, close))
            risk = (close - stop) / close if stop == stop and close > stop else None
            trades.append({"instrument": m.labels[j], "column": j, "signal": dates[t],
                           "entry": None, "entry_price": None, "exit": None, "exit_price": close,
                           "reason": "pending", "days": 0, "gross": 0.0, "net": 0.0,
                           "closing": False, "stop": stop if risk else None, "stop_now": None,
                           "risk": risk, "r": None, "gapped": False, "sold_at_target": 0.0,
                           "high": close, "low": close})
        trades.sort(key=lambda x: (x["column"], x["signal"]))
    return trades


def drift(m, first, last):
    """Each instrument's mean daily return over the stage, while a member:
    what holding it on an average day paid."""
    c = m.bars["close"]
    window = np.array([first <= d <= last for d in m.dates])
    with np.errstate(all="ignore"):
        daily = c[1:] / c[:-1] - 1
    ok = window[1:, None] & m.member[1:] & np.isfinite(daily)
    total = np.where(ok, daily, 0).sum(axis=0)
    count = ok.sum(axis=0)
    return np.where(count > 0, total / np.maximum(count, 1), 0.0)


def members_index(m):
    """The equal-weight members' value by day (1 before the first)."""
    if not hasattr(m, "_members_index"):
        close = m.bars["close"]
        with np.errstate(all="ignore"):
            daily = close[1:] / close[:-1] - 1
        ok = m.member[:-1] & np.isfinite(daily)
        mean = np.where(ok, daily, 0).sum(axis=1) / np.maximum(ok.sum(axis=1), 1)
        m._members_index = np.concatenate([[1.0], np.cumprod(1 + mean)])
        m._day = {d: i for i, d in enumerate(m.dates)}
    return m._members_index


def statistics(m, trades, first, last):
    """`edge` is before costs and against each instrument's mean drift over
    the whole stage, which a trader could not know. `over_members` is after
    costs and against the equal-weight members over the trade's own days
    (the close before the entry to the close of the exit day)."""
    if len(trades) < 30:
        return {"insufficient": True, "trades": len(trades)}
    per_day = drift(m, first, last)
    net = np.array([t["net"] for t in trades])
    base = np.array([(1 + per_day[t["column"]]) ** t["days"] - 1 for t in trades])
    edge = np.array([t["gross"] for t in trades]) - base
    index = members_index(m)
    held = np.array([index[m._day[t["exit"]]] / index[max(m._day[t["entry"]] - 1, 0)] - 1 for t in trades])
    by_month = defaultdict(list)
    for t, e in zip(trades, edge):
        by_month[t["entry"][:7]].append(e)
    monthly = [float(np.mean(v)) for _, v in sorted(by_month.items())]
    t_edge = E.newey_west(monthly, 1)
    if t_edge is None:
        return {"insufficient": True, "trades": len(trades), "months": len(monthly)}
    wins, losses = net[net > 0], net[net <= 0]
    years = (int(last[:4]) - int(first[:4]) + 1)
    return {**in_r(trades, net, base),
            "trades": len(trades), "per_year": len(trades) / years,
            "win_rate": float((net > 0).mean()),
            "avg_win": float(wins.mean()) if len(wins) else 0.0,
            "avg_loss": float(losses.mean()) if len(losses) else 0.0,
            "expectancy": float(net.mean()), "baseline": float(base.mean()),
            "edge": float(edge.mean()), "t": t_edge, "months": len(monthly),
            "over_members": float((net - held).mean()),
            "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else None,
            "avg_days": float(np.mean([t["days"] for t in trades])),
            "side": 1 if edge.mean() >= 0 else -1,
            "gross_annual": float(edge.mean()), "net_annual": float(net.mean())}


def in_r(trades, net, base):
    """The same trades in R, and as a share of an account that risks RISK
    on each with no position over CAP. Empty when a trade has no stop."""
    if any(t["risk"] is None for t in trades):
        return {}
    risk = np.array([t["risk"] for t in trades])
    r = net / risk
    weight = np.minimum(RISK / risk, CAP)
    won, lost = r[r > 0], r[r <= 0]
    return {"risk": float(risk.mean()), "avg_r": float(r.mean()),
            "avg_win_r": float(won.mean()) if len(won) else 0.0,
            "avg_loss_r": float(lost.mean()) if len(lost) else 0.0,
            "worst_r": float(r.min()), "sized": float(((net - base) * weight).mean()),
            "sized_net": float((net * weight).mean()),
            "stopped": float(np.mean([t["reason"] == "stop" for t in trades])),
            "gapped": float(np.mean([t["gapped"] for t in trades]))}


def passes(stats, t_needed):
    return (not stats.get("insufficient") and stats["expectancy"] > 0
            and stats["edge"] > 0 and stats["t"] >= t_needed)


def good(stats):
    return not stats.get("insufficient") and stats["expectancy"] > 0 and stats["edge"] > 0


def by_system(rows):
    """{key: {stage: ledger row}} of the trading systems in `rows`."""
    out = defaultdict(dict)
    for r in rows:
        if r["type"] == "trade":
            out[r["key"]][r["stage"]] = r
    return out


def shown(rows):
    """The systems the product shows: positive profit per trade and positive
    edge in discovery and in validation."""
    return [s for s in by_system(rows).values()
            if all(st in s and good(s[st]["stats"]) for st in ("discover", "validate"))]


def as_hypothesis(system):
    """The ledger's shape for a system: one formula string that identifies it."""
    expr = "entry: %s || exit: %s || stop_atr: %s" % (system["entry"], system.get("exit"),
                                                     system.get("stop_atr"))
    fields = ["entry", "exit", "stop_atr", "max_days"]
    if system.get("stop") is not None:       # a system with a stop policy is another system
        expr += " || stop: %s" % json.dumps(system["stop"], sort_keys=True)
        fields.append("stop")
    return {"id": system["id"], "type": "trade", "horizon": int(system["max_days"]), "expr": expr,
            "rationale": system.get("rationale", ""), "source": system.get("source", ""),
            "system": {k: system.get(k) for k in fields}}


def line(row):
    s = row["stats"]
    if s.get("insufficient"):
        return "  %-26s yetersiz islem (%d)" % (row["id"][:26], s.get("trades", 0))
    return ("  %-26s %5d islem  kazanan %%%2.0f  ort.kazanc %+5.1f%%  ort.kayip %+5.1f%%  "
            "islem basi net %+5.2f%%  rastgele giris %+5.2f%%  katki %+5.2f%% (t %+4.1f)  %4.1f gun  %s"
            % (row["id"][:26], s["trades"], 100 * s["win_rate"], 100 * s["avg_win"],
               100 * s["avg_loss"], 100 * s["expectancy"], 100 * s["baseline"], 100 * s["edge"],
               s["t"], s["avg_days"], row["verdict"]))


def record(m, system, stage, stats, verdict):
    hyp = as_hypothesis(system)
    return E.record(hyp, stage, stats, verdict, m.universe, system=hyp["system"])


def main(argv):
    universe = "sp500"
    if "--universe" in argv:
        i = argv.index("--universe")
        universe, argv = argv[i + 1], argv[:i] + argv[i + 2:]
        if universe not in E.UNIVERSES:
            raise SystemExit("bilinmeyen evren: %s" % universe)
    cmd = argv[1] if len(argv) > 1 else "ledger"
    rows = [r for r in E.ledger(universe) if r["type"] == "trade"]
    if cmd == "ledger":
        for r in rows:
            print("%-9s" % r["stage"] + line(r))
        return
    m = E.Market(universe)
    done = {(r["key"], r["stage"]) for r in rows}
    if cmd == "discover":
        systems = json.load(open(argv[2]))
        first, last = E.STAGES["discover"]
        print("%s: %d sistem" % (universe, len(systems)))
        for sys_ in systems:
            hyp = as_hypothesis(sys_)
            if (E.key(hyp), "discover") in done:
                continue
            if not 1 <= int(sys_["max_days"]) <= MAX_DAYS_LIMIT:
                print("  %-26s gecersiz max_days" % sys_["id"][:26])
                continue
            try:
                stats = statistics(m, simulate(m, sys_, first, last), first, last)
            except Exception as exc:
                print("  %-26s formul hatasi: %s" % (sys_["id"][:26], str(exc)[:70]))
                continue
            print(line(record(m, sys_, "discover", stats,
                              "terfi" if passes(stats, E.PROMOTE_T) else "-")))
        return
    if cmd in ("validate", "sealed"):
        source, needed = ("discover", "terfi") if cmd == "validate" else ("validate", "gecti")
        first, last = E.STAGES[cmd]
        todo = [r for r in rows if r["stage"] == source and r["verdict"] == needed
                and (r["key"], cmd) not in done]
        print("%s %s: %d aday" % (universe, cmd, len(todo)))
        for r in todo:
            sys_ = {"id": r["id"], "rationale": r["rationale"], "source": r["source"], **r["system"]}
            stats = statistics(m, simulate(m, sys_, first, last), first, last)
            print(line(record(m, sys_, cmd, stats,
                              "gecti" if passes(stats, E.CONFIRM_T) else "kaldi")))
        return
    if cmd == "seen":
        first, last = E.STAGES["validate"]
        todo = [r for r in rows if r["stage"] == "discover" and (r["key"], "validate") not in done]
        print("%s seen: %d sistem" % (universe, len(todo)))
        for r in todo:
            sys_ = {"id": r["id"], "rationale": r["rationale"], "source": r["source"], **r["system"]}
            stats = statistics(m, simulate(m, sys_, first, last), first, last)
            print(line(record(m, sys_, "validate", stats, "goruldu")))
        return
    if cmd == "product":
        first, last = E.STAGES["sealed"]
        todo = [s["discover"] for s in shown(rows) if "sealed" not in s]
        print("%s product: %d sistem gosteriliyor, %d tanesi muhurlu yillarda ilk kez okunuyor"
              % (universe, len(shown(rows)), len(todo)))
        for r in todo:
            sys_ = {"id": r["id"], "rationale": r["rationale"], "source": r["source"], **r["system"]}
            stats = statistics(m, simulate(m, sys_, first, last), first, last)
            print(line(record(m, sys_, "sealed", stats, "gosterilen" if good(stats) else "isaretli")))
        return
    if cmd == "show":
        found = [r for r in rows if r["id"] == argv[2] and r["stage"] == "discover"]
        if not found:
            raise SystemExit("defterde yok: %s" % argv[2])
        sys_ = {"id": argv[2], **found[0]["system"]}
        # The sealed years stay unread: the journal shows discovery and validation.
        first, last = E.STAGES["discover"][0], E.STAGES["validate"][1]
        trades = [t for t in simulate(m, sys_, first, last) if t["instrument"] == argv[3]]
        print("%s, %s, %s .. %s: %d islem" % (argv[2], argv[3], first, last, len(trades)))
        print("  giris: %s\n  cikis: %s | stop %s ATR | en cok %s gun"
              % (sys_["entry"], sys_["exit"], sys_["stop_atr"], sys_["max_days"]))
        for t in trades:
            print("  sinyal %s  giris %s @ %9.2f  cikis %s @ %9.2f  %-5s %3d gun  net %+6.1f%%"
                  % (t["signal"], t["entry"], t["entry_price"], t["exit"], t["exit_price"],
                     t["reason"], t["days"], 100 * t["net"]))
        if trades:
            net = [t["net"] for t in trades]
            print("  kazanan %d/%d, islem basi net %+.2f%%, toplam (bilesik) %+.0f%%"
                  % (sum(x > 0 for x in net), len(net), 100 * sum(net) / len(net),
                     100 * (math.prod(1 + x for x in net) - 1)))
        return
    raise SystemExit("bilinmeyen komut: %s" % cmd)


if __name__ == "__main__":
    main(sys.argv)
