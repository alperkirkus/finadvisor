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

**The verdict has no measured predictive power, and the screen's score
leans the wrong way.** The project's own point-in-time backtest (51
companies, 2013-2019 development window, lookahead and restatement bias
removed by construction) scores exactly the number the screen orders by and
finds a *negative* cross-sectional rank correlation with 12-month forward
returns (mean IC **−0.12**, Newey-West t = −3.3). Most of it is factor
exposure rather than skill: the score loads on profitability and *against*
momentum, and its alpha after Fama-French five factors plus momentum is not
significant. The accrual ratio points the way Sloan (1996) predicts
(lower accruals, higher returns), but after the same factor controls that
too stops being significant here.

So this is a structured, inspectable read of financial condition against
criteria that are written down — not a return forecast, not investment
advice, and not a target price. The thresholds are deliberately **not** tuned
to the backtest: with about 42 survivorship-biased names per date and a
single market regime, the smallest effect the test can detect is an IC of
0.10, and tuning against it would be overfitting rather than calibration. Every weight in `verdict.py` carries its justification inline,
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
whatever filings are already cached (52 companies), not all 10,412 filers —
scoring one needs a live quote and a beta regression, so the screen is built
offline by `ranking.py` and served from a file.

`backtest.py` measures whether the signal predicts anything. It rebuilds
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
pillars say. One weak reading is noise; both together is the only signal in
this model with measured evidence behind it.

Component weights inside each pillar come from how reliable each measure is
known to be, documented next to the weight in `verdict.py` — not fitted to
the backtest, which cannot support a fitted weight. The accrual ratio carries
the largest single share for the one reason that survives scrutiny: it
replicates a published effect and was the strongest signal in this project's
own test. Piotroski is reported but no longer weighted, because its prior and
its measurement agree that it does not discriminate here.

**The backtest finding is negative and worth stating plainly.** On the
development window (24 quarterly dates, about 42 names each) the screen's
score ranks 12-month returns the wrong way: mean IC −0.12 (t = −3.3), top
quintile 4.5pp behind the bottom. The sign holds at shorter horizons but
weakens (−0.06 at one and three months). The factor regression explains
much of it — loadings of +0.43 on profitability (RMW) and −0.31 on momentum —
and leaves an alpha of −0.40% a month at t = −1.4, not significant. The
valuation pillar is the likely source of the momentum tilt: "cheap against
its own history" mostly selects stocks that have recently fallen, and its
own IC is negative (−0.08).

The accrual ratio carries the expected sign (IC −0.10 at six months,
t = −3.6, and the below-−6% cohort beats the universe in the pooled legacy
test), but its long-short return loads on the investment (CMA) and value
(HML) factors and has no significant alpha after them. F-Score shows no
ranking power on the development window (IC ≈ 0.01), consistent with its
documented weakness among large caps. The verdict is therefore presented as
a structured read of financial condition against stated criteria, not as a
return forecast, and the thresholds are deliberately *not* tuned to this
data. The universe is also survivorship-biased (WBA, delisted in 2025, no
longer resolves at all), which inflates absolute returns; comparisons
between names on the same date are less affected.

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
