"""Data-quality harness for the ingest layer.

Every check here compares derived numbers against something the company
itself reported, so a broken tag chain or a wrong period subtraction shows
up as a failure instead of a plausible-looking wrong answer. Run it after
touching edgar.py.
"""
import sys

import edgar
import metrics as M

UNIVERSE = ["AAPL", "MSFT", "JPM", "XOM", "WMT", "PFE", "F", "NEE",
            "BA", "T", "TSLA", "NVDA", "KO", "JNJ", "CAT",
            # Negative or near-zero book equity from sustained buybacks --
            # the case that silently corrupts every equity ratio.
            "MCD", "SBUX", "HD"]

FLOWS = ["revenue", "net_income", "cfo", "operating_income"]


def check_period_arithmetic(panel, tol=0.02, recent=12):
    """Four derived quarters must reconstruct the reported fiscal year.

    This is the load-bearing check on the period arithmetic. It has one
    unavoidable false positive: when a company divests a segment, the 10-K
    restates the prior fiscal year to exclude it while the original 10-Q
    quarters keep their as-filed values, so the sum legitimately disagrees.
    That is a property of the source data, not a bug, and it is reported
    separately -- but in the periods an analysis actually uses, any drift is
    treated as a failure.
    """
    issues, historical = [], []
    dates = sorted(panel)
    cutoff = dates[-recent] if len(dates) > recent else dates[0]
    for key in FLOWS:
        for d in dates:
            annual = panel[d].get(key + "_fy")
            if annual is None or abs(annual) < 1e6:
                continue
            i = dates.index(d)
            if i < 3:
                continue
            quarters = [panel[q].get(key) for q in dates[i - 3:i + 1]]
            if any(q is None for q in quarters):
                continue
            drift = abs(sum(quarters) - annual) / abs(annual)
            if drift > tol:
                msg = ("%s %s: 4 ceyrek toplami %.1fB, raporlanan yil %.1fB (sapma %.1f%%)"
                       % (d, key, sum(quarters) / 1e9, annual / 1e9, drift * 100))
                (issues if d >= cutoff else historical).append(msg)
    if historical:
        issues.append("%d eski donemde yeniden duzenleme kaynakli sapma (analiz penceresi disi)"
                      % len(historical))
    return issues


def check_balance_sheet_identity(panel, tol=0.02):
    """Assets = liabilities + equity, allowing for noncontrolling interest.

    `equity` resolves to the parent-only figure when available, so the
    identity can legitimately fall short by the minority stake -- but never
    overshoot, and never by a large margin.
    """
    issues = []
    for d, r in panel.items():
        a, l, e = r.get("assets"), r.get("liabilities"), r.get("equity")
        if None in (a, l, e) or a == 0:
            continue
        gap = (a - l - e) / a
        if gap < -tol:
            issues.append("%s: varlik < borc + ozsermaye (%.1f%%)" % (d, gap * 100))
        elif gap > 0.25:
            issues.append("%s: varlik ile borc+ozsermaye arasi %.1f%% fark -- "
                          "azinlik payi icin fazla buyuk" % (d, gap * 100))
    return issues


def check_signs(panel):
    """Quantities that cannot be negative in a well-formed filing."""
    issues = []
    for d, r in panel.items():
        for key in ("assets", "current_assets", "inventory", "ppe", "goodwill"):
            v = r.get(key)
            if v is not None and v < 0:
                issues.append("%s: %s negatif (%.1fB)" % (d, key, v / 1e9))
        capex = r.get("capex")
        if capex is not None and capex < 0:
            issues.append("%s: capex negatif (%.1fB) -- isaret konvansiyonu ters"
                          % (d, capex / 1e9))
    return issues


def check_equity_quality(panel, sector="other"):
    """Flags dates where equity-based ratios would be meaningless.

    Not a bug in the pipeline -- a property of the filer -- but it has to be
    detected, because a negative denominator produces a plausible-looking
    number rather than an error.
    """
    issues = []
    dates = sorted(d for d in panel if "equity" in panel[d] and "assets" in panel[d])
    for d in dates[-4:]:
        eq, a = panel[d]["equity"], panel[d]["assets"]
        if not a:
            continue
        ratio = eq / a
        if ratio <= 0:
            issues.append("%s: ozsermaye negatif (%.1f%% varlik) -- roe/d2e "
                          "cekilmeli" % (d, ratio * 100))
        elif ratio < 0.10 and sector not in ("financial", "real_estate"):
            issues.append("%s: ozsermaye cok ince (%.1f%% varlik) -- roe sisik"
                          % (d, ratio * 100))
    return issues


def check_continuity(panel, max_gap_days=200):
    """Quarters should be roughly evenly spaced with no long holes."""
    dates = sorted(d for d in panel if "revenue" in panel[d])
    issues = []
    for a, b in zip(dates, dates[1:]):
        gap = edgar._days(a, b)
        if gap > max_gap_days:
            issues.append("%s -> %s arasi %d gun bosluk" % (a, b, gap))
    return issues


def run(tickers=None):
    tickers = tickers or UNIVERSE
    total_fail = 0
    print("%-6s %-13s %5s %6s  %s" % ("TICK", "sektor", "cyrk", "kapsam", "sorunlar"))
    for t in tickers:
        try:
            cik, _ = edgar.resolve_cik(t)
            prof = edgar.profile(cik)
            sec = edgar.sector(prof["sic"])
            panel = edgar.panel(edgar.companyfacts(cik))
        except Exception as exc:
            print("%-6s HATA: %s" % (t, exc))
            total_fail += 1
            continue

        usable = [d for d in sorted(panel)
                  if "assets" in panel[d] and "revenue" in panel[d]]
        issues = (check_period_arithmetic(panel)
                  + check_balance_sheet_identity(panel)
                  + check_signs(panel)
                  + check_equity_quality(panel, sec)
                  + check_continuity(panel))
        cov = M.analyze(panel, usable[-1], sec)["coverage"] if usable else 0.0
        if cov < 0.80:
            issues.append("kapsam %.0f%% -- esigin altinda" % (cov * 100))

        total_fail += len(issues)
        print("%-6s %-13s %5d %5.0f%%  %s"
              % (t, sec, len(usable), cov * 100,
                 "temiz" if not issues else "%d sorun" % len(issues)))
        for line in issues[:4]:
            print("           - %s" % line)
        if len(issues) > 4:
            print("           - ... %d tane daha" % (len(issues) - 4))

    print("\ntoplam sorun: %d" % total_fail)
    return total_fail


if __name__ == "__main__":
    sys.exit(1 if run(sys.argv[1:] or None) else 0)
