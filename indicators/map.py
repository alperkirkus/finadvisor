"""Which technical indicators say the same thing. See README.md; no return
is read anywhere in this file.

    <research venv>/python -I indicators/map.py <dataset directory>

Needs numpy, scipy, duckdb and TA-Lib, none of which the product uses.
"""
import json
import os
import re
import sys
import warnings
from collections import Counter

import duckdb
import numpy as np
import talib
from scipy.cluster.hierarchy import average, fcluster
from scipy.spatial.distance import squareform
from scipy.stats import rankdata
from talib import abstract

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "indicators")
GROUPS = ("Cycle Indicators", "Momentum Indicators", "Overlap Studies", "Pattern Recognition",
          "Statistic Functions", "Volatility Indicators", "Volume Indicators")
RUNNING_TOTALS = {"AD", "ASI", "NVI", "OBV", "PVI", "PVT", "WAD"}
FIRST, LAST = "2006-01", "2025-12"
MIN_HISTORY = 300
RARE, CUT = 0.99, 0.30
FIELDS = ("open", "high", "low", "close", "volume")


def functions():
    groups = talib.get_function_groups()
    names, skipped = [], []
    for group in GROUPS:
        for name in groups[group]:
            needs = [x for v in abstract.Function(name).info["input_names"].values()
                     for x in (v if isinstance(v, list) else [v])]
            (names if all(x in FIELDS for x in needs) else skipped).append((name, group))
    return names, skipped


def outputs(name, bars):
    """{output label: series} for one function at its defaults."""
    fn = abstract.Function(name)
    got = fn(bars)
    labels = fn.info["output_names"]
    if len(labels) == 1:
        return {name: np.asarray(got, dtype=float)}
    return {"%s.%s" % (name, label): np.asarray(series, dtype=float)
            for label, series in zip(labels, got)}


def degrees(names, bars):
    """{output: (power of price, power of volume) it scales with}."""
    def scaled(price, volume):
        return {k: bars[k] * (volume if k == "volume" else price) for k in FIELDS}

    def power(a, b):
        ok = np.isfinite(a) & np.isfinite(b) & (np.abs(a) > 1e-12)
        if ok.sum() < 20:
            return 0
        return int(round(float(np.median(np.log10(np.abs(b[ok] / a[ok]) + 1e-300)))))
    out = {}
    for name, _ in names:
        base, by_price, by_volume = (outputs(name, scaled(p, v))
                                     for p, v in ((1, 1), (10, 1), (1, 10)))
        for label in base:
            out[label] = (power(base[label], by_price[label]),
                          power(base[label], by_volume[label]))
    return out


def month_ends(dates):
    """Row index of the last bar of each month in the window."""
    last = {}
    for i, d in enumerate(dates):
        last[d[:7]] = i
    return {m: i for m, i in last.items() if FIRST <= m <= LAST}


def companies(theirs):
    """Yields (label, dates, adjusted bars, membership spans) for every
    member with enough daily history."""
    c = duckdb.connect()
    spans = {}
    for label, start, end in c.execute(
            'select ticker, strftime(start, \'%Y-%m-%d\'), strftime("end", \'%Y-%m-%d\') '
            "from read_parquet($1)", [os.path.join(theirs, "membership_intervals.parquet")]).fetchall():
        if start <= LAST + "-31" and (end is None or end >= FIRST + "-01"):
            spans.setdefault(label, []).append((start, end))
    rows = c.execute("""
        select ticker, list(strftime(date, '%Y-%m-%d') order by date),
               list(open order by date), list(high order by date), list(low order by date),
               list(close order by date), list(volume order by date), list(adj_close order by date)
        from read_parquet($1)
        where date >= '2004-01-01' and close > 0 and adj_close > 0 and open > 0
              and high > 0 and low > 0 and volume is not null and ticker in $2
        group by ticker""", [os.path.join(theirs, "prices.parquet"), list(spans)]).fetchall()
    if len(rows) < 500:
        raise ValueError("only %d members have daily bars in %s" % (len(rows), theirs))
    for label, dates, o, h, low, close, vol, adj in rows:
        if len(dates) < MIN_HISTORY + 30:
            continue
        factor = np.asarray(adj, dtype=float) / np.asarray(close, dtype=float)
        yield label, dates, {
            "open": np.asarray(o, dtype=float) * factor, "high": np.asarray(h, dtype=float) * factor,
            "low": np.asarray(low, dtype=float) * factor, "close": np.asarray(adj, dtype=float),
            "volume": np.asarray(vol, dtype=float)}, spans[label]


def comparable(out, series, bars, deg):
    """An output put on a footing that compares across companies (README)."""
    if out.split(".")[0] in RUNNING_TOTALS:
        series = series - np.concatenate([np.full(20, np.nan), series[:-20]])
    usual = talib.SMA(bars["volume"], 20)
    p, v = deg[out]
    with np.errstate(all="ignore"):
        return series / bars["close"] ** p / np.where(usual > 0, usual, np.nan) ** v


