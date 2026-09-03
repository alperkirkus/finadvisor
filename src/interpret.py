"""Rule-based interpretation of the evidence package.

Everything the framework document states as a threshold, a sector
adjustment, a score caveat or a red-flag combination is encoded here, so a
company can be read end to end without a model call. The output is
deliberately structured findings rather than generated prose: a template
pretending to be an analyst's paragraph reads worse and hides its own
reasoning.
"""

# (weak_below, strong_above). Bands are contextual -- the same gross margin
# is mediocre in software and excellent in retail -- so a sector bucket may
# override the general band.
BANDS = {
    "gross_margin":       (0.20, 0.40),
    "operating_margin":   (0.05, 0.15),
    "net_margin":         (0.03, 0.10),
    "fcf_margin":         (0.05, 0.15),
    "roe":                (0.08, 0.15),
    "roa":                (0.03, 0.08),
    "roic":               (0.08, 0.15),
    "current_ratio":      (1.00, 1.50),
    "quick_ratio":        (0.75, 1.10),
    "interest_coverage":  (2.00, 6.00),
    "cash_conversion":    (0.80, 1.00),
}

# Metrics where a lower number is the better number.
INVERTED = {
    "net_debt_to_ebitda": (3.00, 1.50),
    "debt_to_equity":     (1.50, 0.50),
    "accrual_ratio":      (0.05, 0.00),
}

SECTOR_BANDS = {
    "other": {"gross_margin": (0.50, 0.70)},        # software-heavy bucket
    "retail": {"gross_margin": (0.15, 0.30), "operating_margin": (0.03, 0.08),
               "net_margin": (0.01, 0.05)},
    "utility": {"net_debt_to_ebitda": (5.00, 3.00), "current_ratio": (0.80, 1.20)},
    "energy": {"gross_margin": (0.10, 0.25)},
    "real_estate": {"net_debt_to_ebitda": (6.00, 4.00)},
    "financial": {"roe": (0.08, 0.12), "roa": (0.005, 0.010)},
}

SECTOR_NOTES = {
    "utility": "Kamu hizmetleri yapısal olarak yüksek kaldıraçlıdır; eşikler buna göre gevşetildi.",
    "real_estate": "Gayrimenkulde yüksek kaldıraç yapısaldır.",
    "retail": "Perakendede ince marj normaldir; eşikler sektöre göre indirildi.",
    "financial": "Bankalarda ROA %1 civarı iyidir; marj ve likidite kavramları uygulanmaz.",
    "other": "Yazılım/hizmet ağırlıklı bu grupta brüt marj eşiği yükseltildi.",
}

BAND_LABEL = {"weak": "zayıf", "normal": "normal", "strong": "güçlü"}

# Metrics that are computed for a sector but must not be graded in it. A
# bank's deposits are not in the debt chain, so its debt_to_equity looks
# conservative when the institution is in fact heavily levered; grading it
# would be worse than saying nothing. Bank margins are structurally high for
# the same kind of reason -- the general band would call every bank strong.
NO_BAND = {
    "financial": {"debt_to_equity", "net_margin", "operating_margin"},
    "real_estate": {"net_margin", "operating_margin"},
}


def _band(key, value, sector, thin_equity=False):
    if key in NO_BAND.get(sector, ()):
        return None
    # A sliver of book equity inflates every return-on-equity figure
    # mechanically. The number is reported but not graded.
    if thin_equity and key in ("roe", "debt_to_equity"):
        return None
    override = SECTOR_BANDS.get(sector, {}).get(key)
    if key in INVERTED:
        weak, strong = override or INVERTED[key]
        if value > weak:
            return "weak"
        return "strong" if value < strong else "normal"
    bounds = override or BANDS.get(key)
    if bounds is None:
        return None
    weak, strong = bounds
    if value < weak:
        return "weak"
    return "strong" if value > strong else "normal"


def verdicts(pkg):
    """Per-metric band assignment, sector-adjusted."""
    sector = pkg["company"]["sector_bucket"]
    thin = pkg.get("equity_thin", False)
    out = []
    for key, value in pkg["latest_metrics"].items():
        band = _band(key, value, sector, thin)
        if band is None:
            continue
        overridden = key in SECTOR_BANDS.get(sector, {})
        out.append({"metric": key, "value": value, "band": band,
                    "band_label": BAND_LABEL[band],
                    "sector_adjusted": overridden})
    order = {"weak": 0, "normal": 2, "strong": 1}
    return sorted(out, key=lambda v: (order[v["band"]], v["metric"]))


