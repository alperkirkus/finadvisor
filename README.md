# FinAdvisor

Financial statement analysis for US-listed companies, built on SEC EDGAR
filings. Enter a ticker and get a read on the business: computed ratios,
quality and distress scores, ten years of trends, a valuation against the
company's own history, and an explicit investability verdict with the
reasoning attached.

Everything is computed in Python from the filings themselves. The optional
language-model layer interprets that output in prose and is not on the
product path — the app, its scores and its verdict all run without an API
key.

## What this is not

**The verdict has no measured predictive power for returns.** The
project's point-in-time backtest scores exactly the number the screen
orders by, on every S&P 500 member of the day that can be resolved (about
405 names per date in 2013-2019, companies later acquired or failed among
them). Its cross-sectional rank correlation
with 12-month forward returns is **+0.03** (t = 1.7) against a smallest
detectable effect of 0.05 — nothing measurable — and its alpha after
Fama-French five factors plus momentum is 0.05% a month (t = 0.3); what it
carries is a profitability tilt. Two reads do carry information, listed
under "Results" below with their caveats: the business score and trailing
volatility separate the names that later fell hard, and the bank-style
valuation ranks returns among financial firms.

So this is a structured, inspectable read of financial condition against
criteria that are written down — not a return forecast, not investment
advice, and not a target price. The thresholds are deliberately **not** tuned
to the backtest: there is no signal to tune toward, and fitting weights to
noise in one market regime would be overfitting rather than calibration. Every weight in `verdict.py` carries its justification inline,
so you can disagree with a specific one rather than with a black box.

Read `knowledge/analysis-framework.md` for the criteria and, more usefully,
for each score's documented failure mode.

## Architecture

```
SEC EDGAR XBRL
      |
  edgar.py      ingest + normalization -> canonical quarterly panel
  metrics.py    ratios, Piotroski / Altman / Beneish -- deterministic
  report.py     evidence package (metrics + trends + gaps + coverage)
  ranking.py    scores a universe with the same rules and orders it
      |
      +-- interpret.py the framework's thresholds, sector adjustments, score
      |                caveats and red-flag combinations as code -- reads a
      |                company end to end with no model call and no cost
      +-- analyst.py   optional: Claude reads the same package against
      |                knowledge/ for narrative interpretation (needs a key)
      +-- valuation.py price, market cap, multiples, DCF and reverse DCF,
      |                with a per-company WACC (beta regressed against the
      |                S&P 500, CAPM cost of equity, realised cost of debt)
      +-- verdict.py   four scored pillars -- quality, safety, earnings
      |                quality, valuation -- and an explicit investability
      |                verdict plus a next-quarter projection
      +-- regime.py    S&P 500 against its 200-day average (market regime)
      +-- api.py       FastAPI: /api/company, /api/search, /api/interpret,
                            /api/valuation, /api/market, /api/analyze
                            |
                        web/  Next.js UI
```

The landing screen lists the ten best-scoring companies. It calls
`verdict.assess` per company and orders the results — a screen ranked by a
different rule than the one it explains would be a second, hidden model.
Blocked companies sink to the bottom whatever they score, and so does anything
whose valuation rests on a large model-versus-market gap: the number may be
right, but promoting it silently would be its own distortion. The universe is
today's S&P 500 (`ranking.screen_universe`, from the Wikipedia constituents
table), not all 10,412 filers — scoring one needs a live quote and a beta
regression, so the screen is built offline by `ranking.py`, four companies
at a time, and served from a file.

