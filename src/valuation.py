"""Price-based valuation and an explicit investability verdict.

The rest of the engine deliberately never sees a price, which is why it can
only describe how a business performs. This module adds the missing half:
what the market is paying for it, what the price implies about the future,
and a criteria-based verdict.

Two things here are assumptions rather than filings, and both are stated in
the output: the discount rate, and the growth fade used in the forecast.
Everything else comes from the evidence package or the quote.
"""
import json
import math
import threading
import time
import urllib.error
import urllib.request

import edgar

UA = "Mozilla/5.0 (FinAdvisor research)"

# Unofficial endpoint -- no key, no documented contract. Fine for research,
# and the single function below is the only thing to swap for a licensed
# feed if this ever ships.
QUOTE_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
             "%s?range=1mo&interval=1d")
HISTORY_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
               "%s?range=5y&interval=1mo")
MARKET_INDEX = "%5EGSPC"      # S&P 500
TREASURY_10Y = "%5ETNX"       # 10-year yield, quoted in percent

# Equity risk premium. A forward-looking implied ERP for the US market has
# sat in the 4-5% range for years; a single assumption is honest here
# because the alternative is a false precision.
EQUITY_RISK_PREMIUM = 0.045

# No listed equity is meaningfully less risky than half the market.
BETA_FLOOR = 0.50

# Fallback discount rates by sector, used only when a beta cannot be
# regressed (too little price history). A flat sector rate applied to every
# company is badly wrong -- it discounts Coca-Cola at the same rate as a
# semiconductor firm and makes every defensive name look overvalued -- so
# the real cost of capital is computed per company below.
WACC_FALLBACK = {
    "manufacturing": 0.085, "retail": 0.075, "other": 0.095,
    "energy": 0.090, "utility": 0.055, "financial": 0.090,
    "real_estate": 0.070, "unknown": 0.085,
}
TERMINAL_GROWTH = 0.025
LIVE_PRICE_MAX_AGE = 7     # days before a live run refetches the price history
HORIZON = 10


def quote(ticker):
    req = urllib.request.Request(QUOTE_URL % ticker, headers={"User-Agent": UA})
    # One retry: a screen fetches hundreds of quotes in parallel and Yahoo
    # answers the occasional one with a transient error.
    for attempt in (1, 2):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=20).read())
            break
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError("fiyat alinamadi: %s" % exc)
            time.sleep(1.5)
    meta = d["chart"]["result"][0]["meta"]
    closes = [c for c in d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
              if c is not None]
    return {"price": meta["regularMarketPrice"],
            "currency": meta.get("currency", "USD"),
            "exchange": meta.get("fullExchangeName"),
            "as_of_epoch": meta.get("regularMarketTime"),
            "month_low": min(closes) if closes else None,
            "month_high": max(closes) if closes else None,
            "source": "Yahoo Finance (resmi olmayan uc nokta)"}


_TTL_SECONDS = 3600
_ttl_store, _ttl_lock = {}, threading.Lock()


def _ttl(fn):
    """Remember a market fetch for an hour. A screen of 500 companies would
    otherwise download the S&P 500 history and the 10-year yield 500 times;
    an hour keeps a long-running API from serving a stale beta."""
    def wrapped(*args):
        key = (fn.__name__,) + args
        now = time.time()
        with _ttl_lock:
            hit = _ttl_store.get(key)
            if hit and now - hit[0] < _TTL_SECONDS:
                return hit[1]
        value = fn(*args)
        if value is not None:
            with _ttl_lock:
                _ttl_store[key] = (now, value)
        return value
    wrapped.__name__ = fn.__name__
    return wrapped


@_ttl
def _monthly_closes(symbol):
    req = urllib.request.Request(HISTORY_URL % symbol, headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=25).read())
    result = d["chart"]["result"][0]
    closes = result["indicators"]["adjclose"][0]["adjclose"] \
        if "adjclose" in result["indicators"] \
        else result["indicators"]["quote"][0]["close"]
    stamps = result["timestamp"]
    return [(t, c) for t, c in zip(stamps, closes) if c is not None]


def _returns(pairs):
    return {t: (b / a - 1) for (_, a), (t, b) in zip(pairs, pairs[1:]) if a}


def beta(ticker):
    """Regresses monthly returns against the S&P 500 over five years.

    Beta is the one input that cannot be read off a filing, and assuming a
    sector average for it is what makes a naive DCF misprice defensive
    businesses so badly.
    """
    try:
        stock = _returns(_monthly_closes(ticker))
        market = _returns(_monthly_closes(MARKET_INDEX))
    except Exception:
        return None
    return _regress_beta(stock, market)


def beta_asof(stock_closes, market_closes, asof, months=60):
    """The beta a live run would have regressed on `asof`.

    Same regression as `beta`, over the `months` monthly returns ending at
    the as-of month, from {YYYY-MM: close} series.
    """
    end = asof[:7]
    keys = sorted(k for k in stock_closes if k <= end and k in market_closes)
    keys = keys[-(months + 1):]
    pairs_s = [(k, stock_closes[k]) for k in keys]
    pairs_m = [(k, market_closes[k]) for k in keys]
    return _regress_beta(_returns(pairs_s), _returns(pairs_m))


