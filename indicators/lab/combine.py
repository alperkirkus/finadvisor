"""One algorithm out of many systems: which of them, taken together.

trades.py scores a system on its own and stops.py chooses its stop. This
asks what the owner asked from the start (plan.md, Phase 25, written
before any combination was scored): when several systems look at the same
instrument on the same day, which agreement among them is worth trading.

    combine.py fit       # 2006-2016: the candidates, and every variant fitted
    combine.py choose    # 2017-2021: one variant per family, or none
    combine.py sealed    # 2022-2025, read once
    combine.py fundamentals   # S&P 500: the chosen trades by the company side's verdict
    combine.py show      # what was chosen

Every command takes `--universe sp500|midsmall|etf|bist`.

A candidate is an instrument-day on which at least one system of a family
signals. All candidates of a family are traded by one template (TEMPLATES),
so variants differ in which candidates they take and in nothing else.
`take()` is the part the product also runs: from a stored model and a
market, the days the algorithm enters.
"""
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import components as C        # noqa: E402
import engine as E            # noqa: E402
import stops as X             # noqa: E402
import trades as T            # noqa: E402

OUT = os.path.join(E.P.OUT, "combine")
FAMILIES = ("dip", "strength")
TEMPLATES = {"dip": {"exit": "(z20 > 0)", "stop_atr": 2.5, "max_days": 15},
             "strength": {"exit": "(bd20 < 0)", "stop_atr": 2.5, "max_days": 40}}
COMPONENTS = [n for n in C.NAMES if n not in C.CALENDAR]
STATE = ("votes", "votes_5d", "votes_other_5d", "breadth")
RECENT = 5
MIN_WIN, MIN_PER_YEAR = 0.45, 20
PENALTIES = (10.0, 100.0, 1000.0, 10000.0)
TREE_DEPTH, TREE_LEAF, TREE_COVER, TREE_ROWS = 3, 0.02, 0.25, 300000


def result_path(universe):
    return os.path.join(OUT, "result_%s.json" % universe)


def load_result(universe):
    path = result_path(universe)
    return json.load(open(path)) if os.path.exists(path) else {}


def save_result(universe, result):
    os.makedirs(OUT, exist_ok=True)
    with open(result_path(universe) + ".tmp", "w") as fh:
        json.dump(result, fh, ensure_ascii=False)
        fh.write("\n")
    os.replace(result_path(universe) + ".tmp", result_path(universe))


def split(m):
    """{family: ids of its systems}, by where they buy on 2006-2016."""
    out = {f: [] for f in FAMILIES}
    for system in X.systems():
        name = X.family(m, system)
        if name:
            out[name].append(system["id"])
    return out


def _recent(fired):
    """Per system, a signal today or on one of the RECENT - 1 days before."""
    out = fired.copy()
    for k in range(1, RECENT):
        out[:, k:] |= fired[:, :-k]
    return out


def state(m, members, others):
    """What the systems say, per instrument-day: the family's signals one by
    one, and the four counts a combination may read."""
    by_id = {s["id"]: s for s in X.systems()}
    own = np.stack([T.flags(m, by_id[x]["entry"]) & m.member for x in members])
    other = np.stack([T.flags(m, by_id[x]["entry"]) & m.member for x in others]) if others else \
        np.zeros((0,) + m.member.shape, dtype=bool)
    votes = own.sum(axis=0)
    candidate = votes > 0
    listed = np.maximum(m.member.sum(axis=1), 1)
    breadth = np.broadcast_to((candidate.sum(axis=1) / listed)[:, None], m.member.shape)
    return {"own": own, "candidate": candidate, "votes": votes,
            "votes_5d": _recent(own).sum(axis=0), "votes_other_5d": _recent(other).sum(axis=0),
            "breadth": breadth}


def names(members):
    return list(STATE) + COMPONENTS + ["fires:" + x for x in members]


