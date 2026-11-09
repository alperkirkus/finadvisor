"""Assembles the deterministic evidence package for one company.

This is the contract handed to the language model. Everything in it is
computed, sourced and checkable; the model adds interpretation on top and
is never asked to produce or recall a number.
"""
import json
import sys

import edgar
import metrics as M

TREND_KEYS = ["revenue_ttm", "net_income_ttm", "fcf_ttm", "ebitda_ttm",
              "net_debt",
              "gross_margin", "operating_margin", "net_margin",
              "fcf_margin", "roe", "roic", "accrual_ratio", "current_ratio",
              "net_debt_to_ebitda", "revenue_growth_yoy",
              "interest_coverage", "cash_conversion"]


def build(ticker, quarters=20, asof=None, facts=None, cik=None):
    """Evidence package. `asof` reconstructs it as of a past date.

    `facts` lets a caller that builds many as-of packages for one company
    load its companyfacts once instead of once per date; `cik` is for a
    ticker the SEC ticker map no longer carries.
    """
    if cik is None:
        cik, _ = edgar.resolve_cik(ticker)
    prof = edgar.profile(cik)
    sec = edgar.sector(prof["sic"])
    if facts is None:
        facts = edgar.companyfacts(cik)
    panel = edgar.panel(facts, asof)
    hist = M.history(panel, sec, quarters)
    if not hist:
        # A normal exception, not SystemExit: callers that score a universe
        # catch Exception, and SystemExit slips past that and kills the run.
        raise ValueError("%s: kullanilabilir donem yok" % ticker)
    latest = hist[-1]

    trends = {}
    for k in TREND_KEYS:
        series = [(h["date"], h["metrics"].get(k)) for h in hist]
        series = [(d, v) for d, v in series if v is not None]
        if len(series) >= 4:
            label, before, recent = _direction([v for _, v in series], k)
            trends[k] = {"series": series, "direction": label,
                         "prior_4q_avg": before, "recent_4q_avg": recent,
                         "polarity": "lower_is_better" if k in LOWER_IS_BETTER
                                     else "higher_is_better"}

    return _round({
        "company": {"ticker": ticker.upper(), "name": prof["name"], "cik": cik,
                    "sic": prof["sic"], "industry": prof["industry"],
                    "sector_bucket": sec},
        "as_of": latest["date"],
        "knowledge_cutoff": asof,
        "periods_available": len(panel),
        "data_coverage": latest["coverage"],
        "data_gaps": latest["missing"],
        "not_applicable_for_sector": latest["not_applicable"],
        "latest_metrics": latest["metrics"],
        "equity_negative": latest["notes"].get("equity_negative", False),
        "equity_thin": latest["notes"].get("equity_thin", False),
        "scores": latest["scores"],
        "trends": trends,
        "source": "SEC EDGAR XBRL companyfacts, forms 10-K/10-Q",
        "disclaimer": ("Bu cikti bir analiz araci ciktisidir, yatirim "
                       "danismanligi veya alim-satim tavsiyesi degildir."),
    })


def _round(obj):
    """Trims float noise. Full XBRL precision is meaningless downstream and
    triples the token cost of the package."""
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 4) if abs(obj) < 1000 else round(obj)
    return obj


# For most metrics rising is better, but not all: a more negative accrual
# ratio means cash flow is outrunning reported profit, and less net debt
# per unit of EBITDA is healthier. Direction is reported as good/bad, so
# these have to be inverted rather than read literally.
LOWER_IS_BETTER = {"accrual_ratio", "net_debt_to_ebitda", "debt_to_equity",
                   "effective_tax_rate"}


def _direction(vals, key=None, window=4):
    """Compares the mean of the last `window` periods with the `window` before.

    Returns the change in quality terms, not in raw sign.
    """
    if len(vals) < window * 2:
        return "insufficient_history", None, None
    recent = sum(vals[-window:]) / window
    before = sum(vals[-window * 2:-window]) / window
    if before == 0:
        return "flat", before, recent
    change = (recent - before) / abs(before)
    if key in LOWER_IS_BETTER:
        change = -change
    label = ("improving" if change > 0.05 else
             "deteriorating" if change < -0.05 else "flat")
    return label, before, recent


def to_markdown(pkg):
    c, out = pkg["company"], []
    out.append("# %s (%s) -- %s" % (c["name"], c["ticker"], pkg["as_of"]))
    out.append("%s | SIC %s | veri kapsami %.0f%% | %d donem"
               % (c["industry"], c["sic"], pkg["data_coverage"] * 100,
                  pkg["periods_available"]))
    out.append("\n## Metrikler (TTM)")
    for k, v in sorted(pkg["latest_metrics"].items()):
        out.append("- %s: %s" % (k, _fmt(k, v)))
    out.append("\n## Skorlar")
    s = pkg["scores"]
    if "piotroski" in s:
        f = s["piotroski"]
        failed = [k for k, v in f["tests"].items() if v == 0]
        out.append("- Piotroski F-Score: %d/%d (basarisiz: %s)"
                   % (f["score"], f["max"], ", ".join(failed) or "yok"))
    if "altman_z" in s and "z_double_prime" in s["altman_z"]:
        z = s["altman_z"]
        out.append("- Altman Z''-Score: %.2f (%s)" % (z["z_double_prime"], z["zone"]))
    if "beneish_m" in s:
        b = s["beneish_m"]
        out.append("- Beneish M-Score: %.2f (%s)"
                   % (b["m_score"], "BAYRAK" if b["flag"] else "temiz"))
    out.append("\n## Trendler (son 4 ceyrek ort. vs onceki 4 ceyrek ort.)")
    for k, t in sorted(pkg["trends"].items()):
        out.append("- %s: %s (%s -> %s)"
                   % (k, t["direction"], _fmt(k, t["prior_4q_avg"]),
                      _fmt(k, t["recent_4q_avg"])))
    if pkg["data_gaps"]:
        out.append("\n## Veri bosluklari\n- " + ", ".join(pkg["data_gaps"]))
    out.append("\n> " + pkg["disclaimer"])
    return "\n".join(out)


def _fmt(key, v):
    if v is None:
        return "n/a"
    if abs(v) > 1e6:
        return "%.2fB" % (v / 1e9)
    if key.endswith(("margin", "_yoy", "ratio")) or key in ("roe", "roa", "roic"):
        return "%.1f%%" % (v * 100)
    return "%.2f" % v


if __name__ == "__main__":
    pkg = build(sys.argv[1] if len(sys.argv) > 1 else "AAPL")
    if "--json" in sys.argv:
        print(json.dumps(pkg, indent=2))
    else:
        print(to_markdown(pkg))