That file fixes the order and nothing else. Its prices are those of the run,
so the list never shows them as today's: every row on screen is priced again
through the company page's own path (`/api/live`, the same function and the
same cache), which is what keeps a row and the page it opens on one number.
What an earlier run said is shown beside it as a dated record — that run's
price and distance to fair value, the price change since, and its verdict
where the verdict has changed. The record is the latest run at least a day
old (`ranking.baseline`), so rebuilding twice in an afternoon does not erase
last week's. The list can be narrowed by how long a fair-value target of that
size has historically taken (`wait`: near, about two years, three years or
more — the only values the backtest's hit rates produce).

`backtest.py` measures whether the signal predicts anything. The universe
is the S&P 500 as it stood on each date: membership intervals come from the
public historical-components dataset (github.com/fja05680/sp500), and a name
is scored only while it was in the index, so companies that rose into it
later are not scored on dates before they qualified. `universe.py` resolves
the members to CIKs and prefetches their filings and prices. It rebuilds
each company's package as it stood on a past date with the product's own
builder — `report.build(..., asof=)` only reads filings published by then,
which removes lookahead and restatement bias together — values it with that
month's price, filed share count, 10-year yield (FRED) and a beta regressed
on the preceding 60 months, scores it with `verdict.assess`, and records the
screen's `overall` score. The headline statistic is the per-date rank IC
against excess return over the equal-weight universe, at 1, 3, 6 and 12
months, with Newey-West t-statistics, quintile spreads and a regression of
the monthly long-short return on Fama-French five factors plus momentum.

As-of dates are split. Development covers dates whose return ends by
2019-12; the holdout starts in 2020 and is printed only with `--holdout`,
each look logged to `data/holdout_log.json`. Any change to weights or
signals is judged on the development window alone.

Scoring is **self-relative as well as absolute**. A hand-set band saying
"gross margin above 40% is strong" is unavoidably arbitrary across sectors,
while the panel already holds ten years of the company's own readings — so
each component blends its absolute band with where today sits in that
distribution (40% weight on the percentile). The absolute band still anchors
the level, because a business that has always been poor should not score well
merely for being at its own best; the percentile catches a company sliding
against its own record while still clearing a generic threshold.

Two further consequences of having the history. **Stability** is scored
directly — the coefficient of variation of ROIC over the decade takes a
quarter of the quality pillar, since durability is most of what quality means
once the level is known. The **accrual flag** — accrual ratio above the
framework's warning level *and* cash conversion confirming it — is a warning,
not a block: such a company can never be called investable, and its
rationale says why, but it is not thrown out. It used to block outright on
the strength of the first backtest; on S&P 500 members the accrual effect is
not significant, and non-cash profit can be benign (Alphabet's includes
unrealised investment gains), so a hard block was claiming more than the
evidence holds.

Component weights inside each pillar come from how reliable each measure is
known to be, documented next to the weight in `verdict.py` — not fitted to
the backtest, which cannot support a fitted weight. The accrual ratio carries
the largest single share because it is the best-documented earnings-quality
measure in the literature, not because this project measured it working.
Piotroski is reported but no longer weighted, because its prior and its
measurement agree that it does not discriminate among large companies.

### Results (regenerated after the November 2026 review)

Every figure below is recomputed from the current `data/backtest_rows*.json`
after the fixes listed under "Independent review"; 12-month horizon,
per-date rank IC with Newey-West t. "Dev" is 2013-2019. **2020-2025 is no
longer a clean holdout**: it was looked at more than once and several
design choices (REIT reclassification, sub-group notes) were made after
seeing it, so treat it as a second in-sample window. Survivorship is partial
on the S&P 500 and total on mid/small (see below), and about 440 signal/horizon/universe combinations were tried,
so a t of 2-3 on any single one is weak evidence.

| Read | S&P 500 dev | S&P 500 2020-25 | S&P 400/600 dev | S&P 400/600 2020-25 |
|---|---|---|---|---|
| Screen score (`overall`), IC | +0.03 (t 1.7) | +0.02 (t 0.8) | +0.04 (t 1.5) | +0.03 (t 1.3) |
| Financials, bank valuation pillar, IC | +0.12 (t 2.6) | +0.13 (t 2.5) | +0.09 (t 1.5) | +0.14 (t 5.4) |
| Net share issuance, IC | −0.03 (t −1.1) | −0.09 (t −3.1) | −0.06 (t −3.0) | −0.08 (t −2.9) |
| Accrual ratio, IC | +0.00 (t 0.1) | −0.02 (t −0.9) | +0.01 | +0.01 |
| Business score, AUC for a >25% fall | 0.59 (t 5.3) | 0.55 (t 2.4) | 0.58 (t 3.1) | 0.59 (t 6.7) |

- **Return ranking: no.** Neither the screen score nor the own-history
  fair value ranks returns in any window; cheap-against-own-history names
  are mostly businesses in decline (a value trap), and none of seventeen
  filters, insider purchases or earnings surprise separated them reliably.
- **Risk: yes.** A higher business score goes with fewer large falls in
  every window, and trailing volatility of 35% or more fell more than 25%
  over the next year at 2.2x the universe rate (15.0% vs 6.7%). Each verdict
  reports the volatility base rate.
- **Financials: probably, with caveats.** The justified P/B pillar ranks
  financial-sector returns in both S&P 500 windows (t 2.6 and 2.5) and in
  the mid/small 2020-2025 window, but only about 40 names a date are
  scored and the detectable minimum is about 0.15. By sub-group (both
  universes pooled) banks hold in both windows (+0.09, t 2.5; +0.16,
  t 4.6), insurers point the same way without significance (t 1.7, 1.9),
  brokers and asset managers show nothing. The verdict states the
  sub-group record.
- **Net share issuance** ranks mid/small returns in both windows and
  S&P 500 returns only after 2019; it is reported, not scored.
- **Horizons beyond 12 months** are shown as outcomes (how often a target
  was reached), never as significant: with 16-20 overlapping dates a
  Newey-West t there is meaningless.

**Survivorship was total; on the S&P 500 it is now partial.** Until
November 2026 every scored company still traded: members later acquired or
failed, and renamed companies under their old tickers, were not resolved,
and about 22% of each date's members were missing. Two repairs (plan.md,
Phase 16). A member that only changed ticker is read under the symbol that
holds its history and joins that record. And 99 members Yahoo no longer
serves are scored from their own XBRL filings and an outside price history
(`outside_prices.py`; the filer is the unique name match, or the one
candidate that filed around the end of the membership), each held in cash
at its last price for three years after it stops trading. 440 of about 503
members a date are scored, up from 391; 51 tickers are still missing, 30 of
them because no filer could be told from the name.

The recovered companies did worse, as they had to: in 2013-2019 11.1% of
them fell more than 25% in a year against 6.1% of the rest, and their mean
12-month return was 7.4% against 13.0%. The universe's own figures moved
with them (fall rate 6.1% to 6.7%, mean annual return 13.1% to 12.3%), so
every base rate shown to users came down a little. The findings did not
change in kind: the screen score still ranks nothing (+0.02, t 1.1, became
+0.03, t 1.7, and +0.03 became +0.02 in 2020-2025), the financial
valuation holds (t 2.4 to 2.6), and the business score's separation of the
companies that fell got clearer with the fallen in the data (AUC 0.58,
t 3.8, to 0.59, t 5.3). Mid/small still scores survivors only: the outside
dataset covers the S&P 500. Its price files stay under `data/`, outside
the repository; the dataset has no licence.

### Independent review (November 2026)

Two independent reviews — one of the valuation methodology, one of the
backtest and data pipeline — found errors that moved verdicts and results.
Fixed:

- Missing debt read as zero (Realty Income's $26B of notes made it
  "investable"); debt is now unknown, not zero, when untagged and the
  company is not valued.
- Reused tickers scored the wrong company (BBT); dates with a market value
  no index member could have are skipped.
- Share counts double-adjusted for splits, spin-offs treated as splits,
  XBRL scale errors; revenue tag picking the contract-revenue subset
  (MetLife 3% of revenue); net interest tags read as expense; pretax income
  standing in for operating income.
- FCF was after interest yet discounted at WACC, and ignored stock-based
  compensation; valuation now uses FCFF. The historical multiple used spot
  FCF against today's normalised FCF (Coca-Cola +38% vs about +20%
  consistently). The implied-growth test compared a first-year rate with a
  ten-year CAGR.
- Utilities blocked by Altman Z'' and current ratio (invalid there); quality
  called "strong" with ROIC below WACC; block text naming the wrong cause;
  raw betas (now Blume-adjusted, 0.8 floor for insurers); cost of debt below
  the risk-free rate; exchanges valued as banks; REITs valued as banks;
  Beneish dropping missing indices as 0.

