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

**The verdict has no measured predictive power.** The project's own
point-in-time backtest scores exactly the number the screen orders by, on
every S&P 500 member of the day that can still be resolved (about 316 names
per date, 2013-2019 development window, lookahead and restatement bias
removed by construction). Its cross-sectional rank correlation with
12-month forward returns is **+0.01** (t = 0.6) against a smallest
detectable effect of 0.06 — none. After Fama-French five factors plus
momentum its alpha is exactly zero; what it does carry is a profitability
tilt. No single input does better: the accrual ratio points the way Sloan
(1996) predicts but is not significant, and Piotroski's F-Score leans
slightly the wrong way.

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
      +-- api.py       FastAPI: /api/company, /api/search, /api/interpret,
                            /api/valuation, /api/analyze
                            |
                        web/  Next.js UI
```

The landing screen lists the ten best-scoring companies. It calls
`verdict.assess` per company and orders the results — a screen ranked by a
different rule than the one it explains would be a second, hidden model.
Blocked companies sink to the bottom whatever they score, and so does anything
whose valuation rests on a large model-versus-market gap: the number may be
right, but promoting it silently would be its own distortion. The universe is
a fixed list of 53 large caps (`ranking.SCREEN_UNIVERSE`), not all 10,412
filers and not the backtest's S&P 500 cache —
scoring one needs a live quote and a beta regression, so the screen is built
offline by `ranking.py` and served from a file.

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
once the level is known. And the **accrual gate** is decisive rather than
diluted: when the accrual ratio is above the framework's warning level *and*
cash conversion confirms it, the verdict is blocked whatever the other
pillars say. One weak reading is noise; both together is the pattern the
accounting literature ties to later earnings disappointments, although this
project's own backtest finds the accrual effect too weak to measure among
large caps.

Component weights inside each pillar come from how reliable each measure is
known to be, documented next to the weight in `verdict.py` — not fitted to
the backtest, which cannot support a fitted weight. The accrual ratio carries
the largest single share because it is the best-documented earnings-quality
measure in the literature, not because this project measured it working.
Piotroski is reported but no longer weighted, because its prior and its
measurement agree that it does not discriminate among large companies.

**The backtest finding is negative and worth stating plainly.** On the
development window (24 quarterly dates, about 316 names each) the screen's
score has a mean 12-month IC of +0.013 (t = 0.6), and its top quintile beats
the bottom by 0.8pp (t = 0.6). The smallest IC this sample can detect at 80%
power is 0.059, so the result is a measured absence, not an unmeasured one.
Regressed on Fama-French five factors plus momentum, the monthly long-short
return has an alpha of 0.00% (t = 0.0) and a profitability (RMW) loading of
+0.47: the score picks profitable companies and nothing beyond what that
factor already pays. No pillar reaches significance.

An earlier run on a fixed list of 51 mega caps found the score ranking
returns the wrong way (IC −0.12, t = −3.3) and an accrual effect at
t = +4.2. Neither survives on the broader universe; both were small-sample
artifacts, which is the reason for testing on the index rather than a hand
list. On the broad universe the accrual ratio keeps the expected sign
(IC −0.03, alpha −0.30% a month, t = −1.5) and F-Score leans slightly the
wrong way (IC −0.03, t = −2.2), in line with its documented weakness among
large caps.

Survivorship is reduced, not removed. About 75% of each date's members are
scored; most of the rest are companies later acquired or delisted, which
have neither a CIK in the SEC ticker map nor a free price history any more.
That inflates absolute returns; comparisons between names on the same date
are less affected. `--universe legacy` reruns the original 51-name list.

The backtest also measures the textbook accounting anomalies as candidate
replacements, each with the sign its source predicts: gross profitability
(Novy-Marx 2013), asset growth (Cooper, Gulen & Schill 2008), net share
issuance (Pontiff & Woodgate 2008), 12-1 month momentum (Jegadeesh & Titman
1993) and earnings yield (Basu 1977), plus an equal-weight composite of their
within-sector percentiles with the accrual ratio. Every IC is also reported
sector-neutral, so a signal that only sorts banks below software firms
scores zero. On the development window none of them, and not the composite,
ranks S&P 500 returns: every 12-month IC is within ±0.03, below the 0.06 the
sample can detect, and the composite's alpha after the six factors is
0.01% a month. Their factor loadings are the expected ones (asset growth
−0.59 on CMA, earnings yield +0.72 on HML, gross profitability +0.43 on
RMW), so the signals are built correctly; among large US companies in
2013-2019 they simply earned nothing beyond the factors they proxy. Nothing
from this set is promoted into the verdict. Earnings and revenue surprise
(seasonal random walk, Foster, Olsen & Shevlin 1984; Jegadeesh & Livnat
2006) fare no better: post-earnings drift is not visible among these names.

What the system does carry is a read on **risk**. A higher business score
goes with fewer large falls (12-month AUC for a drop of more than 25%:
0.60 on the development window), and it holds among names of similar
volatility (0.57) and in the 2020-2025 holdout (0.58, t = 3.0). The
valuation pillar went the other way on the development window (0.43).

That suggested a v2: order the screen by business score alone, and let a
strong business at a merely *fair* price (valuation ≥ 40) count as
investable. Its holdout criteria were written down before the one logged
look at 2020-2025: fewer large falls among "investable" names, fewer in the
screen's top quintile, and top-quintile return no more than 1pp worse. The
first held (6.9% vs 7.2%), the second did not (8.4% vs 8.0%) — the valuation
pillar's crash link did not repeat after 2019 — so v2 was not shipped and
the rule and the screen are unchanged.

What did ship is the part that held in both windows, reported rather than
scored: each verdict now carries the trailing 12-month volatility and the
development-window rate of large falls for its group. Names with annual
volatility of 35% or more fell more than 25% over the next year 2.4 times
as often as the universe in 2013-2019 and 1.4 times as often in 2020-2025;
the rest fell 0.9 and 0.8 times as often. A weak business score on its own
(1.6x, then 1.0x) did not survive the holdout and is not used for this.

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

The verdict is a decision rule, not an average. A failure in earnings
quality or balance-sheet safety blocks the verdict outright, because a cheap
price does not compensate for either, and the weakest pillar caps the
composite so a strong dimension cannot hide a failing one.

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