def matrix(m, st, tt, jj):
    """The features of the instrument-days (tt, jj), in names() order."""
    cols = [np.asarray(st[k][tt, jj], dtype=np.float32) for k in STATE]
    cols += [m.parts[k][tt, jj] for k in COMPONENTS]
    cols += [st["own"][i, tt, jj].astype(np.float32) for i in range(len(st["own"]))]
    return np.column_stack(cols).astype(np.float32)


def labelled(m, family, st, stage):
    """Every candidate of a stage traded by the template: where (t, j), its
    features, its net result in R."""
    first, last = E.STAGES[stage]
    p = T.prepare(m, {"entry": st["candidate"], **TEMPLATES[family]}, first, last)
    o, h, low, c, atr, lows = p["bars"]
    cfg = T.policy(TEMPLATES[family])
    out = T._each(o, h, low, c, atr, lows, p["leave"], p["dist"], p["sig_j"], p["sig_t"],
                  p["ends"], p["hold"], cfg)
    ok = np.isfinite(out[:, 0])
    tt, jj = p["sig_t"][ok], p["sig_j"][ok]
    price = o[tt + 1, jj]
    r = (out[ok, 0] - 2 * m.cost) / ((price - out[ok, 1]) / price)
    return tt, jj, matrix(m, st, tt, jj), r


def scale(x, model):
    """Features as the linear score reads them: gaps filled with the
    2006-2016 median, centred and scaled on 2006-2016, cut at five."""
    z = np.where(np.isfinite(x), x, np.asarray(model["median"], dtype=np.float32))
    z = (z - np.asarray(model["mean"], dtype=np.float32)) / np.asarray(model["std"], dtype=np.float32)
    return np.clip(z, -5, 5)


def ridge(z, y, penalty):
    a = z.T.astype(np.float64) @ z.astype(np.float64)
    a[np.diag_indices_from(a)] += penalty
    return np.linalg.solve(a, z.T.astype(np.float64) @ (y - y.mean()))


def grow(x, y, depth, min_rows):
    """A regression tree by greedy halving: at each node the feature and
    decile that lower the squared error most."""
    node = {"mean": float(y.mean()), "rows": int(len(y))}
    if depth == 0 or len(y) < 2 * min_rows:
        return node
    best, total, count = None, y.sum(), len(y)
    for f in range(x.shape[1]):
        col = x[:, f]
        for cut in np.unique(np.nanpercentile(col, (10, 20, 30, 40, 50, 60, 70, 80, 90))):
            left = col <= cut
            n = int(left.sum())
            if n < min_rows or count - n < min_rows:
                continue
            s = y[left].sum()
            gain = s * s / n + (total - s) ** 2 / (count - n)
            if best is None or gain > best[0]:
                best = (gain, f, float(cut))
    if best is None:
        return node
    left = x[:, best[1]] <= best[2]
    node.update({"feature": best[1], "cut": best[2],
                 "left": grow(x[left], y[left], depth - 1, min_rows),
                 "right": grow(x[~left], y[~left], depth - 1, min_rows)})
    return node


def leaves(node, path="", out=None):
    out = [] if out is None else out
    if "feature" not in node:
        out.append((path, node["mean"], node["rows"]))
    else:
        leaves(node["left"], path + "L", out)
        leaves(node["right"], path + "R", out)
    return out


def leaf_of(node, x):
    """The leaf each row falls in, as its path of L and R."""
    out = np.full(len(x), "", dtype=object)

    def walk(n, rows, path):
        if "feature" not in n:
            out[rows] = path
            return
        left = x[rows, n["feature"]] <= n["cut"]
        walk(n["left"], rows[left], path + "L")
        walk(n["right"], rows[~left], path + "R")
    walk(node, np.arange(len(x)), "")
    return out


def describe(node, feats, path):
    """A leaf's conditions in words: feature, side, threshold."""
    parts = []
    for step in path:
        parts.append("%s %s %.4g" % (feats[node["feature"]], "<=" if step == "L" else ">", node["cut"]))
        node = node["left"] if step == "L" else node["right"]
    return " & ".join(parts)


