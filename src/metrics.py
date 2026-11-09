"""Deterministic metric and score engine.

Every number an analyst would act on is computed here, in code, from the
canonical panel -- never by the language model. The model's job downstream
is to interpret these values, not to produce them.

Scores implemented: Piotroski F-Score (quality), Altman Z''-Score (distress),
Beneish M-Score (earnings manipulation), plus the standard ratio set.
"""

TTM = 4  # quarters


def _sum(panel, dates, key):
    vals = [panel[d].get(key) for d in dates]
    return sum(vals) if all(v is not None for v in vals) else None


def _div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def ttm(panel, date, key, n=TTM):
    """Trailing-n-quarter sum of a flow item ending at `date`."""
    dates = sorted(panel)
    i = dates.index(date)
    if i + 1 < n:
        return None
    return _sum(panel, dates[i - n + 1:i + 1], key)


def snapshot(panel, date):
    """All ratios for one period: TTM flows over point-in-time balances."""
    r = panel[date]
    g = r.get
    rev = ttm(panel, date, "revenue")
    ni = ttm(panel, date, "net_income")
    cfo = ttm(panel, date, "cfo")
    capex = ttm(panel, date, "capex")
    op = ttm(panel, date, "operating_income")
    cogs = ttm(panel, date, "cogs")
    tax = ttm(panel, date, "tax")
    pretax = ttm(panel, date, "pretax_income")
    interest = ttm(panel, date, "interest_expense")
    dep = ttm(panel, date, "depreciation")

    gross = (rev - cogs) if (rev is not None and cogs is not None) else ttm(panel, date, "gross_profit")
    fcf = (cfo - capex) if (cfo is not None and capex is not None) else None
    ebitda = (op + dep) if (op is not None and dep is not None) else None
    debt = (g("debt_current") or 0) + (g("debt_noncurrent") or 0)
    cash_eq = (g("cash") or 0) + (g("short_term_investments") or 0)
    net_debt = debt - cash_eq
    wc = _sub(g("current_assets"), g("current_liabilities"))
    # Not every filer tags a pretax total -- some publish only the domestic
    # and foreign components, which must never be summed as if either were
    # the total. Net income plus tax expense reconstructs it from two figures
    # the company did report.
    if pretax is None and ni is not None and tax is not None:
        pretax = ni + tax
    tax_rate = _div(tax, pretax)
    invested = _add(g("equity"), debt) if g("equity") is not None else None
    nopat = op * (1 - tax_rate) if (op is not None and tax_rate is not None) else None

    # Sustained buybacks push book equity to zero or below at a lot of mature
    # US companies. Once it does, any ratio with equity in the denominator
    # stops meaning anything -- McDonald's prints an ROE of -859% and a
    # debt/equity of -39 -- so those are withheld rather than reported as
    # numbers a reader might act on.
    equity = g("equity")
    assets = g("assets")
    eq_to_assets = _div(equity, assets)
    equity_usable = equity is not None and equity > 0
    equity_thin = bool(equity_usable and eq_to_assets is not None
                       and eq_to_assets < 0.10)

    m = {
        "revenue_ttm": rev, "net_income_ttm": ni, "cfo_ttm": cfo, "fcf_ttm": fcf,
        "ebitda_ttm": ebitda, "total_debt": debt, "net_debt": net_debt,
        "working_capital": wc,
        "gross_margin": _div(gross, rev),
        "operating_margin": _div(op, rev),
        "net_margin": _div(ni, rev),
        "fcf_margin": _div(fcf, rev),
        "roe": _div(ni, equity) if equity_usable else None,
        "equity_to_assets": eq_to_assets,
        "roa": _div(ni, g("assets")),
        "roic": _div(nopat, invested),
        "asset_turnover": _div(rev, g("assets")),
        "current_ratio": _div(g("current_assets"), g("current_liabilities")),
        "quick_ratio": _div(_sub(g("current_assets"), g("inventory")), g("current_liabilities")),
        "debt_to_equity": _div(debt, equity) if equity_usable else None,
        "net_debt_to_ebitda": _div(net_debt, ebitda),
        "interest_coverage": _div(op, abs(interest)) if interest else None,
        "effective_tax_rate": tax_rate,
        # Accruals: the gap between reported profit and cash. Sloan (1996)
        # showed a persistently wide gap predicts future underperformance.
        "accrual_ratio": _div(_sub(ni, cfo), g("assets")),
        "cash_conversion": _div(cfo, ni),
    }

    m["_equity_negative"] = not equity_usable
    m["_equity_thin"] = equity_thin

    prior = _prior_year(panel, date)
    if prior:
        m["revenue_growth_yoy"] = _growth(ttm(panel, prior, "revenue"), rev)
        m["net_income_growth_yoy"] = _growth(ttm(panel, prior, "net_income"), ni)
        m["fcf_growth_yoy"] = _growth(_fcf_at(panel, prior), fcf)
    return m