Not fixed then: survivorship and renamed tickers (since repaired in part,
see "Survivorship" below), regulated utilities and REITs lack a sector
valuation model (two were tested and failed, see "Sector fair values"), a
dozen companies whose debt tags cannot be read are not valued, and insurers
are still valued with the bank model.

### Price, trend and market regime (portfolio backtest)

`strategy.py` adds what prices say to the verdict and tests rules fixed in
advance, as a portfolio (monthly rebalance, 10 bp per side, daily Yahoo
data for point-in-time S&P 500 members since 2004; 301 of 963 historical
members have no Yahoo history, so the universe is survivorship-biased and
the equal-weight benchmark built from the same names is the fair yardstick).
Strategy A holds the 50 members in an uptrend (above their 200-day average)
with the best 12-1 momentum and nearness to the 52-week high, and moves to
T-bills when the S&P 500 is below its 200-day average. B adds the quality
filter (business score >= 60, not blocked, volatility < 35%).

| | 2006-2012 | 2013-2019 | 2020-2025 | 2006-2025 |
|---|---|---|---|---|
| A, CAGR / Sharpe / max drawdown | 9.4% / 0.83 / −9% | 9.0% / 0.88 / −10% | 7.2% / 0.39 / −17% | 8.6% / 0.68 / −17% |
| B (A + quality) | — | 9.0% / 0.86 / −9% | 7.3% / 0.36 / −23% | — |
| A without the regime switch | 0.8% / 0.04 / −52% | 10.6% / 0.92 / −14% | 9.8% / 0.47 / −21% | 6.9% / 0.41 / −52% |
| Equal-weight universe | 6.6% / 0.34 / −53% | 14.8% / 1.17 / −14% | 11.1% / 0.50 / −27% | 10.8% / 0.59 / −53% |
| SPY | 3.8% / 0.21 / −51% | 14.6% / 1.22 / −14% | 15.0% / 0.75 / −24% | 10.8% / 0.65 / −51% |

(Regenerated in November 2026 after the universe repair described under
"Survivorship, cross-checked". The same rules on a universe that keeps its
dead companies are in the table there; every figure in this one is about a
point a year too high.)

The pre-registered test failed: A and B beat the equal-weight universe on
Sharpe and drawdown in 2006-2012 but not in 2013-2019. Stock selection by
trend and momentum lags the plain universe in every window (A without the
switch), and the quality filter adds little. What did the work is the
market-regime switch alone. Checked afterwards, and therefore exploratory:
SPY held only while the S&P 500 is above its 200-day average (T-bills
otherwise, 26 switches in 20 years, 10 bp per switch; `SPY_regime` in
`strategy.py`) returned 10.3% a year against SPY's 10.8%, at 10.1%
volatility against 15.1%, Sharpe 0.86 against 0.65, worst drawdown −22%
against −51%. That rule was published in 2007 (Faber), so most
of this window is after its publication; it still costs return in steady
bull markets, whipsaws in sideways ones, and is slow in fast crashes
(2020: −22%).

The switch is now in the product: `regime.py` reads the S&P 500 against its
200-day average at the last month end (the tested rule) and today, served at
`/api/market` and shown on the home page and on every company page, with the
backtest above beside it.

### Evidence composite (pre-registered, failed)

Of the signals tested on mid/small caps in 2013-2019, five had the sign their
literature predicts: low net issuance, low volatility, ROIC, gross
profitability and revenue surprise. Their equal-weight within-sector
percentile average (`evidence` in `backtest.py`) was fixed before it was
computed; because the five were picked on dev, only 2020-2025 could test it.

| 12-month rank IC (t) | 2013-2019 (picked here) | 2020-2025 (test) |
|---|---|---|
| mid/small | +0.094 (2.4) | +0.017 (0.4) |
| S&P 500 | +0.052 (1.4) | +0.009 (0.2) |

The criterion (mid/small IC > 0 with t >= 2 in 2020-2025) failed. By year
the 2020-2025 IC is −0.20 in 2020 (the rally led by unprofitable, volatile
names), +0.09 to +0.12 in 2021-2023, +0.06 in 2024 and −0.12 in 2025; the
top quintile trailed the bottom. Of the components only net issuance held
up out of sample (12-month IC −0.08 to −0.09, t −2.9, in both universes).
The composite is therefore not shown in the product. One unplanned
observation: as a crash indicator its AUC was 0.59-0.60 in both windows and
both universes, slightly above the business score's.

### Earnings surprise from the release date (pre-registered, passed on dev)

The quarterly backtest found no earnings drift because it dates a quarter
by its 10-Q and scores it at the next quarter end, after the drift.
`earnings.py` dates each surprise by the company's 8-K Item 2.02 filing
(after-hours releases move to the next trading day) and measures the
60-trading-day return against SPY from that close.

| SUE, rank IC (t) | 2013-2019 | 2020-2025 | Realizable (from the 10-Q), 2013-2019 / 2020-2025 |
|---|---|---|---|
| S&P 500 | +0.043 (2.6) | +0.023 (1.3) | +0.015 (0.9) / +0.012 (0.7) |
| mid/small | +0.040 (2.9) | +0.008 (0.5) | +0.025 (1.6) / +0.008 (0.5) |

The pre-registered criterion (IC > 0, t >= 2 in 2013-2019 in both
universes) held: the drift exists when measured from the release. It is
weaker in 2020-2025, as the literature on its decay predicts, and the
top-minus-bottom quintile spread is about one percentage point over the 60
days. It is also not something this system can act on: the surprise uses
EPS from XBRL, which arrives with the 10-Q two to four weeks after the
release, and measured from that date the signal is not significant in
either window. Acting on the release itself would mean parsing the
unstructured press release (EX-99.1). The signal is therefore documented,
not shown in the product.

### EPS from the earnings release (pre-registered, failed)

