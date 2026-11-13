"""What is left of the measured results once the number of tests is counted.

Several hundred signal, horizon and universe combinations were tried, so a
t of 2 on one of them is expected by chance. This adjusts every recorded
rank-IC t for that (Bonferroni, Holm, Benjamini-Hochberg-Yekutieli) and
states each as the t it is worth afterwards (Harvey & Liu 2015), and
deflates the strategy Sharpe ratios for the variants run (Bailey & Lopez de
Prado 2014). Pre-registered in plan.md (Phase 12); nothing here re-tunes
anything.

    python src/multitest.py
"""
import json
import math
import os
from statistics import NormalDist

import strategy as S

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
STATED_TRIALS = 300      # combinations the README says were tried
ALPHA = 0.05
EULER = 0.5772156649015329
N = NormalDist()

FILES = [("S&P 500", "backtest_summary.json"), ("mid/small", "backtest_summary_midsmall.json"),
         ("S&P 500", "earnings_summary.json"), ("mid/small", "earnings_summary_midsmall.json"),
         ("S&P 500", "shorts_summary.json"), ("mid/small", "shorts_summary_midsmall.json")]

# Tests the README reports whose t is not stored in any summary file (the
# 2020-2025 window is printed, never saved; the within-financials test has
# no section of its own). Added to the family with the t the README states.
README_ONLY = [
    ("S&P 500", "financials/valuation/12/2013-2019", 2.6),
    ("S&P 500", "financials/valuation/12/2020-2025", 2.5),
    ("mid/small", "financials/valuation/12/2013-2019", 1.5),
    ("mid/small", "financials/valuation/12/2020-2025", 5.4),
    ("S&P 500", "net_issuance/12/2020-2025", -3.1),
    ("mid/small", "net_issuance/12/2020-2025", -2.9),
    # Phase 17, sector fair values (within-sector IC; cells with 20 names)
    ("S&P 500", "utility/justified_pb/12/2013-2019", -0.4),
    ("S&P 500", "utility/justified_pb/12/2020-2025", -2.3),
    ("mid/small", "utility/justified_pb/12/2020-2025", -0.2),
    ("S&P 500", "real_estate/ev_ebitda/12/2013-2019", 0.2),
    ("S&P 500", "real_estate/ev_ebitda/12/2020-2025", 0.5),
    ("mid/small", "real_estate/ev_ebitda/12/2020-2025", -0.7),
]
NAMED = ["financials/valuation", "net_issuance/12", "ic/dev/12/net_issuance",
         "dev/sue", "holdout/sue", "dtc_1m", "dtc_3m"]


def _walk(node, path=()):
    if isinstance(node, dict):
        if "mean_ic" in node and node.get("nw_t") is not None:
            yield "/".join(path), node["nw_t"]
        for key, value in node.items():
            yield from _walk(value, path + (str(key),))


def family():
    """[(universe, test, t)] for every rank IC on record."""
    tests = []
    for universe, name in FILES:
        found = list(_walk(json.load(open(os.path.join(DATA, name)))))
        if not found:
            raise ValueError("no rank-IC t in %s" % name)
        tests += [(universe, path, t) for path, t in found]
    tests += README_ONLY
    for _, path, t in tests:
        if not math.isfinite(t):
            raise ValueError("non-finite t for %s" % path)
    return tests


def p_value(t):
    # erfc keeps the tail: through the normal CDF a t of 9 rounds to p = 0.
    return math.erfc(abs(t) / math.sqrt(2))


def t_of(p):
    """The |t| a two-sided p corresponds to; 0 when nothing is left."""
    return -N.inv_cdf(p / 2) if p < 1 else 0.0


def adjust(ps, trials):
    """Bonferroni, Holm and BHY adjusted p for each p, in the given order.

    Bonferroni and Holm count `trials` tests, of which only len(ps) left a
    record; ranking the recorded ones as if the rest were all weaker makes
    Holm's multipliers larger, never smaller. BHY runs on the recorded ones.
    """
    n = len(ps)
    order = sorted(range(n), key=lambda i: ps[i])
    bonferroni = [min(1.0, p * trials) for p in ps]
    holm, running = [0.0] * n, 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (trials - rank) * ps[i]))
        holm[i] = running
    harmonic = sum(1 / k for k in range(1, n + 1))
    bhy, running = [0.0] * n, 1.0
    for rank in range(n - 1, -1, -1):
        i = order[rank]
        running = min(running, ps[i] * n * harmonic / (rank + 1))
        bhy[i] = running
    return bonferroni, holm, bhy


