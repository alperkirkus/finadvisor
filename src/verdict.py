"""Investability verdict and next-quarter projection.

Four pillars are scored independently -- quality, safety, earnings quality,
valuation -- and the verdict is a function of all four rather than an
average, because a failure in safety or earnings quality is not something a
cheap price compensates for.

Two states matter as much as the verdict itself: when the valuation model
does not apply to a company (little or no free cash flow to discount), and
when the data is too thin to judge. Both are reported as such instead of
being coerced into a number.
"""

import json
import os

import interpret

SUMMARY_PATH = os.path.join(os.path.dirname(__file__), "..", "data",
                            "backtest_summary.json")


def _summary():
    if not hasattr(_summary, "cache"):
        try:
            _summary.cache = json.load(open(SUMMARY_PATH))
        except Exception:
            _summary.cache = None
    return _summary.cache


def _backtest_stat(name):
    """Pulls one cohort's measured statistics from the saved backtest."""
    summary = _summary()
    if not summary:
        return None
    for c in summary.get("cohorts", []):
        if c["name"] == name and not c.get("insufficient"):
            return c
    return None


HIGH_VOLATILITY = 0.35

# Fair-value upside bands; the backtest tabulates outcomes per band.
UPSIDE_BANDS = [(-9.0, -0.30, "pahalı (−%30 altı)"),
                (-0.30, -0.10, "biraz pahalı (−%30…−%10)"),
                (-0.10, 0.10, "adil (±%10)"),
                (0.10, 0.30, "ucuz (+%10…+%30)"),
                (0.30, 9.0, "çok ucuz (+%30 üstü)")]
FV_HORIZONS = (12, 24, 36)


def upside_band(upside):
    if upside is None:
        return None
    for lo, hi, name in UPSIDE_BANDS:
        if lo <= upside < hi:
            return name
    return None


def _horizon_label(cell):
    """olumlu / olumsuz only when the band's excess return is both sizeable
    and statistically distinguishable from zero; otherwise belirsiz."""
    if not cell or cell.get("t") is None:
        return "belirsiz"
    if cell["mean_excess"] >= 0.02 and cell["t"] >= 2:
        return "olumlu"
    if cell["mean_excess"] <= -0.02 and cell["t"] <= -2:
        return "olumsuz"
    return "belirsiz"