The drift above needs the quarter's EPS on the release day. `release_eps.py`
draws 400 release events at random (S&P 500, 2013-2025);
`release_extract.py` reads the diluted EPS out of each 8-K's press release
with edgartools, by rules written on a separate set of 30 events and frozen
before the sample was parsed; the reference is the EPS first filed in XBRL
(plan.md, Phase 13).

| | Events | EPS read | Equal to XBRL within $0.01 |
|---|---|---|---|
| Quarters XBRL reports directly | 342 | 262 (77%) | 232 (89% of those read) |
| Fiscal fourth quarters | 58 | 46 (79%) | 25 (54%) |

The criterion was 80% read and 95% of those equal; neither held, and the
right number came out for 232 of 342 quarters, 68%. The misses are a release
with no table the parser recognises (77); the wrong ones are a non-GAAP or
continuing-operations line, a share count or an income line read as EPS, a
prior-period or year-to-date column, and a few where the XBRL reference is
itself wrong (a scale error). The fourth-quarter row is not a fair test:
its reference is the year minus nine months, which rounds differently from
a reported quarter. On the 30 development events the same rules read 85%
and matched all of them, which is what rules fitted to 30 events are worth.
The surprise therefore stays documented and not shown: a wrong EPS in one
release out of nine would put false surprises into the signal.

### Survivorship, measured

`survivorship.py` explains the 301 historical S&P 500 members with no Yahoo
history, from free sources: Wikipedia's "Historical components of the S&P
500" (removal date, name, reason) and SEC's every-name-ever CIK file. 21
had only changed ticker (ABC is now COR, ANTM is ELV, UTX is RTX); a rename
is accepted only when the new ticker is a current member whose "date added"
predates the switch, or when the same CIK trades under a new ticker. Their
histories are now read under the new ticker (`data/survivorship/aliases.json`).
Of the 280 left, 126 were acquired, 37 dropped for size, 11 split or spun
off, 19 failed while in the index (bankrupt, or seized by the FDIC: Lehman,
WaMu, Ambac, SVB, First Republic, ...) and 87 have no removal record (mostly
2005-2009).

With the renamed members back, the portfolio results moved by at most half
a point a year in one window and 0.1 over 2006-2025 (the table above is
regenerated with them). As a pessimistic bound, the equal-weight universe with every
failed member held to zero in its last month (`EW_failures`) returns 6.1%
instead of 6.6% a year in 2006-2012 and 10.5% instead of 10.8% over
2006-2025. The 126 acquired names are still missing. This section used to
conclude that survivorship does not drive the price-based results and that
the missing takeovers, if anything, understate the universe; the cross-check
below measures the opposite.

### Survivorship, cross-checked against an outside dataset (November 2026)

`crosscheck.py` compares the universe of `strategy.py`, month by month over
2006-2025, with github.com/Johnbrick123/sp500-data (release snapshot-2026-11:
every S&P 500 member with a price, dead companies included, drawn from
Yahoo, Tiingo, the old Quandl WIKI file and CRSP) and with RSP, the
equal-weight S&P 500 fund, as a yardstick neither side built.

| Equal-weight universe, CAGR | 2006-2012 | 2013-2019 | 2020-2025 | 2006-2025 |
|---|---|---|---|---|
| Ours (names Yahoo still serves) | 6.6% | 14.8% | 11.1% | 10.8% |
| Their prices, our names | 6.6% | 14.7% | 11.1% | 10.8% |
| Their prices, every member | 5.2% | 14.0% | 10.8% | 9.9% |
| The members we lack | 2.6% | 10.7% | 5.6% | 6.3% |
| RSP (after fees) | 5.2% | 13.5% | 10.7% | 9.7% |

- **The benchmark is overstated by about a point a year**, 1.4 points in
  2006-2012. We hold a return for 322 of about 500 members a month in
  2006-2012, 405 in 2013-2019 and 473 in 2020-2025; the members we lack
  returned 6.3% a year against 10.8% for the ones we hold. RSP agrees with
  the full universe, not with ours.
- **The prices we do hold are sound**: on 94,858 common name-months, 99.85%
  of monthly returns agree within half a point, and their prices on our names
  reproduce our benchmark.
- **Fourteen symbols were answering with the wrong company.** The first
  run of this check found EP, GR, JCI, DD, CPWR, PLD, CCU, WEN, TT, KG, CB
  and GENZ disagreeing for 13 to 67 months each, and BBT and PARA with no
  counterpart: Yahoo answers for the ticker with its later owner, or with
  the acquirer's history (today's Chubb is ACE before 2016, Prologis is AMB
  before 2011). Fourteen renames had also been missed, because Yahoo does
  answer for the old ticker (BBT, FB) or the CIK-based recovery did not
  find the new one (GPS, CTL, SYMC). `universe.PLACEMENTS` lists each with the
  corporate event behind it: the stretch is moved to the symbol that holds
  the company's history, or left out when no free series does. Name-months
  disagreeing by more than five points fell from 414 to 19.
- **What still disagrees is one month at a time**: nineteen names, several
  of them in a spin-off month (EXPE 2011-12, HPQ 2015-11, DHR 2016-07),
  where Yahoo's adjusted close and the holder's actual return differ.
- `backtest.py`, `earnings.py` and `shorts.py` still take a price by the
  membership ticker and do not read `PLACEMENTS`. Their stored results
  predate it; the exposure is 36 of 20,323 verdict-backtest rows and 157 of
  53,003 earnings events (BBT, CB, IR, JCI, WEN).

The dataset has no licence and part of it derives from CRSP: it is read as
a check, not stored here.

### Price strategies on the full universe (pre-registered, same outcome)

Phase 8's rules, unchanged, run by `crosscheck.py` on the outside universe
with its dead companies (plan.md, Phase 11; the criterion is Phase 8's, the
benchmark now the full universe).

| Full universe | 2006-2012 | 2013-2019 | 2020-2025 | 2006-2025 |
|---|---|---|---|---|
| A, CAGR / Sharpe / max drawdown | 7.5% / 0.64 / −10% | 8.0% / 0.82 / −10% | 6.8% / 0.37 / −17% | 7.5% / 0.59 / −17% |
| B (A + quality) | — | 8.8% / 0.84 / −9% | 7.7% / 0.38 / −23% | — |
| A without the regime switch | −1.2% / −0.09 / −52% | 9.8% / 0.88 / −15% | 9.4% / 0.45 / −21% | 5.7% / 0.34 / −52% |
| Equal-weight universe | 5.2% / 0.28 / −56% | 14.0% / 1.10 / −14% | 10.8% / 0.49 / −28% | 9.9% / 0.54 / −56% |

