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
335 names per date in 2013-2019). Its cross-sectional rank correlation
with 12-month forward returns is **+0.02** (t = 1.1) against a smallest
detectable effect of 0.06 — nothing measurable — and its alpha after
Fama-French five factors plus momentum is 0.08% a month (t = 0.4); what it
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
seeing it, so treat it as a second in-sample window. Survivorship is total
(see below), and about 300 signal/horizon/universe combinations were tried,
so a t of 2-3 on any single one is weak evidence.

| Read | S&P 500 dev | S&P 500 2020-25 | S&P 400/600 dev | S&P 400/600 2020-25 |
|---|---|---|---|---|
| Screen score (`overall`), IC | +0.02 (t 1.1) | +0.03 (t 1.0) | +0.05 (t 1.5) | +0.03 (t 1.3) |
| Financials, bank valuation pillar, IC | +0.13 (t 2.4) | +0.13 (t 2.5) | +0.09 (t 1.5) | +0.14 (t 4.8) |
| Net share issuance, IC | −0.02 (t −0.6) | −0.09 (t −2.9) | −0.06 (t −3.0) | −0.08 (t −2.9) |
| Accrual ratio, IC | −0.01 (t −0.6) | −0.02 (t −0.7) | +0.01 | +0.01 |
| Business score, AUC for a >25% fall | 0.58 (t 3.8) | 0.55 (t 2.5) | 0.58 (t 3.1) | 0.59 (t 6.7) |

- **Return ranking: no.** Neither the screen score nor the own-history
  fair value ranks returns in any window; cheap-against-own-history names
  are mostly businesses in decline (a value trap), and none of seventeen
  filters, insider purchases or earnings surprise separated them reliably.
- **Risk: yes.** A higher business score goes with fewer large falls in
  every window, and trailing volatility of 35% or more fell more than 25%
  over the next year at 2.3x the universe rate (13.8% vs 6.1%). Each verdict
  reports the volatility base rate.
- **Financials: probably, with caveats.** The justified P/B pillar ranks
  financial-sector returns in both S&P 500 windows (t 2.4 and 2.5) and in
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

**Survivorship is total, not partial.** Every scored company still trades
today; members later acquired or delisted, and renamed companies under their
old tickers (FB, ANTM, BLL, BK), cannot be resolved with free data, so about
22% of each date's members are missing and none of the missing ones are
scored. Absolute figures shown to users (crash base rates, target hit rates,
the 13% average annual return) are biased upward. Fixing it needs a
point-in-time ticker history and delisting returns (CRSP, Sharadar).

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

Not fixed: survivorship and renamed tickers (needs paid data), regulated
utilities and REITs lack a sector valuation model (they mostly read
"fiyatlanamaz"), a dozen companies whose debt tags cannot be read are not
valued, and insurers are still valued with the bank model.

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
| A, CAGR / Sharpe / max drawdown | 9.1% / 0.80 / −9% | 9.0% / 0.88 / −11% | 7.1% / 0.39 / −17% | 8.5% / 0.67 / −17% |
| B (A + quality) | — | 9.6% / 0.90 / −9% | 7.1% / 0.35 / −23% | — |
| A without the regime switch | 1.6% / 0.08 / −50% | 10.5% / 0.91 / −14% | 9.9% / 0.48 / −20% | 7.1% / 0.43 / −50% |
| Equal-weight universe | 6.8% / 0.35 / −53% | 14.9% / 1.18 / −14% | 11.0% / 0.50 / −27% | 10.9% / 0.60 / −53% |
| SPY | 3.8% / 0.21 / −51% | 14.6% / 1.22 / −14% | 15.0% / 0.75 / −24% | 10.8% / 0.65 / −51% |

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
failed member held to zero in its last month (`EW_failures`) returns 6.3%
instead of 6.8% a year in 2006-2012 and 10.7% instead of 10.9% over
2006-2025. Survivorship is therefore not what drives the price-based
conclusions above. The 126 acquired names are still missing; takeover
premiums make their absence, if anything, understate the universe.

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
with the S&P 500. One snapshot a month is the intended rhythm; differences
mean little before six to twelve months.

`validate.py` is the regression guard. Run it after any change to `edgar.py`:
it checks the derived quarters against each company's own reported fiscal
year, the balance sheet identity, sign conventions and period continuity
across a fifteen-company universe.

## Setup

```bash
cp .env.example .env       # set SEC_CONTACT to your own address
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python anthropic pydantic fastapi "uvicorn[standard]"
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
```

## Scope

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
quality warns rather than blocks, for the reason above.

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
