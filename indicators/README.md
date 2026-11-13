# Indicator map

Two hundred technical indicators are not two hundred pieces of information.
Most are transformations of the same price series and move together. This
maps which ones do, **without looking at a single return**, so that what is
later tested against returns is a handful of distinct things and not two
hundred correlated tries.

Every rule below was written before the map was computed.

## The set

Every function TA-Lib 0.8.3 lists under Cycle, Momentum, Overlap Studies,
Pattern Recognition, Statistic Functions, Volatility and Volume Indicators,
at its default parameters, every output series: 204 functions. A function
that needs an input other than open, high, low, close and volume is left
out and named.

## The data

Daily bars of every S&P 500 member since 2004, companies since acquired or
failed included, adjusted for splits and dividends (the outside dataset
`src/crosscheck.py` reads; local only). Observations are taken at each
month end from 2006 to 2025, for the companies in the index on that day
with at least 300 trading days behind them.

## Making outputs comparable across companies

- **Units.** An output that scales with the price (a moving average, a
  band, an ATR) is divided by the close, and one that scales with volume by
  the 20-day average volume. Which outputs scale, and with what power, is
  found by recomputing each on prices and on volumes multiplied by ten, not
  by a list.
- **Running totals** (AD, ASI, NVI, OBV, PVI, PVT, WAD) depend on where the
  series began; their 20-day change is used.
- Within each month end every output is replaced by its percentile rank
  across the companies, so the map is about how indicators order companies
  against each other, which is how a screen would use them.

## The map

- **Similarity** of two outputs: the absolute rank correlation, pooled over
  all month ends. Absolute, because an indicator and its mirror image are
  the same information.
- **Rare events.** An output that takes its most common value in more than
  99% of observations (most candlestick patterns) cannot be placed by
  correlation; these are listed apart and left out.
- **Clusters**: average-linkage hierarchical clustering on one minus the
  similarity, cut at 0.30, so the outputs in a cluster agree at 0.70 on
  average.
- **Representative** of a cluster: the output with the highest mean
  similarity to the others in it (shorter name, then alphabetical, on a
  tie). A cluster of one represents itself.
- **How many dimensions**: the eigenvalues of the correlation matrix of the
  mapped outputs — how many exceed one, and how many carry 90% of the
  variance.

## Result (2026-11-13)

203 functions (MAVP needs a period series and is left out), 243 outputs,
115,998 observations: 810 companies at 240 month ends.

- 35 outputs are rare events, all of them candlestick patterns.
- The other 208 fall into **77 clusters**; 29 eigenvalues exceed one and 48
  components carry 90% of the variance. The first component alone carries
  39%, the first three 54%.
- **Two families hold 41% of the mapped outputs.** One has 57 members:
  every moving average and band (SMA, EMA, WMA, KAMA, Bollinger, Keltner,
  Donchian), and with them RSI, ROC, MOM, Williams %R, CCI, CMO, %B, Fisher
  and Vortex. All of them order companies by where the price stands
  against its last few weeks. The other has 28: MACD and its variants, PPO,
  TSI, KST, Coppock, Awesome Oscillator, WaveTrend, which order them by
  momentum over the last one to three months.
- Six more clusters have four or more members: fast smoothers (10), the
  MACD histogram with DEMA, TEMA and ZLEMA (7), the stochastics (5), the
  ranges ATR, NATR, ADR and Rogers-Satchell (4, agreeing at 0.95),
  accumulation with AD, ADOSC and CMF (4), and bar-shape measures (4).
- 52 outputs stand alone: 19 candlestick patterns and 33 others, among them
  the Hilbert cycle measures, Bollinger width, beta, kurtosis, relative
  volume, VWAP and TRIX.

So two hundred indicators are about thirty separate things, and most of
what is popular is two of them. `data/indicators/map.json` has every
cluster and its representative.

## The test (written 2026-11-13, before any representative met a return)

Candidates are the cluster representatives, in two tiers fixed by the map
alone. **Tier 1**: the eight clusters with four or more members, the
information most indicators restate. **Tier 2**: the other 47 clusters that
are not candlestick patterns. The 22 candlestick clusters are not tested.

An output that changes a past value when later bars arrive (a zigzag, a
fractal) cannot be traded on as printed. Each candidate is recomputed on a
series cut off at the day in question; one that differs from its
full-series value is dropped and named.

Observations: every quarter end from 2006-03 to 2025-09, the companies in
the index that day with 300 trading days behind them, the indicator as of
that close. A company that stops trading is held at its last price.

Three statistics per candidate, two-sided:
1. **Fall risk**: AUC for a fall of more than 25% over the next twelve
   months, by date (at least 20 names and 3 falls), Newey-West lag 3.
