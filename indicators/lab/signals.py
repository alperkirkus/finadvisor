"""Today's signals and every past trade of the systems the product shows.

trades.py decides which systems are shown for a market (plan.md, Phase 23)
and keeps their record on the lab's panels. This runs the same systems on
fresh daily bars of the instruments that trade today and writes what the
application reads:

    data/signals/<market>.json                the systems, their record, and
                                              the instruments in a position
                                              or about to enter one
    data/signals/<market>/<instrument>.json   every trade each system made
                                              on that instrument since 2006

    signals.py refresh [market]    # fetch the bars again, then build
    signals.py build [market]      # build from the bars already fetched

What leads the list is the combined algorithm of a market and family
(combine.py, plan.md Phase 25): one signal per instrument, out of all the
systems that look at it. The single systems follow as its evidence.

The record of a system (three periods) is the lab's and includes companies
that no longer trade. An instrument's own journal is computed here, on
prices adjusted for splits and dividends, so its levels differ from the
quotes of the day. The list of systems was fixed on FIXED_ON; trades whose
signal came later are counted apart as `forward`, the only part of the
record that the choice of systems could not have seen.
"""
import json
import os
import sys
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import combine as K           # noqa: E402
import engine as E            # noqa: E402
import panel as P             # noqa: E402
import stops as X             # noqa: E402
import trades as T            # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
OUT = os.path.join(ROOT, "data", "signals")
RANKING = os.path.join(ROOT, "data", "ranking.json")
FIXED_ON = "2026-11-13"
START = "2006-01-01"
CHART_DAYS = 750

MARKETS = {
    "sp500": {"label": "ABD hisseleri", "lab": "sp500", "suffix": "", "currency": "USD"},
    "etf": {"label": "Endeks ve ETF", "lab": "etf", "suffix": "", "currency": "USD"},
    "bist": {"label": "BIST", "lab": "bist", "suffix": ".IS", "currency": "TRY"},
}

ETF_NAMES = {
    "SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000", "DIA": "Dow Jones",
    "MDY": "S&P 400 orta ölçek", "EFA": "Gelişmiş ülkeler (ABD dışı)", "EEM": "Gelişen ülkeler",
    "EWJ": "Japonya", "EWZ": "Brezilya", "FXI": "Çin büyük şirketler", "EWG": "Almanya",
    "EWU": "Birleşik Krallık", "EWW": "Meksika", "XLK": "Teknoloji", "XLF": "Finans",
    "XLE": "Enerji", "XLV": "Sağlık", "XLI": "Sanayi", "XLP": "Temel tüketim",
    "XLY": "İsteğe bağlı tüketim", "XLU": "Kamu hizmetleri", "XLB": "Hammadde",
    "VNQ": "Gayrimenkul", "TLT": "ABD 20+ yıl tahvil", "IEF": "ABD 7-10 yıl tahvil",
    "LQD": "Yatırım yapılabilir şirket tahvili", "HYG": "Yüksek getirili şirket tahvili",
    "TIP": "Enflasyona endeksli tahvil", "GLD": "Altın", "SLV": "Gümüş", "USO": "Petrol",
    "DBC": "Emtia sepeti", "UNG": "Doğal gaz", "UUP": "Dolar endeksi", "FXE": "Euro",
    "FXY": "Japon yeni",
}