def fair_value_read(val):
    """What happened, historically, after the system gave a target like this one.

    The fair value is an estimate from the company's own history. This puts
    next to it the measured record of such estimates: for S&P 500 members
    whose upside fell in the same band, how often the price reached the
    target within one, two and three years, and how they did against the
    average member -- labelled olumlu or olumsuz only where the difference
    is significant.
    """
    upside = (val or {}).get("upside_to_fair")
    pvf = (val or {}).get("price_vs_fair")
    table = (_summary() or {}).get("fair_value_table")
    method = "bank" if (val or {}).get("bank") else "reversion"
    bands = ((table or {}).get("methods") or {}).get(method) or {}
    band = upside_band(upside)
    if band is None or not pvf or not bands.get(band):
        return None
    cells = bands[band]
    if str(FV_HORIZONS[0]) not in cells:
        return None
    labels = {h: _horizon_label(cells.get(str(h))) for h in FV_HORIZONS}
    final = labels[FV_HORIZONS[-1]]
    tone = {"olumlu": "good", "olumsuz": "critical", "belirsiz": "neutral"}[final]
    parts, hits = [], []
    for h in FV_HORIZONS:
        c = cells.get(str(h))
        if not c:
            continue
        parts.append("%d yıl: %s (evrene göre %+.1f%%)"
                     % (h // 12, labels[h], c["mean_excess"] * 100))
        hits.append("%d yılda %%%.0f" % (h // 12, c["hit_rate"] * 100))
    return {"name": "Adil değer hedefi", "value": upside,
            "state": "3 yıl: %s" % final, "tone": tone,
            "reading": ("Fiyat %.2f, adil değer %.2f (%s). Geçmişte bu bantta "
                        "%s." % (pvf["price"], pvf["fair"], band, "; ".join(parts))),
            "evidence": ("Backtest (S&P 500, %s, %s): bu banttaki hedeflere "
                         "ulaşma oranı %s; n=%d. %s"
                         % (table["period"],
                            "gerekçeli F/DD yöntemi, finansal şirketler"
                            if method == "bank" else "tarihsel çarpan yöntemi",
                            ", ".join(hits), cells[str(FV_HORIZONS[0])]["n"],
                            "Finansal şirketlerde bu yöntemin ucuz bulduğu "
                            "isimler iki dönemde de evrenin önünde gitti; "
                            "2023'te batan bankalar veride olmadığı için son "
                            "dönem iyimser olabilir."
                            if method == "bank" else
                            "Adil değer şirketin kendi geçmiş çarpanından "
                            "türetilir ve ileriye dönük bilgi içermez -- "
                            "ucuz bantlarda değer tuzağı riski budur."))}


def risk_cell(volatility):
    """The risk group a company falls in; the backtest tabulates the same key.

    Only a split whose elevated fall rate held in both the 2013-2019
    development window and the 2020-2025 holdout is made: trailing annual
    volatility of 35% or more (about 2.4x the universe rate, then 1.4x). A
    weak business score did not hold up on its own (1.6x, then 1.0x) and
    did not add consistently on top of volatility, so it is not used.
    """
    if volatility is None:
        return None
    return "high_vol" if volatility >= HIGH_VOLATILITY else "normal"


ISSUANCE_BAND = 0.02     # +/-2% of shares a year


def issuance_read(val):
    """Net share issuance: the one accounting signal confirmed outside the
    S&P 500 in this project's backtest. Companies issuing shares lagged and
    net buyers led among S&P 400/600 members, in 2013-2019 and again in
    2020-2025; among S&P 500 members it showed nothing."""
    x = (val or {}).get("net_issuance")
    if x is None:
        return None
    if x > ISSUANCE_BAND:
        state, tone, reading = ("seyreltme", "warning",
                                "Hisse sayısı bir yılda %%%.1f arttı." % (x * 100))
    elif x < -ISSUANCE_BAND:
        state, tone, reading = ("geri alım", "good",
                                "Hisse sayısı bir yılda %%%.1f azaldı." % (-x * 100))
    else:
        state, tone, reading = ("nötr", "neutral",
                                "Hisse sayısı bir yılda %%%+.1f değişti."
                                % (round(x * 100, 1) + 0.0))
    return {"name": "Net hisse ihracı (12 ay)", "value": x, "state": state,
            "tone": tone, "reading": reading,
            "evidence": ("Backtest: S&P 400/600 şirketlerinde hisse ihraç "
                         "edenler sonraki 12 ayda geride kaldı (IC −0.049, t −2.5 "
                         "2013-2019; −0.087, t −3.0 2020-2025). S&P 500 "
                         "şirketlerinde etki görülmedi (IC −0.02); büyük "
                         "şirketlerde bu okuma bilgi amaçlıdır.")}


def fall_risk(val):
    """Measured base rate of a >25% fall over 12 months for companies like this.

    The backtest's one finding that survived its holdout is about risk, not
    return: high trailing volatility goes with more frequent large falls.
    This reports the development-window rate for the company's group -- a
    base rate, not a forecast.
    """
    vol = ((val or {}).get("volatility") or {}).get("annualized")
    summary = _summary() or {}
    table = summary.get("crash_table")
    key = risk_cell(vol)
    if key is None or not table:
        return None
    cell = table["cells"].get(key)
    base = table.get("universe_rate")
    if not cell or cell["n"] < 50 or not base:
        return None
    rate = cell["fall_25"]
    state, tone, note = {
        "normal": ("normal", "neutral", "Yüksek oynaklık işareti yok."),
        "high_vol": ("yüksek", "critical",
                     "Yüksek oynaklıklı şirketler 2020-2025 kontrol "
                     "döneminde de evrenden sık düştü."),
    }[key]
    return {"name": "12 ayda %25+ düşüş riski", "value": rate,
            "state": state, "tone": tone,
            "reading": ("Son 12 ayın yıllık oynaklığı %%%.0f (%s itibarıyla)."
                        % (vol * 100, val["volatility"]["through"])),
            "evidence": ("Backtest'te (S&P 500, 2013-2019) bu gruptaki "
                         "şirketlerde sonraki 12 ayda %%25'ten fazla düşüş "
                         "oranı %%%.1f oldu; tüm evrende %%%.1f, n=%d. %s Bir "
                         "taban oranıdır, bu şirket için tahmin değildir."
                         % (rate * 100, base * 100, cell["n"], note))}


def measured_signals(pkg):
    """The signals this project has actually measured, reported separately.

    The composite verdict is a framework read; its rank correlation with
    forward returns is approximately zero. The accrual ratio is surfaced on
    its own because it is the best-documented single input in the
    literature, with this project's own measured statistics attached --
    including when they fall short of significance, so the reader can see
    how much evidence actually sits behind it.
    """
    out = []
    accrual = pkg["latest_metrics"].get("accrual_ratio")
    if accrual is not None:
        # Bands follow the framework document, not the backtest: negative is
        # healthy, above +5% is its stated warning level. Only the -6% line
        # is a measured threshold, and it is the one the cohort test used.
        if accrual < -0.06:
            state, tone = "güçlü", "good"
            reading = "Nakit, raporlanan kârı belirgin şekilde aşıyor."
        elif accrual <= 0.02:
            state, tone = "sağlıklı", "neutral"
            reading = "Nakit ile kâr birbirine yakın; uyarı seviyesi yok."
        elif accrual <= 0.05:
            state, tone = "izlenmeli", "warning"
            reading = "Kâr, nakit akışının önüne geçmeye başlıyor."
        else:
            state, tone = "zayıf", "critical"
            reading = "Kâr nakde dönmüyor; çerçevenin uyarı eşiğinin üstünde."

        stat = _backtest_stat("Tahakkuk < -%6")
        in_cohort = accrual < -0.06
        if stat:
            significant = abs(stat["t_stat"]) >= 2
            evidence = ("Ölçülen eşik: −%%6 altındaki kohort, backtest'te evrene "
                        "göre %+.2f puan — kazanma oranı %%%.0f, t=%+.2f, n=%d. "
                        "Bu şirket %s. %s"
                        % (stat["vs_universe"] * 100, stat["win_rate"] * 100,
                           stat["t_stat"], stat["n"],
                           "o kohortta" if in_cohort else "o kohortta değil",
                           "Sloan (1996) etkisiyle tutarlı." if significant else
                           "Fark istatistiksel olarak anlamlı değil; yalnızca "
                           "yönü Sloan (1996) ile tutarlı."))
        else:
            evidence = ("Sloan (1996): tahakkukları yüksek şirketler sonraki "
                        "dönemde sistematik olarak düşük performans gösterir.")

        out.append({"name": "Tahakkuk oranı", "value": round(accrual, 4),
                    "state": state, "tone": tone, "reading": reading,
                    "evidence": evidence})
    return out

# A pillar score is 0-100. These are the boundaries the verdict reads.
PASS, WEAK = 60, 40
STALE_DAYS = 200     # latest usable period this far behind the latest balance sheet

# Component weights are set from how reliable each measure is known to be --
# not fitted to the backtest, which on 51 survivorship-biased large caps in a
# single regime cannot support a fitted weight. Every entry carries the
# reason it earns its share, and the equal averaging this replaces was itself
# an unjustified default.
WEIGHTS = {
    # Whether invested capital earns more than it costs is the standard test
    # of business quality (Greenwald; Damodaran), so it leads. Stability
    # earns a quarter of the weight on its own: once the level is accounted
    # for, durability is most of what "quality" means, and a return that
    # barely moves through a decade is a different proposition from one that
    # swings to the same average.
    "quality": {
        "roic_spread": 0.35,
        "roic_trend": 0.20,
        "operating_margin": 0.20,
        "roic_stability": 0.25,
    },
    # Coverage and leverage are what actually decide whether a bad two years
    # becomes a financing emergency. Altman Z'' is kept but held down: it was
    # fitted on 1968 manufacturers and never sees interest coverage, which is
    # the very thing that fails first.
    "safety": {
        "interest_coverage": 0.35,
        "net_debt_to_ebitda": 0.30,
        "altman_z": 0.15,
        "equity_condition": 0.10,
        "current_ratio": 0.10,
        "bank_capital": 0.40,
    },
    # The accrual ratio carries the most weight of any single input in the
    # whole model: it replicates a long-established published effect (Sloan
    # 1996) and carries the expected sign in this project's own backtest,
    # though not at significance among large caps. Beneish is held down for its high false-positive rate.
    "earnings_quality": {
        "accrual_ratio": 0.50,
        "cash_conversion": 0.35,
        "beneish": 0.15,
    },
    # Asking whether the growth the price requires is above or below what the
    # company has ever delivered is far more robust than a fair-value point
    # estimate, which inherits every discount-rate and terminal assumption.
    # The premium to the company's own historical multiple is the headline
    # method, so it carries the most. The reverse DCF is kept because it asks
    # the question a different way and does not share the same failure mode.
    # Margin of safety is gone: it is now derived from the same reversion
    # estimate as the premium and would have double-counted it.
    "valuation": {
        "premium_to_own_history": 0.40,
        "implied_vs_history": 0.35,
        "fcf_yield_vs_wacc": 0.25,
        # Banks: price against the justified P/B value, and the earnings
        # yield against the cost of equity -- the same two questions as the
        # cash-flow version, asked in equity terms.
        "pb_premium": 0.60,
        "earnings_yield_vs_ke": 0.40,
    },
    # Quality leads, but a failure in either of the other two blocks the
    # verdict outright in `_decide`, so their weight here only shapes the
    # composite among companies that already pass.
    "business": {
        "Kalite": 0.40,
        "Güvenlik": 0.30,
        "Kâr kalitesi": 0.30,
    },
}


# Metrics where a lower reading is the better one, so a high percentile
# within the company's own history is a bad sign rather than a good one.
LOWER_IS_BETTER = {"accrual_ratio", "net_debt_to_ebitda", "debt_to_equity",
                   "effective_tax_rate"}

# How much of a component's score comes from the company's own ten-year
# distribution rather than a hand-set absolute band. The absolute band still
# anchors the level -- a business that has always been poor should not score
# well for merely being at its own best -- but the bands are unavoidably
# arbitrary across sectors, and where a company sits against its own record
# is a fact rather than a judgement.
SELF_RELATIVE_WEIGHT = 0.40


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _percentile(series, value, key):
    """Where today's reading sits in the company's own history, 0-100."""
    values = [v for _, v in series if v is not None]
    if len(values) < 12 or value is None:
        return None
    below = sum(1 for v in values if v < value)
    pct = below / len(values) * 100
    return 100 - pct if key in LOWER_IS_BETTER else pct


def _blend(pkg, key, absolute):
    """Absolute band tempered by the company's own distribution."""
    if absolute is None:
        return None
    series = (pkg["trends"].get(key) or {}).get("series") or []
    pct = _percentile(series, pkg["latest_metrics"].get(key), key)
    if pct is None:
        return absolute
    return absolute * (1 - SELF_RELATIVE_WEIGHT) + pct * SELF_RELATIVE_WEIGHT


def _stability(pkg, key):
    """Score for how steady a series has been, 0-100.

    A business whose returns barely move through a decade is a different
    proposition from one that swings, even at the same average -- durability
    is most of what "quality" means once the level is accounted for. Measured
    as the coefficient of variation, so it is scale-free.
    """
    values = [v for _, v in ((pkg["trends"].get(key) or {}).get("series") or [])
              if v is not None]
    if len(values) < 12:
        return None
    mean = sum(values) / len(values)
    if mean <= 0:
        return 25.0
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    cv = var ** 0.5 / mean
    # A coefficient of variation of 0.10 is very steady; 0.60 is erratic.
    return _scale(cv, 0.60, 0.10)


def _scale(value, floor, ceiling):
    """Linear 0-100 between two reference points, either direction."""
    if value is None:
        return None
    if ceiling == floor:
        return 50.0
    return _clamp((value - floor) / (ceiling - floor) * 100)


def quality(pkg, val):
    """Does the business earn more than its capital costs, and improving?"""
    m = pkg["latest_metrics"]
    wacc = (val or {}).get("assumptions", {}).get("wacc")
    parts, reasons = {}, []

    if pkg["company"]["sector_bucket"] == "financial":
        return _bank_quality(pkg, val)

    roic = m.get("roic")
    if roic is not None and wacc:
        spread = roic - wacc
        parts["roic_spread"] = _blend(pkg, "roic", _scale(spread, -0.04, 0.12))
        reasons.append("roic %.1f%% vs sermaye maliyeti %.1f%% (fark %+.1f puan)"
                       % (roic * 100, wacc * 100, spread * 100))
    elif roic is not None:
        # Without a discount rate, fall back to an absolute band around the
        # 8-10% cost of capital most large companies sit near.
        parts["roic_spread"] = _blend(pkg, "roic", _scale(roic, 0.04, 0.18))
        reasons.append("roic %.1f%% (sermaye maliyeti hesaplanamadı)" % (roic * 100))

    # F-Score is reported but no longer weighted. Piotroski fitted it on
    # small, high-book-to-market firms and it discriminates poorly among
    # large ones; the backtest in `backtest.py` found it inverted in exactly
    # that universe (pooled rho -0.08, F<=5 beating F>=7; development IC ~0). Dropping a component
    # whose prior and whose measurement agree is not curve-fitting -- but
    # note the thresholds around it are deliberately left alone.
    f = pkg["scores"].get("piotroski")
    if f:
        reasons.append("F-Score %d/%d (bilgi amacli, agirliklandirilmadi)"
                       % (f["score"], f["max"]))

    op = m.get("operating_margin")
    if op is not None:
        parts["operating_margin"] = _blend(pkg, "operating_margin",
                                           _scale(op, 0.02, 0.22))
        reasons.append("faaliyet marjı %.1f%%" % (op * 100))

    direction = (pkg["trends"].get("roic") or {}).get("direction")
    if direction and direction != "insufficient_history":
        parts["roic_trend"] = {"improving": 80.0, "flat": 55.0,
                               "deteriorating": 25.0}.get(direction, 50.0)
        reasons.append("roic yönü: %s" % direction)

    steady = _stability(pkg, "roic")
    if steady is not None:
        parts["roic_stability"] = steady
        reasons.append("roic istikrarı %.0f/100 (10 yıllık dalgalanma)" % steady)

    return _weighted("Kalite", "quality", parts, reasons)


def _bank_quality(pkg, val):
    """For a lender, return on equity against the cost of equity plays the
    part ROIC against WACC plays elsewhere; its trend and its stability
    through a cycle are read the same way."""
    m = pkg["latest_metrics"]
    parts, reasons = {}, []
    ke = ((val or {}).get("cost_of_capital") or {}).get("cost_of_equity")
    roe = m.get("roe")
    if roe is not None and ke:
        spread = roe - ke
        parts["roic_spread"] = _blend(pkg, "roe", _scale(spread, -0.04, 0.08))
        reasons.append("roe %.1f%% vs özsermaye maliyeti %.1f%% (fark %+.1f puan)"
                       % (roe * 100, ke * 100, spread * 100))
    elif roe is not None:
        parts["roic_spread"] = _blend(pkg, "roe", _scale(roe, 0.06, 0.18))
        reasons.append("roe %.1f%% (özsermaye maliyeti hesaplanamadı)" % (roe * 100))
    op = m.get("operating_margin")
    if op is not None:
        parts["operating_margin"] = _blend(pkg, "operating_margin",
                                           _scale(op, 0.10, 0.40))
        reasons.append("faaliyet marjı %.1f%%" % (op * 100))
    direction = (pkg["trends"].get("roe") or {}).get("direction")
    if direction and direction != "insufficient_history":
        parts["roic_trend"] = {"improving": 80.0, "flat": 55.0,
                               "deteriorating": 25.0}.get(direction, 50.0)
        reasons.append("roe yönü: %s" % direction)
    steady = _stability(pkg, "roe")
    if steady is not None:
        parts["roic_stability"] = steady
        reasons.append("roe istikrarı %.0f/100" % steady)
    return _weighted("Kalite", "quality", parts, reasons)


def safety(pkg, val):
    """Can it survive a bad two years without a financing emergency?"""
    m = pkg["latest_metrics"]
    sector = pkg["company"]["sector_bucket"]
    parts, reasons = {}, []

    if sector == "financial":
        # A bank's leverage is its business model, so debt-to-EBITDA and
        # coverage do not apply; equity against total assets is the
        # loss-absorbing capital the framework asks about (regulatory CET1
        # is not in the XBRL facts). 5% is thin, 10% comfortable.
        eta = m.get("equity_to_assets")
        if eta is not None:
            parts["bank_capital"] = _scale(eta, 0.05, 0.10)
            reasons.append("özsermaye / varlık %.1f%%" % (eta * 100))

    z = pkg["scores"].get("altman_z") or {}
    if "z_double_prime" in z:
        parts["altman_z"] = _scale(z["z_double_prime"], 0.8, 3.2)
        reasons.append("Altman Z'' %.2f (%s)" % (z["z_double_prime"], z["zone"]))

    cov = m.get("interest_coverage")
    if cov is not None:
        parts["interest_coverage"] = _blend(pkg, "interest_coverage",
                                            _scale(cov, 1.0, 8.0))
        reasons.append("faiz karşılama %.2f" % cov)

    lev = m.get("net_debt_to_ebitda")
    if lev is not None:
        # Utilities, telecom and real estate carry structurally more debt per
        # unit of EBITDA, so the band shifts rather than marking every
        # regulated business unsafe.
        ceiling = 6.0 if sector in ("utility", "real_estate") else 5.0
        floor = 2.0 if sector in ("utility", "real_estate") else 0.5
        parts["net_debt_to_ebitda"] = _blend(pkg, "net_debt_to_ebitda",
                                             _scale(lev, ceiling, floor))
        reasons.append("net borç/FAVÖK %.2f" % lev)

    if pkg.get("equity_negative"):
        parts["equity_condition"] = 35.0
        reasons.append("defter özsermayesi negatif")
    elif pkg.get("equity_thin"):
        parts["equity_condition"] = 45.0
        reasons.append("özsermaye tabanı ince")
    else:
        parts["equity_condition"] = 75.0

    cur = m.get("current_ratio")
    if cur is not None:
        parts["current_ratio"] = _blend(pkg, "current_ratio",
                                        _scale(cur, 0.7, 1.8))
        reasons.append("cari oran %.2f" % cur)

    return _weighted("Güvenlik", "safety", parts, reasons)


def earnings_quality(pkg):
    """Is the reported profit actually cash?"""
    m = pkg["latest_metrics"]
    parts, reasons = {}, []

    accrual = m.get("accrual_ratio")
    if accrual is not None:
        # Anchored on the framework's stated warning level (+5%) and the
        # measured -6% threshold from the backtest cohort test.
        parts["accrual_ratio"] = _blend(pkg, "accrual_ratio",
                                        _scale(accrual, 0.06, -0.06))
        reasons.append("tahakkuk oranı %+.1f%%" % (accrual * 100))

    conv = m.get("cash_conversion")
    if conv is not None:
        parts["cash_conversion"] = _blend(pkg, "cash_conversion",
                                          _scale(conv, 0.6, 1.3))
        reasons.append("nakde dönüşüm %.2f" % conv)

    b = pkg["scores"].get("beneish_m")
    if b:
        parts["beneish"] = 35.0 if b["flag"] else 80.0
        reasons.append("Beneish %.2f (%s)"
                       % (b["m_score"], "bayrak" if b["flag"] else "temiz"))

    return _weighted("Kâr kalitesi", "earnings_quality", parts, reasons)


def valuation(pkg, val):
    """Is the price paying for something the company has ever delivered?

    The implied-growth comparison carries most of the weight. A fair-value
    point estimate inherits every DCF assumption; asking whether the growth
    the price requires is above or below the company's own track record is a
    far more robust question.
    """
    if not val:
        return {"name": "Değerleme", "score": None, "band": "veri yok",
                "reasons": ["fiyat verisi alınamadı"]}

    if val.get("bank"):
        return _bank_valuation(val)

    mos = val.get("margin_of_safety")
    fcf_yield = val["multiples"].get("fcf_yield")
    implied = (val.get("dcf") or {}).get("implied_growth")
    historical = val["assumptions"].get("historical_fcf_growth")
    wacc = val["assumptions"]["wacc"]
    parts, reasons = {}, []

    if fcf_yield is None or fcf_yield < 0.01:
        return {"name": "Değerleme", "score": None, "band": "model uygulanamaz",
                "reasons": ["serbest nakit akışı piyasa değerine göre ihmal "
                            "edilebilir veya negatif -- nakit akışı iskontosu "
                            "bu şirkete anlamlı bir değer vermiyor"],
                "not_applicable": True}

    if implied is not None and historical is not None:
        gap = historical - implied
        parts["implied_vs_history"] = _scale(gap, -0.12, 0.06)
        reasons.append("fiyat %.1f%% yıllık FCF büyümesi ima ediyor, şirketin "
                       "geçmişi %.1f%%" % (implied * 100, historical * 100))
    elif implied is not None:
        parts["implied_vs_history"] = _scale(implied, 0.20, 0.03)
        reasons.append("fiyatın ima ettiği büyüme %.1f%%" % (implied * 100))

    rev = val.get("reversion")
    if rev:
        premium = rev["premium_to_own_history"]
        # Zero premium scores mid-band; a 60% premium to its own median is
        # the weak end, a 30% discount the strong end.
        parts["premium_to_own_history"] = _scale(premium, 0.60, -0.30)
        note = ("kendi tarihsel EV/FCF medyanına göre %+.0f%% "
                "(%.1f× vs %.1f×, %.1f yıllık pencere)"
                % (premium * 100, rev["current_ev_fcf"],
                   rev["median_ev_fcf"], rev["years"]))
        if rev.get("window_note"):
            note += " -- pencere kısa"
        reasons.append(note)
    elif mos is not None:
        parts["premium_to_own_history"] = _scale(mos, -0.50, 0.30)
        reasons.append("güvenlik payı %+.0f%% (iskonto edilmiş nakit akışı)"
                       % (mos * 100))

    if fcf_yield is not None:
        parts["fcf_yield_vs_wacc"] = _scale(fcf_yield - wacc, -0.06, 0.03)
        note = ("FCF getirisi %.1f%% vs sermaye maliyeti %.1f%%"
                % (fcf_yield * 100, wacc * 100))
        # A cash yield below the government bond is worth naming explicitly:
        # at that point the entire case rests on growth, since the security
        # pays less than the risk-free alternative today.
        rf = (val.get("cost_of_capital") or {}).get("risk_free")
        if rf and fcf_yield < rf:
            note += (" -- 10 yıllık tahvilin (%.2f%%) altında, tez tamamen "
                     "büyümeye dayanıyor" % (rf * 100))
        reasons.append(note)

    return _weighted("Değerleme", "valuation", parts, reasons)


def _bank_valuation(val):
    bank = val["bank"]
    price = val["quote"]["price"]
    parts, reasons = {}, []
    premium = price / bank["fair"] - 1
    parts["pb_premium"] = _scale(premium, 0.60, -0.30)
    reasons.append("fiyat, gerekçeli F/DD değerine (%.2f) göre %+.0f%% -- %s"
                   % (bank["fair"], premium * 100, bank["basis"]))
    ey = val["multiples"].get("earnings_yield")
    ke = bank["cost_of_equity"]
    if ey is not None:
        parts["earnings_yield_vs_ke"] = _scale(ey - ke, -0.04, 0.03)
        reasons.append("kâr getirisi %.1f%% vs özsermaye maliyeti %.1f%%"
                       % (ey * 100, ke * 100))
    return _weighted("Değerleme", "valuation", parts, reasons)


def _weighted(name, key, parts, reasons):
    """Weighted pillar score, renormalised over whatever could be computed.

    A missing component redistributes its weight across the rest rather than
    scoring zero, so a data gap lowers confidence -- reported separately --
    instead of silently penalising the company.
    """
    weights = WEIGHTS[key]
    usable = {k: v for k, v in parts.items() if v is not None}
    total = sum(weights[k] for k in usable)
    if not usable or not total:
        return {"name": name, "score": None, "band": "veri yok",
                "reasons": reasons, "components": {}}
    score = round(sum(v * weights[k] for k, v in usable.items()) / total, 1)
    band = "güçlü" if score >= PASS else "zayıf" if score < WEAK else "orta"
    return {"name": name, "score": score, "band": band, "reasons": reasons,
            "components": {k: round(v, 1) for k, v in usable.items()},
            "weights_used": {k: round(weights[k] / total, 3) for k in usable}}


def next_quarter(pkg):
    """Mechanical extrapolation of what is already in motion.

    Only continuations are projected -- the revenue run-rate, the margin
    trend, seasonality from the same quarter a year earlier. Demand,
    pricing, competition and management decisions do not appear on a balance
    sheet and are not guessed at.
    """
    rev_series = (pkg["trends"].get("revenue_ttm") or {}).get("series") or []
    if len(rev_series) < 9:
        return {"available": False,
                "reason": "yeterli geçmiş yok (en az 9 çeyrek gerekir)"}

    ttm_now = rev_series[-1][1]
    ttm_prior = rev_series[-5][1]
    growth = (ttm_now / ttm_prior - 1) if ttm_prior else 0.0

    # A TTM figure already smooths seasonality, so the quarterly run-rate
    # comes from the TTM level and the year-over-year rate applied to it.
    quarter_run_rate = ttm_now / 4
    low = quarter_run_rate * (1 + growth * 0.5)
    high = quarter_run_rate * (1 + growth * 1.5)
    if low > high:
        low, high = high, low
    # With growth near zero the multipliers collapse to a single point, which
    # would present a forecast as if it were certain. A floor of +/-3% keeps
    # the range honest about the uncertainty that is always there.
    mid = (low + high) / 2
    floor = mid * 0.03
    if high - low < floor * 2:
        low, high = mid - floor, mid + floor

    m = pkg["latest_metrics"]
    out = {"available": True,
           "revenue_range": [round(low), round(high)],
           "basis": "TTM %s, yıllık büyüme %+.1f%%; çeyreklik koşu hızına "
                    "uygulanan yarım-kat ile bir buçuk kat bandı"
                    % (_money(ttm_now), growth * 100),
           "caveats": []}

    op = m.get("operating_margin")
    op_dir = (pkg["trends"].get("operating_margin") or {}).get("direction")
    if op is not None:
        out["operating_income_range"] = [round(low * op), round(high * op)]
        out["margin_assumption"] = ("faaliyet marjı %.1f%% sabit varsayıldı (yön: %s)"
                                    % (op * 100, op_dir or "bilinmiyor"))
        if op_dir == "deteriorating":
            out["caveats"].append("marj daralıyor -- sabit marj varsayımı "
                                  "faaliyet kârını yukarı saptırır")
        elif op_dir == "improving":
            out["caveats"].append("marj genişliyor -- sabit marj varsayımı "
                                  "faaliyet kârını aşağı saptırır")

    for key, label in (("fcf_margin", "serbest nakit"), ):
        margin = m.get(key)
        if margin is not None:
            out["fcf_range"] = [round(low * margin), round(high * margin)]
            out["fcf_assumption"] = "%s marjı %.1f%% sabit varsayıldı" % (label, margin * 100)

    out["caveats"].append("Talep, fiyatlama, rekabet ve yönetim kararları "
                          "bilançoda görünmez ve projeksiyona girmez.")
    return out


def _money(v):
    return "%.1f Mr$" % (v / 1e9) if abs(v) >= 1e9 else "%.0f M$" % (v / 1e6)


def assess(pkg, val=None):
    """The full verdict."""
    pillars = [quality(pkg, val), safety(pkg, val),
               earnings_quality(pkg), valuation(pkg, val)]
    by_name = {p["name"]: p for p in pillars}

    business = [by_name["Kalite"], by_name["Güvenlik"], by_name["Kâr kalitesi"]]
    scored = {p["name"]: p["score"] for p in business if p["score"] is not None}
    # Weighted, then capped by the weakest pillar. Without the cap a strong
    # dimension hides a failing one -- Tesla averages to 69 on a quality
    # score of 14 -- and a business is only as sound as its worst side.
    business_score = None
    if scored:
        bw = WEIGHTS["business"]
        total = sum(bw[k] for k in scored)
        weighted = sum(v * bw[k] for k, v in scored.items()) / total
        business_score = round(min(weighted, min(scored.values()) + 20), 1)
    price_pillar = by_name["Değerleme"]

    label, rationale = _decide(pkg, business, business_score, price_pillar)

    # The verdict never travels without the caveats: the same accrual signal
    # that fails a pillar usually has a benign reading, and showing one
    # without the other is how a tool like this misleads.
    flags = interpret.red_flags(pkg)

    return {
        "verdict": label,
        "rationale": rationale,
        "caveats": flags,
        "business_score": business_score,
        "pillars": pillars,
        "measured_signals": measured_signals(pkg) + [
            s for s in [fair_value_read(val), fall_risk(val),
                        issuance_read(val)] if s],
        "next_quarter": next_quarter(pkg),
        "confidence": interpret.confidence(pkg),
        "basis": "Bu sonuc, knowledge/analysis-framework.md icindeki acikca "
                 "tanimli kriterlere gore mali durumun yapilandirilmis bir "
                 "okumasidir; getiri tahmini degildir. Bilesik skorun ileri "
                 "getiriyle olculmus siralama gucu yoktur (S&P 500 "
                 "uyeleri uzerinde IC +0.01); skor yalnizca karlilik "
                 "faktorune egilim tasir. Tahakkuk orani 'olculmus "
                 "sinyaller' bolumunde ayrica gosterilir.",
        "disclaimer": "Bu bir analiz araci ciktisidir. Yatirim danismanligi, "
                      "alim-satim tavsiyesi veya hedef fiyat degildir. "
                      "Karar senin.",
    }


def by_name_reasons(pillars, name):
    for p in pillars:
        if p["name"] == name:
            return p["reasons"]
    return []


def _decide(pkg, business, business_score, price):
    """The decision rule, written out rather than averaged into a number."""
    failing = [p["name"] for p in business
               if p["score"] is not None and p["score"] < WEAK]
    thin_data = pkg["periods_available"] < 12 or pkg["data_coverage"] < 0.80

    if pkg.get("stale_days", 0) > STALE_DAYS:
        return "degerlendirilemez", ("Son kullanılabilir dönem %s, ama şirket "
                                     "%s tarihli bilanço yayımlamış: gelir "
                                     "verisi bu arada etiketlenmemiş. Eski "
                                     "dönemi güncelmiş gibi okumamak için "
                                     "hüküm verilmedi."
                                     % (pkg["as_of"], pkg["latest_balance_date"]))
    if thin_data:
        return "degerlendirilemez", ("Veri tabanı hüküm vermeye yetmiyor: "
                                     "%d dönem, kapsam %%%d."
                                     % (pkg["periods_available"],
                                        round(pkg["data_coverage"] * 100)))
    if business_score is None:
        return "degerlendirilemez", "İşletme kalitesi hesaplanamadı."

    # The accrual gate. This is the best-documented earnings-quality input
    # (Sloan 1996; its sign holds in this project's backtest, its size does
    # not reach significance among large caps), and diluting it into a pillar average lets a company with
    # profits that are visibly not turning into cash pass on the strength of
    # its balance sheet. When the accrual ratio is above the framework's
    # warning level *and* cash conversion confirms it, that is decisive on
    # its own -- one weak reading is noise, both together is not.
    m = pkg["latest_metrics"]
    accrual, conversion = m.get("accrual_ratio"), m.get("cash_conversion")
    if (accrual is not None and conversion is not None
            and accrual > 0.05 and conversion < 0.8):
        return "yatirim yapilamaz", (
            "Kâr nakde dönmüyor: tahakkuk oranı %+.1f%% (uyarı eşiği %%5) ve "
            "nakde dönüşüm %.2f. Bu ikisi birlikte, diğer sütunlar ne "
            "derse desin bloke eder."
            % (accrual * 100, conversion))

    if "Kâr kalitesi" in failing:
        return "yatirim yapilamaz", ("Kâr kalitesi eşiğin altında. Raporlanan "
                                     "kâr nakde dönmüyorsa diğer her metrik "
                                     "şüpheli hale gelir ve ucuz fiyat bunu "
                                     "telafi etmez.")
    if "Güvenlik" in failing:
        return "yatirim yapilamaz", ("Bilanço güvenliği eşiğin altında. "
                                     "Finansman baskısı altındaki bir şirkette "
                                     "değerleme ikincil bir sorudur.")
    if "Kalite" in failing:
        detail = "; ".join(by_name_reasons(business, "Kalite")[:2])
        return "yatirim yapilamaz", ("İşletme sermaye maliyetini karşılamıyor: "
                                     "%s." % detail)

    by_name = {p["name"]: p for p in business}
    if price.get("not_applicable"):
        return "fiyatlanamaz", ("İşletme tarafı %s (%.0f/100), ancak serbest "
                               "nakit akışı iskontosu bu şirkete "
                               "uygulanamıyor. Değerleme için nakit akışı "
                               "üretmeye başlaması veya farklı bir yöntem "
                               "gerekir." % (_band(business_score), business_score))
    if price["score"] is None:
        return "fiyat verisi yok", "İşletme değerlendirildi, fiyat alınamadı."

    if business_score >= PASS and price["score"] >= PASS:
        return "yatirim yapilabilir", ("İşletme kalitesi ve fiyat birlikte "
                                       "olumlu: işletme %.0f/100, değerleme "
                                       "%.0f/100."
                                       % (business_score, price["score"]))
    if business_score >= PASS and price["score"] < WEAK:
        why = ("fiyat, özsermaye kârlılığının haklı çıkardığı defter değeri "
               "çarpanının üzerinde"
               if pkg["company"]["sector_bucket"] == "financial" else
               "fiyat şirketin geçmişte teslim etmediği bir büyümeyi ima ediyor")
        return "iyi sirket, pahali fiyat", ("İşletme %.0f/100 ile güçlü ama "
                                            "değerleme %.0f/100 -- %s."
                                            % (business_score, price["score"], why))
    if business_score < PASS and price["score"] >= PASS:
        return "ucuz ama sorunlu", ("Fiyat %.0f/100 ile cazip, işletme "
                                    "%.0f/100 -- indirim bir sebeple var. "
                                    "Tez, sorunun geçici olduğuna dayanmak "
                                    "zorunda."
                                    % (price["score"], business_score))
    return "kosullu", ("Ne işletme ne fiyat tarafı net: işletme %.0f/100, "
                       "değerleme %.0f/100." % (business_score, price["score"]))


def _band(score):
    return "güçlü" if score >= PASS else "zayıf" if score < WEAK else "orta"


if __name__ == "__main__":
    import sys
    import report as _report
    import valuation as _valuation

    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    pkg = _report.build(ticker)
    try:
        val = _valuation.value(pkg)
    except RuntimeError as exc:
        val = None
        print("fiyat alinamadi: %s" % exc)
    a = assess(pkg, val)

    print("# %s (%s)" % (pkg["company"]["name"], ticker))
    if val:
        print("fiyat %.2f %s | piyasa degeri %s | wacc %.2f%% (beta %s)"
              % (val["quote"]["price"], val["quote"]["currency"],
                 _money(val["market_cap"]), val["assumptions"]["wacc"] * 100,
                 val["cost_of_capital"].get("beta", "-")))
        if val["fair_value"]:
            print("adil deger %s-%s (baz %s) | guvenlik payi %s"
                  % (val["fair_value"]["low"], val["fair_value"]["high"],
                     val["fair_value"].get("base"),
                     ("%+.0f%%" % (val["margin_of_safety"] * 100))
                     if val["margin_of_safety"] is not None else "-"))
        ig = (val.get("dcf") or {}).get("implied_growth")
        hg = val["assumptions"]["historical_fcf_growth"]
        if ig is not None:
            print("fiyatin ima ettigi buyume %.1f%% | sirketin gecmisi %s"
                  % (ig * 100, ("%.1f%%" % (hg * 100)) if hg is not None else "-"))

    print("\nSONUC: %s" % a["verdict"].upper())
    print("  %s" % a["rationale"])
    print("\nSutunlar:")
    for p in a["pillars"]:
        print("  %-14s %-6s %s" % (p["name"],
              ("%.0f" % p["score"]) if p["score"] is not None else p["band"],
              "; ".join(p["reasons"])[:110]))
    nq = a["next_quarter"]
    if nq["available"]:
        print("\nGelecek ceyrek:")
        print("  gelir %s - %s" % (_money(nq["revenue_range"][0]), _money(nq["revenue_range"][1])))
        if nq.get("operating_income_range"):
            print("  faaliyet kari %s - %s" % (_money(nq["operating_income_range"][0]),
                                               _money(nq["operating_income_range"][1])))
    if a["caveats"]:
        print("\nUyarilar:")
        for f in a["caveats"]:
            print("  [%s] %s" % (f["severity"], f["signal"]))
    print("\n%s" % a["disclaimer"])