def _regress_beta(stock, market):
    shared = sorted(set(stock) & set(market))
    if len(shared) < 36:
        return None
    xs = [market[t] for t in shared]
    ys = [stock[t] for t in shared]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if not var:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return {"beta": round(cov / var, 3), "months": len(shared)}


# The 10-year yield enters every cost of equity, and a justified P/B
# divides by (Ke - g), about six points: a quarter-point move in the spot
# yield moved bank fair values by 4% in four days with no news from any
# bank. The rate used is the mean of the last three months of daily closes;
# the backtest takes the same three months to its as-of month.
RISK_FREE_MONTHS = 3
RISK_FREE_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
                 "?range=%dmo&interval=1d")


@_ttl
def risk_free_rate():
    try:
        req = urllib.request.Request(RISK_FREE_URL % (TREASURY_10Y, RISK_FREE_MONTHS),
                                     headers={"User-Agent": UA})
        d = json.loads(urllib.request.urlopen(req, timeout=20).read())
        closes = [c for c in d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
                  if c is not None and math.isfinite(c) and c > 0]
        if len(closes) < 20 * RISK_FREE_MONTHS // 2:
            return None
        return round(sum(closes) / len(closes) / 100, 4)
    except Exception:
        return None


def cost_of_capital(pkg, mcap, debt, market=None):
    """Per-company WACC: CAPM equity cost, realised debt cost, market weights.

    `market` supplies the risk-free rate and beta as of a past date. In that
    mode a missing input raises instead of falling back to the sector rate:
    a backtest scored on a substituted rate would measure the substitute.
    """
    sector = pkg["company"]["sector_bucket"]
    m = pkg["latest_metrics"]
    if market is not None:
        rf, b = market.get("risk_free"), market.get("beta")
        if rf is None or b is None or not mcap:
            raise RuntimeError("point-in-time risk-free rate or beta missing")
    else:
        rf = risk_free_rate()
        b = beta(pkg["company"]["ticker"])
    if rf is None or b is None or not mcap:
        return {"wacc": WACC_FALLBACK.get(sector, WACC_FALLBACK["unknown"]),
                "method": "sektor varsayimi (beta veya faiz alinamadi)"}

    # A regressed beta near zero would imply equity is nearly riskless, which
    # it never is -- Exxon prints 0.18 over this window. Flooring the beta
    # rather than the premium is the lighter of the two conventions and keeps
    # low-beta defensives from being discounted almost like a bond.
    # Blume (1971) adjustment, the convention behind published adjusted
    # betas: raw regression betas drift toward 1, so 2/3 raw + 1/3 market.
    # Insurers get a floor of 0.8: catastrophe risk does not move with the
    # market, so a regressed beta of 0.2 understates what holders require.
    adjusted = 0.67 * b["beta"] + 0.33
    sic = pkg["company"].get("sic")
    try:
        insurer = 6300 <= int(sic) <= 6499
    except (TypeError, ValueError):
        insurer = False
    beta_used = max(adjusted, 0.8 if insurer else BETA_FLOOR)
    ke = rf + beta_used * EQUITY_RISK_PREMIUM
    tax = m.get("effective_tax_rate")
    tax = 0.21 if tax is None or not 0 <= tax <= 0.5 else tax

    interest = m.get("interest_coverage")
    op = m.get("operating_margin")
    rev = m.get("revenue_ttm")
    kd = None
    if debt and interest and op and rev:
        # Interest expense is recoverable from the coverage ratio and
        # operating income, both already computed.
        kd = (op * rev / interest) / debt
    # Reported interest over debt can sit below the risk-free rate when
    # interest is capitalised (Exxon: 1.5%); no company borrows below it.
    if kd is None or not rf < kd < 0.20:
        kd = max(rf + 0.01, 0.035)

    equity_w = mcap / (mcap + (debt or 0))
    wacc = equity_w * ke + (1 - equity_w) * kd * (1 - tax)
    # Kept inside a defensible band: outside it the terminal value dominates
    # or turns negative and the output stops being informative.
    wacc = max(0.045, min(0.16, wacc))
    return {"wacc": round(wacc, 4), "method": "CAPM + gerceklesmis borc maliyeti",
            "beta": b["beta"], "beta_used": round(beta_used, 3),
            "beta_floored": beta_used > b["beta"],
            "beta_months": b["months"],
            "risk_free": rf, "equity_risk_premium": EQUITY_RISK_PREMIUM,
            "cost_of_equity": round(ke, 4), "cost_of_debt": round(kd, 4),
            "tax_rate_used": round(tax, 4), "equity_weight": round(equity_w, 3)}


def shares_outstanding(cik, splits=None):
    """Latest filed share count, on today's split basis when `splits` is
    given: a split after the last filing would otherwise halve (or double)
    the market value against a post-split quote."""
    counts = edgar.share_count_detail(edgar.companyfacts(cik))
    if not counts:
        return None
    value, filed = counts[max(counts)]
    return edgar.to_price_basis(value, filed, splits) if splits else value