# What the application calls a system and how it states its rule.
NAMES = {
    "sys_dip_rising_trend": (
        "Yükselen trendde sert düşüş",
        "Fiyat 20 günlük ortalamasının 2 standart sapma altına iner; 200 günlük ortalamanın "
        "üstündedir ve son 60 günde artıdadır. 20 günlük ortalamaya dönünce çıkılır."),
    "sys_no_news_dip": (
        "Habersiz düşüş",
        "Fiyat 20 günlük ortalamasının 2 standart sapma altına iner; son 5 günde hacim "
        "olağanın 1,5 katını aşmamış ve %2'den büyük aşağı boşluk olmamıştır. 20 günlük "
        "ortalamaya dönünce çıkılır."),
    "sys_calm_regime_dip": (
        "Sakin dönemde düşüş",
        "Fiyat 20 günlük ortalamasının 2 standart sapma altına iner; günlük aralığı kendi "
        "60 günlük ortalamasının altındadır. 20 günlük ortalamaya dönünce çıkılır."),
    "sys_shallow_dip_above_50d": (
        "50 günlüğün üstünde sığ düşüş",
        "Fiyat 20 günlük ortalamasının 1,5 standart sapma altına iner ama 50 günlük "
        "ortalamanın üstünde kalır; 20 günlük ortalama 50 günlüğün üstündedir. Ortalamanın "
        "1 standart sapma üstüne çıkınca çıkılır."),
    "sys_low_volume_pullback_trigger": (
        "Düşük hacimli geri çekilme",
        "50 günlük ortalama 200 günlüğün üstündedir; fiyat dün 20 günlük aralığının alt "
        "üçte birindedir, son 5 günün hacmi olağanın altındadır ve bugün artıda kapanır. "
        "20 günlük aralığın tepesine yaklaşınca çıkılır."),
    "sys_winner_oversold_orderly": (
        "Güçlü hissede aşırı satım",
        "Son 12 ayda %20'den fazla yükselmiş hissede RSI 35'in altına iner; günlük aralık "
        "genişlememiştir. RSI 55'i geçince çıkılır."),
    "sys_ts_momentum_turn": (
        "12 aylık getiri artıya dönüyor",
        "12 aylık getiri (son ay hariç) eksiden artıya geçer ve fiyat 200 günlük ortalamanın "
        "üstündedir. Fiyat 200 günlük ortalamanın altına inince çıkılır."),
    "sys_reclaim_200d_calm": (
        "Sıkışmışken 200 günlüğü geri alma",
        "Fiyat 200 günlük ortalamasını aşağıdan yukarı keser; Bollinger bandı kendi yıllık "
        "ortalamasından dardır. 200 günlüğün %3 altına inince çıkılır."),
    "sys_ma20_50_cross": (
        "20/50 ortalama kesişimi",
        "20 günlük ortalama 50 günlüğü yukarı keser. Aşağı kesince çıkılır."),
    "sys_golden_cross": (
        "Altın kesişim (50/200)",
        "50 günlük ortalama 200 günlüğü yukarı keser. Aşağı kesince çıkılır."),
    "sys_bollinger_uptrend": (
        "Yükselen trendde Bollinger alt bandı",
        "Fiyat 200 günlük ortalamasının üstündeyken Bollinger alt bandının altında kapanır. "
        "20 günlük ortalamaya dönünce çıkılır."),
    "sys_ma50_trend": (
        "50 günlük ortalamanın üstüne çıkış",
        "Fiyat 50 günlük ortalamasını yukarı keser. Aşağı kesince çıkılır."),
    "sys_macd_signal_cross": (
        "MACD sinyal kesişimi",
        "MACD çizgisi sinyal çizgisini yukarı keser. Aşağı kesince çıkılır."),
    "sys_macd_zero_uptrend": (
        "Yükselen trendde MACD sıfır kesişimi",
        "Fiyat 200 günlük ortalamasının üstündeyken MACD sıfırı yukarı keser. MACD sıfırın "
        "altına inince çıkılır."),
    "sys_turtle_20_10": (
        "20 günlük zirve kırılımı",
        "Fiyat son 20 günün en yüksek kapanışını aşar. 10 günün en düşük kapanışının altına "
        "inince çıkılır."),
    "sys_turtle_55_20": (
        "55 günlük zirve kırılımı",
        "Fiyat son 55 günün en yüksek kapanışını aşar. 20 günün en düşük kapanışının altına "
        "inince çıkılır."),
    "sys_breakout_volume": (
        "Hacimli 20 günlük kırılım",
        "Fiyat son 20 günün en yüksek kapanışını olağanın 1,5 katı hacimle aşar. 10 günün en "
        "düşük kapanışının altına inince çıkılır."),
    "sys_squeeze_breakout": (
        "Sıkışma sonrası kırılım",
        "Bollinger bandı kendi yıllık ortalamasının %70'inden darken fiyat 20 günlük zirveyi "
        "aşar. 10 günün en düşük kapanışının altına inince çıkılır."),
    "sys_adx_trend_start": (
        "ADX ile trend başlangıcı",
        "ADX 5 gün önce 20'nin altındayken 25'in üstüne çıkar ve fiyat 50 günlük ortalamanın "
        "üstündedir. Fiyat 50 günlüğün altına inince çıkılır."),
    "sys_squeeze_volume_breakout_room": (
        "Sıkışma, hacim ve trendle kırılım",
        "Fiyat 200 günlük ortalamanın üstündeyken, son 10 gün dar bantta geçtikten sonra "
        "20 günlük zirveyi olağanın 1,5 katı hacimle aşar. 20 günün en düşük kapanışının "
        "altına inince çıkılır."),
    "sys_higher_low_break": (
        "Yükselen dipten sonra kırılım",
        "Fiyat 20 gündür 50 günlük ortalamanın üstündedir, son 10 günde aralığının alt "
        "kısmına geri çekilmiş ve şimdi 20 günlük zirveyi aşmıştır. 20 günün en düşük "
        "kapanışının altına inince çıkılır."),
    "sys_base_breakout_room": (
        "Ortalamaya yakın 55 günlük kırılım",
        "Fiyat 55 günlük zirveyi aşar ama 50 günlük ortalamasından en çok %8 uzaktadır; "
        "50 günlük 200 günlüğün üstündedir. Fiyat 50 günlüğün altına inince çıkılır."),
    "sys_quiet_uptrend_volume_wake": (
        "Sessiz trendde hacim uyanışı",
        "50 günlük ortalama 200 günlüğün üstünde ve bant darken, fiyat olağanın 2 katı "
        "hacimle %1'den fazla yükselir. 10 günün en düşük kapanışının altına inince çıkılır."),
    "sys_base_accumulation": (
        "Yatay bantta birikim",
        "Fiyat 20 günde %4'ten az oynamış, hacim akışı alıcı yönünde ve fiyat 200 günlük "
        "ortalamanın üstündedir. 20 günlük dip kırılınca ya da RSI 75'i geçince çıkılır."),
    "sys_tight_flag_near_high": (
        "Zirve yakınında dar bayrak",
        "Fiyat 52 haftalık zirvesinin en çok %5 altındadır, günlük aralık ve hacim "
        "daralmıştır, fiyat 50 günlük ortalamanın üstündedir. 20 günün en düşük kapanışının "
        "altına inince çıkılır."),
    "sys_tight_range_strong_closes": (
        "Dar aralık, güçlü kapanışlar",
        "Bant darken son 5 gün günün üst kısmında kapanmış ve fiyat 50 günlük ortalamanın "
        "üstündedir. 10 günün en düşük kapanışının altına inince çıkılır."),
    "sys_fresh_55d_high": (
        "İlk 55 günlük zirve",
        "Fiyat, son 40 günde hiç yapmadığı 55 günlük zirveyi yapar. Fiyat 50 günlük "
        "ortalamanın altına inince çıkılır."),
    "sys_breakout_rising_participation": (
        "Artan katılımla kırılım",
        "Fiyat 20 günlük zirveyi aşar; 20 günlük ortalama 50 günlüğün üstündedir ve son "
        "20 günün hacmi 120 günlük ortalamanın %20 üstündedir. 20 günün en düşük kapanışının "
        "altına inince çıkılır."),
    "sys_strong_trend_mean_reclaim": (
        "Güçlü trendde ortalamayı geri alma",
        "ADX 30'un üstünde ve ortalamalar yukarı dizilmişken fiyat 20 günlük ortalamasını "
        "yukarı keser. 20 günlük ortalama 50 günlüğün altına inince çıkılır."),
    "sys_vol_drop_in_uptrend": (
        "Yükselen trendde oynaklık düşüşü",
        "Fiyat 200 günlük ortalamanın üstünde ve 50 günlük 200 günlüğün üstündeyken günlük "
        "aralık belirgin biçimde daralır. Fiyat 50 günlüğün altına inince ya da aralık "
        "yeniden genişleyince çıkılır."),
}

