"""The mathematical cores of the indicator families, as separate components.

Two hundred indicators reduce to a few dozen computations (see ../map.py).
Each component here is one of them, named for what it measures and defined
by one formula on daily open, high, low, close and volume. They are the
vocabulary hypotheses are written in: a hypothesis combines components, it
does not pick an indicator.

Every component is a date x company array, known at that day's close.
"""
import numpy as np
import talib

# (name, family, formula) -- the catalog a hypothesis author reads.
CATALOG = [
    ("ma_gap50", "trend", "close / SMA(close, 50) - 1"),
    ("ma_gap200", "trend", "close / SMA(close, 200) - 1"),
    ("ma_cross", "trend", "SMA(close, 50) / SMA(close, 200) - 1"),
    ("ma_cross_fast", "trend", "SMA(close, 20) / SMA(close, 50) - 1"),
    ("brk20", "breakout", "close / highest close of the previous 20 days - 1 (> 0 = new 20-day closing high)"),
    ("brk55", "breakout", "close / highest close of the previous 55 days - 1"),
    ("bd10", "breakout", "close / lowest close of the previous 10 days - 1 (< 0 = new 10-day closing low)"),
    ("bd20", "breakout", "close / lowest close of the previous 20 days - 1"),
    ("slope20", "trend", "slope of a 20-day linear fit of close, over close"),
    ("adx", "trend strength", "ADX(14), 0-100, direction-free"),
    ("er20", "trend strength", "|close - close[20 days ago]| / sum of |daily changes| over 20 days, 0-1"),
    ("ret1", "momentum", "1-day return"),
    ("ret5", "momentum", "5-day return"),
    ("ret20", "momentum", "20-day return"),
    ("ret60", "momentum", "60-day return"),
    ("ret250", "momentum", "250-day return"),
    ("mom12_1", "momentum", "return from 252 to 21 days ago (12-month momentum, last month skipped)"),
    ("macd", "momentum", "MACD line (12/26) over close"),
    ("accel", "momentum change", "ret20 minus ret20 of 20 days ago"),
    ("z20", "stretch", "(close - SMA(close, 20)) / STD(close, 20): Bollinger position"),
    ("rsi", "stretch", "RSI(14), 0-100"),
    ("pos20", "stretch", "(close - lowest low 20) / (highest high 20 - lowest low 20), 0-1: stochastic"),
    ("high_gap250", "stretch", "close / highest high of 250 days - 1 (<= 0; 0 = at the 52-week high)"),
    ("low_gap250", "stretch", "close / lowest low of 250 days - 1 (>= 0)"),
    ("range14", "volatility", "ATR(14) / close: average daily range as a share of price"),
    ("range_ratio", "volatility change", "ATR(5) / ATR(60): above 1 = range expanding"),
    ("squeeze", "volatility change", "Bollinger width(20) / its own 250-day mean: below 1 = compressed"),
    ("vol20", "volatility", "standard deviation of daily returns over 20 days"),
    ("rvol", "volume", "volume / SMA(volume, 20): today's volume against usual"),
    ("vol_trend", "volume", "SMA(volume, 20) / SMA(volume, 120)"),
    ("cmf", "volume and price", "Chaikin money flow(20): volume-weighted close location, -1..1"),
    ("updown", "volume and price", "log(volume on up days / volume on down days) over 20 days"),
    ("obv_slope", "volume and price", "20-day change of on-balance volume / 20-day volume, -1..1"),
    ("clv5", "bar shape", "5-day mean of ((close-low) - (high-close)) / (high-low), -1..1"),
    ("gap", "bar shape", "open / previous close - 1"),
    ("liquidity", "size", "log of the 20-day mean of close x volume"),
    ("month", "calendar", "calendar month of the day, 1-12 (same for every company)"),
    ("days_in", "calendar", "trading days since the month began, 0 = first trading day"),
    ("days_left", "calendar", "trading days left in the month, 0 = last trading day"),
]
CALENDAR = ("month", "days_in", "days_left")
NAMES = [name for name, _, _ in CATALOG]


def _lag(x, n):
    out = np.full_like(x, np.nan)
    out[n:] = x[:-n]
    return out


def _rolling_sum(x, n):
    c = np.cumsum(np.nan_to_num(x))
    out = np.full_like(x, np.nan)
    out[n - 1:] = c[n - 1:] - np.concatenate([[0.0], c[:-n]])
    return out


