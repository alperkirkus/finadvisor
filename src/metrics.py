"""Deterministic metric and score engine.

Every number an analyst would act on is computed here, in code, from the
canonical panel -- never by the language model. The model's job downstream
is to interpret these values, not to produce them.

Scores implemented: Piotroski F-Score (quality), Altman Z''-Score (distress),
Beneish M-Score (earnings manipulation), plus the standard ratio set.
"""

from datetime import date as _date

TTM = 4  # quarters


def _days(a, b):
    return (_date.fromisoformat(b) - _date.fromisoformat(a)).days


def _sum(panel, dates, key):
    vals = [panel[d].get(key) for d in dates]
    return sum(vals) if all(v is not None for v in vals) else None


def _div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def ttm(panel, date, key, n=TTM):
    """Trailing-n-quarter sum of a flow item ending at `date`.

    The window is the last n quarters that carry the item, and they must be
    consecutive -- spanning about (n - 1) quarters of calendar time. Counting
    panel rows instead let a stray off-quarter date (an acquisition-date
    goodwill balance, say) into the window and blanked every trailing figure
    of the company.
    """
    if panel.get(date, {}).get(key) is None:
        return None
    dates = [d for d in sorted(panel) if d <= date and panel[d].get(key) is not None]
    window = dates[-n:]
    if len(window) < n:
        return None
    span = _days(window[0], window[-1])
    if not (n - 1) * 80 <= span <= (n - 1) * 100:
        return None
    return sum(panel[d][key] for d in window)


def snapshot(panel, date, sec=None):
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
    if op is None and pretax is not None:
        # EBIT = pretax income + interest expense. For a lender, interest is
        # its cost of goods and pretax income is the operating line.
        if sec == "financial" or interest is None:
            op = pretax         # EBT: understates EBIT by the unknown interest
        else:
            op = pretax + abs(interest)
    dep = ttm(panel, date, "depreciation")

    gross = (rev - cogs) if (rev is not None and cogs is not None) else ttm(panel, date, "gross_profit")
    fcf = (cfo - capex) if (cfo is not None and capex is not None) else None
    sbc = ttm(panel, date, "sbc")
    ebitda = (op + dep) if (op is not None and dep is not None) else None
    debt, debt_unknown = _total_debt(g, interest, rev)
    cash_eq = (g("cash") or 0) + (g("short_term_investments") or 0)
    net_debt = debt - cash_eq if debt is not None else None
    wc = _sub(g("current_assets"), g("current_liabilities"))
    # Not every filer tags a pretax total -- some publish only the domestic
    # and foreign components, which must never be summed as if either were
    # the total. Net income plus tax expense reconstructs it from two figures
    # the company did report.
    if pretax is None and ni is not None and tax is not None:
        pretax = ni + tax
    tax_rate = _div(tax, pretax)
    invested = (_add(g("equity"), debt)
                if g("equity") is not None and debt is not None else None)
    nopat = op * (1 - tax_rate) if (op is not None and tax_rate is not None) else None
    # Free cash flow to the firm, the flow a WACC discounts (Damodaran ch.
    # 15; Koller ch. 8). CFO under US GAAP is after interest, so after-tax
    # interest is added back -- otherwise interest is paid twice, once in the
    # flow and once through the net debt subtracted from enterprise value --
    # and stock-based compensation, a real cost that CFO adds back, is
    # deducted.
    t = tax_rate if tax_rate is not None and 0 <= tax_rate <= 0.35 else 0.21
    fcff = (cfo + abs(interest or 0) * (1 - t) - capex - (sbc or 0)
            if (cfo is not None and capex is not None) else None)

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
        "fcff_ttm": fcff, "fcff_margin": _div(fcff, rev),
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

    m["_debt_unknown"] = debt_unknown
    m["_equity_negative"] = not equity_usable
    m["_equity_thin"] = equity_thin

    prior = _prior_year(panel, date)
    if prior:
        m["revenue_growth_yoy"] = _growth(ttm(panel, prior, "revenue"), rev)
        m["net_income_growth_yoy"] = _growth(ttm(panel, prior, "net_income"), ni)
        m["fcf_growth_yoy"] = _growth(_fcf_at(panel, prior), fcf)
    return m


def _total_debt(g, interest, revenue):
    """(total debt, unknown flag) from the debt shapes edgar keeps apart.

    A filer with no debt tag at all is either debt-free or tags its debt in
    a way not covered here. Interest expense tells them apart: with
    negligible interest the debt is taken as zero, with material interest it
    is unknown -- never silently zero, which once valued a REIT carrying
    $26B of notes as debt-free.
    """
    short = g("debt_short")
    if g("debt_current_ltd") is not None:
        current = g("debt_current_ltd") + (short or 0)
    elif g("debt_current_all") is not None:
        current = g("debt_current_all")          # already includes borrowings
    else:
        current = short
    if g("debt_noncurrent") is not None:
        return g("debt_noncurrent") + (current or 0), False
    if g("debt_total") is not None:
        return g("debt_total") + (short or 0), False   # current portion inside
    if g("debt_notes") is not None:
        return g("debt_notes") + (short or 0), False
    if current is not None:
        return current, False
    if g("_debt_ever"):
        return None, True       # it had debt, and the tag has gone quiet
    # No debt tag, but most of the balance sheet funded by long-term
    # liabilities (Ford and Paccar finance arms): debt exists, untagged.
    noncurrent = _sub(g("liabilities"), g("current_liabilities"))
    if noncurrent is not None and g("assets") and noncurrent > 0.35 * g("assets"):
        return None, True
    material = (interest is not None and abs(interest) > 0
                and (revenue is None or abs(interest) > 0.001 * abs(revenue)))
    return (None, True) if material else (0, False)


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
    """The balance-sheet date about `back` quarters before `date`, by
    calendar rather than by row count, for the same reason as `ttm`."""
    target = back * 91
    cands = [d for d in panel if "assets" in panel[d]
             and abs(_days(d, date) - target) <= 35]
    return min(cands, key=lambda d: abs(_days(d, date) - target)) if cands else None


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
    # A missing index enters at its neutral value 1, not 0: dropping it to
    # zero always pulled the score toward "clean".
    m = -4.84 + sum(w * (v if v is not None else 1.0) for w, v in terms.values())
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
                  "fcff_ttm", "fcff_margin",
                  # Deposits and policy liabilities are a financial firm's
                  # raw material; "debt" in the industrial sense is not a
                  # meaningful line for it.
                  "total_debt", "net_debt", "debt_to_equity",
                  "altman_z", "piotroski", "beneish_m",
                  # The same cash-flow swings make accruals and cash
                  # conversion noise for a bank: JPM's CFO / net income
                  # reads -2.5 in a normal year.
                  "accrual_ratio", "cash_conversion"},
    "real_estate": {"gross_margin", "altman_z", "beneish_m",
                    # REITs present an unclassified balance sheet.
                    "current_ratio", "quick_ratio", "working_capital"},
    # Altman Z'' and the current ratio misread a regulated utility: the
    # framework's own section 4 calls Z invalid there, and a 0.6 current
    # ratio is normal for a business with guaranteed cash inflows.
    "utility": {"gross_margin", "altman_z", "current_ratio"},
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
    raw = snapshot(panel, date, sec)
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