# The systems the product does not show on their own still vote in the
# combined algorithm, and are named when they agree with it.
SHORT = {
    "sys_52w_high": "52 haftalık zirveye dönüş", "sys_rsi30_bounce": "RSI 30'un altı",
    "sys_rsi30_uptrend": "Yükselen trendde RSI 30'un altı",
    "sys_bollinger_lower": "Bollinger alt bandının altı",
    "sys_stoch_oversold_up": "Yükselen trendde aralığın dibi",
    "sys_gap_down_uptrend": "Yükselen trendde aşağı boşluk",
    "sys_band_reentry": "Bollinger bandına geri dönüş",
    "sys_oversold_reversal_bar": "Aşırı satımda dönüş günü", "sys_rsi25_quick": "RSI 25'in altı",
    "sys_climax_stabilised": "Hacimli satış sonrası durulma",
    "sys_down_streak_uptrend": "Yükselen trendde dört gün düşüş",
    "sys_gap_down_recovered": "Aşağı boşluğun gün içinde toparlanması",
    "sys_rsi_divergence_retest": "RSI toparlanırken dibin yeniden denenmesi",
    "sys_band_dip_atr_stop": "Bollinger alt bandı (stoplu)",
    "sys_pullback_rsi_resume": "Geri çekilme sonrası RSI 50'yi geçiş",
    "sys_pullback_to_50d": "50 günlük ortalamaya geri çekilme",
    "sys_breakout_retest": "Kırılımın yeniden denenmesi",
    "sys_macd_recross_uptrend": "Yükselen trendde MACD yeniden kesişim",
    "sys_adx_trend_dip": "Güçlü trendde geri çekilme",
    "sys_fast_cross_calm": "Sakin dönemde 20/50 kesişimi",
    "sys_gap_and_hold": "Hacimli yukarı boşluk", "sys_accumulation_dip": "Alıcılı düşüş",
    "sys_vol_spike_absorbed": "Oynaklık sıçramasının emilmesi",
    "sys_smooth_trend_first_dip": "Düzgün trendde ilk düşüş",
    "sys_shock_resolved_up": "Sarsıntı sonrası sakinleşme",
    "sys_golden_state_dip": "Altın kesişim varken RSI 40'ın altı",
    "sys_early_golden_breakout": "Yeni altın kesişimde 55 günlük kırılım",
}
# How a tree's conditions read in the application.
FEATURE = {
    "votes": "aynı gün sinyal veren kural sayısı", "votes_5d": "son 5 günde sinyal veren kural sayısı",
    "votes_other_5d": "son 5 günde sinyal veren diğer aile kuralı sayısı",
    "breadth": "o gün aday olan enstrümanların payı", "adx": "ADX",
    "ma_cross": "50 günlük ortalamanın 200 günlüğe farkı", "rsi": "RSI",
    "ma_cross_fast": "20 günlük ortalamanın 50 günlüğe farkı", "z20": "Bollinger konumu",
    "ma_gap50": "fiyatın 50 günlük ortalamaya farkı", "ma_gap200": "fiyatın 200 günlük ortalamaya farkı",
    "ret250": "12 aylık getiri", "mom12_1": "12 aylık getiri (son ay hariç)",
    "high_gap250": "52 haftalık zirveye uzaklık", "low_gap250": "52 haftalık dibe uzaklık",
    "range14": "günlük aralık (ATR/fiyat)", "range_ratio": "günlük aralığın genişlemesi",
    "vol20": "20 günlük oynaklık", "cmf": "para akışı",
}