def one(o, h, low, c, v):
    """Every component for one company's contiguous bars (float64 arrays)."""
    with np.errstate(all="ignore"):
        sma20, sma50, sma200 = talib.SMA(c, 20), talib.SMA(c, 50), talib.SMA(c, 200)
        sd20 = talib.STDDEV(c, 20)
        ret1 = talib.ROCP(c, 1)
        ret20 = talib.ROCP(c, 20)
        step = np.abs(np.diff(c, prepend=np.nan))
        hh20, ll20 = talib.MAX(h, 20), talib.MIN(low, 20)
        width = 4 * sd20 / sma20
        vsma20 = talib.SMA(v, 20)
        up = np.where(ret1 > 0, v, 0.0)
        down = np.where(ret1 < 0, v, 0.0)
        obv = talib.OBV(c, v)
        spread = h - low
        clv = np.where(spread > 0, ((c - low) - (h - c)) / spread, 0.0)
        return {
            "ma_gap50": c / sma50 - 1, "ma_gap200": c / sma200 - 1, "ma_cross": sma50 / sma200 - 1,
            "ma_cross_fast": sma20 / sma50 - 1,
            "brk20": c / _lag(talib.MAX(c, 20), 1) - 1, "brk55": c / _lag(talib.MAX(c, 55), 1) - 1,
            "bd10": c / _lag(talib.MIN(c, 10), 1) - 1, "bd20": c / _lag(talib.MIN(c, 20), 1) - 1,
            "slope20": talib.LINEARREG_SLOPE(c, 20) / c,
            "adx": talib.ADX(h, low, c, 14),
            "er20": np.abs(c - _lag(c, 20)) / _rolling_sum(step, 20),
            "ret1": ret1, "ret5": talib.ROCP(c, 5), "ret20": ret20,
            "ret60": talib.ROCP(c, 60), "ret250": talib.ROCP(c, 250),
            "mom12_1": _lag(c, 21) / _lag(c, 252) - 1,
            "macd": talib.MACDFIX(c)[0] / c,
            "accel": ret20 - _lag(ret20, 20),
            "z20": (c - sma20) / sd20, "rsi": talib.RSI(c, 14),
            "pos20": (c - ll20) / (hh20 - ll20),
            "high_gap250": c / talib.MAX(h, 250) - 1, "low_gap250": c / talib.MIN(low, 250) - 1,
            "range14": talib.ATR(h, low, c, 14) / c,
            "range_ratio": talib.ATR(h, low, c, 5) / talib.ATR(h, low, c, 60),
            "squeeze": width / talib.SMA(width, 250),
            "vol20": talib.STDDEV(ret1, 20),
            "rvol": v / vsma20, "vol_trend": vsma20 / talib.SMA(v, 120),
            "cmf": _rolling_sum(clv * v, 20) / _rolling_sum(v, 20),
            "updown": np.log(_rolling_sum(up, 20) / _rolling_sum(down, 20)),
            "obv_slope": (obv - _lag(obv, 20)) / _rolling_sum(v, 20),
            "clv5": talib.SMA(clv, 5),
            "gap": o / _lag(c, 1) - 1,
            "liquidity": np.log(talib.SMA(c * v, 20)),
        }


def compute(panel):
    """{name: date x company float32 array} for the whole panel."""
    shape = panel["close"].shape
    out = {name: np.full(shape, np.nan, dtype=np.float32) for name in NAMES}
    dates = [str(d) for d in panel["dates"]]
    first, last = {}, {}
    for i, d in enumerate(dates):
        first.setdefault(d[:7], i)
        last[d[:7]] = i
    for i, d in enumerate(dates):
        out["month"][i] = int(d[5:7])
        out["days_in"][i] = i - first[d[:7]]
        out["days_left"][i] = last[d[:7]] - i
    for j in range(shape[1]):
        ok = np.where(np.isfinite(panel["close"][:, j]))[0]
        if len(ok) < 300:
            continue
        a, b = ok[0], ok[-1] + 1
        cols = []
        for k in ("open", "high", "low", "close", "volume"):
            x = panel[k][a:b, j].astype(np.float64)
            gaps = ~np.isfinite(x)
            if gaps.any():          # a missing day inside the history: carry the last bar
                idx = np.where(gaps, 0, np.arange(len(x)))
                np.maximum.accumulate(idx, out=idx)
                x = x[idx]
            cols.append(x)
        got = one(*cols)
        for name in got:
            series = got[name]
            series[~np.isfinite(series)] = np.nan
            out[name][a:b, j] = series
    return out