def _direction(pkg, key):
    return (pkg["trends"].get(key) or {}).get("direction")


def _m(pkg, key):
    return pkg["latest_metrics"].get(key)


def red_flags(pkg):
    """The framework's combination checks.

    Single metrics mislead; these fire only when several move together,
    which is what gives them meaning.
    """
    flags = []
    ni_growth = _m(pkg, "net_income_growth_yoy")
    conv, accrual = _m(pkg, "cash_conversion"), _m(pkg, "accrual_ratio")
    cov, d2e, roe = _m(pkg, "interest_coverage"), _m(pkg, "debt_to_equity"), _m(pkg, "roe")
    ndte, roic = _m(pkg, "net_debt_to_ebitda"), _m(pkg, "roic")

    if conv is not None and conv < 0.8 and (ni_growth or 0) > 0:
        flags.append({
            "signal": "Kâr artıyor ama nakde dönmüyor",
            "evidence": "cash_conversion %.2f (0.80 altı), net kâr büyümesi %+.1f%%"
                        % (conv, ni_growth * 100),
            "severity": "yuksek",
            "benign_explanation": "Hızlı büyümede işletme sermayesi nakit emer; "
                                  "büyüme yavaşlarken geri gelir."})

    if accrual is not None and accrual > 0.05:
        flags.append({
            "signal": "Tahakkuk oranı yüksek",
            "evidence": "accrual_ratio %+.1f%% (%%5 üstü uyarı eşiği)" % (accrual * 100),
            "severity": "yuksek" if accrual > 0.10 else "orta",
            "benign_explanation": "Satın alma sonrası bilanço kalemleri geçici olarak şişer."})

    if cov is not None and cov < 2.0:
        sev = "yuksek" if cov < 1.5 else "orta"
        ev = "interest_coverage %.2f" % cov
        if ndte is not None:
            ev += ", net_debt_to_ebitda %.2f" % ndte
        if _direction(pkg, "net_debt_to_ebitda") == "deteriorating":
            ev += " ve kaldıraç kötüleşiyor"
            sev = "yuksek"
        flags.append({
            "signal": "Faaliyet kârı faiz giderini zar zor karşılıyor",
            "evidence": ev, "severity": sev,
            "benign_explanation": "Tek seferlik değer düşüklüğü faaliyet kârını "
                                  "bastırmış olabilir; nakit akışına bak."})

    # Superseded by the equity-quality flag below when equity is thin or
    # negative: that flag makes the same point without leaning on the two
    # ratios it is calling unreliable.
    equity_suspect = pkg.get("equity_negative") or pkg.get("equity_thin")
    if not equity_suspect and None not in (roe, d2e) and roe > 0.15 and d2e > 1.5:
        flags.append({
            "signal": "Yüksek özsermaye getirisi kaldıraçtan geliyor",
            "evidence": "roe %.1f%% ama debt_to_equity %.2f" % (roe * 100, d2e),
            "severity": "orta" if (cov or 9) > 3 else "yuksek",
            "benign_explanation": "Geri alım yapan olgun şirketlerde özsermaye "
                                  "küçülür ve oran mekanik olarak yükselir."})

    if (roic is not None and roic < 0.08
            and _direction(pkg, "roic") in ("deteriorating", "flat")):
        flags.append({
            "signal": "Sermaye getirisi maliyetinin altında",
            "evidence": "roic %.1f%% (sermaye maliyeti kabaca %%8-10), yön: %s"
                        % (roic * 100, _direction(pkg, "roic")),
            "severity": "yuksek" if roic < 0.05 else "orta",
            "benign_explanation": "Satın alınmış maddi olmayan varlıkların itfası "
                                  "nakit dışıdır ve sermaye tabanını şişirir."})

    if (_direction(pkg, "fcf_margin") == "deteriorating"
            and _direction(pkg, "roic") == "deteriorating"):
        flags.append({
            "signal": "Nakit marjı ve sermaye getirisi birlikte düşüyor",
            "evidence": "fcf_margin ve roic aynı yönde kötüleşiyor -- yatırım "
                        "döngüsü değer üretmiyor profili",
            "severity": "orta",
            "benign_explanation": "Getirisi gecikmeli gelen büyüme yatırımı da "
                                  "aynı izi bırakır; ayırt etmek için ROIC'in "
                                  "yatırım bitiminde toparlanması beklenir."})

    e2a = _m(pkg, "equity_to_assets")
    if pkg.get("equity_negative"):
        flags.append({
            "signal": "Defter özsermayesi negatif",
            "evidence": "equity_to_assets %+.1f%% -- roe ve debt_to_equity "
                        "hesaplanmadı, bu koşulda anlamsızdır"
                        % ((e2a or 0) * 100),
            "severity": "orta",
            "benign_explanation": "Uzun süreli hisse geri alımı defter "
                                  "özsermayesini eritir; kârlı şirketlerde "
                                  "yaygındır ve tek başına sıkıntı sinyali "
                                  "değildir. Kaldıraç için net_debt_to_ebitda "
                                  "ve interest_coverage'a bak."})
    elif pkg.get("equity_thin"):
        flags.append({
            "signal": "Özsermaye tabanı çok ince",
            "evidence": "equity_to_assets %.1f%% -- roe %s mekanik olarak şişkin, "
                        "derecelendirilmedi"
                        % ((e2a or 0) * 100,
                           ("%.1f%%" % (_m(pkg, "roe") * 100))
                           if _m(pkg, "roe") is not None else "-"),
            "severity": "orta",
            "benign_explanation": "Geri alım veya birikmiş zarar kaynaklı olabilir; "
                                  "yükümlülük karşılama gücü için faiz karşılamaya bak."})

    tax = _m(pkg, "effective_tax_rate")
    if tax is not None and not 0.05 < tax < 0.40:
        flags.append({
            "signal": "Efektif vergi oranı olağandışı",
            "evidence": "effective_tax_rate %+.1f%% -- net kâr tek seferlik vergi "
                        "kalemleriyle bozulmuş" % (tax * 100),
            "severity": "dusuk",
            "benign_explanation": "Zarar mahsubu veya karşılık çözülmesi; "
                                  "operating_margin daha temiz sinyaldir."})

    rank = {"yuksek": 0, "orta": 1, "dusuk": 2}
    return sorted(flags, key=lambda f: rank[f["severity"]])