def name_of(system_id):
    return NAMES.get(system_id, (SHORT.get(system_id, system_id),))[0]


def conditions(tree, features, path):
    """A leaf of the tree as a sentence."""
    parts, node = [], tree
    for step in path:
        what = FEATURE.get(features[node["feature"]], features[node["feature"]])
        parts.append("%s %s %s" % (what, "en çok" if step == "L" else "en az",
                                   ("%.3g" % node["cut"]).replace(".", ",")))
        node = node["left"] if step == "L" else node["right"]
    return ", ".join(parts)


PERIOD_FIELDS = ("trades", "win_rate", "avg_win", "avg_loss", "expectancy", "baseline", "edge",
                 "t", "avg_days", "risk", "avg_r", "avg_win_r", "avg_loss_r", "stopped")


def _tr(x):
    return ("%g" % x).replace(".", ",")


def stop_text(system):
    """The stop policy of a system in the application's words."""
    spec = system.get("stop")
    if spec is None:
        x = system.get("stop_atr")
        spec = {"initial": ["atr", x]} if x else {}
    kind, size = spec.get("initial") or ("none", 0)
    trail, step = spec.get("trail") or ("none", 0)
    first = {"atr": "girişin %s ATR altı" % _tr(size) if kind == "atr" else "",
             "pct": "girişin %%%s altı" % _tr(100 * size) if kind == "pct" else "",
             "low": "sinyal günüyle biten %s günün en düşüğü" % _tr(size) if kind == "low" else "",
             "expr": "sinyal günü hesaplanan mesafe"}.get(kind)
    follow = {"chandelier": "girişten beri görülen en yüksek fiyatın %s ATR altı" % _tr(step)
              if trail == "chandelier" else "",
              "low": "önceki %s günün en düşüğü" % _tr(step) if trail == "low" else "",
              "pct": "girişten beri en yüksek kapanışın %%%s altı" % _tr(100 * step)
              if trail == "pct" else ""}.get(trail)
    parts = []
    if first and follow:
        parts.append("İlk stop %s; sonra %s, yalnızca yukarı taşınır." % (first, follow))
    elif first:
        parts.append("Stop %s, sabit." % first)
    elif follow:
        parts.append("Stop %s, yalnızca yukarı taşınır." % follow)
    else:
        parts.append("Stop yok; R hesaplanamaz.")
    if spec.get("breakeven_r"):
        parts.append("Fiyat +%sR'ye ulaşınca stop giriş fiyatına çekilir." % _tr(spec["breakeven_r"]))
    if spec.get("target_r"):
        part = spec.get("target_part") or 1
        parts.append("Hedef +%sR: %s." % (_tr(spec["target_r"]),
                                           "pozisyonun tamamı satılır" if part >= 1 else
                                           "pozisyonun %%%s'i satılır, kalanın stopu giriş fiyatına "
                                           "çekilir" % _tr(100 * part)))
    if spec.get("stall_days"):
        parts.append("%s gün sonra kapanış girişin altındaysa çıkılır." % _tr(spec["stall_days"]))
    if not spec.get("rule_exit", True):
        parts.append("Sistemin kendi çıkış kuralı kullanılmaz.")
    return " ".join(parts)