The outcome is the one already recorded: A beats the universe on Sharpe and
drawdown in 2006-2012 and not in 2013-2019, B does not pass. What changes is
the level. Strategy A loses 1.9 points a year in 2006-2012 and 1.1 over
2006-2025, slightly more than the benchmark does, so momentum picked from a
universe without its casualties was flattered more than the average name.
Without the regime switch it loses money over 2006-2012. B barely moves
(9.0% to 8.8% a year in 2013-2019): only companies with a verdict row can
pass its filter, and the dead companies the verdict backtest now scores
are keyed by their old tickers, which this price universe does not use.

### Multiple testing (pre-registered correction, November 2026)

`multitest.py` counts the tests. The summaries hold 424 rank-IC t-statistics
(25 signals at six horizons, a sector-neutral version at two of them, in two
universes, plus the earnings and short-interest tests); twelve more that this file reports but
never stored were added with the t stated here. Of those 436, 67 have
|t| >= 2 where chance alone would give 20, and the t a single test needs
after a Bonferroni correction is 3.86.

Seventeen survive Bonferroni and Holm, eighteen Benjamini-Hochberg-Yekutieli.
Seventeen of the eighteen are 24- and 36-month horizons, whose t-statistics
rest on 16 to 20 overlapping dates and were already ruled out above as
meaningless. One is not: the bank valuation pillar among mid/small
financials in 2020-2025 (t 5.4, worth 4.3 after the correction).

| 12-month or shorter claim | t | t after BHY | |
|---|---|---|---|
| Bank valuation, mid/small 2020-2025 | +5.4 | 4.3 | survives |
| Bank valuation, S&P 500 2013-2019 / 2020-2025 | +2.6 / +2.5 | 0.4 / 0.2 | does not |
| Net issuance, mid/small 2013-2019 | −3.0 | 0.9 | does not |
| Net issuance, 2020-2025, S&P 500 / mid/small | −3.1 / −2.9 | 1.2 / 0.9 | does not |
| SUE from the release, 2013-2019, S&P 500 / mid/small | +2.6 / +2.9 | 0.4 / 0.9 | does not |
| Days to cover, 3 months, mid/small | −2.9 | 0.9 | does not |

So taken one test at a time, nothing this project measured on returns at a
year or less clears the bar except one cell of the bank result, in a window
that had been looked at before. Two limits on that reading, in opposite
directions. The correction gives no credit for repetition: net issuance
shows the same sign at t near −2.9 in three of four window-universe pairs,
which a per-test adjustment cannot see. And the family is only what left a
record; anything tried and discarded without one would raise the bar.

Deflated Sharpe ratios, on monthly returns of the repaired Yahoo universe,
against the four variants `strategy.py` runs: SPY with the regime switch
0.997 (Sharpe 0.86), strategy A 0.981 (0.68), strategy B 0.889 (0.58, 130
months). The Sharpe the best of four unskilled variants would be expected
to show is 0.19. Four understates the search behind the regime rule, which
was picked after the results were seen and comes from a paper that chose it
among others, and strategy A's own Sharpe falls to 0.59 on the full
universe.

### Sector fair values for utilities and REITs (pre-registered, failed)

A regulated utility mostly reads "fiyatlanamaz" here, because capital
spending leaves no free cash flow to value, and a REIT is valued like an
industrial company. Two candidates were run as backtest columns before
anything in the product changed (plan.md, Phase 17): for utilities the
justified price-to-book value already used for banks, on the argument that
a regulated utility earns an allowed return on its equity base; for REITs a
reversion to the company's own median EV/EBITDA. The test was the one the
bank model met, within the sector: a 12-month rank IC above zero with
t >= 2 in 2013-2019 and above zero in 2020-2025.

| Within-sector IC of the upside (t) | S&P 500 2013-2019 | S&P 500 2020-2025 | mid/small 2020-2025 |
|---|---|---|---|
| Utilities, justified P/B | −0.04 (−0.4) | −0.16 (−2.3) | −0.02 (−0.2) |
| REITs, own EV/EBITDA | +0.02 (0.2) | +0.07 (0.5) | −0.04 (−0.7) |

Neither passed. The utility model has the wrong sign in every cell, and
significantly so in 2020-2025: the utilities it called cheap went on to
lag. The REIT model shows nothing. With 16 to 30 names a date the smallest
effect either test could see is about 0.2, and mid/small could not field
20 names in 2013-2019 at all, so this says the models are unproven, and for
utilities wrong, not that no sector model exists. Those companies stay
unpriced, and insurers stay on the bank model.

### Distance to default as a fall-risk input (pre-registered, failed)

The fall-risk read uses trailing volatility alone. The candidate was the
naive Merton distance to default (Bharath & Shumway 2008; market value,
total debt, trailing volatility and return, nothing fitted), for
non-financial companies (plan.md, Phase 15; AUC for a fall of more than 25%
in twelve months, the 2020-2025 window opened for it).

| AUC (t) | S&P 500 2013-2019 | S&P 500 2020-2025 | mid/small 2013-2019 | mid/small 2020-2025 |
|---|---|---|---|---|
| Distance to default | 0.64 (6.2) | 0.57 (2.7) | 0.59 (3.4) | 0.59 (5.5) |
| The same, volatility under 35% | 0.63 (4.6) | 0.48 (−0.8) | 0.57 (2.6) | 0.54 (1.4) |
| Trailing volatility alone | 0.73 (9.0) | 0.65 (5.1) | 0.70 (9.9) | 0.63 (8.4) |
| Business score, same rows | 0.58 (3.2) | 0.56 (3.7) | 0.59 (4.0) | 0.59 (11.8) |