def taken(variant, model, x, votes):
    """Which rows a variant takes."""
    if variant["kind"] == "all":
        return np.ones(len(x), dtype=bool)
    if variant["kind"] == "votes":
        return votes >= variant["k"]
    if variant["kind"] == "ridge":
        score = scale(x, model) @ np.asarray(model["weights"], dtype=np.float32)
        return score >= variant["threshold"]
    filled = np.where(np.isfinite(x), x, np.asarray(model["median"], dtype=np.float32))
    return np.isin(leaf_of(model["tree"], filled), variant["leaves"])


def take(m, model, variant):
    """The algorithm's entry signals on a market: a date x instrument array.
    Also returns the state it was read from, for saying which systems agreed."""
    st = state(m, model["members"], model["others"])
    tt, jj = np.nonzero(st["candidate"])
    out = np.zeros(m.member.shape, dtype=bool)
    if len(tt):
        on = taken(variant, model, matrix(m, st, tt, jj), st["votes"][tt, jj])
        out[tt[on], jj[on]] = True
    return out, st


def run(m, family, entry, stage):
    """A variant as a system on a stage: one position per instrument, the
    family's template."""
    first, last = E.STAGES[stage]
    trades = T.simulate(m, {"id": "combined", "entry": entry, **TEMPLATES[family]}, first, last)
    return T.statistics(m, trades, first, last)


def line(name, s):
    if s.get("insufficient"):
        return "  %-34s yetersiz islem (%d)" % (name, s.get("trades", 0))
    return ("  %-34s %6d islem (yilda %4.0f)  kazanan %%%2.0f  R %+5.2f (kazanc %+5.2f, kayip %+5.2f)  "
            "net %+5.2f%%  katki %+5.2f%% (t %+4.1f)  %4.1f gun  stop %%%2.0f"
            % (name, s["trades"], s["per_year"], 100 * s["win_rate"], s["avg_r"], s["avg_win_r"],
               s["avg_loss_r"], 100 * s["expectancy"], 100 * s["edge"], s["t"], s["avg_days"],
               100 * s["stopped"]))


def label_of(v):
    return {"all": "her aday", "votes": "en az %s sistem" % v.get("k"),
            "ridge": "dogrusal skor, ust %%%s" % v.get("top"),
            "tree": "agac, en iyi yapraklar"}[v["kind"]]