def moments(xs):
    n = len(xs)
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    skew = sum(((x - mean) / sd) ** 3 for x in xs) / n
    kurt = sum(((x - mean) / sd) ** 4 for x in xs) / n
    return mean, sd, skew, kurt


def deflated_sharpe(excess, trial_sharpes):
    """(Sharpe per period, the Sharpe the best of that many unskilled trials
    would be expected to show, probability the true Sharpe exceeds it)."""
    mean, sd, skew, kurt = moments(excess)
    sr, trials = mean / sd, len(trial_sharpes)
    m = sum(trial_sharpes) / trials
    spread = math.sqrt(sum((x - m) ** 2 for x in trial_sharpes) / (trials - 1))
    hurdle = spread * ((1 - EULER) * N.inv_cdf(1 - 1 / trials)
                       + EULER * N.inv_cdf(1 - 1 / (trials * math.e)))
    z = ((sr - hurdle) * math.sqrt(len(excess) - 1)
         / math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    return sr, hurdle, N.cdf(z)


def main():
    tests = family()
    trials = max(len(tests), STATED_TRIALS)
    ps = [p_value(t) for _, _, t in tests]
    bonferroni, holm, bhy = adjust(ps, trials)
    rows = [{"universe": u, "test": path, "t": t, "p": p, "bonferroni": b, "holm": h, "bhy": y,
             "t_after": {"bonferroni": t_of(b), "holm": t_of(h), "bhy": t_of(y)}}
            for (u, path, t), p, b, h, y in zip(tests, ps, bonferroni, holm, bhy)]
    print("Aile: %d kayitli test (M = %d). |t| >= 2 olan: %d; sansla beklenen: %.0f"
          % (len(tests), trials, sum(abs(r["t"]) >= 2 for r in rows),
             len(tests) * p_value(2)))
    print("Bonferroni esigi |t| >= %.2f" % t_of(ALPHA / trials))
    for name, key in (("Bonferroni", "bonferroni"), ("Holm", "holm"), ("BHY", "bhy")):
        print("  %-10s p < %.2f: %d test" % (name, ALPHA, sum(r[key] < ALPHA for r in rows)))
    print("\nBHY'den gecenler:")
    for r in sorted((r for r in rows if r["bhy"] < ALPHA), key=lambda r: r["p"]):
        print("  %-9s %-44s t %+5.2f  BHY p %.4f  duzeltilmis t %.2f"
              % (r["universe"], r["test"], r["t"], r["bhy"], r["t_after"]["bhy"]))
    print("\nAdi gecen iddialar (t -> Bonferroni / Holm / BHY sonrasi t):")
    for r in rows:
        if any(r["test"].startswith(n) or r["test"].endswith(n) for n in NAMED):
            print("  %-9s %-36s t %+5.2f -> %4.2f / %4.2f / %4.2f   BHY p %.3f %s"
                  % (r["universe"], r["test"], r["t"], r["t_after"]["bonferroni"],
                     r["t_after"]["holm"], r["t_after"]["bhy"], r["bhy"],
                     "GECTI" if r["bhy"] < ALPHA else "kaldi"))

    rets, _, _ = S.run()
    variants = ("A", "A_no_regime", "B", "SPY_regime")
    excess = {k: [r - tb for month, r, tb in rets[k] if "2006-01" <= month <= "2025-12"]
              for k in variants}
    sharpes = [moments(x)[0] / moments(x)[1] for x in excess.values()]
    strategies = {}
    print("\nDeflated Sharpe (aylik getiriler, %d varyant):" % len(variants))
    for k in ("SPY_regime", "A", "B"):
        sr, hurdle, prob = deflated_sharpe(excess[k], sharpes)
        strategies[k] = {"months": len(excess[k]), "sharpe_annual": sr * math.sqrt(12),
                         "hurdle_annual": hurdle * math.sqrt(12), "dsr": prob}
        print("  %-11s %3d ay  Sharpe %.2f  sansin en iyisi icin beklenen %.2f  DSR %.3f"
              % (k, len(excess[k]), sr * math.sqrt(12), hurdle * math.sqrt(12), prob))
    json.dump({"family": len(tests), "trials": trials, "alpha": ALPHA,
               "bonferroni_t": t_of(ALPHA / trials), "tests": rows, "strategies": strategies},
              open(os.path.join(DATA, "multitest_summary.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
