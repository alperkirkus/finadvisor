"""Which stop. Every combination of stop, trail, target and exit, scored.

trades.py gives a system the stop its author wrote beside the entry. This
asks the question on its own: over every system that has an edge in a
market, which way of getting out leaves the most in the account. The rules
were fixed before any variant was scored (plan.md, Phase 24).

    stops.py excursions                # how far trades run against and for, 2006-2016
    stops.py grid discover             # every variant x every system
    stops.py effects | top             # what each choice is worth; the best variants
    stops.py designs <designs.json>    # authored designs outside the grid, 2006-2016
    stops.py finalists [designs.json]  # the twenty best per family, 2006-2016
    stops.py choose                    # the finalists on 2017-2021, one is chosen
    stops.py sealed                    # the chosen one on 2022-2025, read once
    stops.py restate                   # the product's systems with the chosen stop
    stops.py account                   # chosen, authored and no stop as an account
    stops.py grid validate             # diagnostic only: do the periods agree
    stops.py agreement                 # rank correlation of the two grids
    stops.py show                      # what was decided

Every command takes `--universe sp500|midsmall|etf|bist`.

R. A trade's risk is its entry price minus the stop in force that day, as
a share of the entry price; its result in R is its net result over that
risk. R alone always prefers the nearest stop, because it lets the
position grow without limit as the stop closes in. So a variant is ranked
by `sized`: what a trade adds to an account that risks RISK of itself on
every trade and never puts more than CAP of itself in one position, after
costs and after what the instrument pays on an average day anyway.
"""
import itertools
import json
import os
import sys
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E            # noqa: E402
import trades as T            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(E.P.OUT, "stops")
SYSTEM_FILES = ("systems_classic.json", "systems_round1.json")
FINALISTS, MIN_TRADES, MIN_SHARE, MIN_POOL = 20, 30, 0.8, 3
FAMILIES = ("dip", "strength")
S = {name: i for i, name in enumerate(T.STATS)}


def variants():
    """The grid of Phase 24 as stop specs."""
    initial = ([("none", 0)] + [("atr", x) for x in (1, 1.5, 2, 2.5, 3, 4, 5)]
               + [("pct", x) for x in (0.03, 0.05, 0.08, 0.12)] + [("low", n) for n in T.LOWS])
    trail = ([("none", 0)] + [("chandelier", x) for x in (2, 3, 4)]
             + [("low", n) for n in (5, 10, 20)] + [("pct", x) for x in (0.05, 0.10, 0.15)])
    targets = [(None, 1)] + [(x, 1) for x in (1, 1.5, 2, 3, 5)] + [(1, 0.5), (2, 0.5)]
    out = []
    for first, then, even, (target, part), rule, stall in itertools.product(
            initial, trail, (None, 1, 2), targets, (True, False), (None, 5, 10)):
        if first[0] == "none" and then[0] == "none" and (even or target):
            continue
        out.append({"initial": list(first), "trail": list(then), "breakeven_r": even,
                    "target_r": target, "target_part": part, "rule_exit": rule,
                    "stall_days": stall})
    return out


def label(spec):
    if spec == "authored":
        return "yazarin stopu"
    size = {"atr": "%g ATR", "pct": "%%%g", "low": "%g gun dibi", "chandelier": "zirve-%g ATR"}

    def one(pair, percent_of):
        kind, x = pair or ("none", 0)
        if kind == "none":
            return "yok"
        if kind == "expr":
            return "formul"
        return (percent_of if kind == "pct" else size[kind]) % (100 * x if kind == "pct" else x)
    parts = ["stop " + one(spec.get("initial"), "%%%g"), "iz " + one(spec.get("trail"), "zirve kapanis-%%%g")]
    if spec.get("breakeven_r"):
        parts.append("basabas +%gR" % spec["breakeven_r"])
    if spec.get("target_r"):
        parts.append("hedef %gR%s" % (spec["target_r"],
                                      " (yarisi)" if (spec.get("target_part") or 1) < 1 else ""))
    if not spec.get("rule_exit", True):
        parts.append("kural cikisi yok")
    if spec.get("stall_days"):
        parts.append("durgun %dg" % spec["stall_days"])
    if spec.get("bail"):
        parts.append("ek cikis")
    return " | ".join(parts)


def systems():
    out = []
    for name in SYSTEM_FILES:
        out += json.load(open(os.path.join(HERE, "hypotheses", name)))
    return out