def fit(m):
    result = load_result(m.universe)
    if "models" in result:
        raise SystemExit("%s: modeller zaten kuruldu" % m.universe)
    fams = split(m)
    result.update({"families": fams, "models": {}, "discover": {}})
    for family in FAMILIES:
        members, others = fams[family], fams[FAMILIES[1 - FAMILIES.index(family)]]
        if len(members) < 3:
            print("%s %s: ailede %d sistem, birlestirilecek bir sey yok" % (m.universe, family, len(members)))
            continue
        st = state(m, members, others)
        tt, jj, x, r = labelled(m, family, st, "discover")
        feats = names(members)
        low_, high_ = np.percentile(r, (1, 99))
        y = np.clip(r, low_, high_)
        median = np.nanmedian(x, axis=0)
        median = np.where(np.isfinite(median), median, 0).astype(np.float32)
        filled = np.where(np.isfinite(x), x, median)
        std = filled.std(axis=0)
        model = {"family": family, "members": members, "others": others, "features": feats,
                 "median": median.tolist(), "mean": filled.mean(axis=0).tolist(),
                 "std": np.where(std > 0, std, 1).tolist()}
        z = scale(x, model)
        early = np.array([m.dates[t] <= "2012-12-31" for t in tt])
        scores = {}
        for penalty in PENALTIES:
            w = ridge(z[early], y[early], penalty)
            pred = z[~early] @ w
            scores[penalty] = float(np.corrcoef(pred, y[~early])[0, 1]) if pred.std() > 0 else -1.0
        penalty = max(scores, key=scores.get)
        model["penalty"], model["penalty_scores"] = penalty, scores
        model["weights"] = ridge(z, y, penalty).tolist()
        score = z @ np.asarray(model["weights"], dtype=np.float32)
        rng = np.random.default_rng(0)
        rows = rng.choice(len(y), min(len(y), TREE_ROWS), replace=False)
        model["tree"] = grow(filled[rows], y[rows], TREE_DEPTH, int(TREE_LEAF * len(rows)))
        ranked = sorted(leaves(model["tree"]), key=lambda leaf: -leaf[1])
        picked, covered = [], 0
        for path, mean, n in ranked:
            if picked and covered + n > TREE_COVER * len(rows):
                break
            picked.append(path)
            covered += n
        variants = [{"kind": "all"}] + [{"kind": "votes", "k": k} for k in (2, 3, 4)]
        variants += [{"kind": "ridge", "top": 100 - q, "threshold": float(np.percentile(score, q))}
                     for q in (50, 75, 90)]
        variants.append({"kind": "tree", "leaves": picked})
        model["variants"] = variants
        result["models"][family] = model
        print("%s %s: %d sistem, %d aday (2006-2016), ortalama R %+.3f, kazanan %%%.0f; ceza %g"
              % (m.universe, family, len(members), len(r), r.mean(), 100 * (r > 0).mean(), penalty))
        order = np.argsort(-np.abs(model["weights"]))[:12]
        print("  dogrusal skorda en agir: " + ", ".join("%s %+.3f" % (feats[i], model["weights"][i])
                                                          for i in order))
        for path in picked:
            leaf = next(x_ for x_ in ranked if x_[0] == path)
            print("  agac yapragi (R %+.3f, adaylarin %%%.0f'i): %s"
                  % (leaf[1], 100 * leaf[2] / len(rows), describe(model["tree"], feats, path)))
        votes = st["votes"][tt, jj]
        result["discover"][family] = {}
        for i, v in enumerate(variants):
            on = taken(v, model, x, votes)
            entry, _ = take(m, model, v)
            stats = run(m, family, entry, "discover")
            result["discover"][family][str(i)] = stats
            print(line(label_of(v), stats) + "   [adaylarin %%%.0f'i, tek tek R %+.3f]"
                  % (100 * on.mean(), r[on].mean() if on.any() else 0))
    save_result(m.universe, result)


def qualifies(s, base):
    return (not s.get("insufficient") and s["win_rate"] >= MIN_WIN and s["per_year"] >= MIN_PER_YEAR
            and s["edge"] > 0 and not base.get("insufficient") and s["avg_r"] > base["avg_r"])


def choose(m):
    result = load_result(m.universe)
    if "models" not in result:
        raise SystemExit("%s: once `combine.py fit`" % m.universe)
    if "choice" in result:
        raise SystemExit("%s: secim zaten yapildi" % m.universe)
    result["validate"], result["choice"] = {}, {}
    for family, model in result["models"].items():
        print("%s %s, 2017-2021:" % (m.universe, family))
        stats = {}
        for i, v in enumerate(model["variants"]):
            entry, _ = take(m, model, v)
            stats[str(i)] = run(m, family, entry, "validate")
            print(line(label_of(v), stats[str(i)]))
        result["validate"][family] = stats
        fit_ = [i for i in stats if i != "0" and qualifies(stats[i], stats["0"])]
        if fit_:
            best = max(fit_, key=lambda i: stats[i]["avg_r"])
            result["choice"][family] = int(best)
            print("  secilen: %s" % label_of(model["variants"][int(best)]))
        else:
            result["choice"][family] = None
            print("  secilen yok: hicbir varyant kosullari saglamadi")
    save_result(m.universe, result)


def sealed(m):
    result = load_result(m.universe)
    if "choice" not in result:
        raise SystemExit("%s: once `combine.py choose`" % m.universe)
    if "sealed" in result:
        raise SystemExit("%s: muhurlu yillar zaten okundu" % m.universe)
    result["sealed"] = {}
    for family, pick in result["choice"].items():
        if pick is None:
            continue
        model = result["models"][family]
        print("%s %s, 2022-2025:" % (m.universe, family))
        out = {}
        for who, i in (("chosen", pick), ("all", 0)):
            entry, _ = take(m, model, model["variants"][i])
            out[who] = run(m, family, entry, "sealed")
            print(line(label_of(model["variants"][i]), out[who]))
        out["confirmed"] = (not out["chosen"].get("insufficient") and not out["all"].get("insufficient")
                            and out["chosen"]["avg_r"] > out["all"]["avg_r"]
                            and out["chosen"]["expectancy"] > 0)
        result["sealed"][family] = out
    save_result(m.universe, result)


