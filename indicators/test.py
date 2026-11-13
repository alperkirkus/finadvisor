"""Tests the cluster representatives of the indicator map. The rules are in
README.md ("The test") and nothing here chooses among them.

    <research venv>/python -I indicators/test.py <dataset directory>
"""
import json
import os
import sys
import warnings
from datetime import date, timedelta

import numpy as np
from scipy.stats import rankdata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map as IM              # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import multitest as M         # noqa: E402

WINDOWS = [("2006-2012", "2006-01", "2012-12"), ("2013-2019", "2013-01", "2019-12"),
           ("2020-2025", "2020-01", "2025-12")]
FIRST, LAST = "2006-03", "2025-09"
FALL, CALM = -0.25, 0.35
MIN_NAMES, MIN_FALLS = 20, 3


def tiers():
    clusters = json.load(open(os.path.join(IM.OUT, "map.json")))["clusters"]
    one = [c["representative"] for c in clusters if c["size"] >= 4]
    two = [c["representative"] for c in clusters
           if c["size"] < 4 and not all(m.startswith("CDL") for m in c["members"])]
    return one, two


def repaints(out, bars):
    """Does the output's value on a past day change when later bars arrive?"""
    name = out.split(".")[0]
    full = IM.outputs(name, bars)[out]
    n = len(full)
    for i in range(n - 400, n - 30, 37):
        cut = IM.outputs(name, {k: v[:i + 1] for k, v in bars.items()})[out][-1]
        a, b = full[i], cut
        if np.isfinite(a) != np.isfinite(b):
            return True
        if np.isfinite(a) and abs(a - b) > 1e-6 * max(1.0, abs(a)):
            return True
    return False


def quarter_ends(dates):
    last = {}
    for i, d in enumerate(dates):
        if d[5:7] in ("03", "06", "09", "12"):
            last[d[:7]] = i
    return {m: i for m, i in last.items() if FIRST <= m <= LAST}


def forward(dates, ordinals, close, i, days):
    """Return from bar i to the last bar on or before `days` later: a company
    that has stopped trading is held at its last price."""
    j = int(np.searchsorted(ordinals, ordinals[i] + days, side="right")) - 1
    return close[j] / close[i] - 1


def newey_west(series, lag):
    x = np.asarray(series, dtype=float)
    n = len(x)
    if n < 8:
        return None
    dev = x - x.mean()
    var = float(dev @ dev) / n
    for k in range(1, lag + 1):
        var += 2 * (1 - k / (lag + 1)) * float(dev[k:] @ dev[:-k]) / n
    se = np.sqrt(max(var, 0) / n)
    return (float(x.mean()), float(x.mean() / se)) if se > 0 else None


def auc(values, falls):
    """P(a company that fell had the higher value); 0.5 is no information."""
    r = rankdata(values)
    pos = falls.sum()
    return (r[falls].sum() - pos * (pos + 1) / 2) / (pos * (len(values) - pos))


def spearman(a, b):
    ra, rb = rankdata(a), rankdata(b)
    ra, rb = ra - ra.mean(), rb - rb.mean()
    den = np.sqrt((ra @ ra) * (rb @ rb))
    return float(ra @ rb / den) if den > 0 else None


def statistics(by_month, column, months, calm_only=False):
    """{statistic: (mean, t, dates)} for one candidate over the given months."""
    fall, ic12, ic1 = [], [], []
    for m in months:
        x, r12, r1, vol = by_month[m]
        v = x[:, column]
        ok = np.isfinite(v) & np.isfinite(r12)
        if calm_only:
            ok &= np.isfinite(vol) & (vol < CALM)
        if ok.sum() < MIN_NAMES:
            continue
        fell = r12[ok] < FALL
        if MIN_FALLS <= fell.sum() < ok.sum():
            fall.append(auc(v[ok], fell) - 0.5)
        a = spearman(v[ok], r12[ok])
        if a is not None:
            ic12.append(a)
        ok1 = ok & np.isfinite(r1)
        b = spearman(v[ok1], r1[ok1]) if ok1.sum() >= MIN_NAMES else None
        if b is not None:
            ic1.append(b)
    out = {}
    for key, series, lag in (("fall", fall, 3), ("ic12", ic12, 3), ("ic1", ic1, 0)):
        nw = newey_west(series, lag)
        out[key] = None if nw is None else (nw[0], nw[1], len(series))
    return out