It separates the companies that fell in every cell, which was the first
criterion. The second asked whether it does so beyond volatility, among the
names under the 35% line the product already draws, and there it fails on
the S&P 500 in 2020-2025. It is mostly volatility restated with leverage,
and plain volatility does better than it in every cell — better, too, than
the business score. The read stays on volatility; distance to default is
computed in the backtest and not shown. (These figures are from the rows
as they stood before the universe was extended.) Short interest could not be tested
this way (its data begins in 2018) and the evidence composite's fall AUC had
already been seen in both windows.

The company page now opens with the fall-risk read, and the screen can be
narrowed by it. A fixed line was the wrong tool for that: 35% put 8% of
S&P 500 members in the high group in 2013-2019 and 39% of them there in
November 2026. The read below replaced it.

### The risk read from the daily range (from the indicator study)

`indicators/` maps 203 technical indicators without looking at a return
(two families hold 41% of them; about thirty separate things in all), then
tests one representative of each family under rules written first (its
README has both). Nothing ranked twelve-month returns. One thing separated
the companies that fell, and better than trailing volatility: the daily
range, ATR over the price, with an AUC of 0.72 (t 14.2; 0.72, 0.74 and 0.68
by window) against 0.68 for the volatility read on the same rows, and 0.69
among the companies under the 35% line.

The product now reads risk from it. A company is placed by the fifth its
daily range falls in among the screen's members at the last run, and shown
the share of companies in that fifth, at quarter ends 2006-2025 and ranked
the same way, that fell more than 25% in the next twelve months
(`indicators/risk_table.py`, 38,225 observations, dead companies included):

| Daily-range fifth | Fell more than 25% | 2006-2012 | 2013-2019 | 2020-2025 |
|---|---|---|---|---|
| 1, calmest | 4.8% | 8.0% | 2.6% | 4.1% |
| 2 | 7.6% | 10.9% | 5.3% | 6.9% |
| 3 | 9.8% | 12.8% | 7.9% | 8.8% |
| 4 | 13.3% | 17.0% | 11.1% | 12.0% |
| 5, most volatile | 20.9% | 22.9% | 22.3% | 17.0% |
| All | 11.3% | | | |

The order holds in every window. Because the place is a rank among the
members of the day, a fifth of the screen is in each group whatever the
market is doing. Momentum had also qualified under the study's rule and is
not used: inside a daily-range fifth, weak and strong momentum differ by a
point or less and not in one direction, so its separate effect was the
daily range seen twice.

The range is the 14-day ATR over the price **averaged over 60 days**. The
indicator lab (`indicators/lab/`) searched for risk measures that beat the
14-day reading: 63 hypotheses, most of them combinations, almost all worse
(adding trend, volume, drawdown or liquidity diluted it; nothing without a
range in it came close). One was confirmed in all three of its stages —
the range plus a small weight on its own 60-day minimum — by 0.003 to 0.006
of AUC: what a company's range has been for a quarter says a little more
about the next year than what it was this fortnight. The gain is too small
to matter. What matters is steadiness: by the 14-day range 25% of companies
change fifth from one week to the next and 13% of the top fifth leave it;
by the 60-day average 5% and 3%, with the same fall rates by fifth and an
AUC not below the 14-day one in the later stages (+0.008 and +0.003, plan.md
Phase 22). The verdict reads the top fifth, so that is a fifth of the label
changes. Where a
company cannot be placed (no run, or no daily bars) the read falls back to
trailing volatility and says which measure it is using; the backtest still
uses that one, its price files being monthly.

The verdict reads it too (plan.md, Phase 19). A company in the most
volatile fifth is not called "yatirim yapilabilir": it is "koşullu", and the
rationale gives the fall rate of its group. The page had been showing
"investable" beside "fall risk very high" for eight of 76 companies, the
same kind of contradiction as a pass on valuation beside a price above fair
value. Once in the top fifth a company stays there until its range is 5%
under the line, so one sitting on the line does not change label weekly.
The backtest has no daily range and applies the rule with the top fifth of
each date by trailing volatility.

This is a rule about what the label promises, not a claim about returns.
On the old 35% line, companies called investable in 2013-2019 that were
volatile fell more than 25% in a year 14.8% of the time against 4.7% for
the rest. In 2020-2025 they did not fall more (6.2% against 7.4%) and
returned far more on average (40% against 14%), that line then catching
the rebound from March 2020. A volatile company can do very well; it is
also the kind most likely to fall hard, and the label now says so.

With the backtest re-run under the rule, the share of companies called
investable that fell more than 25% in a year went from 5.4% to 3.2% in
2013-2019 and from 7.1% to 6.6% in 2020-2025 on the S&P 500, and from 5.2%
to 4.5% and 9.7% to 8.8% on mid/small; their mean return went from 13.5%
to 14.0% and from 19.9% to 17.4%, and on mid/small from 14.9% to 14.3% and
19.4% to 19.3%. Fewer hard falls in every cell, and in one of them a
visibly lower average return.

### Trading signals (entry, exit, stop; judged trade by trade)

A second view, "Sinyaller", beside the company screen: for US stocks, 36
ETFs and 51 Borsa Istanbul names, the instruments that a trading system
would enter at the next open or holds now, each system's record, and every
trade it made on an instrument since 2006 drawn on the price. The systems
and the method are in `indicators/lab/README.md`; the numbers here are
what a reader should hold on to.

The criterion is profit per trade after costs, the owner's choice. 57
systems were tried per market (17 textbook ones, 40 combinations of
indicator components). Nearly all are profitable per trade in 2006-2016,
because the instruments rose; fewer than half beat a purchase made on a
random day and held as long. A system is shown when it made money per
trade and beat the random entry in 2006-2016 and again in 2017-2021, and
listed when it did so a third time in 2022-2025:

| | Tried | Shown | Listed | What the listed ones are |
|---|---|---|---|---|
| US stocks | 57 | 8 | 1 | buying a two-sigma fall that came without a volume spike or a gap: +0.09% a trade in 2022-2025 over eight days, 60% winners |
| ETFs | 57 | 8 | 4 | buying falls inside an uptrend: the best +1.00% a trade, 74% winners |
| BIST | 57 | 22 | 17 | trend and breakout systems: +3% to +18% a trade in nominal lira, 28% to 53% winners, a few very large gains |