def _dcf(fcf0, growth, wacc, years=HORIZON, terminal=TERMINAL_GROWTH):
    """Present value of a fading-growth cash-flow stream plus a terminal value.

    Growth fades linearly from `growth` to the terminal rate over the
    horizon rather than stepping down at the end, which is both more
    plausible and less sensitive to where the horizon is cut.
    """
    if wacc <= terminal:
        return None
    pv, fcf = 0.0, fcf0
    for year in range(1, years + 1):
        g = growth + (terminal - growth) * (year - 1) / max(1, years - 1)
        fcf *= (1 + g)
        pv += fcf / (1 + wacc) ** year
    tv = fcf * (1 + terminal) / (wacc - terminal)
    return pv + tv / (1 + wacc) ** years


def path_cagr(first_year_growth, years=HORIZON, terminal=TERMINAL_GROWTH):
    """Average yearly growth of the fading path `_dcf` uses. The reverse
    DCF solves for the first year's rate; comparing that with a flat
    historical CAGR overstates what the price asks for (Coca-Cola: 16% in
    year one is about 9% a year over the horizon)."""
    level = 1.0
    for year in range(1, years + 1):
        g = first_year_growth + (terminal - first_year_growth) * (year - 1) / max(1, years - 1)
        level *= 1 + g
    return round(level ** (1 / years) - 1, 4)


def implied_growth(target_ev, fcf0, wacc):
    """The growth rate the current price is paying for (a reverse DCF).

    Answering "what would have to be true" is more useful than a single
    fair-value point, because it can be judged against the company's own
    history.
    """
    if not fcf0 or fcf0 <= 0 or not target_ev or target_ev <= 0:
        return None
    lo, hi = -0.30, 0.60
    for _ in range(80):
        mid = (lo + hi) / 2
        value = _dcf(fcf0, mid, wacc)
        if value is None:
            return None
        if value < target_ev:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 4)


def shares_series(cik, asof=None):
    """{period_end: share count} from the filings (see edgar.share_counts).

    Buybacks make today's share count useless for a past period: Apple
    retired roughly 45% of its shares over this window, so pricing 2016 with
    the current count understates that year's market value by nearly half
    and inflates the premium the company appears to trade at now.
    """
    return edgar.share_count_detail(edgar.companyfacts(cik), asof)


def _nearest_shares(series, when, strict=False):
    """The share count reported on or before a date, else the earliest after.

    `strict` drops the later-count fallback: on a past as-of date a later
    count is information the decision could not have had.
    """
    if not series:
        return None
    earlier = [d for d in series if d <= when]
    if earlier:
        return series[max(earlier)]
    if strict:
        return None
    return series[min(series)]