def _sub(a, b):
    return None if a is None or b is None else a - b


def _add(a, b):
    return None if a is None or b is None else a + b


def _growth(old, new):
    if old is None or new is None or old <= 0:
        return None
    return new / old - 1


def _fcf_at(panel, date):
    return _sub(ttm(panel, date, "cfo"), ttm(panel, date, "capex"))


def _prior_year(panel, date, back=4):
    dates = sorted(panel)
    i = dates.index(date)
    return dates[i - back] if i >= back else None


def piotroski(panel, date):
    """F-Score: nine binary quality tests, 0-9. >=7 strong, <=3 weak."""
    prior = _prior_year(panel, date)
    if not prior:
        return None
    now, was = snapshot(panel, date), snapshot(panel, prior)
    r, rp = panel[date], panel[prior]
    ni, cfo = now["net_income_ttm"], now["cfo_ttm"]

    tests = {
        "roa_positive": _pos(now["roa"]),
        "cfo_positive": _pos(cfo),
        "roa_improving": _gt(now["roa"], was["roa"]),
        "accruals_clean": _gt(cfo, ni),                      # cash beats profit
        # Skipped rather than guessed when equity is non-positive in either
        # year: the ratio flips sign and the comparison becomes noise.
        "leverage_falling": _lt(now["debt_to_equity"], was["debt_to_equity"]),
        "liquidity_rising": _gt(now["current_ratio"], was["current_ratio"]),
        "no_dilution": _lte(r.get("shares"), rp.get("shares")),
        "margin_expanding": _gt(now["gross_margin"], was["gross_margin"]),
        "turnover_rising": _gt(now["asset_turnover"], was["asset_turnover"]),
    }
    known = {k: v for k, v in tests.items() if v is not None}
    return {"score": sum(known.values()), "max": len(known), "tests": tests}


def altman_z(panel, date, market_cap=None):
    """Altman Z''-Score (the model variant that needs no market price).

    >2.6 safe, 1.1-2.6 grey, <1.1 distress. When a market cap is supplied
    the original public-manufacturer Z is returned alongside it.
    """
    r = panel[date]
    ta = r.get("assets")
    if not ta:
        return None
    now = snapshot(panel, date)
    tl = r.get("liabilities") or _sub(ta, r.get("equity"))
    ebit = ttm(panel, date, "operating_income")
    out = {}
    zz = _lin(ta, [(6.56, now["working_capital"]), (3.26, r.get("retained_earnings")),
                   (6.72, ebit)])
    bve_tl = _div(r.get("equity"), tl)
    if zz is not None and bve_tl is not None:
        out["z_double_prime"] = zz + 1.05 * bve_tl
        out["zone"] = ("distress" if out["z_double_prime"] < 1.1
                       else "grey" if out["z_double_prime"] < 2.6 else "safe")
    if market_cap:
        z = _lin(ta, [(1.2, now["working_capital"]), (1.4, r.get("retained_earnings")),
                      (3.3, ebit), (1.0, now["revenue_ttm"])])
        if z is not None and tl:
            out["z_original"] = z + 0.6 * market_cap / tl
    return out or None


def beneish_m(panel, date):
    """Beneish M-Score: eight indices flagging earnings manipulation.

    > -1.78 is the classic manipulation flag. It is a screen for aggressive
    accounting, not proof of fraud, and misfires on fast-growing companies.
    """
    prior = _prior_year(panel, date)
    if not prior:
        return None
    n, p = snapshot(panel, date), snapshot(panel, prior)
    rn, rp = panel[date], panel[prior]

    def idx(num_now, den_now, num_was, den_was):
        a, b = _div(num_now, den_now), _div(num_was, den_was)
        return _div(a, b)

    rev_n, rev_p = n["revenue_ttm"], p["revenue_ttm"]
    dsri = idx(rn.get("receivables"), rev_n, rp.get("receivables"), rev_p)
    gmi = _div(p["gross_margin"], n["gross_margin"])
    sgi = _div(rev_n, rev_p)
    # Asset quality: share of assets that is neither PP&E nor current.
    aqi = idx(_soft(rn), rn.get("assets"), _soft(rp), rp.get("assets"))
    dep_n = _div(ttm(panel, date, "depreciation"),
                 _add(ttm(panel, date, "depreciation"), rn.get("ppe")))
    dep_p = _div(ttm(panel, prior, "depreciation"),
                 _add(ttm(panel, prior, "depreciation"), rp.get("ppe")))
    depi = _div(dep_p, dep_n)
    sgai = idx(ttm(panel, date, "sga"), rev_n, ttm(panel, prior, "sga"), rev_p)
    lvgi = idx(rn.get("liabilities"), rn.get("assets"), rp.get("liabilities"), rp.get("assets"))
    tata = _div(_sub(n["net_income_ttm"], n["cfo_ttm"]), rn.get("assets"))

    terms = {"DSRI": (0.920, dsri), "GMI": (0.528, gmi), "AQI": (0.404, aqi),
             "SGI": (0.892, sgi), "DEPI": (0.115, depi), "SGAI": (-0.172, sgai),
             "TATA": (4.679, tata), "LVGI": (-0.327, lvgi)}
    used = {k: v for k, (_, v) in terms.items() if v is not None}
    if len(used) < 6:
        return None
    m = -4.84 + sum(w * v for w, v in terms.values() if v is not None)
    return {"m_score": m, "flag": m > -1.78, "indices": used,
            "components_used": len(used)}