None passed the lab's stricter rule (a t of 3, then 2). About seven of 57
would be listed by chance. The US edge is a tenth to half a percent a
trade and does not survive a careless fill; the BIST figures are in lira,
on companies that are still listed, and 2026 so far is negative for most
of them. The list was fixed on 2026-11-13 after every period had been
read, so the record that counts from here is the trades opened afterwards,
which the view shows on their own line. This is a record of what rules
did, not advice to trade them.

The list is led by one combined algorithm per market, not by the
separate systems: every instrument-day on which any system signals is a
candidate, and a score fitted on 2006-2016 (how many systems agree, how
much of the market is a candidate that day, where the price stands in its
trend, momentum, volume and range) decides which candidates are taken
(`indicators/lab/combine.py`). Chosen on 2017-2021 and read once on
2022-2025, the S&P 500 dip algorithm made +0.62% a trade with 65% winners
where taking every candidate made +0.09%, and +0.94% against +0.09% on
2017-2021; ETF dips gained nothing from it, BIST has two with few trades,
and no combination of the trend systems qualified on US stocks or ETFs.
An instrument's page shows one summary: the combined signal for the short
horizon and the company verdict for the long one, which were tested
against each other and do not inform each other.

Every trade has a stop and is also stated in R (its net result over the
distance from entry to stop). Which stop was put to a test of its own:
22,902 combinations of initial stop, trailing stop, break-even move,
target, stall limit and exit rule, plus 29 authored designs, chosen on
2017-2021 and read once on 2022-2025 (`indicators/lab/stops.py`). None
beat the stops the systems already had on the last period, and on these
systems any stop costs some profit per trade; what a stop buys is a
smaller bad trade, and not when the price opens under it. So authored
stops stay, the eight shown systems written without one take their
family's best tested stop, and the daily list gives the stop, the risk as
a share of the price and the position size that risks 1% of an account
with no position over a fifth of it.

### Short interest (pre-registered, narrowly failed)

`shorts.py` tests FINRA's free consolidated short interest (from 2018, one
mid-month settlement a month, returns starting 14 days after settlement to
cover publication). Signal: days to cover (short position / average daily
volume, Hong et al. 2016), predicted negative.

| Rank IC (t), 2018-2025 | 1 month | 3 months |
|---|---|---|
| S&P 500, days to cover | −0.016 (−1.9) | −0.023 (−2.2) |
| mid/small, days to cover | −0.020 (−2.5) | −0.026 (−2.9) |
| S&P 500, short / shares | −0.017 (−1.4) | −0.027 (−1.5) |
| mid/small, short / shares | −0.022 (−1.8) | −0.037 (−2.1) |

The criterion (1-month IC < 0 with |t| >= 2 in both universes) failed on
the S&P 500 by a tenth of a t-statistic and is not relaxed after the fact.
The sign is right in every cell and the 3-month result is significant in
both universes; the most-shorted fifth trailed the least-shorted by about
1-1.3 points over three months. It is documented, not shown as a signal.

**Forward tracking.** With the holdout spent, the only clean test left is
the future. `tracking.py snapshot` freezes the current screen with its
prices into `tracking/` (kept in the repository, because a snapshot cannot
be regenerated); `tracking.py report` reprices every snapshot and compares
each verdict group and the top ten with that snapshot's average name and
with the S&P 500. A scheduler takes one every Monday (`scripts/snapshot.plist`,
`tracking.py snapshot --weekly`). Weekly snapshots overlap almost entirely,
so they add little evidence on a twelve-month return and differences still
mean little before six to twelve months; what they add is a count of how
often a verdict changes from week to week, and a record no single day's
prices decide.

`validate.py` is the regression guard. Run it after any change to `edgar.py`:
it checks the derived quarters against each company's own reported fiscal
year, the balance sheet identity, sign conventions and period continuity
across a fifteen-company universe.

## Setup

```bash
cp .env.example .env       # set SEC_CONTACT to your own address
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python anthropic pydantic fastapi "uvicorn[standard]"
uv pip install --python .venv/bin/python numpy TA-Lib    # only for the signals view
cd web && npm install
```

No API key is required. Ingest, metrics, scores, trends, the rule-based
assessment and the whole UI run without one. The optional narrative layer
(`analyst.py`) is the only part that calls a model; copy `.env.example` to
`.env` and fill it in if you want it.

## Running

Two processes. The Python engine serves the data:

```bash
.venv/bin/uvicorn api:app --app-dir src --port 8000
```

and Next.js serves the UI, proxying `/api/*` to it:

```bash
cd web && npm run dev     # http://localhost:3000
```

Command line, no browser needed:

```bash
.venv/bin/python src/report.py PFE            # evidence package
.venv/bin/python src/interpret.py PFE         # rule-based read, no key needed
.venv/bin/python src/verdict.py KO            # price, valuation, verdict
.venv/bin/python src/ranking.py               # rebuild the screen (~3 min)
.venv/bin/python src/analyst.py PFE           # full AI report
.venv/bin/python src/analyst.py PFE --dry-run # assemble the request, spend nothing
.venv/bin/python src/validate.py              # data-quality harness
.venv/bin/python src/backtest.py              # point-in-time signal test, dev window (~2 min)
.venv/bin/python src/backtest.py --holdout    # also print the 2020+ holdout (logged)
.venv/bin/python indicators/lab/signals.py refresh   # today's signals (~5 min)
```

## Scope

`intraday/` is a separate study with its own README: whether five-minute
bars of price and volume say anything about the next bar that survives the
cost of trading it. It shares only the tools that count tests.

US markets only. BIST is deferred: KAP publishes XBRL but has no public API,
so it needs a scraper rather than a client.

The output is an analysis tool, not investment advice. It reaches an explicit
investability verdict from stated, inspectable criteria, and every verdict
carries its own caveats and the assumptions behind it — but it is not a
licensed recommendation and produces no target price. In Türkiye,
"yatırım danışmanlığı" is an SPK-licensed activity; get advice on that
before publishing this commercially.