def historical_multiple(pkg, shares, asof=None):
    """What the market has typically paid for this company's own cash flow.

    A discounted cash flow needs a discount rate, and the rate is where the
    answer actually comes from: NVIDIA's regressed beta of 2.19 produces a
    14.5% rate, while the growth fed into the same model is capped at 15% --
    so the very trait that raises the rate is then removed from the
    numerator, and the business prints as 67% overvalued. Reversion to a
    company's own historical multiple avoids that entirely. It needs no rate,
    no terminal value and no growth forecast, and multiple mean-reversion is
    the assumption practitioners actually use for a target price.
    """
    import backtest

    ticker = pkg["company"]["ticker"]
    try:
        # Live runs refresh a cache older than a week; a point-in-time run
        # only reads months up to its as-of date, so any cache will do.
        payload = backtest.prices(ticker, need_raw=True,
                                  max_age_days=None if asof else LIVE_PRICE_MAX_AGE)
    except Exception:
        return None
    # A market value needs the price as traded, adjusted for splits only.
    # The dividend-adjusted series lowers every past price by the dividends
    # paid since, which understated past multiples -- by a fifth or more for
    # a decade of a 2-3% yield -- and pulled every fair value down with them.
    series, splits = payload["raw"], payload["splits"]

    fcf_series = (pkg["trends"].get("fcff_ttm") or {}).get("series") or []
    debt_series = dict((pkg["trends"].get("net_debt") or {}).get("series") or [])
    debt_now = pkg["latest_metrics"].get("net_debt") or 0
    share_hist = shares_series(pkg["company"]["cik"], asof)

    observations = []
    for date_str, _spot in fcf_series:
        fcf = _normalised_at(pkg, date_str)
        if not fcf or fcf <= 0:
            continue
        # Filings land about a month after period end, so the multiple the
        # market was paying is measured a month later, not on the period end.
        month = _month_after(date_str)
        if asof is not None and month > asof[:7]:
            continue
        price = series.get(month)
        if not price:
            continue
        hit = _nearest_shares(share_hist, date_str, strict=asof is not None)
        if hit is None:
            if asof is not None:
                continue
            count = shares
        else:
            # On the price's split basis: only splits after that filing.
            count = edgar.to_price_basis(hit[0], hit[1], splits)
        debt = debt_series.get(date_str, debt_now)
        enterprise = price * count + (debt or 0)
        observations.append((date_str, round(enterprise / fcf, 2)))

    if len(observations) < 12:
        return None
    values = sorted(v for _, v in observations)
    median = values[len(values) // 2]
    current = None
    if observations:
        current = observations[-1][1]
    # A median is only as representative as the window it spans. Nvidia has
    # barely three years of positive free cash flow here, all of it inside
    # the AI build-out, so its "own history" is a boom -- worth saying rather
    # than quietly treating as a normal reference.
    years = len(observations) / 4
    return {"median_ev_fcf": median,
            "low_ev_fcf": values[max(0, int(len(values) * 0.25))],
            "high_ev_fcf": values[min(len(values) - 1, int(len(values) * 0.75))],
            "observations": len(observations),
            "years": round(years, 1),
            "window_quality": "yeterli" if years >= 7 else
                              "kisa" if years >= 5 else "cok kisa",
            "span": [observations[0][0], observations[-1][0]]}


def ebitda_reversion(pkg, shares, asof=None):
    """Fair value per share from the company's own median EV/EBITDA.

    The EV/FCF reversion with EBITDA in place of free cash flow, for a REIT:
    its earnings carry depreciation on property that does not wear out the
    way the charge assumes, and EBITDA is before it. Only quarters whose
    price, filed share count and net debt are all known by `asof` enter.
    """
    import backtest

    m = pkg["latest_metrics"]
    ebitda_now, debt_now = m.get("ebitda_ttm"), m.get("net_debt")
    if not shares or debt_now is None or not ebitda_now or ebitda_now <= 0:
        return None
    try:
        payload = backtest.prices(pkg["company"]["ticker"], need_raw=True,
                                  max_age_days=None if asof else LIVE_PRICE_MAX_AGE)
    except Exception:
        return None
    series, splits = payload["raw"], payload["splits"]
    debt_series = dict((pkg["trends"].get("net_debt") or {}).get("series") or [])
    share_hist = shares_series(pkg["company"]["cik"], asof)
    multiples = []
    for date_str, ebitda in (pkg["trends"].get("ebitda_ttm") or {}).get("series") or []:
        month = _month_after(date_str)
        if not ebitda or ebitda <= 0 or (asof is not None and month > asof[:7]):
            continue
        price, debt = series.get(month), debt_series.get(date_str)
        hit = _nearest_shares(share_hist, date_str, strict=True)
        if not price or debt is None or hit is None:
            continue
        count = edgar.to_price_basis(hit[0], hit[1], splits)
        multiples.append((price * count + debt) / ebitda)
    if len(multiples) < 12:
        return None
    multiples.sort()
    median = multiples[len(multiples) // 2]
    fair = (median * ebitda_now - debt_now) / shares
    if not math.isfinite(fair) or fair <= 0:
        return None
    return {"fair": round(fair, 2), "median_ev_ebitda": round(median, 2),
            "observations": len(multiples)}


def trailing_volatility(closes, end_month, months=12):
    """Annualised volatility of the monthly returns ending at `end_month`.

    `closes` is {YYYY-MM: adjusted close}. Needs ten of the twelve months.
    """
    rets = []
    for i in range(months):
        m1, m0 = _add_month(end_month, -i), _add_month(end_month, -i - 1)
        if m1 in closes and m0 in closes and closes[m0]:
            rets.append(closes[m1] / closes[m0] - 1)
    if len(rets) < months - 2:
        return None
    mean = sum(rets) / len(rets)
    sd = (sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5
    return {"annualized": round(sd * 12 ** 0.5, 4), "months": len(rets),
            "through": end_month}


DAILY_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
             "?range=2y&interval=1d")
RANGE_DAYS, RANGE_SMOOTH = 14, 60


def daily_range(high, low, close, n=RANGE_DAYS, smooth=RANGE_SMOOTH):
    """The mean daily swing as a share of the price: average true range
    over the close (Wilder, `n` days), averaged over the last `smooth`
    days. The fall-risk read is built on it; of everything the indicator
    study tried it separated the companies that fell best. The 60-day
    average separates them as well as the 14-day reading and moves a fifth
    as much from week to week (indicators/lab, Phase 22), and the verdict
    reads this number."""
    ranges = [max(h - l, abs(h - c), abs(l - c))
              for h, l, c in zip(high[1:], low[1:], close[:-1])]
    if len(ranges) < 10 * n + smooth:
        return None
    atr = sum(ranges[:n]) / n
    shares = [atr / close[n]]
    for i, r in enumerate(ranges[n:], n + 1):
        atr = (atr * (n - 1) + r) / n
        shares.append(atr / close[i])
    return sum(shares[-smooth:]) / smooth


@_ttl
def risk_inputs(ticker):
    """{"range", "through"} from two years of daily bars, or None when they
    cannot be read. Live only: the backtest's price files hold monthly
    closes."""
    try:
        req = urllib.request.Request(DAILY_URL % ticker, headers={"User-Agent": UA})
        result = json.loads(urllib.request.urlopen(req, timeout=20).read())["chart"]["result"][0]
        q = result["indicators"]["quote"][0]
        rows = [(t, h, l, c) for t, h, l, c in zip(result["timestamp"], q["high"], q["low"],
                                                   q["close"])
                if None not in (h, l, c) and c > 0]
        high, low, close = ([r[i] for r in rows] for i in (1, 2, 3))
        spread = daily_range(high, low, close)
        if spread is None or not math.isfinite(spread):
            return None
        return {"range": round(spread, 5),
                "through": time.strftime("%Y-%m-%d", time.gmtime(rows[-1][0]))}
    except Exception:
        return None


def distance_to_default(equity, debt, volatility, drift):
    """Naive Merton distance to default (Bharath & Shumway 2008): how many
    standard deviations of asset value separate the firm from its debt, a
    year out. `equity` is the market value, `debt` the face value owed,
    `volatility` the equity's annual volatility, `drift` its trailing
    one-year return. None when an input is missing -- an unknown or zero
    debt is not read as safety."""
    if (not equity or not debt or equity <= 0 or debt <= 0
            or not volatility or drift is None):
        return None
    weight = equity / (equity + debt)
    asset_vol = weight * volatility + (1 - weight) * (0.05 + 0.25 * volatility)
    dd = (math.log((equity + debt) / debt) + drift - asset_vol ** 2 / 2) / asset_vol
    return round(dd, 3) if math.isfinite(dd) else None


def _add_month(month, n):
    year, mon = int(month[:4]), int(month[5:7]) + n
    year += (mon - 1) // 12
    return "%04d-%02d" % (year, (mon - 1) % 12 + 1)


def value_driver(pkg, capital, shares, net_debt):
    """Fair value from the key value driver formula.

    EV = NOPAT x (1 - g / ROIC) / (WACC - g) (Koller, Goedhart & Wessels,
    *Valuation*, ch. 3): a company is worth its operating profit after the
    reinvestment its growth requires, and that reinvestment is smaller the
    higher its return on capital. It is the non-financial counterpart of the
    justified P/B used for banks -- value from the spread between return and
    cost of capital rather than from the company's own past multiple.

    NOPAT is the median operating margin of the history times current
    revenue, after tax -- earning power, not one quarter's margin; ROIC is
    the median of the history; g is the terminal rate.
    """
    m = pkg["latest_metrics"]
    rev = m.get("revenue_ttm")
    wacc = capital.get("wacc")
    margins = sorted(v for _, v in (pkg["trends"].get("operating_margin") or {})
                     .get("series") or [] if v is not None)
    roics = sorted(v for _, v in (pkg["trends"].get("roic") or {})
                   .get("series") or [] if v is not None)
    if not rev or not wacc or not shares or len(margins) < 8 or len(roics) < 8:
        return None
    margin, roic = margins[len(margins) // 2], roics[len(roics) // 2]
    tax = m.get("effective_tax_rate")
    tax = 0.21 if tax is None or not 0 <= tax <= 0.35 else tax
    nopat = margin * rev * (1 - tax)
    g = TERMINAL_GROWTH
    if nopat <= 0 or roic <= g:
        return None

    def per_share(rate):
        if rate <= g:
            return None
        ev = nopat * (1 - g / roic) / (rate - g)
        return round((ev - (net_debt or 0)) / shares, 2)

    fair = per_share(wacc)
    if fair is None or fair <= 0:
        return None
    return {"fair": fair, "low": per_share(wacc + 0.01), "high": per_share(wacc - 0.01),
            "nopat": round(nopat), "roic_used": round(roic, 4),
            "margin_used": round(margin, 4), "wacc": round(wacc, 4), "growth": g,
            "basis": ("NOPAT %s × (1 − g/ROIC %.1f%%) / (WACC %.1f%% − g %.1f%%)"
                      % (_short(nopat), roic * 100, wacc * 100, g * 100))}


def _short(v):
    return "%.1f Mr$" % (v / 1e9) if abs(v) >= 1e9 else "%.0f M$" % (v / 1e6)


def justified_pb(pkg, capital, shares, net_income):
    """Bank fair value from the justified price-to-book multiple.

    P/B = (ROE - g) / (Ke - g): a bank is worth more than its book only to
    the extent its return on equity exceeds what shareholders require
    (Damodaran, Investment Valuation ch. 21; the residual-income identity in
    Penman). Free cash flow, the basis for everything else here, is
    meaningless for a lender. ROE is the median of the available history,
    the sustainable rate rather than one good year; Ke is the CAPM cost of
    equity, not a WACC, because deposits are a bank's raw material, not its
    financing.
    """
    m = pkg["latest_metrics"]
    roe_now = m.get("roe")
    ke = capital.get("cost_of_equity")
    if not roe_now or roe_now <= 0 or not net_income or not ke or not shares:
        return None
    book = net_income / roe_now
    series = sorted(v for _, v in (pkg["trends"].get("roe") or {}).get("series") or []
                    if v is not None)
    if len(series) < 8:
        return None
    roe = series[len(series) // 2]
    g = TERMINAL_GROWTH

    def per_share(rate):
        if rate <= g:
            return None
        return round(max(roe - g, 0) / (rate - g) * book / shares, 2)

    fair = per_share(ke)
    if not fair:
        return None
    return {"fair": fair, "low": per_share(ke + 0.01), "high": per_share(ke - 0.01),
            "sic": pkg["company"].get("sic"),
            "roe_used": round(roe, 4), "roe_now": round(roe_now, 4),
            "cost_of_equity": round(ke, 4), "growth": g,
            "book_per_share": round(book / shares, 2),
            "justified_pb": round(max(roe - g, 0) / (ke - g), 2),
            "basis": ("gerekçeli F/DD %.2f× = (medyan ROE %.1f%% − g %.1f%%) / "
                      "(Ke %.1f%% − g) × defter değeri %.2f"
                      % (max(roe - g, 0) / (ke - g), roe * 100, g * 100,
                         ke * 100, book / shares))}


def _month_after(date_str):
    year, month, _ = (int(x) for x in date_str.split("-"))
    month += 1
    if month > 12:
        month, year = 1, year + 1
    return "%04d-%02d" % (year, month)


def normalized_fcf(pkg):
    """Cash flow at a normal point in the investment cycle.

    Spot trailing free cash flow is the wrong base for a ten-year discount
    when the company happens to be in a capex trough: Microsoft's current
    build-out drags its trailing FCF down, and projecting that dip forward
    values the business at a fraction of any reasonable estimate. Taking the
    median free-cash-flow margin over the available history and applying it
    to current revenue keeps the scale current while removing the cycle --
    the earnings-power idea from Greenwald rather than a spot multiple.
    """
    series = (pkg["trends"].get("fcff_margin") or {}).get("series") or []
    margins = sorted(v for _, v in series if v is not None)
    revenue = pkg["latest_metrics"].get("revenue_ttm")
    spot = pkg["latest_metrics"].get("fcff_ttm")
    if len(margins) < 8 or not revenue:
        return {"base": spot, "method": "son 12 aylik firma serbest nakit akisi (yetersiz gecmis)"}
    median = margins[len(margins) // 2]
    return {"base": median * revenue,
            "spot": spot,
            "median_margin": round(median, 4),
            "method": "medyan firma serbest nakit akisi marji (%.1f%%) x son 12 aylik gelir"
                      % (median * 100)}


def _normalised_at(pkg, date):
    """Normalised FCFF as it would have been computed on `date`: the median
    FCFF margin of the quarters up to that date times that date's revenue.
    The historical multiple divides by this, so its denominator is the same
    kind of number as today's -- before, past multiples used spot FCF and
    today's used the normalised figure, which moved Coca-Cola's premium to
    its own history from about +12% to +38%."""
    margins = [v for d, v in (pkg["trends"].get("fcff_margin") or {}).get("series") or []
               if d <= date and v is not None]
    revenue = dict((pkg["trends"].get("revenue_ttm") or {}).get("series") or []).get(date)
    if len(margins) < 4 or not revenue:
        return None
    margins.sort()
    return margins[len(margins) // 2] * revenue


def _hist_growth(pkg, key="fcf_ttm", years=5):
    """Annualised growth of a trend series, clamped to a sane band."""
    series = (pkg["trends"].get(key) or {}).get("series") or []
    series = [(d, v) for d, v in series if v and v > 0]
    if len(series) < 8:
        return None
    span_years = max(1.0, (len(series) - 1) / 4)
    span_years = min(span_years, years)
    n = int(span_years * 4)
    first, last = series[-n - 1][1], series[-1][1]
    if first <= 0:
        return None
    cagr = (last / first) ** (1 / span_years) - 1
    # A ten-year explicit forecast above 15% assumes the company outruns
    # almost every historical precedent; growth mean-reverts hard, and the
    # trailing window is easily distorted by a commodity cycle -- ExxonMobil's
    # 2020 trough to 2022 peak reads as 10% secular growth. The floor exists
    # for the same reason in reverse.
    return max(-0.05, min(0.15, cagr))


def value(pkg, market=None):
    """Full price-aware valuation of an evidence package.

    `market` reconstructs the valuation as of a past date. It supplies
    `asof`, `price`, `shares` (on the same split basis as `price`),
    `risk_free` and `beta`; every other input comes from the package, which
    is already point-in-time when built with `asof`. Without it the quote,
    share count, rate and beta are read live.
    """
    company = pkg["company"]
    m = pkg["latest_metrics"]
    if market is not None:
        q = {"price": market["price"], "currency": "USD", "exchange": None,
             "as_of_epoch": None, "month_low": None, "month_high": None,
             "source": "point-in-time monthly close %s" % market["asof"][:7]}
        shares = market["shares"]
    else:
        q = quote(company["ticker"])
        try:
            import backtest
            splits = backtest.prices(company["ticker"],
                                     max_age_days=LIVE_PRICE_MAX_AGE)["splits"]
        except Exception:
            splits = None
        shares = shares_outstanding(company["cik"], splits)
    if not shares:
        raise RuntimeError("hisse sayisi bulunamadi")

    price = q["price"]
    mcap = price * shares
    net_debt = m.get("net_debt")
    if pkg.get("debt_unknown") and company["sector_bucket"] != "financial":
        # Every fair value here subtracts net debt; reading unknown debt as
        # zero overstates the equity by exactly the missing debt.
        raise RuntimeError("borç verisi raporlanan etiketlerden okunamadı")
    ev = mcap + net_debt if net_debt is not None else None
    capital = cost_of_capital(pkg, mcap, m.get("total_debt"), market)
    wacc = capital["wacc"]

    ni, fcf = m.get("net_income_ttm"), m.get("fcf_ttm")
    ebitda, rev = m.get("ebitda_ttm"), m.get("revenue_ttm")
    cfo = m.get("cfo_ttm")

    multiples = {
        "pe": _pos_div(mcap, ni),
        "p_fcf": _pos_div(mcap, fcf),
        "p_cfo": _pos_div(mcap, cfo),
        "ev_ebitda": _pos_div(ev, ebitda),
        "ev_sales": _pos_div(ev, rev),
        "fcf_yield": _pos_div(fcf, mcap, 4),
        "fcff_yield": _pos_div(normalized_fcf(pkg)["base"], ev, 4)
                      if ev and ev > 0 else None,
        "earnings_yield": _pos_div(ni, mcap, 4),
    }

    # Growth comes from revenue rather than free cash flow: the revenue
    # series is far less noisy, and a capex cycle should move the level of
    # cash flow, not the long-run growth rate applied to it.
    growth = _hist_growth(pkg, "revenue_ttm")
    if growth is None:
        growth = _hist_growth(pkg, "fcf_ttm")
    norm = normalized_fcf(pkg)
    fcf_base = norm["base"]

    dcf, base_value = {}, None
    if fcf_base and fcf_base > 0:
        # A +/-1 point band around the computed rate. Two points either side
        # spans 3.8%-7.8% on a 5.8% cost of capital, which produces a range
        # so wide it cannot inform a decision.
        for label, rate in (("optimistic", wacc - 0.01), ("base", wacc),
                            ("conservative", wacc + 0.01)):
            band = {}
            for gname, g in (("historical", growth), ("low_growth", 0.03)):
                if g is None:
                    continue
                operating = _dcf(fcf_base, g, rate)
                if operating is None:
                    continue
                band[gname] = {"per_share": round((operating - (net_debt or 0)) / shares, 2),
                               "growth_used": round(g, 4)}
            dcf[label] = {"wacc": round(rate, 4), **band}
        dcf["implied_growth"] = implied_growth(ev if ev else mcap, fcf_base, wacc)
        if dcf["implied_growth"] is not None:
            dcf["implied_growth_cagr"] = path_cagr(dcf["implied_growth"])

        # The headline estimate: the computed discount rate applied to the
        # company's own realised cash-flow growth. Everything else in the
        # range is a sensitivity around this one.
        base = dcf.get("base", {})
        chosen = base.get("historical") or base.get("low_growth")
        if chosen:
            base_value = chosen["per_share"]

    # A terminal value is hypersensitive to (wacc - terminal growth): moving
    # the rate one point can shift the estimate by a third. A single number
    # hides that, so the grid is reported alongside it and the reader can see
    # how much of the answer is assumption.
    sensitivity = None
    if fcf_base and fcf_base > 0 and growth is not None:
        sensitivity = {"growth": [], "wacc": [], "grid": []}
        # Deduplicated: at the edges of the growth clamp two of the three
        # scenarios collapse onto the same rate, and a grid with two
        # identical columns says nothing while implying it says something.
        growths = sorted({round(max(-0.05, min(0.15, growth + d)), 4)
                          for d in (-0.03, 0.0, 0.03)})
        waccs = [round(wacc + d, 4) for d in (-0.01, 0.0, 0.01)]
        base_index = growths.index(round(max(-0.05, min(0.15, growth)), 4))
        sensitivity["base_cell"] = [1, base_index]
        sensitivity["growth"] = [round(g, 4) for g in growths]
        sensitivity["wacc"] = [round(r, 4) for r in waccs]
        for r in waccs:
            row = []
            for g in growths:
                operating = _dcf(fcf_base, g, r)
                row.append(round((operating - (net_debt or 0)) / shares, 2)
                           if operating else None)
            sensitivity["grid"].append(row)

    # The headline estimate: the company's own typical multiple applied to
    # normalised cash flow. The discounted value is kept as a cross-check
    # rather than the answer.
    hist_mult = historical_multiple(pkg, shares,
                                    market["asof"] if market else None)
    reversion = None
    if hist_mult and fcf_base and fcf_base > 0:
        def per_share(multiple):
            return round((multiple * fcf_base - (net_debt or 0)) / shares, 2)
        current_mult = round((ev if ev else mcap) / fcf_base, 2)
        reversion = {
            "fair": per_share(hist_mult["median_ev_fcf"]),
            "low": per_share(hist_mult["low_ev_fcf"]),
            "high": per_share(hist_mult["high_ev_fcf"]),
            "current_ev_fcf": current_mult,
            "median_ev_fcf": hist_mult["median_ev_fcf"],
            "premium_to_own_history": round(
                current_mult / hist_mult["median_ev_fcf"] - 1, 4),
            "observations": hist_mult["observations"],
            "years": hist_mult["years"],
            "window_quality": hist_mult["window_quality"],
            "window_note": (None if hist_mult["window_quality"] == "yeterli" else
                            "Referans pencere yalnızca %.1f yıl. Medyan, tam bir "
                            "piyasa döngüsünü kapsamıyor; şirket bu dönemde "
                            "olağandışı bir değerlemede işlem gördüyse 'kendi "
                            "tarihi' o olağandışılığı normal sayar."
                            % hist_mult["years"]),
            "span": hist_mult["span"],
            "basis": ("kendi tarihsel EV/FCF medyanı %.1f× "
                      "(%d çeyrek, %s–%s) × normalize nakit akışı"
                      % (hist_mult["median_ev_fcf"], hist_mult["observations"],
                         hist_mult["span"][0][:7], hist_mult["span"][-1][:7])),
        }

    volatility = issuance = None
    try:
        import backtest
        payload = backtest.prices(company["ticker"], max_age_days=(
            None if market else LIVE_PRICE_MAX_AGE))
        closes = payload["closes"]
        end = market["asof"][:7] if market else max(closes)
        volatility = trailing_volatility(closes, end)
        issuance = edgar.net_issuance(edgar.companyfacts(company["cik"]),
                                      market["asof"] if market else None,
                                      payload["splits"])
    except Exception:
        volatility = issuance = None

    bank = driver = None
    if company["sector_bucket"] == "financial":
        bank = justified_pb(pkg, capital, shares, net_income=ni)
    else:
        driver = value_driver(pkg, capital, shares, net_debt)

    fair = _fair_range(dcf)
    headline = reversion["fair"] if reversion else base_value
    if bank:
        headline = bank["fair"]
    if fair and base_value is not None:
        fair["base"] = base_value
        fair["basis"] = ("sermaye maliyeti %.2f%%, normalize nakit akışı, "
                         "gelir CAGR'ından %+.1f%% büyüme"
                         % (wacc * 100, (growth or 0.03) * 100))

    return {
        "quote": q,
        "shares_outstanding": shares,
        "market_cap": mcap,
        "enterprise_value": ev,
        "multiples": multiples,
        "cost_of_capital": capital,
        "normalized_fcf": norm,
        "assumptions": {"wacc": wacc, "terminal_growth": TERMINAL_GROWTH,
                        "horizon_years": HORIZON,
                        "historical_fcf_growth": growth,
                        "growth_basis": "gelir CAGR",
                        "cash_flow_base": norm["method"],
                        "note": "Büyüme ufuk boyunca terminal orana doğrusal "
                                "olarak söner. Sermaye maliyeti CAPM ile "
                                "hesaplanır; risksiz oran 10 yıllık ABD "
                                "tahvili, risk primi %4.5 varsayımıdır."},
        "dcf": dcf,
        "volatility": volatility,
        "risk": None if market else risk_inputs(company["ticker"]),
        "net_issuance": issuance,
        "sensitivity": sensitivity,
        "reversion": reversion,
        "dcf_fair_value": fair,
        "bank": bank,
        "value_driver": driver,
        "fair_value": ({"base": bank["fair"], "low": bank["low"],
                        "high": bank["high"], "basis": bank["basis"],
                        "method": "gerekçeli F/DD (ROE - g) / (Ke - g)"}
                       if bank else
                       {"base": reversion["fair"], "low": reversion["low"],
                        "high": reversion["high"], "basis": reversion["basis"],
                        "method": "tarihsel çarpana dönüş"}
                       if reversion else fair),
        # Two different questions, both asked in practice. The margin of
        # safety is the discount to intrinsic value (Graham's framing); the
        # upside is the move required to reach it from today's price.
        "margin_of_safety": _mos(headline, price),
        "upside_to_fair": (round(headline / price - 1, 4) if headline else None),
        "price_vs_fair": ({"price": round(price, 2), "fair": headline,
                           "gap": round(headline - price, 2)}
                          if headline else None),
        "dcf_upside": (round(base_value / price - 1, 4) if base_value else None),
        "divergence": _divergence(headline, price,
                                  {"grid": [[reversion["low"], reversion["high"]]]}
                                  if reversion else sensitivity),
    }


def _mos(fair, price):
    if not fair or fair <= 0:
        return None
    return round((fair - price) / fair, 4)


def _divergence(fair, price, sensitivity):
    """Flags a gap between the model and the market too large to take at face value.

    A discount rate built from a regressed beta captures market risk, not
    company-specific risk: it does not know about a patent cliff, a pending
    legal exposure or a business in structural decline. When the model and
    the price disagree by more than about 60%, the more likely reading is
    that the market is pricing something the model cannot see -- not that a
    mega-cap is mispriced by that margin.
    """
    if not fair or not price:
        return None
    gap = fair / price - 1
    inside = None
    if sensitivity:
        flat = [v for row in sensitivity["grid"] for v in row if v]
        if flat:
            inside = min(flat) <= price <= max(flat)
    if abs(gap) <= 0.60:
        return {"level": "normal", "price_within_sensitivity": inside,
                "note": ("Fiyat, varsayım duyarlılık aralığının içinde -- "
                         "model fiyatı ne net ucuz ne net pahalı buluyor."
                         if inside else
                         "Fiyat duyarlılık aralığının dışında; ayrışma "
                         "varsayım seçiminden kaynaklanmıyor.")}
    return {
        "level": "yuksek",
        "price_within_sensitivity": inside,
        "note": ("Model ile piyasa arasında %+.0f%% ayrışma var. Bu "
                 "büyüklükte bir farkta daha olası açıklama, piyasanın "
                 "modelin görmediği bir riski (patent uçurumu, dava, "
                 "yapısal gerileme) veya bir fırsatı fiyatlaması. İskonto "
                 "oranı regresyona dayalı betadan gelir ve şirkete özgü "
                 "riski içermez -- bu sayıyı tek başına karar girdisi "
                 "olarak kullanma." % (gap * 100)),
    }


def _pos_div(a, b, places=2):
    """Multiples are only meaningful with a positive denominator."""
    if a is None or b is None or b <= 0:
        return None
    return round(a / b, places)


def _fair_range(dcf):
    values = [v["per_share"] for k, band in dcf.items()
              if isinstance(band, dict) and k != "implied_growth"
              for v in band.values() if isinstance(v, dict)]
    if not values:
        return None
    values.sort()
    return {"low": values[0], "mid": round(sum(values) / len(values), 2),
            "high": values[-1], "scenarios": len(values)}