def pool(universe):
    """Ids of the systems whose authored version made money per trade and
    beat a random entry by more than a round trip's cost on 2006-2016 in
    this universe: the ones with something for a stop to protect."""
    rows, cost = T.by_system(E.ledger(universe)), E.UNIVERSES[universe][1]
    return {s["discover"]["id"] for s in rows.values()
            if "discover" in s and T.good(s["discover"]["stats"])
            and s["discover"]["stats"]["edge"] > 2 * cost}


def family(m, system):
    """`dip` when the system buys under its 20-day average on 2006-2016."""
    p = T.prepare(m, system, *E.STAGES["discover"])
    if not len(p["sig_t"]):
        return None
    with np.errstate(all="ignore"):
        z = float(np.nanmean(m.parts["z20"][p["sig_t"], p["sig_j"]]))
    return "dip" if z < 0 else "strength"


def sums(m, system, stage, rows, spec=None):
    """STATS sums of every policy row on one system and stage."""
    first, last = E.STAGES[stage]
    p = T.prepare(m, {**system, "stop": spec} if spec else system, first, last)
    o, h, low, c, atr, lows = p["bars"]
    return T._grid(o, h, low, c, atr, lows, p["leave"], p["dist"], p["sig_j"], p["sig_t"],
                   p["ends"], p["hold"], rows, T.drift(m, first, last), m.cost)


def derive(s):
    """Per-trade figures from STATS sums (one row or many, last axis)."""
    s = np.asarray(s, dtype=np.float64)
    n = np.maximum(s[..., S["n"]], 1)
    with np.errstate(all="ignore"):
        return {"trades": s[..., S["n"]], "win_rate": s[..., S["wins"]] / n,
                "net": s[..., S["net"]] / n, "own": (s[..., S["net"]] - s[..., S["base"]]) / n,
                "sized": s[..., S["sized"]] / n, "sized_net": s[..., S["sized_net"]] / n,
                "avg_r": s[..., S["r"]] / n, "risk": s[..., S["risk"]] / n,
                "avg_win_r": s[..., S["win_r"]] / np.maximum(s[..., S["wins_r"]], 1),
                "avg_loss_r": s[..., S["loss_r"]] / np.maximum(n - s[..., S["wins_r"]], 1),
                "days": s[..., S["days"]] / n, "stopped": s[..., S["stops"]] / n,
                "gapped": s[..., S["gaps"]] / np.maximum(s[..., S["stops"]], 1),
                "at_target": s[..., S["targets"]] / n, "worst": s[..., S["worst"]],
                "worst_r": s[..., S["worst_r"]],
                "sized_per_day": s[..., S["sized"]] / np.maximum(s[..., S["sized_days"]], 1e-12),
                "weight": s[..., S["weight"]] / n}


def grid_path(universe, stage):
    return os.path.join(OUT, "grid_%s_%s.npz" % (universe, stage))


def result_path(universe):
    return os.path.join(OUT, "result_%s.json" % universe)


def load_result(universe):
    path = result_path(universe)
    return json.load(open(path)) if os.path.exists(path) else {}