COMBINED = {
    "dip": ("Dipten alış",
            "Aday: düşüş alan %d kuraldan en az biri sinyal verir. %s Çıkış: fiyat 20 günlük "
            "ortalamasına dönünce."),
    "strength": ("Trendde alış",
                 "Aday: güçlenmeyi alan %d kuraldan en az biri sinyal verir. %s Çıkış: fiyat son "
                 "20 günün en düşük kapanışının altına inince."),
}
SCORE_TEXT = ("Adaylar tek bir skorla sıralanır: aynı gün kaç kuralın sinyal verdiği, son beş günde "
              "kaçının verdiği, o gün piyasada kaç aday olduğu ve trend, momentum, hacim, oynaklık "
              "ölçülerinin ağırlıklı toplamı (ağırlıklar 2006-2016'da öğrenildi). Yalnızca o "
              "dönemin en iyi %%%d'lik diliminin eşiğini geçen adaylar alınır.")
TREE_TEXT = ("Adaylardan yalnızca 2006-2016'da en iyi sonucu veren koşul gruplarına düşenler "
             "alınır (%s).")
VOTES_TEXT = "Yalnızca aynı gün en az %d kuralın sinyal verdiği adaylar alınır."


_LAB = {}


def _lab(universe):
    if universe not in _LAB:
        _LAB.clear()                     # one panel in memory at a time
        _LAB[universe] = E.Market(universe)
    return _LAB[universe]


def combined(market, m, through):
    """The combined algorithms of a market as the product's systems, with
    their trades on the live bars and, per trade, the systems that agreed
    on the signal day."""
    combo = K.load_result(MARKETS[market]["lab"])
    day = {d: i for i, d in enumerate(m.dates)}
    out = []
    for family, pick in (combo.get("choice") or {}).items():
        if pick is None or family not in combo.get("sealed", {}):
            continue
        model = combo["models"][family]
        variant = model["variants"][pick]
        entry, st = K.take(m, model, variant)
        template = K.TEMPLATES[family]
        system = {"id": "combined_" + family, "entry": entry, **template}
        trades = T.simulate(m, system, START, through, live=True)
        for t in trades:
            fired = st["own"][:, day[t["signal"]], t["column"]]
            t["agree"] = [name_of(x) for x, on in zip(model["members"], fired) if on]
        title, text = COMBINED[family]
        lab = _lab(MARKETS[market]["lab"])
        lab_entry, _ = K.take(lab, model, variant)
        record = performance(lab, T.simulate(lab, {**system, "entry": lab_entry}, START,
                                             lab.dates[-1], live=True),
                             symbols(market), lab.dates[-1])
        how = (SCORE_TEXT % variant["top"] if variant["kind"] == "ridge" else
               VOTES_TEXT % variant["k"] if variant["kind"] == "votes" else
               TREE_TEXT % "; ".join(conditions(model["tree"], model["features"], p)
                                     for p in variant["leaves"]))
        sealed = combo["sealed"][family]
        out.append({
            "system": system, "trades": trades, "title": title,
            "rule": text % (len(model["members"]), how),
            "status": "listed" if sealed["confirmed"] else "marked",
            "periods": {"discover": combo["discover"][family][str(pick)],
                        "validate": combo["validate"][family][str(pick)],
                        "sealed": sealed["chosen"]},
            "baseline": {"discover": combo["discover"][family]["0"],
                         "validate": combo["validate"][family]["0"], "sealed": sealed["all"]},
            "members": len(model["members"]), "performance": record})
    return out


COST_STEPS = (0.0, 0.0005, 0.001, 0.002, 0.003, 0.005)
REGIMES = (("down", 0.0, 0.4), ("mixed", 0.4, 0.6), ("up", 0.6, 1.01))


def _group(trades):
    net = np.array([t["net"] for t in trades])
    r = np.array([t["r"] for t in trades])
    return {"trades": len(trades), "win_rate": float((net > 0).mean()), "net": float(net.mean()),
            "avg_r": float(r.mean()), "sum_r": float(r.sum())}