SCORE_CAVEATS = {
    "piotroski": "Bu bir değişim skoru, seviye skoru değil. Başarısız testler "
                 "skorun kendisinden daha bilgilendiricidir.",
    "altman_z": "1968'de imalat şirketlerinde kalibre edildi ve faiz karşılama "
                "oranını hiç görmez.",
    "beneish_m": "Yanlış pozitif oranı yüksektir; hızlı büyüme ve satın almalar "
                 "skoru bayrağa iter. Dolandırıcılık kanıtı değildir.",
}


def score_reading(pkg):
    out = []
    s = pkg["scores"]
    if "piotroski" in s:
        f = s["piotroski"]
        failed = [k for k, v in f["tests"].items() if v == 0]
        out.append({"score": "piotroski",
                    "value": "%d/%d" % (f["score"], f["max"]),
                    "band": "strong" if f["score"] >= 7 else
                            "weak" if f["score"] <= 3 else "normal",
                    "detail": "Başarısız: " + (", ".join(failed) or "yok"),
                    "caveat": SCORE_CAVEATS["piotroski"]})
    z = s.get("altman_z") or {}
    if "z_double_prime" in z:
        out.append({"score": "altman_z", "value": "%.2f" % z["z_double_prime"],
                    "band": {"safe": "strong", "grey": "normal",
                             "distress": "weak"}[z["zone"]],
                    "detail": "Bölge: %s" % z["zone"],
                    "caveat": SCORE_CAVEATS["altman_z"]})
    if "beneish_m" in s:
        b = s["beneish_m"]
        out.append({"score": "beneish_m", "value": "%.2f" % b["m_score"],
                    "band": "normal" if b["flag"] else "strong",
                    "detail": "%s · %d/8 bileşen"
                              % ("Bayrak" if b["flag"] else "Temiz",
                                 b["components_used"]),
                    "caveat": SCORE_CAVEATS["beneish_m"]})
    return out


def watch_items(pkg, verdict_list, flag_list):
    """The metrics whose next move actually changes the read.

    A metric already in the strong band is left out even when a flag
    mentions it: telling the reader to watch for a 34% ROIC to clear 15% is
    noise, and it makes the whole list look unconsidered.
    """
    bands = {v["metric"]: v["band"] for v in verdict_list}
    items, seen = [], set()

    for f in flag_list:
        for key in ("interest_coverage", "roic", "cash_conversion",
                    "accrual_ratio", "net_debt_to_ebitda", "equity_to_assets"):
            if (key in f["evidence"] and key not in seen
                    and _m(pkg, key) is not None
                    and bands.get(key) != "strong"):
                seen.add(key)
                items.append(_watch(pkg, key, bands.get(key)))
    for v in verdict_list:
        if v["band"] == "weak" and v["metric"] not in seen and len(items) < 5:
            seen.add(v["metric"])
            items.append(_watch(pkg, v["metric"], "weak"))
    return items