The headline fair value comes from reversion to the company's **own
historical EV/FCF multiple**, not from a discounted cash flow. A DCF needs a
discount rate, and the rate is where the answer actually comes from: NVIDIA's
regressed beta of 2.19 produces a 14.5% rate while the growth fed into the
same model is capped at 15%, so the trait that raises the rate is then
removed from the numerator and the business prints as 67% overvalued. On that
method every quality large cap came out 25-70% expensive, which is not a
finding — it is one macro opinion wearing a per-company disguise. Multiple
reversion needs no rate, no terminal value and no growth forecast, and it is
the assumption practitioners actually use for a target. The discounted value
is kept as a cross-check; when the two disagree, the answer is assumption.

Building it surfaced two errors worth naming. Historical market value must
use the share count **of that period** — Apple retired roughly 45% of its
shares over the window, so today's count understates 2016's market value by
nearly half and inflates the premium the company appears to trade at. And the
price series is split-adjusted while a filing's share count is not: Walmart's
2024 three-for-one split made its historical multiple read 8.7x against a
current 40.5x, a phantom 366% premium. Split history is fetched with the
prices and applied to the counts.

A median is only as representative as its window, so the reference span is
reported and flagged: NVIDIA has barely three years of positive free cash
flow here, all of it inside the AI build-out, which makes its "own history" a
boom rather than a norm.

The discounted cross-check is deliberately not a single number. A terminal value is
hypersensitive to the gap between the discount rate and the growth rate — one
point on the rate moves Coca-Cola's estimate from 68 to 53 — so the output
carries a base estimate, a 3x3 sensitivity grid behind it, and a divergence
flag when the model and the market disagree by more than 60%. At that
magnitude the likelier reading is that the price knows something a
beta-derived discount rate cannot see (a patent cliff, a legal exposure,
structural decline), not that a mega-cap is mispriced by half.

Three choices keep the discounted value honest rather than precise. The cash
flow base is the median free-cash-flow margin over the available history
applied to current revenue, not spot trailing FCF — otherwise a capex trough
gets projected for a decade, which valued Microsoft at 136 against a 510
price. Growth comes from revenue rather than free cash flow, because the
revenue series is far less noisy, and is clamped to −5%…+15%: a ten-year
explicit forecast above that outruns nearly every historical precedent, and
a trailing window happily reads ExxonMobil's 2020 trough as secular growth.
Beta is floored at 0.50, since no listed equity is meaningfully less risky
than half the market.

The verdict is a decision rule, not an average. A failure in balance-sheet
safety or in business quality blocks the verdict outright, because a cheap
price does not compensate for either, and the weakest of those pillars caps
the composite so a strong dimension cannot hide a failing one. Weak earnings
quality warns rather than blocks, for the reason above. One consistency rule
sits on top: the valuation pillar weighs three reads and the headline fair
value is only one of them, so the pillar can pass while the price stands more
than 10% above that fair value. Such a company is "koşullu", not investable —
a label and the number printed beside it must not contradict each other. The
rule was added in November 2026 for that reason, not from a measurement. A
second rule of the same kind, on fall risk, is described under "The risk
read from the daily range".

Labels moved without any news from the company. Between the runs of 9 and
13 November 2026 the 10-year yield rose from 4.86% to 5.10%; 80 of 427 fair
values moved (median −3.9%; the two examined, a justified-P/B and a
discounted-cash-flow value, both took the spot yield), 347 did not, and 29
of 502 verdicts changed — twelve of the fourteen that left "yatirim
yapilabilir" did so because a valuation score sitting just above the 60 line
slipped under it.

Two changes answer that (plan.md, Phase 14, judged on 2013-2019 only). The
risk-free rate is the mean of the last three months of daily 10-year yields,
not the spot value. And the valuation band has a margin: the price pillar
passes at 60 and then keeps passing down to 55, is weak below 40 and then
stays weak up to 45; the previous reading is the last screen run, or the
quarter before in the backtest, and the rationale says so when the margin
rather than the line decides. The consistency rule above keeps no margin.

| Verdict changes between consecutive quarters | S&P 500 | mid/small |
|---|---|---|
| Before | 23.0% | 24.6% |
| Smoothed rate | 22.7% | 24.3% |
| Smoothed rate and margin | 22.0% | 23.0% |

The financial valuation IC went from +0.130 to +0.128 and stayed at +0.088,
so both pre-registered conditions held and the changes are in. At quarterly
spacing the effect is a point or so: a quarter brings a filing and three
months of price, against which five points of margin are little. The
movement they are aimed at is week to week — eleven of those twelve
companies had a new score above 55 — and that is what the weekly snapshots
will count.

Prices come from an unofficial Yahoo Finance endpoint — no key, no
documented contract. `valuation.quote()` is the single function to replace
with a licensed feed. Share counts come from the SEC filing cover page
(`dei:EntityCommonStockSharesOutstanding`), not the price vendor.

## Notes on the data

EDGAR is free, official and complete, but several of its behaviours corrupt
data silently rather than erroring. Cash-flow items in a 10-Q are
year-to-date, not quarterly. The fiscal year-end quarter never appears
directly. Tag usage varies by filer and era — Pfizer never tags
`OperatingIncomeLoss`; Ford stopped tagging `NetIncomeLoss` in 2025. A
reorganization mints a new CIK, so `company_tickers.json` maps XOM to a
holdco with one quarter of history. A single tag can carry two values for the
same date. `edgar.py` documents each of these where it handles them.

A trap sits in the valuation rather than the ingest: a flat sector discount
rate makes every defensive business look overvalued. Coca-Cola's real cost
of capital is near 5.8% (beta 0.29), and discounting it at a generic 9%
values it at roughly half the market price. The rate is regressed per
company for that reason.

Another sits in the metrics: sustained buybacks drive
book equity to zero or below at many mature US companies, and once it goes
non-positive every equity ratio produces a confident-looking wrong answer
(McDonald's computes to an ROE of -859%). Those ratios are withheld, not
reported, and the condition is surfaced as its own finding.