def main(theirs):
    warnings.simplefilter("ignore")
    one, two = tiers()
    names, _ = IM.functions()
    deg, dropped, candidates = None, [], None
    rows = {}
    for label, dates, bars, spans in IM.companies(theirs):
        if deg is None:
            deg = IM.degrees(names, bars)
            dropped = [c for c in one + two if repaints(c, bars)]
            candidates = [c for c in one + two if c not in dropped]
        picks = [(m, i) for m, i in sorted(quarter_ends(dates).items())
                 if i >= IM.MIN_HISTORY and any(s <= dates[i] and (e is None or dates[i] < e)
                                                for s, e in spans)]
        if not picks:
            continue
        ordinals = np.array([date.fromisoformat(d).toordinal() for d in dates])
        close = bars["close"]
        computed = {}
        for name in sorted({c.split(".")[0] for c in candidates}):
            try:
                computed.update(IM.outputs(name, bars))
            except Exception:
                continue
        series = {c: IM.comparable(c, computed[c], bars, deg) for c in candidates if c in computed}
        for m, i in picks:
            monthly = [close[int(np.searchsorted(ordinals, ordinals[i] - 30 * k, side="right")) - 1]
                       for k in range(13)]
            changes = np.diff(np.log(monthly[::-1]))
            vol = float(np.std(changes, ddof=1) * np.sqrt(12))
            rows.setdefault(m, []).append((
                [series[c][i] if c in series else np.nan for c in candidates],
                forward(dates, ordinals, close, i, 365), forward(dates, ordinals, close, i, 30), vol))
    by_month = {}
    for m, obs in rows.items():
        x = np.array([o[0] for o in obs], dtype=float)
        x[~np.isfinite(x)] = np.nan
        by_month[m] = (x, np.array([o[1] for o in obs]), np.array([o[2] for o in obs]),
                       np.array([o[3] for o in obs]))
    months = sorted(by_month)
    if len(months) < 60:
        raise ValueError("only %d quarter ends in %s" % (len(months), theirs))
    vol_stats = statistics({m: (np.column_stack([v[3]]), v[1], v[2], v[3])
                            for m, v in by_month.items()}, 0, months)

    results = []
    for column, c in enumerate(candidates):
        whole = statistics(by_month, column, months)
        parts = [statistics(by_month, column, [m for m in months if a <= m <= b])
                 for _, a, b in WINDOWS]
        calm = statistics(by_month, column, months, calm_only=True)
        row = {"candidate": c, "tier": 1 if c in one else 2}
        for key in ("fall", "ic12", "ic1"):
            w = whole[key]
            signs = [None if p[key] is None else p[key][0] > 0 for p in parts]
            row[key] = None if w is None else {
                "mean": w[0], "t": w[1], "dates": w[2],
                "windows": [None if p[key] is None else round(p[key][0], 4) for p in parts],
                "one_sign": None not in signs and len(set(signs)) == 1}
        row["fall_calm"] = None if calm["fall"] is None else {"mean": calm["fall"][0],
                                                               "t": calm["fall"][1]}
        results.append(row)

    line = M.t_of(M.ALPHA / (3 * len([c for c in candidates if c in one])))
    flat = [(r, key) for r in results if r["tier"] == 2 for key in ("fall", "ic12", "ic1")
            if r[key] is not None]
    _, _, bhy = M.adjust([M.p_value(r[key]["t"]) for r, key in flat], len(flat))
    for (r, key), p in zip(flat, bhy):
        r[key]["bhy"] = p

    names_tr = {"fall": "dusus riski (AUC-0.5)", "ic12": "getiri 12 ay (IC)", "ic1": "getiri 1 ay (IC)"}
    print("%d ceyrek sonu, tarih basina ortalama %d sirket" % (len(months), np.mean([len(v[1]) for v in by_month.values()])))
    print("Yeniden boyandigi icin cikarilan: %s" % (" ".join(dropped) or "-"))
    print("Olcek icin, son 12 ayin oynakligi: %s"
          % ", ".join("%s %+.3f (t %.1f)" % (names_tr[k].split(" (")[0], vol_stats[k][0], vol_stats[k][1])
                      for k in ("fall", "ic12", "ic1")))
    print("\nKADEME 1 -- %d aday x 3 = %d test, Bonferroni |t| >= %.2f ve uc pencerede tek isaret"
          % (len([r for r in results if r["tier"] == 1]), 3 * len([r for r in results if r["tier"] == 1]), line))
    for r in results:
        if r["tier"] != 1:
            continue
        for key in ("fall", "ic12", "ic1"):
            s = r[key]
            if s is None:
                print("  %-16s %-22s yetersiz" % (r["candidate"], names_tr[key]))
                continue
            passed = abs(s["t"]) >= line and s["one_sign"]
            extra = ""
            if key == "fall" and r["fall_calm"]:
                same = (r["fall_calm"]["mean"] > 0) == (s["mean"] > 0)
                extra = " | sakin isimlerde %+.3f (t %.1f)%s" % (
                    r["fall_calm"]["mean"], r["fall_calm"]["t"],
                    "" if not passed else " -> risk okumasina girer" if same and abs(r["fall_calm"]["t"]) >= 2
                    else " -> oynakligin otesinde degil")
            print("  %-16s %-22s %+.3f (t %+5.1f)  pencereler %s  %s%s"
                  % (r["candidate"], names_tr[key], s["mean"], s["t"],
                     " ".join("%+.3f" % w if w is not None else "  -  " for w in s["windows"]),
                     "GECTI" if passed else "kaldi", extra))
    found = [(r, key) for r, key in flat if r[key]["bhy"] < M.ALPHA and r[key]["one_sign"]]
    print("\nKADEME 2 -- %d aday, %d istatistik (kesif); BHY p < 0.05 ve tek isaret: %d"
          % (len([r for r in results if r["tier"] == 2]), len(flat), len(found)))
    for r, key in sorted(found, key=lambda rk: rk[0][rk[1]]["bhy"]):
        s = r[key]
        print("  %-22s %-22s %+.3f (t %+5.1f, BHY p %.4f)  pencereler %s"
              % (r["candidate"], names_tr[key], s["mean"], s["t"], s["bhy"],
                 " ".join("%+.3f" % w if w is not None else "  -  " for w in s["windows"])))
    json.dump({"quarter_ends": len(months), "dropped": dropped, "bonferroni_t": line,
               "volatility": {k: v and list(v) for k, v in vol_stats.items()},
               "results": results},
              open(os.path.join(IM.OUT, "test.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