def _watch(pkg, key, band=None):
    value = _m(pkg, key)
    sector = pkg["company"]["sector_bucket"]
    bounds = SECTOR_BANDS.get(sector, {}).get(key) or BANDS.get(key) or INVERTED.get(key)
    if bounds is None:
        return {"metric": key, "current": value,
                "confirms_if": "iyileşirse", "refutes_if": "kötüleşirse"}
    weak, strong = bounds
    inverted = key in INVERTED
    # For a metric already outside its acceptable band, the informative move
    # is crossing back over that boundary -- quoting the strong target and a
    # threshold it already breached reads as if nobody looked at the number.
    if band == "weak":
        edge = "%.2f %s inerse" % (weak, "altına") if inverted \
            else "%.2f üstüne çıkarsa" % weak
        return {"metric": key, "current": value,
                "confirms_if": edge,
                "refutes_if": "bu seviyede kalır veya kötüleşirse"}
    if inverted:
        return {"metric": key, "current": value,
                "confirms_if": "%.2f altına inerse" % strong,
                "refutes_if": "%.2f üstüne çıkarsa" % weak}
    return {"metric": key, "current": value,
            "confirms_if": "%.2f üstüne çıkarsa" % strong,
            "refutes_if": "%.2f altına inerse" % weak}


def confidence(pkg):
    cov, periods = pkg["data_coverage"], pkg["periods_available"]
    gaps = len(pkg["data_gaps"])
    reasons = ["veri kapsamı %%%d" % round(cov * 100), "%d dönem geçmiş" % periods]
    if gaps:
        reasons.append("%d raporlanmamış kalem" % gaps)
    if pkg["not_applicable_for_sector"]:
        reasons.append("%d metrik bu sektörde uygulanmıyor"
                       % len(pkg["not_applicable_for_sector"]))
    if periods < 12:
        level, reasons = "dusuk", reasons + ["12 çeyrekten az geçmiş -- trend yorumu yapılmadı"]
    elif cov >= 0.95 and gaps <= 1:
        level = "yuksek"
    elif cov >= 0.85:
        level = "orta"
    else:
        level = "dusuk"
    return {"level": level, "rationale": ", ".join(reasons) + "."}


def interpret(pkg):
    v = verdicts(pkg)
    f = red_flags(pkg)
    sector = pkg["company"]["sector_bucket"]
    return {
        "verdicts": v,
        "strengths": [x for x in v if x["band"] == "strong"],
        "concerns": [x for x in v if x["band"] == "weak"],
        "red_flags": f,
        "scores": score_reading(pkg),
        "watch_items": watch_items(pkg, v, f),
        "confidence": confidence(pkg),
        "sector_note": SECTOR_NOTES.get(sector),
        "method": "Kural tabanli -- knowledge/analysis-framework.md esiklerinden "
                  "deterministik olarak uretildi, dil modeli kullanilmadi.",
    }


if __name__ == "__main__":
    import sys
    import report as _report

    pkg = _report.build(sys.argv[1] if len(sys.argv) > 1 else "AAPL")
    r = interpret(pkg)
    c = pkg["company"]
    print("# %s (%s) -- %s" % (c["name"], c["ticker"], pkg["as_of"]))
    print("%s | guven: %s" % (c["industry"], r["confidence"]["level"]))
    if r["sector_note"]:
        print("\n%s" % r["sector_note"])
    print("\n## Kirmizi bayraklar")
    for f in r["red_flags"] or []:
        print("- [%s] %s" % (f["severity"], f["signal"]))
        print("    %s" % f["evidence"])
        if f["benign_explanation"]:
            print("    zararsiz alternatif: %s" % f["benign_explanation"])
    if not r["red_flags"]:
        print("- hicbir kombinasyon tetiklenmedi")
    print("\n## Guclu: %s" % (", ".join(x["metric"] for x in r["strengths"]) or "-"))
    print("## Zayif: %s" % (", ".join(x["metric"] for x in r["concerns"]) or "-"))
    print("\n## Izlenecekler")
    for w in r["watch_items"]:
        print("- %-22s simdi %-10s dogrular: %-22s curutur: %s"
              % (w["metric"], round(w["current"], 3), w["confirms_if"], w["refutes_if"]))
    print("\n%s" % r["method"])