def _streak(flags):
    best = run = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return best


UNSEEN = "2017-01-01"                    # the algorithms were fitted on the years before
SLOTS = 5                                # positions the account of the Performans tab may hold


def performance(m, trades, names, through):
    """The closed trades of an algorithm on the live bars, as the questions
    an owner asks: how many, how often right, how much, how bad in a row,
    by year, by state of the market, by instrument, at other costs, and
    what an account that cannot take every signal would have done, beside
    what holding every member in equal parts paid. Only the years the
    algorithm was not fitted on count, except in the table by year, which
    shows them all and says which is which. It is given the lab's panel,
    not today's instruments, so companies that left are in it."""
    closed = [t for t in trades if t["reason"] not in ("open", "pending") and t["r"] is not None]
    every_year = defaultdict(list)
    for t in closed:
        every_year[t["entry"][:4]].append(t)
    done = [t for t in closed if t["signal"] >= UNSEEN]
    if len(done) < 30:
        return None
    net = np.array([t["net"] for t in done])
    gross = np.array([t["gross"] for t in done])
    r = np.array([t["r"] for t in done])
    won = net > 0
    in_order = sorted(done, key=lambda t: (t["exit"], t["entry"]))
    above = (m.parts["ma_gap200"] > 0) & m.member
    known = np.isfinite(m.parts["ma_gap200"]) & m.member
    share = above.sum(axis=1) / np.maximum(known.sum(axis=1), 1)
    day = {d: i for i, d in enumerate(m.dates)}
    by_year, by_regime, by_instrument = defaultdict(list), defaultdict(list), defaultdict(list)
    for t in done:
        by_year[t["entry"][:4]].append(t)
        s = share[day[t["signal"]]]
        by_regime[next(k for k, lo, hi in REGIMES if lo <= s < hi)].append(t)
        by_instrument[t["instrument"]].append(t)
    for t in done:
        t["weight"] = min(T.RISK / t["risk"], T.CAP)
    account = X.account(m, done, span=(UNSEEN, through), slots=SLOTS)
    # What simply holding paid over the same days: every member in equal
    # parts, rebalanced daily, no costs.
    close = m.bars["close"]
    span = np.array([UNSEEN <= d <= through for d in m.dates])
    with np.errstate(all="ignore"):
        daily = close[1:] / close[:-1] - 1
    both = m.member[:-1] & np.isfinite(daily) & span[1:, None]
    mean = np.where(both, daily, 0).sum(axis=1) / np.maximum(both.sum(axis=1), 1)
    curve = np.cumprod(1 + mean[span[1:]])
    holding = {"yearly": float(curve[-1] ** (252 / len(curve)) - 1),
               "drawdown": float((curve / np.maximum.accumulate(curve) - 1).min())}
    years = max((day[through] - day[min(t["entry"] for t in done)]) / 252, 1)
    return {
        "since": UNSEEN[:4], "trades": len(done), "years": round(years, 1),
        "per_year": len(done) / years,
        "win_rate": float(won.mean()), "avg_win": float(net[won].mean()),
        "avg_loss": float(net[~won].mean()), "avg_win_r": float(r[won].mean()),
        "avg_loss_r": float(r[~won].mean()), "avg_r": float(r.mean()), "net": float(net.mean()),
        "gross": float(gross.mean()), "risk": float(np.mean([t["risk"] for t in done])),
        "sum_r": float(r.sum()), "avg_days": float(np.mean([t["days"] for t in done])),
        "breakeven_win_rate": float(-r[~won].mean() / (r[won].mean() - r[~won].mean())),
        "longest_losing_run": _streak(t["net"] <= 0 for t in in_order),
        "longest_stop_run": _streak(t["reason"] == "stop" for t in in_order),
        "stopped": float(np.mean([t["reason"] == "stop" for t in done])),
        "gapped": float(np.mean([t["gapped"] for t in done])),
        "worst": float(net.min()), "best": float(net.max()),
        "by_year": [{"year": y, "fitted": y < UNSEEN[:4], **_group(ts)}
                    for y, ts in sorted(every_year.items())],
        "by_regime": [{"regime": k, **_group(by_regime[k])} for k, _, _ in REGIMES if by_regime[k]],
        "by_instrument": sorted(({"instrument": k, "name": names.get(k, k), **_group(ts)}
                                 for k, ts in by_instrument.items() if len(ts) >= 10),
                                key=lambda x: -x["avg_r"]),
        "instruments_traded": len(by_instrument),
        "costs": [{"per_side": c, "net": float((gross - 2 * c).mean()),
                   "win_rate": float((gross - 2 * c > 0).mean())} for c in COST_STEPS],
        "account": account, "slots": SLOTS, "holding": holding, "through": through}