2. **Return, twelve months**: rank IC against the forward return, lag 3.
3. **Return, one month**: rank IC, no lag (the months do not overlap).

**Tier 1 is the test**: 8 candidates × 3 statistics = 24, so a statistic
counts when |t| >= 3.08 over the whole period (Bonferroni) **and** it has
the same sign in each of 2006-2012, 2013-2019 and 2020-2025. For fall risk
there is one more condition before it can enter the product's risk read,
which already splits on trailing volatility: among companies whose trailing
volatility is under 35%, the same sign with |t| >= 2.

**Tier 2 is exploration**: 47 × 3 = 141 statistics, reported with
Benjamini-Hochberg-Yekutieli adjusted p. One with adjusted p < 0.05 and the
same sign in all three windows is a place to look, to be tested on data
collected after today; it changes nothing in the product.

Trailing volatility itself is shown on the same rows for scale. It is the
product's existing read, not a candidate.

## Test result (2026-11-13)

79 quarter ends, 483 companies a date. No candidate repaints. For scale,
the product's own read, twelve-month trailing volatility, has a fall AUC
of 0.68 (t 9.5) on these rows and no return IC.

Tier 1, AUC or IC over 2006-2025 (t), and by window:

| Family, representative | Fall risk, AUC | 12-month IC | 1-month IC |
|---|---|---|---|
| Price against its recent average, WMA | 0.52 (1.8) | +0.04 (2.0) | +0.05 (2.9) |
| Momentum over 1-3 months, MACD | **0.46 (−3.6)** | −0.01 (−0.7) | −0.04 (−1.8) |
| Fast smoothers, Gaussian filter | 0.51 (0.5) | +0.03 (1.7) | **+0.05 (3.3)** |
| Change in momentum, MACD histogram | 0.52 (1.6) | −0.04 (−2.6) | −0.03 (−2.0) |
| Stochastics | 0.47 (−2.5) | −0.03 (−1.9) | −0.04 (−2.7) |
| Accumulation, AD | **0.46 (−3.6)** | −0.00 (−0.2) | −0.02 (−1.6) |
| Daily range, ATR | **0.72 (14.2)** | −0.03 (−0.7) | +0.02 (0.5) |
| Bar shape, SI | 0.51 (0.6) | −0.01 (−0.5) | −0.03 (−1.6) |

Bold: |t| >= 3.08 and one sign in all three windows. Four of 24.

- **Nothing ranks twelve-month returns.** Not one of the eight, and in
  tier 2 not one of 47.
- **The daily range separates the companies that fall, and better than the
  product's read does**: AUC 0.72, 0.74 and 0.68 in the three windows
  against 0.68 overall for monthly-return volatility. Among companies the
  product calls calm (trailing volatility under 35%) it still reaches 0.69
  (t 13.4). Both are volatility; the daily range is the finer measure of
  it, and a single line at 35% leaves most of what it knows unused.
- **Weak momentum goes with more falls**, a little: AUC 0.46 for MACD
  (higher momentum, fewer falls), holding among calm names (t −2.2).
  Accumulation shows the same size of effect and does not hold among calm
  names (t −0.9).
- **One return result, at one month**: the price below its fast average is
  followed by a higher return (IC +0.05, t 3.3). It is +0.07 and +0.06 in
  the first two windows and +0.02 in 2020-2025, it is before any cost, and
  a one-month signal turns over a portfolio twelve times a year.
  **Correction, same day**: this is not a general short-term reversal. The
  test reads signals at quarter ends only, and the lab (`lab/`), reading
  them every week, finds the same ranking at +0.01. By month end over
  2006-2025 the IC is +0.048 at quarter ends and +0.002 at the other month
  ends, largest after December (+0.09) and June (+0.07): a turn-of-quarter
  effect, strongest at the turn of the year. All of it was seen on the
  whole period, so only later data can test it.

Tier 2: 12 of 141 statistics have adjusted p < 0.05 and one sign, every one
of them a fall-risk reading. Four restate volatility (variance, true range,
Bollinger width, directional movement, AUC 0.63 to 0.66); the others are
trend-direction measures at 0.52 to 0.58 (parabolic SAR, TRIX, SuperTrend,
relative volatility, VWAP, negative volume index, Hilbert trend mode). No
return statistic comes near.

By the rule written above, the daily range and momentum qualify for the
product's risk read. The daily range is in it (`risk_table.py`, and
"The risk read from the daily range" in the main README), since averaged
over 60 days (`lab/`, where combinations and events are tested). Momentum is not:
inside a daily-range fifth it changes the fall rate by a point or less and
not in one direction.

    <research venv>/python -I indicators/map.py <dataset directory>
    <research venv>/python -I indicators/test.py <dataset directory>
