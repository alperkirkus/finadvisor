"""Market regime: is the S&P 500 above its 200-day average?

The portfolio backtest (strategy.py, README) found this one switch to be the
layer with the strongest evidence: stock picking by trend and momentum added
nothing, but stepping out of stocks while the index sat below its 200-day
average roughly halved the worst drawdown at a similar return. The rule is
checked at month end, as in the backtest; today's position is shown too, but
a daily crossing is not a signal under the tested rule.
"""
import json
import time
import urllib.request

import valuation as V

INDEX = "%5EGSPC"
SMA_DAYS = 200
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
       "?range=2y&interval=1d")
UA = "Mozilla/5.0 (FinAdvisor research)"

# strategy.py SPY_regime, 2006-2025, monthly check, 10 bp per switch, T-bills when off.
# Exploratory: the rule was chosen after the pre-registered test (Phase 8).
EVIDENCE = {
    "window": "2006-2025",
    "with_rule": {"cagr": 0.103, "vol": 0.101, "sharpe": 0.86, "maxdd": -0.222},
    "index": {"cagr": 0.108, "vol": 0.151, "sharpe": 0.65, "maxdd": -0.508},
    "switches": 26,
    "note": ("Keşif amaçlı: kural ön kayıtlı testten sonra seçildi. 2007'de "
             "yayımlanmış (Faber), test döneminin çoğu yayından sonra. Ani "
             "çöküşlerde geç kalır (2020'de −%22), yatay piyasada boşa al-sat yapar."),
}


@V._ttl
def _daily(symbol):
    req = urllib.request.Request(URL % symbol, headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=25).read())["chart"]["result"][0]
    closes = d["indicators"]["quote"][0]["close"]
    return [(time.strftime("%Y-%m-%d", time.gmtime(t)), c)
            for t, c in zip(d["timestamp"], closes) if c]


def _state(series, i):
    window = [c for _, c in series[i - SMA_DAYS + 1:i + 1]]
    sma = sum(window) / SMA_DAYS
    return series[i][1] > sma, series[i][1], sma


def read(series=None):
    """Today's position and the month-end signal the tested rule acts on."""
    series = series or _daily(INDEX)
    if len(series) < SMA_DAYS + 25:
        raise ValueError("200 günlük ortalama için yeterli geçmiş yok")
    last = len(series) - 1
    on_now, close, sma = _state(series, last)

    month_ends = [i for i in range(SMA_DAYS - 1, last)
                  if series[i][0][:7] != series[i + 1][0][:7]]
    # The current month has not ended yet, so its last day is not a month end.
    signal_i = month_ends[-1]
    on_signal, close_m, sma_m = _state(series, signal_i)

    since = None
    for i in reversed(month_ends[:-1]):
        if _state(series, i)[0] != on_signal:
            since = series[month_ends[month_ends.index(i) + 1]][0]
            break

    return {
        "as_of": series[last][0],
        "close": round(close, 2),
        "sma200": round(sma, 2),
        "distance": round(close / sma - 1, 4),
        "above_now": on_now,
        "signal": "risk_on" if on_signal else "risk_off",
        "signal_date": series[signal_i][0],
        "signal_distance": round(close_m / sma_m - 1, 4),
        "signal_since": since,
        "evidence": EVIDENCE,
    }


if __name__ == "__main__":
    r = read()
    print(json.dumps({k: v for k, v in r.items() if k != "evidence"}, indent=1))
