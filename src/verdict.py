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


def _backtest_stat(name):
    """Pulls one cohort's measured statistics from the saved backtest."""
    if not hasattr(_backtest_stat, "cache"):
        try:
            _backtest_stat.cache = json.load(open(SUMMARY_PATH))
        except Exception:
            _backtest_stat.cache = None
    summary = _backtest_stat.cache
    if not summary:
        return None
    for c in summary.get("cohorts", []):
        if c["name"] == name and not c.get("insufficient"):
            return c
    return None


def measured_signals(pkg):
    """The signals this project has actually measured, reported separately.

    The composite verdict is a framework read; its rank correlation with
    forward returns is approximately zero. One input is different: the
    accrual ratio both replicates a long-established published effect and
    came out as the strongest signal in this project's own backtest. It is
    surfaced on its own, with its measured statistics attached, rather than
    diluted into a score -- so the reader can see which part of the output
    has evidence behind it and which part is framework judgment.
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
            evidence = ("Ölçülen eşik: −%%6 altındaki kohort, backtest'te evreni "
                        "%+.2f puan geçti — kazanma oranı %%%.0f, t=%+.2f, n=%d. "
                        "Bu şirket %s. Sloan (1996) etkisiyle tutarlı."
                        % (stat["vs_universe"] * 100, stat["win_rate"] * 100,
                           stat["t_stat"], stat["n"],
                           "o kohortta" if in_cohort else "o kohortta değil"))
        else:
            evidence = ("Sloan (1996): tahakkukları yüksek şirketler sonraki "
                        "dönemde sistematik olarak düşük performans gösterir.")

        out.append({"name": "Tahakkuk oranı", "value": round(accrual, 4),
                    "state": state, "tone": tone, "reading": reading,
                    "evidence": evidence})
    return out

# A pillar score is 0-100. These are the boundaries the verdict reads.
PASS, WEAK = 60, 40

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
    },
    # The accrual ratio carries the most weight of any single input in the
    # whole model: it replicates a long-established published effect (Sloan
    # 1996) and carries the expected sign in this project's own backtest,
    # though not after factor controls. Beneish is held down for its high false-positive rate.
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


def safety(pkg, val):
    """Can it survive a bad two years without a financing emergency?"""
    m = pkg["latest_metrics"]
    sector = pkg["company"]["sector_bucket"]
    parts, reasons = {}, []

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
        "measured_signals": measured_signals(pkg),
        "next_quarter": next_quarter(pkg),
        "confidence": interpret.confidence(pkg),
        "basis": "Bu sonuc, knowledge/analysis-framework.md icindeki acikca "
                 "tanimli kriterlere gore mali durumun yapilandirilmis bir "
                 "okumasidir; getiri tahmini degildir. Bilesik skorun ileri "
                 "getiriyle olculmus siralama gucu yoktur; gelistirme "
                 "doneminde yonu negatiftir ve bu buyuk olcude bilinen "
                 "faktor egilimlerinden gelir. Tahakkuk orani 'olculmus "
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

    if thin_data:
        return "degerlendirilemez", ("Veri tabanı hüküm vermeye yetmiyor: "
                                     "%d dönem, kapsam %%%d."
                                     % (pkg["periods_available"],
                                        round(pkg["data_coverage"] * 100)))
    if business_score is None:
        return "degerlendirilemez", "İşletme kalitesi hesaplanamadı."

    # The accrual gate. This is the one input with measured predictive
    # evidence behind it (the expected sign in this project's backtest, replicating
    # Sloan 1996), and diluting it into a pillar average lets a company with
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
            "nakde dönüşüm %.2f. Bu ikisi birlikte, modelin ölçülmüş kanıta "
            "sahip tek sinyalidir ve diğer sütunlar ne derse desin bloke eder."
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
        return "iyi sirket, pahali fiyat", ("İşletme %.0f/100 ile güçlü ama "
                                            "değerleme %.0f/100 -- fiyat "
                                            "şirketin geçmişte teslim "
                                            "etmediği bir büyümeyi ima ediyor."
                                            % (business_score, price["score"]))
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
            print("adil deger %s-%s (orta %s) | guvenlik payi %s"
                  % (val["fair_value"]["low"], val["fair_value"]["high"],
                     val["fair_value"]["mid"],
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