def save_result(universe, result):
    os.makedirs(OUT, exist_ok=True)
    with open(result_path(universe) + ".tmp", "w") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(result_path(universe) + ".tmp", result_path(universe))
    with open(os.path.join(OUT, "log.jsonl"), "a") as fh:
        fh.write(json.dumps({"universe": universe, "steps": sorted(result),
                             "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")


def run_grid(m, stage):
    specs = variants()
    rows = np.array([T.policy({"stop": s}) for s in specs])
    todo = systems()
    stats = np.zeros((len(todo), len(rows), len(T.STATS)), dtype=np.float32)
    start = time.time()
    members = pool(m.universe)
    order = sorted(range(len(todo)), key=lambda i: todo[i]["id"] not in members)
    # A system's sums are kept as soon as they are done, so a run that is
    # cut short goes on from where it stopped.
    parts = os.path.join(OUT, "parts_%s_%s" % (m.universe, stage))
    os.makedirs(parts, exist_ok=True)
    for i in order:                      # the pooled systems first: the choice waits on them
        system = todo[i]
        part = os.path.join(parts, system["id"] + ".npy")
        if os.path.exists(part):
            stats[i] = np.load(part)
            continue
        stats[i] = sums(m, system, stage, rows)
        np.save(part + ".tmp.npy", stats[i])
        os.replace(part + ".tmp.npy", part)
        print("  %-34s en cok %7.0f islem %5.0fs"
              % (system["id"][:34], stats[i, :, S["n"]].max(), time.time() - start), flush=True)
    np.savez_compressed(grid_path(m.universe, stage), ids=np.array([s["id"] for s in todo]),
                        rows=rows, stats=stats)
    for name in os.listdir(parts):
        os.remove(os.path.join(parts, name))
    os.rmdir(parts)
    print("%s %s: %d sistem x %d varyant, %.0f dk"
          % (m.universe, stage, len(todo), len(rows), (time.time() - start) / 60))


def load_grid(universe, stage, needed):
    """(ids, stats) of a grid. While the grid is still running, the systems
    already done are read from its parts; a needed one that is not done yet
    is an error, never a row of zeros."""
    if os.path.exists(grid_path(universe, stage)):
        z = np.load(grid_path(universe, stage))
        return [str(x) for x in z["ids"]], z["stats"]
    parts = os.path.join(OUT, "parts_%s_%s" % (universe, stage))
    missing = [x for x in needed if not os.path.exists(os.path.join(parts, x + ".npy"))]
    if missing:
        raise SystemExit("%s %s izgarasi bitmedi, eksik: %s" % (universe, stage, ", ".join(missing)))
    ids = sorted(needed)
    return ids, np.stack([np.load(os.path.join(parts, x + ".npy")) for x in ids])


def pooled(stats, members):
    """Sums over the pool's systems, and which variants have enough trades
    in enough of them."""
    part = stats[members].astype(np.float64)
    enough = (part[..., S["n"]] >= MIN_TRADES).mean(axis=0) >= MIN_SHARE
    total = part.sum(axis=0)
    total[..., S["worst"]] = part[..., S["worst"]].min(axis=0)
    total[..., S["worst_r"]] = part[..., S["worst_r"]].min(axis=0)
    return total, enough


def families(m):
    """{family: ids of its pooled systems}; a family with fewer than
    MIN_POOL of them is left empty and so not decided."""
    members = pool(m.universe)
    out = defaultdict(list)
    for system in systems():
        if system["id"] in members:
            out[family(m, system)].append(system["id"])
    return {f: out[f] if len(out[f]) >= MIN_POOL else [] for f in FAMILIES}


def family_of_all(m):
    """The family of every system of the universe, pooled or not."""
    return {system["id"]: family(m, system) for system in systems()}


def pooled_trades(m, members, spec, stage):
    """The trades of every pooled system under one policy on a stage, each
    with its system, its position size and what it added to the account."""
    first, last = E.STAGES[stage]
    per_day = T.drift(m, first, last)
    out = []
    for system in systems():
        if system["id"] not in members:
            continue
        for t in T.simulate(m, system if spec == "authored" else {**system, "stop": spec}, first, last):
            base = (1 + per_day[t["column"]]) ** t["days"] - 1
            t["system"] = system["id"]
            t["weight"] = min(T.RISK / t["risk"], T.CAP) if t["risk"] else T.CAP
            t["sized"] = (t["net"] - base) * t["weight"]
            out.append(t)
    return out


def detail(m, members, spec, stage):
    """One policy on the pool's systems and a stage, from the trades
    themselves: the per-trade figures, a t by month of entry, and the
    sized result of each month for comparing two policies."""
    trades = pooled_trades(m, members, spec, stage)
    if not trades:
        return {"trades": 0}
    net = np.array([t["net"] for t in trades])
    sized = np.array([t["sized"] for t in trades])
    days = np.array([t["days"] for t in trades])
    weight = np.array([t["weight"] for t in trades])
    by_month, by_system = defaultdict(list), defaultdict(list)
    for t in trades:
        by_month[t["entry"][:7]].append(t["sized"])
        by_system[t["system"]].append(t["sized"])
    monthly = {k: float(np.mean(v)) for k, v in sorted(by_month.items())}
    out = {"trades": len(net), "win_rate": float((net > 0).mean()), "net": float(net.mean()),
           "sized": float(sized.mean()), "sized_net": float((net * weight).mean()),
           "t": E.newey_west(list(monthly.values()), 1), "days": float(days.mean()),
           "stopped": float(np.mean([t["reason"] == "stop" for t in trades])),
           "at_target": float(np.mean([t["reason"] == "target" for t in trades])),
           "gapped": float(np.mean([t["gapped"] for t in trades])), "worst": float(net.min()),
           "p01": float(np.percentile(net, 1)), "weight": float(weight.mean()),
           "systems": {k: {"trades": len(v), "sized": float(np.mean(v))}
                       for k, v in by_system.items()},
           "monthly": monthly, "sized_per_day": float(sized.sum() / (weight * days).sum())}
    if all(t["risk"] for t in trades):
        r = net / np.array([t["risk"] for t in trades])
        won, lost = r[r > 0], r[r <= 0]
        out.update({"risk": float(np.mean([t["risk"] for t in trades])), "avg_r": float(r.mean()),
                    "avg_win_r": float(won.mean()) if len(won) else 0.0,
                    "avg_loss_r": float(lost.mean()) if len(lost) else 0.0,
                    "worst_r": float(r.min())})
    return out


def account(m, trades, stage=None, seeds=20, span=None, slots=None):
    """What an account did that took these trades as they came: RISK of the
    account at risk per trade, no position over CAP, never more invested
    than it holds, one position per instrument, and with `slots` never more
    than that many positions at once. When more signals arrive than it can
    take, which ones it takes is drawn at random, `seeds` times. Results are booked when a trade closes, so the drawdown is that
    of closed trades and understates the worst day."""
    first, last = span or E.STAGES[stage]
    day = {d: i for i, d in enumerate(m.dates)}
    years = sum(first <= d <= last for d in m.dates) / 252
    rows = [(day[t["entry"]], day[t["exit"]], t["column"], t["weight"], t["net"]) for t in trades]
    growth, drawdown, taken, invested, runs = [], [], [], [], []
    for seed in range(seeds):
        order = np.random.default_rng(seed).permutation(len(rows))
        queue = sorted((rows[i] for i in order), key=lambda r: r[0])
        equity, peak, worst, open_, held, used, count, exposure = 1.0, 1.0, 0.0, [], set(), 0.0, 0, 0.0
        run = longest = 0
        for entry, leave, column, weight, net in queue:
            still = []
            for x in sorted(open_):
                if x[0] <= entry:
                    equity += x[2] * x[3]
                    run = run + 1 if x[3] <= 0 else 0
                    longest = max(longest, run)
                    used -= x[2]
                    held.discard(x[1])
                    peak = max(peak, equity)
                    worst = min(worst, equity / peak - 1)
                else:
                    still.append(x)
            open_ = still
            size = weight * equity
            if column in held or used + size > equity or (slots and len(open_) >= slots):
                continue
            open_.append((leave, column, size, net))
            held.add(column)
            used += size
            count += 1
            exposure += weight * max(leave - entry, 1)
        for x in sorted(open_):
            equity += x[2] * x[3]
            peak = max(peak, equity)
            worst = min(worst, equity / peak - 1)
        growth.append(max(equity, 1e-9) ** (1 / years) - 1)
        runs.append(longest)
        drawdown.append(worst)
        taken.append(count / years)
        invested.append(exposure / (252 * years))
    return {"yearly": float(np.mean(growth)), "drawdown": float(np.mean(drawdown)),
            "trades_per_year": float(np.mean(taken)), "invested": float(np.mean(invested)),
            "longest_losing_run": float(np.mean(runs)),
            "offered_per_year": len(rows) / years}


def accounts(m):
    """The chosen stop, the authored stops and no stop at all as an account,
    in each period that has been read for stops."""
    result = load_result(m.universe)
    if "choice" not in result:
        raise SystemExit("%s: once `stops.py choose`" % m.universe)
    stages = ["discover", "validate"] + (["sealed"] if "sealed" in result else [])
    result["accounts"] = {}
    for name, picked in result["choice"].items():
        members = set(result["finalists"][name]["members"])
        result["accounts"][name] = {}
        for stage in stages:
            print("%s %s, %s .. %s:" % ((m.universe, name) + E.STAGES[stage]))
            for who, spec in (("chosen", picked["stop"]), ("authored", "authored"), ("none", {})):
                a = account(m, pooled_trades(m, members, spec, stage), stage)
                result["accounts"][name].setdefault(stage, {})[who] = a
                print("  %-58s yilda %+6.1f%%  en derin dusus %+6.1f%%  yilda %5.0f islem (%5.0f sinyal)"
                      "  ortalama yatirilan %%%3.0f"
                      % (("[%s]" % who if who != "chosen" else label(spec))[:58], 100 * a["yearly"],
                         100 * a["drawdown"], a["trades_per_year"], a["offered_per_year"],
                         100 * a["invested"]))
    save_result(m.universe, result)


def against(a, b):
    """t of the monthly difference in sized between two details, a minus b."""
    months = sorted(set(a["monthly"]) & set(b["monthly"]))
    return E.newey_west([a["monthly"][k] - b["monthly"][k] for k in months], 1)


def row(name, d):
    if not d.get("trades"):
        return "  %-96s islem yok" % name[:96]
    r = ("R %+5.2f (kazanc %+5.2f, kayip %+5.2f, risk %%%4.1f)"
         % (d["avg_r"], d["avg_win_r"], d["avg_loss_r"], 100 * d["risk"])) if "avg_r" in d else \
        "R tanimsiz (stop yok)                          "
    return ("  %-96s %6d islem  hesap %+6.2f bp (t %+4.1f)  net %+5.2f%%  kazanan %%%2.0f  %s  "
            "%4.1f gun  stop %%%2.0f  en kotu %+5.1f%%"
            % (name[:96], d["trades"], 1e4 * d["sized"], d["t"] or 0, 100 * d["net"],
               100 * d["win_rate"], r, d["days"], 100 * d["stopped"], 100 * d["worst"]))


def slim(d):
    return {k: v for k, v in d.items() if k != "monthly"}


def excursions(m):
    """How far the pool's trades went against the entry and for it, with no
    stop at all, in ATRs of the signal day: where a stop would have cut a
    trade that came back, and where it would have cut one that did not."""
    first, last = E.STAGES["discover"]
    o, h, low, c, atr, lows, ends = T.arrays(m)
    column = {label_: j for j, label_ in enumerate(m.labels)}
    day = {d: i for i, d in enumerate(m.dates)}
    for name, members in families(m).items():
        against_, toward, won = [], [], []
        for system in systems():
            if system["id"] not in members:
                continue
            for t in T.simulate(m, {**system, "stop": {}}, first, last):
                unit = atr[day[t["signal"]], column[t["instrument"]]]
                against_.append((t["entry_price"] - t["low"]) / unit)
                toward.append((t["high"] - t["entry_price"]) / unit)
                won.append(t["net"] > 0)
        if not won:
            print("%s %s: havuzda sistem yok" % (m.universe, name))
            continue
        against_, toward, won = np.array(against_), np.array(toward), np.array(won)
        print("%s %s: %d sistem, %d islem (stopsuz), kazanan %%%.0f, medyan ATR/fiyat %%%.1f"
              % (m.universe, name, len(members), len(won), 100 * won.mean(),
                 100 * float(np.nanmedian(m.parts["range14"][m.member]))))
        for who, mask in (("kazananlar", won), ("kaybedenler", ~won)):
            q = np.percentile(against_[mask], (50, 75, 90, 95))
            g = np.percentile(toward[mask], (50, 75, 90, 95))
            print("  %-11s aleyhe en cok (ATR) medyan %.1f, %%75 %.1f, %%90 %.1f, %%95 %.1f | "
                  "lehe en cok medyan %.1f, %%75 %.1f, %%90 %.1f, %%95 %.1f"
                  % (who, q[0], q[1], q[2], q[3], g[0], g[1], g[2], g[3]))
        for k in (1, 1.5, 2, 2.5, 3, 4, 5):
            hit = against_ >= k
            print("  %3.1f ATR aleyhe giden islemler %%%4.1f; bunlarin %%%2.0f'i yine de kazancla bitti"
                  % (k, 100 * hit.mean(), 100 * won[hit].mean() if hit.any() else 0))


def score_designs(m, path, ids=None):
    """Authored designs on 2006-2016: STATS sums per design and system
    (the systems in `ids`, in that order; all of them when not given)."""
    designs = json.load(open(path))
    by_id = {s["id"]: s for s in systems()}
    todo = [by_id[x] for x in ids] if ids else systems()
    stats = np.zeros((len(todo), len(designs), len(T.STATS)))
    for q, design in enumerate(designs):
        # A design that cannot be read is named and left with no trades,
        # which keeps it out of the finalists; the others are still scored.
        try:
            row_ = T.policy({"stop": design["stop"]})[None, :]
            for i, system in enumerate(todo):
                stats[i, q] = sums(m, system, "discover", row_, design["stop"])[0]
        except Exception as exc:
            stats[:, q] = 0
            print("  %-30s okunamadi: %s" % (design.get("id", "?")[:30], str(exc)[:90]))
    return designs, stats


def finalists(m, designs_path=None):
    result = load_result(m.universe)
    if "finalists" in result:
        raise SystemExit("%s: finalistler zaten secildi" % m.universe)
    specs, fams = variants(), families(m)
    ids, stats = load_grid(m.universe, "discover", [x for v in fams.values() for x in v])
    candidates = [{"stop": s, "source": "grid"} for s in specs]
    if designs_path:
        designs, extra = score_designs(m, designs_path, ids)
        stats = np.concatenate([stats.astype(np.float64), extra], axis=1)
        candidates += [{"stop": d["stop"], "source": d["id"], "family": d.get("family", "any")}
                       for d in designs]
    result["families"], result["finalists"] = fams, {}
    result["grid"] = {"variants": len(specs), "designs": len(candidates) - len(specs)}
    for name, members in fams.items():
        if not members:
            print("%s %s: havuzda sistem yok" % (m.universe, name))
            continue
        total, enough = pooled(stats, [ids.index(x) for x in members])
        d = derive(total)
        has_r = np.array([bool(T.policy({"stop": c["stop"]})[[0, 2]].any()) for c in candidates])
        fits = np.array([c.get("family", "any") in ("any", name) for c in candidates])
        score = np.where(enough & has_r & fits, d["sized"], -np.inf)
        order = np.argsort(-score)[:FINALISTS]
        print("%s %s: %d sistem (%s), %d varyanttan %d tanesi yeterli islemle"
              % (m.universe, name, len(members), ", ".join(members), len(candidates),
                 int((enough & has_r & fits).sum())))
        chosen = []
        for q in order:
            if not np.isfinite(score[q]):
                continue
            full = detail(m, set(members), candidates[q]["stop"], "discover")
            chosen.append({"stop": candidates[q]["stop"], "source": candidates[q]["source"],
                           "discover": slim(full)})
            print(row(label(candidates[q]["stop"]), full))
        refs = {}
        for ref, spec in (("authored", "authored"), ("none", {})):
            refs[ref] = slim(detail(m, set(members), spec, "discover"))
            print(row("[" + label(spec if spec else {"initial": ["none", 0]}) + "]", refs[ref]))
        result["finalists"][name] = {"members": members, "candidates": chosen, "references": refs}
    save_result(m.universe, result)


def top(m, count=12):
    """The best variants of the grid on 2006-2016, from the grid's own sums
    (nothing is recorded; finalists() is the step that counts)."""
    specs, fams = variants(), families(m)
    ids, stats = load_grid(m.universe, "discover", [x for v in fams.values() for x in v])
    has_r = np.array([s["initial"][0] != "none" or s["trail"][0] != "none" for s in specs])
    for name, members in fams.items():
        if not members:
            print("%s %s: karar verilmiyor (havuzda %d sistemden az)" % (m.universe, name, MIN_POOL))
            continue
        total, enough = pooled(stats, [ids.index(x) for x in members])
        d = derive(total)
        print("%s %s: %d sistem, %d varyant yeterli islemle"
              % (m.universe, name, len(members), int(enough.sum())))
        for title, mask in (("R tanimli", enough & has_r), ("stopsuz", enough & ~has_r)):
            order = [q for q in np.argsort(-np.where(mask, d["sized"], -np.inf))[:count] if mask[q]]
            for q in order[:count if title == "R tanimli" else 3]:
                print("  %-96s %6.0f islem  hesap %+6.2f bp  net %+5.2f%%  R %+5.2f  kazanan %%%2.0f"
                      "  risk %%%4.1f  %4.1f gun  stop %%%2.0f  en kotu %+4.0f%%"
                      % (label(specs[q])[:96], d["trades"][q], 1e4 * d["sized"][q], 100 * d["net"][q],
                         d["avg_r"][q], 100 * d["win_rate"][q], 100 * d["risk"][q], d["days"][q],
                         100 * d["stopped"][q], 100 * d["worst"][q]))


def effects(m):
    """What each choice is worth on its own, 2006-2016: the pooled sized
    result averaged over every variant that makes the choice."""
    specs, fams = variants(), families(m)
    ids, stats = load_grid(m.universe, "discover", [x for v in fams.values() for x in v])
    for name, members in fams.items():
        if not members:
            continue
        total, enough = pooled(stats, [ids.index(x) for x in members])
        d = derive(total)
        print("%s %s (%d sistem): her secimin, digerlerinin ortalamasi uzerinden degeri"
              % (m.universe, name, len(members)))
        for field, title in (("initial", "ilk stop"), ("trail", "iz suren"),
                             ("breakeven_r", "basabas"), ("target", "hedef"),
                             ("rule_exit", "kural cikisi"), ("stall_days", "durgunluk")):
            groups = defaultdict(list)
            for q, s in enumerate(specs):
                if not enough[q]:
                    continue
                key = (s["target_r"], s["target_part"]) if field == "target" else s[field]
                groups[json.dumps(key)].append(q)
            print("  %s" % title)
            for key, qs in groups.items():
                print("    %-22s hesap %+6.2f bp  net %+5.2f%%  R %+5.2f  kazanan %%%2.0f  %4.1f gun"
                      "  (%d varyant)"
                      % (key, 1e4 * np.mean(d["sized"][qs]), 100 * np.mean(d["net"][qs]),
                         np.nanmean(np.where(d["risk"][qs] > 0, d["avg_r"][qs], np.nan)),
                         100 * np.mean(d["win_rate"][qs]), np.mean(d["days"][qs]), len(qs)))


def choose(m):
    result = load_result(m.universe)
    if "finalists" not in result:
        raise SystemExit("%s: once `stops.py finalists`" % m.universe)
    if "choice" in result:
        raise SystemExit("%s: secim zaten yapildi" % m.universe)
    result["choice"] = {}
    for name, block in result["finalists"].items():
        members = set(block["members"])
        refs = {ref: detail(m, members, spec, "validate")
                for ref, spec in (("authored", "authored"), ("none", {}))}
        print("%s %s, 2017-2021:" % (m.universe, name))
        best = None
        for cand in block["candidates"]:
            full = detail(m, members, cand["stop"], "validate")
            cand["validate"] = slim(full)
            cand["validate"]["t_against_authored"] = against(full, refs["authored"])
            print(row(label(cand["stop"]), full) + "  yazarinkine karsi t %+4.1f"
                  % (cand["validate"]["t_against_authored"] or 0))
            if (full.get("trades") and full["sized_net"] > 0 and cand["discover"]["sized_net"] > 0
                    and (best is None or full["sized"] > best["validate"]["sized"])):
                best = cand
        for ref in refs:
            print(row("[%s]" % ref, refs[ref]))
        block["references_validate"] = {k: slim(v) for k, v in refs.items()}
        if best is not None and best["validate"]["sized"] > refs["authored"]["sized"]:
            result["choice"][name] = {"stop": best["stop"], "source": best["source"]}
            print("  secilen: %s" % label(best["stop"]))
        else:
            result["choice"][name] = {"stop": "authored", "source": "authored"}
            print("  secilen: yazarin stoplari (hicbir finalist 2017-2021'de gecemedi)")
    save_result(m.universe, result)


def runner_up(block):
    """Where the authored stops stayed: the finalist a system with no
    authored stop takes instead (the best on 2017-2021 by sized, sized net
    profit positive in both periods), or None."""
    fit = [c for c in block["candidates"]
           if c["validate"].get("trades") and c["validate"]["sized_net"] > 0
           and c["discover"]["sized_net"] > 0]
    return max(fit, key=lambda c: c["validate"]["sized"])["stop"] if fit else None


def stop_for(system, picked, block, confirmed):
    """The stop a system trades with, given its family's choice and whether
    the choice beat the authored stops on 2022-2025. A choice that did not
    is not applied; a system written with no stop still takes the family's
    best finalist of 2017-2021, so that every trade has a stop and an R."""
    if picked["stop"] != "authored" and confirmed:
        return picked["stop"]
    if system.get("stop_atr") or system.get("stop"):
        return "authored"
    return runner_up(block) or "authored"


def sealed(m):
    result = load_result(m.universe)
    if "choice" not in result:
        raise SystemExit("%s: once `stops.py choose`" % m.universe)
    if "sealed" in result:
        raise SystemExit("%s: muhurlu yillar zaten okundu" % m.universe)
    result["sealed"] = {}
    for name, picked in result["choice"].items():
        members = set(result["finalists"][name]["members"])
        mine = detail(m, members, picked["stop"], "sealed")
        authored = detail(m, members, "authored", "sealed")
        bare = detail(m, members, {}, "sealed")
        print("%s %s, 2022-2025:" % (m.universe, name))
        print(row(label(picked["stop"]), mine))
        print(row("[authored]", authored))
        print(row("[none]", bare))
        result["sealed"][name] = {"chosen": slim(mine), "authored": slim(authored),
                                  "none": slim(bare),
                                  "t_against_authored": against(mine, authored),
                                  "confirmed": picked["stop"] != "authored"
                                  and mine["sized"] > authored["sized"]}
        spare = runner_up(result["finalists"][name]) if picked["stop"] == "authored" else None
        if spare:
            second = detail(m, members, spare, "sealed")
            print(row("stopsuz sistemler icin: " + label(spare), second))
            result["sealed"][name]["stopless"] = {"stop": spare, **slim(second)}
    save_result(m.universe, result)


def restate(m):
    """The record of every system the product shows, with the stop chosen
    for its family: what signals.py prints."""
    result = load_result(m.universe)
    if "sealed" not in result:
        raise SystemExit("%s: once `stops.py sealed`" % m.universe)
    by_id = {s["id"]: s for s in systems()}
    family_of = family_of_all(m)
    result["restated"] = {}
    for s in T.shown(E.ledger(m.universe)):
        system = by_id[s["discover"]["id"]]
        name = family_of[system["id"]]
        spec = (stop_for(system, result["choice"][name], result["finalists"][name],
                         result["sealed"][name]["confirmed"])
                if name in result["choice"] else "authored")
        traded = system if spec == "authored" else {**system, "stop": spec}
        periods = {stage: T.statistics(m, T.simulate(m, traded, *span), *span)
                   for stage, span in E.STAGES.items()}
        result["restated"][system["id"]] = {"family": family_of[system["id"]], "stop": spec,
                                            "periods": periods}
        print("%s %-34s %s" % (m.universe, system["id"][:34], label(spec)))
        for stage, stats in periods.items():
            print("  %-9s" % stage + T.line({"id": "", "stats": stats, "verdict": ""})
                  + ("  R %+.2f" % stats["avg_r"] if "avg_r" in stats else ""))
    save_result(m.universe, result)


def agreement(universe):
    """Diagnostic: do the variants that did well on 2006-2016 do well on
    2017-2021. Not used to choose."""
    a, b = np.load(grid_path(universe, "discover")), np.load(grid_path(universe, "validate"))
    ids = [str(x) for x in a["ids"]]
    for name, block in load_result(universe).get("finalists", {}).items():
        members = [ids.index(x) for x in block["members"]]
        (ta, ea), (tb, eb) = pooled(a["stats"], members), pooled(b["stats"], members)
        ok = ea & eb
        x, y = derive(ta)["sized"][ok], derive(tb)["sized"][ok]
        rho = E._spearman(x, y)
        top = np.argsort(-x)[:FINALISTS]
        print("%s %s: %d varyant, donemler arasi sira korelasyonu %+.2f; 2006-2016'nin ilk %d'si "
              "2017-2021'de ortalama olarak varyantlarin %%%.0f'inden iyi"
              % (universe, name, int(ok.sum()), rho, FINALISTS,
                 100 * np.mean((y[:, None] < y[top][None, :]).mean(axis=0))))


def main(argv):
    universe = "sp500"
    if "--universe" in argv:
        i = argv.index("--universe")
        universe, argv = argv[i + 1], argv[:i] + argv[i + 2:]
        if universe not in E.UNIVERSES:
            raise SystemExit("bilinmeyen evren: %s" % universe)
    cmd = argv[1] if len(argv) > 1 else "show"
    if cmd == "show":
        print(json.dumps({k: v for k, v in load_result(universe).items()
                          if k in ("families", "choice")}, ensure_ascii=False, indent=1))
        return
    if cmd == "agreement":
        return agreement(universe)
    m = E.Market(universe)
    if cmd == "grid":
        if argv[2] not in ("discover", "validate"):
            raise SystemExit("izgara yalnizca discover ya da validate uzerinde calisir")
        return run_grid(m, argv[2])
    if cmd == "excursions":
        return excursions(m)
    if cmd == "effects":
        return effects(m)
    if cmd == "top":
        return top(m)
    if cmd == "designs":
        designs, stats = score_designs(m, argv[2])
        ids = [s["id"] for s in systems()]
        for name, members in families(m).items():
            if not members:
                continue
            total, _ = pooled(stats, [ids.index(x) for x in members])
            d = derive(total)
            print("%s %s:" % (universe, name))
            for q, design in enumerate(designs):
                print("  %-30s %6d islem  hesap %+6.2f bp  net %+5.2f%%  R %+5.2f  kazanan %%%2.0f"
                      % (design["id"][:30], d["trades"][q], 1e4 * d["sized"][q], 100 * d["net"][q],
                         d["avg_r"][q], 100 * d["win_rate"][q]))
        return
    if cmd == "finalists":
        return finalists(m, argv[2] if len(argv) > 2 else None)
    if cmd == "choose":
        return choose(m)
    if cmd == "sealed":
        return sealed(m)
    if cmd == "restate":
        return restate(m)
    if cmd == "account":
        return accounts(m)
    raise SystemExit("bilinmeyen komut: %s" % cmd)


if __name__ == "__main__":
    main(sys.argv)