def main(theirs):
    os.makedirs(OUT, exist_ok=True)
    warnings.simplefilter("ignore")
    names, skipped = functions()
    deg, order, sample, months = None, None, [], []
    for label, dates, bars, spans in companies(theirs):
        picks = [(m, i) for m, i in sorted(month_ends(dates).items())
                 if i >= MIN_HISTORY and any(s <= dates[i] and (e is None or dates[i] < e)
                                             for s, e in spans)]
        if not picks:
            continue
        if deg is None:
            deg = degrees(names, bars)
            order = sorted(deg)
        idx = [i for _, i in picks]
        block = np.full((len(idx), len(order)), np.nan, dtype=np.float32)
        computed = {}
        for name, _ in names:
            try:
                computed.update(outputs(name, bars))
            except Exception:
                continue
        for j, out in enumerate(order):
            series = computed.get(out)
            if series is None:
                continue
            block[:, j] = comparable(out, series, bars, deg)[idx]
        sample.append(block)
        months += [m for m, _ in picks]

    x = np.vstack(sample)
    x[~np.isfinite(x)] = np.nan
    months = np.asarray(months)
    n_obs = len(x)

    # Rare events first, on the raw values.
    rare, keep = [], []
    for j, out in enumerate(order):
        col = x[:, j][np.isfinite(x[:, j])]
        if len(col) < 0.2 * n_obs:
            rare.append((out, "computed for %.0f%% of observations" % (100 * len(col) / n_obs)))
            continue
        top = Counter(np.round(col, 6).tolist()).most_common(1)[0][1] / len(col)
        (rare.append((out, "one value in %.1f%% of observations" % (100 * top)))
         if top > RARE else keep.append(j))

    ranks = np.full((n_obs, len(keep)), np.nan, dtype=np.float32)
    for m in np.unique(months):
        at = np.where(months == m)[0]
        for k, j in enumerate(keep):
            col = x[at, j]
            ok = np.isfinite(col)
            if ok.sum() >= 20:
                r = rankdata(col[ok])
                ranks[at[ok], k] = (r - r.mean()) / ok.sum()
    present = np.isfinite(ranks)
    z = np.where(present, ranks, 0).astype(np.float64)
    cross = z.T @ z
    squares = (z ** 2).T @ present.astype(np.float64)
    with np.errstate(all="ignore"):
        corr = cross / np.sqrt(squares * squares.T)
    corr[~np.isfinite(corr)] = 0.0
    np.fill_diagonal(corr, 1.0)
    corr = np.clip((corr + corr.T) / 2, -1, 1)
    sim = np.abs(corr)

    labels = [order[j] for j in keep]
    distance = 1 - sim
    np.fill_diagonal(distance, 0.0)
    cluster_of = fcluster(average(squareform(distance, checks=False)), CUT, criterion="distance")
    clusters = []
    for cid in np.unique(cluster_of):
        members = [i for i in range(len(labels)) if cluster_of[i] == cid]
        if len(members) == 1:
            rep, tight = members[0], None
        else:
            score = {i: float(np.mean([sim[i, k] for k in members if k != i])) for i in members}
            rep = sorted(members, key=lambda i: (-round(score[i], 6), len(labels[i]), labels[i]))[0]
            tight = float(np.mean([sim[i, k] for i in members for k in members if i < k]))
        clusters.append({"representative": labels[rep], "size": len(members),
                         "mean_similarity": tight,
                         "members": sorted(labels[i] for i in members)})
    clusters.sort(key=lambda cl: (-cl["size"], cl["representative"]))

    eig = np.sort(np.linalg.eigvalsh(corr))[::-1]
    share = np.cumsum(eig) / eig.sum()
    group_of = {name: group for name, group in names}
    summary = {
        "functions": len(names), "skipped": [n for n, _ in skipped], "outputs": len(order),
        "observations": int(n_obs), "month_ends": int(len(np.unique(months))),
        "companies": len(sample), "mapped": len(labels), "rare": rare,
        "clusters": clusters, "cut": CUT,
        "eigenvalues_above_one": int((eig > 1).sum()),
        "components_for_90pct": int(np.searchsorted(share, 0.90) + 1),
        "first_components_share": [round(float(v), 3) for v in share[:10]],
    }
    json.dump(summary, open(os.path.join(OUT, "map.json"), "w"), indent=1)
    np.save(os.path.join(OUT, "similarity.npy"), sim.astype(np.float32))
    json.dump(labels, open(os.path.join(OUT, "labels.json"), "w"))

    print("%d fonksiyon (%d atlandi: %s), %d cikti" % (len(names), len(skipped),
                                                       " ".join(n for n, _ in skipped), len(order)))
    print("%d gozlem: %d sirket, %d ay sonu" % (n_obs, len(sample), len(np.unique(months))))
    print("%d cikti haritada, %d nadir olay olarak ayrildi" % (len(labels), len(rare)))
    print("%d kume (kesim %.2f); 1'den buyuk ozdeger: %d; varyansin %%90'i icin bilesen: %d"
          % (len(clusters), CUT, summary["eigenvalues_above_one"], summary["components_for_90pct"]))
    print("ilk bilesenlerin kumulatif payi:", summary["first_components_share"])
    big = [cl for cl in clusters if cl["size"] > 1]
    print("\nBirden fazla uyesi olan %d kume (%d cikti):" % (len(big), sum(cl["size"] for cl in big)))
    for cl in big:
        kinds = Counter(group_of[re.split(r"\.", m)[0]].split()[0] for m in cl["members"])
        print("  %-22s %3d uye, ort. benzerlik %.2f  [%s]  %s"
              % (cl["representative"], cl["size"], cl["mean_similarity"],
                 ", ".join("%s %d" % kv for kv in kinds.most_common()),
                 " ".join(cl["members"])[:150]))
    singles = [cl["representative"] for cl in clusters if cl["size"] == 1]
    print("\nTek basina kalan %d cikti: %s" % (len(singles), " ".join(singles)))


if __name__ == "__main__":
    main(sys.argv[1])