def fundamentals():
    """{ticker: what the company side says today}, for the S&P 500 page."""
    if not os.path.exists(RANKING):
        return {}
    keep = ("verdict", "rationale", "business_score", "valuation_score", "upside", "risk")
    return {r["ticker"]: {k: r.get(k) for k in keep} for r in json.load(open(RANKING))["rows"]}


def _live(market):
    name = "live_" + market
    E.UNIVERSES[name] = ("panel_%s.npz" % name, E.UNIVERSES[MARKETS[market]["lab"]][1])
    return name


def symbols(market):
    """{yahoo symbol without suffix: display name}."""
    if market == "etf":
        return {s: ETF_NAMES.get(s, s) for s in P.ETFS}
    if market == "bist":
        return {s: s for s in P.BIST}
    if not os.path.exists(RANKING):
        raise SystemExit("data/ranking.json yok: python src/ranking.py")
    return {r["ticker"]: r.get("name") or r["ticker"] for r in json.load(open(RANKING))["rows"]}


def fetch(market):
    P.build_list("live_" + market, sorted(symbols(market)), MARKETS[market]["suffix"])


def period(day):
    for stage, (first, last) in E.STAGES.items():
        if first <= day <= last:
            return stage
    return "forward" if day > FIXED_ON else "after"


def _digits(x):
    return None if x is None else float("%.5g" % x)


def public(t):
    live = t["reason"] in ("open", "pending")
    return {"signal": t["signal"], "entry": t["entry"], "entry_price": _digits(t["entry_price"]),
            "exit": None if live else t["exit"], "exit_price": _digits(t["exit_price"]),
            "reason": t["reason"], "days": t["days"], "net": round(t["net"], 4),
            "period": period(t["signal"]), "stop": _digits(t["stop"]), "closing": t["closing"],
            "stop_now": _digits(t["stop_now"]),
            "risk": None if t["risk"] is None else round(t["risk"], 4),
            "r": None if t["r"] is None else round(t["r"], 2), "gapped": t["gapped"],
            **({"agree": t["agree"]} if "agree" in t else {})}


def summary(trades):
    """Closed trades only: how many, how many won, the mean net result."""
    done = [t for t in trades if t["reason"] not in ("open", "pending")]
    if not done:
        return {"trades": 0, "wins": 0, "net": None, "r": None}
    net = [t["net"] for t in done]
    r = [t["r"] for t in done]
    return {"trades": len(net), "wins": sum(x > 0 for x in net), "net": round(sum(net) / len(net), 4),
            "r": None if any(x is None for x in r) else round(sum(r) / len(r), 2)}


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    os.replace(path + ".tmp", path)