def fundamentals(m):
    """S&P 500 only, and no part of the choice: the chosen algorithm's
    trades of 2017-2025, split by the verdict the company side had given at
    the latest quarter end before the signal."""
    result = load_result(m.universe)
    if "sealed" not in result:
        raise SystemExit("%s: once `combine.py sealed`" % m.universe)
    if "fundamentals" in result:
        raise SystemExit("%s: bilanco ayrimi zaten okundu" % m.universe)
    rows = json.load(open(os.path.join(E.P.OUT, "..", "backtest_rows.json")))
    known = {}
    for r in rows:
        known.setdefault(r["ticker"], []).append((r["asof"], r["verdict"]))
    for v in known.values():
        v.sort()
    result["fundamentals"] = {}
    first, last = E.STAGES["validate"][0], E.STAGES["sealed"][1]
    for family, pick in result["choice"].items():
        if pick is None:
            continue
        model = result["models"][family]
        entry, _ = take(m, model, model["variants"][pick])
        trades = T.simulate(m, {"id": "combined", "entry": entry, **TEMPLATES[family]}, first, last)
        groups, months = {}, {}
        for t in trades:
            seen = [v for asof, v in known.get(t["instrument"], []) if asof <= t["signal"]]
            verdict = seen[-1] if seen else "kayit yok"
            groups.setdefault(verdict, []).append(t)
            side = "good" if verdict == "yatirim yapilabilir" else "rest" if seen else None
            if side:
                months.setdefault(t["entry"][:7], {}).setdefault(side, []).append(t["r"])
        print("%s %s, 2017-2025, bilanco kararina gore:" % (m.universe, family))
        out = {}
        for verdict, ts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            r = np.array([t["r"] for t in ts])
            out[verdict] = {"trades": len(ts), "avg_r": float(r.mean()),
                            "win_rate": float((r > 0).mean()),
                            "net": float(np.mean([t["net"] for t in ts]))}
            print("  %-26s %6d islem  kazanan %%%2.0f  R %+5.2f  net %+5.2f%%"
                  % (verdict, len(ts), 100 * out[verdict]["win_rate"], out[verdict]["avg_r"],
                     100 * out[verdict]["net"]))
        both = [np.mean(v["good"]) - np.mean(v["rest"]) for _, v in sorted(months.items())
                if "good" in v and "rest" in v]
        out["t_good_minus_rest"] = E.newey_west(both, 1)
        print("  'yatirim yapilabilir' eksi digerleri, aylik fark t %+.1f (%d ay)"
              % (out["t_good_minus_rest"] or 0, len(both)))
        result["fundamentals"][family] = out
    save_result(m.universe, result)


def main(argv):
    universe = "sp500"
    if "--universe" in argv:
        i = argv.index("--universe")
        universe, argv = argv[i + 1], argv[:i] + argv[i + 2:]
        if universe not in E.UNIVERSES:
            raise SystemExit("bilinmeyen evren: %s" % universe)
    cmd = argv[1] if len(argv) > 1 else "show"
    if cmd == "show":
        r = load_result(universe)
        print(json.dumps({"choice": r.get("choice"),
                          "variants": {f: [label_of(v) for v in mdl["variants"]]
                                       for f, mdl in r.get("models", {}).items()}},
                         ensure_ascii=False, indent=1))
        return
    start = time.time()
    m = E.Market(universe)
    {"fit": fit, "choose": choose, "sealed": sealed, "fundamentals": fundamentals}.get(cmd, lambda _m: (_ for _ in ()).throw(
        SystemExit("bilinmeyen komut: %s" % cmd)))(m)
    print("%.0f sn" % (time.time() - start))


if __name__ == "__main__":
    main(sys.argv)