def _soft(row):
    """Assets that are neither current nor PP&E -- the squishy ones."""
    ta = row.get("assets")
    if ta is None:
        return None
    return ta - (row.get("current_assets") or 0) - (row.get("ppe") or 0)


def _lin(scale, pairs):
    total = 0.0
    for w, v in pairs:
        if v is None:
            return None
        total += w * v / scale
    return total


def _pos(x):
    return None if x is None else int(x > 0)


def _gt(a, b):
    return None if a is None or b is None else int(a > b)


def _lt(a, b):
    return None if a is None or b is None else int(a < b)


def _lte(a, b):
    return None if a is None or b is None else int(a <= b)


# A missing number and an inapplicable one are different facts, and the
# analysis layer must not confuse them: a bank has no gross margin by
# construction, while a bank with no ROE is a data gap. Altman and Piotroski
# were both fitted on non-financials and are not transferable.
NOT_APPLICABLE = {
    # Free cash flow is not a meaningful concept for a bank: lending and
    # deposit-taking run through operating and investing cash flows in a way
    # that makes CFO minus capex arbitrary rather than informative.
    "financial": {"gross_margin", "current_ratio", "quick_ratio",
                  "net_debt_to_ebitda", "interest_coverage", "roic",
                  "asset_turnover", "working_capital", "ebitda_ttm",
                  "fcf_ttm", "fcf_margin", "fcf_growth_yoy",
                  "altman_z", "piotroski", "beneish_m",
                  # The same cash-flow swings make accruals and cash
                  # conversion noise for a bank: JPM's CFO / net income
                  # reads -2.5 in a normal year.
                  "accrual_ratio", "cash_conversion"},
    "real_estate": {"gross_margin", "altman_z", "beneish_m"},
    "utility": {"gross_margin"},
    "energy": set(),
}

BANK_METRICS = {
    "net_interest_margin": "NIM -- kredi getirisi eksi mevduat maliyeti",
    "efficiency_ratio": "faaliyet gideri / net gelir",
    "cet1_ratio": "sermaye yeterliligi",
    "npl_ratio": "takipteki krediler",
    "roa": "bankalarda %1+ iyi",
    "roe": "bankalarda %12+ iyi",
}


def analyze(panel, date, sec="other"):
    """Full deterministic read of one period, sector-aware.

    Separates three states per metric: a value, not-applicable for the
    sector, and genuinely missing from the filings.
    """
    na = NOT_APPLICABLE.get(sec, set())
    raw = snapshot(panel, date)
    notes = {k.lstrip("_"): raw.pop(k) for k in list(raw) if k.startswith("_")}
    # Banks and REITs run at 8-12% equity to assets by regulation and by
    # business model, so the thin-equity warning would fire on every healthy
    # one. Non-positive equity still matters everywhere.
    if sec in ("financial", "real_estate"):
        notes["equity_thin"] = False
    values, missing = {}, []
    for k, v in raw.items():
        if k in na:
            continue
        if v is None:
            # Equity-based ratios are withheld by design when book equity is
            # non-positive; that is a stated condition, not a data gap.
            if k in ("roe", "debt_to_equity") and notes.get("equity_negative"):
                continue
            missing.append(k)
        else:
            values[k] = v

    scores = {}
    for name, fn in (("piotroski", piotroski), ("altman_z", altman_z),
                     ("beneish_m", beneish_m)):
        if name in na:
            continue
        try:
            r = fn(panel, date)
        except Exception:
            r = None
        if r is None:
            missing.append(name)
        else:
            scores[name] = r

    return {"date": date, "sector": sec, "metrics": values, "scores": scores,
            "not_applicable": sorted(na), "missing": sorted(missing),
            "notes": notes,
            "coverage": round(len(values) / max(1, len(values) + len(missing)), 2)}


def history(panel, sec="other", quarters=20):
    """The same read across recent periods -- trends are the actual signal."""
    usable = [d for d in sorted(panel)
              if "assets" in panel[d] and "revenue" in panel[d]]
    return [analyze(panel, d, sec) for d in usable[-quarters:]]