def build(market):
    cfg = MARKETS[market]
    rows = E.ledger(cfg["lab"])
    chosen = T.shown(rows)
    if any("sealed" not in s for s in chosen):
        raise SystemExit("%s: once `trades.py --universe %s product`" % (market, cfg["lab"]))
    names = symbols(market)
    restated = X.load_result(cfg["lab"]).get("restated", {})
    m = E.Market(_live(market))
    through, close = m.dates[-1], m.bars["close"]
    column = {label: j for j, label in enumerate(m.labels)}
    systems, signals, journals = [], [], defaultdict(list)
    joint = combined(market, m, through)
    for c in joint:
        by_instrument = defaultdict(list)
        for t in c["trades"]:
            by_instrument[t["instrument"]].append(t)
        systems.append({
            "id": c["system"]["id"], "title": c["title"], "rule": c["rule"], "status": c["status"],
            "combined": True, "members": c["members"], "stop_text": stop_text(c["system"]),
            "performance": c["performance"],
            "max_days": c["system"]["max_days"],
            "periods": {stage: {k: c["periods"][stage].get(k) for k in PERIOD_FIELDS}
                        for stage in E.STAGES},
            "baseline": {stage: {k: c["baseline"][stage].get(k) for k in PERIOD_FIELDS}
                         for stage in E.STAGES},
            "after": summary([t for t in c["trades"] if period(t["signal"]) == "after"]),
            "forward": summary([t for t in c["trades"] if period(t["signal"]) == "forward"])})
        for label, own in by_instrument.items():
            last = own[-1]
            state = last["reason"] if last["reason"] in ("open", "pending") else "flat"
            journals[label].append({"id": c["system"]["id"], "title": c["title"],
                                    "status": c["status"], "combined": True, "state": state,
                                    "own": summary(own),
                                    "trades": [public(t) for t in reversed(own)]})
            if state != "flat":
                signals.append({"instrument": label, "name": names.get(label, label),
                                "system": c["system"]["id"], "title": c["title"], "state": state,
                                "combined": True, "status": c["status"], "own": summary(own),
                                **public(last)})
    for s in chosen:
        d = s["discover"]
        system = {"id": d["id"], **d["system"]}
        listed = T.good(s["sealed"]["stats"])
        periods = {stage: s[stage]["stats"] for stage in E.STAGES}
        # Phase 24: the stop chosen for the system's market and family, and
        # its record restated with that stop.
        mine = restated.get(d["id"])
        if mine:
            if mine["stop"] != "authored":
                system["stop"] = mine["stop"]
            periods = mine["periods"]
            listed = listed and T.good(periods["sealed"])
        title, rule = NAMES.get(d["id"], (d["id"], d["rationale"]))
        trades = T.simulate(m, system, START, through, live=True)
        by_instrument = defaultdict(list)
        for t in trades:
            by_instrument[t["instrument"]].append(t)
        systems.append({
            "id": d["id"], "title": title, "rule": rule, "status": "listed" if listed else "marked",
            "entry": system["entry"], "exit": system["exit"], "stop_text": stop_text(system),
            "max_days": system["max_days"],
            "periods": {stage: {k: periods[stage].get(k) for k in PERIOD_FIELDS}
                        for stage in E.STAGES},
            "after": summary([t for t in trades if period(t["signal"]) == "after"]),
            "forward": summary([t for t in trades if period(t["signal"]) == "forward"])})
        for label, own in by_instrument.items():
            last = own[-1]
            state = last["reason"] if last["reason"] in ("open", "pending") else "flat"
            journals[label].append({"id": d["id"], "title": title, "status": systems[-1]["status"],
                                    "state": state, "own": summary(own),
                                    "trades": [public(t) for t in reversed(own)]})
            if listed and state != "flat":
                signals.append({"instrument": label, "name": names.get(label, label),
                                "system": d["id"], "title": title, "state": state,
                                "own": summary(own), **public(last)})
    systems.sort(key=lambda x: (not x.get("combined"), x["status"] != "listed", x["id"]))
    signals.sort(key=lambda x: (not x.get("combined"), x["state"] != "pending", x["days"],
                                x["instrument"]))
    generated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write(os.path.join(OUT, market + ".json"), {
        "market": market, "label": cfg["label"], "currency": cfg["currency"],
        "generated_at": generated, "through": through, "fixed_on": FIXED_ON,
        "cost_per_side": m.cost, "tried": len(T.by_system(rows)), "shown": len(chosen),
        "risk_per_trade": T.RISK, "position_cap": T.CAP, "stops_restated": bool(restated),
        "listed": sum(x["status"] == "listed" and not x.get("combined") for x in systems),
        "combined": [x["id"] for x in systems if x.get("combined")],
        "instruments": [{"instrument": label, "name": names.get(label, label)}
                        for label in sorted(m.labels)],
        "systems": systems, "signals": signals})
    company = fundamentals() if market == "sp500" else {}
    for label, j in column.items():
        ok = np.where(np.isfinite(close[:, j]))[0][-CHART_DAYS:]
        _write(os.path.join(OUT, market, label + ".json"), {
            "instrument": label, "name": names.get(label, label), "market": market,
            "currency": cfg["currency"], "through": through, "generated_at": generated,
            "fundamental": company.get(label),
            "prices": [[m.dates[i]] + [_digits(float(m.bars[k][i, j]))
                                       for k in ("open", "high", "low", "close")] for i in ok],
            "systems": sorted(journals.get(label, []),
                              key=lambda x: (not x.get("combined"), x["status"] != "listed",
                                             x["id"]))})
    print("%s: %s itibariyla %d birlesik algoritma, %d sistem, %d enstruman; birlesik "
          "sinyal/pozisyon %d, tek tek %d"
          % (market, through, len(joint), len(systems) - len(joint), len(column),
             sum(bool(x.get("combined")) for x in signals),
             sum(not x.get("combined") for x in signals)))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "build"
    if command not in ("refresh", "build"):
        raise SystemExit("bilinmeyen komut: %s" % command)
    for name in sys.argv[2:] or list(MARKETS):
        if name not in MARKETS:
            raise SystemExit("bilinmeyen piyasa: %s" % name)
        if command == "refresh":
            fetch(name)
        build(name)
