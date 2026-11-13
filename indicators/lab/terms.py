"""Which term carries the result (plan.md, Phase 35).

Every member on every fifth day is bought and held under a neutral exit;
for each of the 36 components the day's members are cut into fifths on it
and the fifths compared. Then the terms that separate on 2006-2015 are
gathered into one composite and tested on what that choice did not see.

    terms.py             # S&P 500, then the composite on 2016-2025 and on mid/small
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import components as C        # noqa: E402
import engine as E            # noqa: E402
import trades as T            # noqa: E402

OUT = os.path.join(E.P.OUT, "terms.json")
TERMS = [n for n in C.NAMES if n not in C.CALENDAR]
HORIZONS = {"10 gun": (2.5, 10), "120 gun": (5.0, 120)}
BLOCKS = ("2006", "2011", "2016", "2021", "2026")
EVERY, MIN_SPREAD = 5, 0.10


def sample(m, first, last, stop, hold):
    """Every member on every EVERY-th day, bought and held: (t, j, net R)."""
    shape = m.member.shape
    pick = m.member & (np.arange(shape[0]) % EVERY == 0)[:, None]
    p = T.prepare(m, {"entry": pick, "exit": None, "max_days": hold}, first, last)
    o, h, low, c, atr, lows = p["bars"]
    out = T._each(o, h, low, c, atr, lows, p["leave"], p["dist"], p["sig_j"], p["sig_t"], p["ends"],
                  p["hold"], T.policy({"stop_atr": stop}))
    ok = np.isfinite(out[:, 0])
    tt, jj = p["sig_t"][ok], p["sig_j"][ok]
    price = o[tt + 1, jj]
    return tt, jj, (out[ok, 0] - 2 * m.cost) / ((price - out[ok, 1]) / price)


def fifths(m, name, tt, jj):
    """The fifth (0..4) each sampled member falls in on that day, by `name`."""
    rank = E._rank(np.asarray(m.parts[name], dtype=np.float32), m.member)[tt, jj]
    return np.where(np.isfinite(rank), np.minimum((rank * 5).astype(int), 4), -1), rank


def block_of(m, tt):
    year = np.array([m.dates[t][:4] for t in tt])
    return np.searchsorted(np.array(BLOCKS[1:-1]), year, side="right")


def table(q, r, block):
    """Mean R by fifth over the span, and the top-minus-bottom spread by block."""
    means = [float(r[q == k].mean()) if (q == k).sum() >= 100 else None for k in range(5)]
    spreads = []
    for b in range(4):
        hi, lo = r[(q == 4) & (block == b)], r[(q == 0) & (block == b)]
        spreads.append(float(hi.mean() - lo.mean()) if len(hi) >= 100 and len(lo) >= 100 else None)
    return means, spreads


def composite(m, chosen, tt, jj):
    parts = []
    for name, sign in chosen:
        _, rank = fifths(m, name, tt, jj)
        parts.append(np.where(np.isfinite(rank), sign * (rank - 0.5), 0.0))
    return np.mean(parts, axis=0)


def by_fifth_of(score, r, tt, block, wanted):
    """Mean R by fifth of `score` within each day, for the blocks in `wanted`."""
    out = {}
    for b in wanted:
        pick = block == b
        q = np.full(pick.sum(), -1)
        days, s = tt[pick], score[pick]
        for day in np.unique(days):
            rows = np.where(days == day)[0]
            if len(rows) >= 50:
                order = s[rows].argsort().argsort()
                q[rows] = np.minimum(order * 5 // len(rows), 4)
        rr = r[pick]
        out[b] = [float(rr[q == k].mean()) for k in range(5)] + [float(rr[q >= 0].mean())]
    return out


def main():
    m = E.Market("sp500")
    result = {"terms": {}, "chosen": []}
    data = {h: sample(m, "2006-01-01", "2025-12-31", *spec) for h, spec in HORIZONS.items()}
    for h, (tt, jj, r) in data.items():
        print("S&P 500, 2006-2025, %s: %d alim, ortalama R %+.3f, kazanan %%%.0f"
              % (h, len(r), r.mean(), 100 * (r > 0).mean()))
    tt, jj, r = data["120 gun"]
    block = block_of(m, tt)
    s_tt, s_jj, s_r = data["10 gun"]
    s_block = block_of(m, s_tt)
    rows = []
    for name in TERMS:
        q, _ = fifths(m, name, tt, jj)
        means, spreads = table(q, r, block)
        sq, _ = fifths(m, name, s_tt, s_jj)
        s_means, s_spreads = table(sq, s_r, s_block)
        rows.append((name, means, spreads, s_means, s_spreads))
        result["terms"][name] = {"long": means, "long_spreads": spreads, "short": s_means,
                                 "short_spreads": s_spreads}
    rows.sort(key=lambda x: -abs((x[1][4] or 0) - (x[1][0] or 0)))
    print("  %-12s | 120 gun: R, en dusuk beste birden en yuksege   fark | fark, blok blok          | 10 gun fark"
          % "kalem")
    for name, means, spreads, s_means, s_spreads in rows:
        print("  %-12s | %s  %+5.2f | %s | %+5.2f" % (
            name, " ".join("%+5.2f" % x for x in means), means[4] - means[0],
            " ".join("  -  " if x is None else "%+5.2f" % x for x in spreads), s_means[4] - s_means[0]))
    chosen = []
    for name, means, spreads, _, _ in rows:
        a, b = spreads[0], spreads[1]
        if a is not None and b is not None and a * b > 0 and min(abs(a), abs(b)) >= MIN_SPREAD:
            chosen.append((name, 1 if a > 0 else -1))
    result["chosen"] = chosen
    print("2006-2015'te iki blokta da ayni yonde en az %.2fR ayiran kalemler: %s"
          % (MIN_SPREAD, ", ".join("%s%s" % ("+" if s > 0 else "-", n) for n, s in chosen) or "yok"))
    if chosen:
        score = composite(m, chosen, tt, jj)
        later = by_fifth_of(score, r, tt, block, (2, 3))
        result["later"] = {str(k): v for k, v in later.items()}
        for b, label in ((2, "2016-2020"), (3, "2021-2025")):
            print("  bilesik skor, S&P 500 %s: R en dusuk beste birden en yuksege %s | tum uyeler %+5.2f"
                  % (label, " ".join("%+5.2f" % x for x in later[b][:5]), later[b][5]))
        E.UNIVERSES.setdefault("midsmall", ("panel_midsmall.npz", 0.002))
        mm = E.Market("midsmall")
        mt, mj, mr = sample(mm, "2011-01-01", "2025-12-31", *HORIZONS["120 gun"])
        mblock = block_of(mm, mt)
        mid = by_fifth_of(composite(mm, chosen, mt, mj), mr, mt, mblock, (1, 2, 3))
        result["midsmall"] = {str(k): v for k, v in mid.items()}
        for b, label in ((1, "2011-2015"), (2, "2016-2020"), (3, "2021-2025")):
            print("  bilesik skor, orta/kucuk %s: R en dusuk beste birden en yuksege %s | tum uyeler %+5.2f"
                  % (label, " ".join("%+5.2f" % x for x in mid[b][:5]), mid[b][5]))
        good = (all(later[b][4] > later[b][0] and later[b][4] > later[b][5] for b in (2, 3))
                and all(mid[b][4] > mid[b][0] and mid[b][4] > mid[b][5] for b in (1, 2, 3)))
        result["counts"] = bool(good)
        print("  sonuc: %s" % ("sayiliyor: en ust dilim her yerde en alt dilimin ve tum uyelerin ustunde"
                               if good else "sayilmiyor"))
    with open(OUT + ".tmp", "w") as fh:
        json.dump(result, fh)
        fh.write("\n")
    os.replace(OUT + ".tmp", OUT)


if __name__ == "__main__":
    main()
