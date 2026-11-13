# FinAdvisor

A personal project of one owner. Two sides: the company side (US filings to
a verdict, `src/`, tab "Şirketler") and the trading lab (price rules judged
trade by trade, `indicators/lab/`, tab "Sinyaller"). Reply to the owner in
Turkish; code, comments, docs and `plan.md` are in English.

## Layout

- `src/`: stdlib-only engine and FastAPI (`api.py`, port 8000).
- `web/`: Next.js app (port 3000, proxies `/api/*`). `./run.sh` starts both.
- `indicators/lab/`: the lab. `panel.py` (price panels), `components.py`
  (39 indicator components), `engine.py` (formulas, `Market`), `trades.py`
  (the one trade simulator), `stops.py`, `combine.py`, `position.py`,
  `hourly.py`, `consistent.py`, `shorts.py`, `book.py`, `breadth.py` (the
  owner's scorecard: every signal at a fixed risk), `trend.py`,
  `capital.py` (studies judged in money), `signals.py` (what the app
  reads). `indicators/lab/README.md` holds every result table.
- `plan.md`: the research log. Every study is a "Phase" there: the rule
  written before the run, then the outcome. Untracked scratch; never commit.
- `data/`: ignored cache (panels, results, `data/signals/`). `tracking/`:
  tracked frozen records.
- `.claude/agents/finadvisor-*.md`: the council. `.claude/skills/finadvisor-study/`:
  the order a study follows.

## Commands

    ./run.sh                                                   # API + web
    .venv/bin/python indicators/lab/signals.py build [market]  # rebuild what the app shows
    .venv/bin/python indicators/lab/<study>.py ...             # numpy + TA-Lib; numba optional, much faster with it

The project venv is uv-managed: `uv pip install --python .venv/bin/python <pkg>`.

## How results are measured

- In R with a fixed sum at risk: R = entry minus the stop of the entry day;
  a trade's result is its net result over that. Say it in money too: "at
  100 dollars a trade". The owner's bar is about +1R a trade on average;
  report the distance to it, never round it up.
- Always after costs (per side: S&P 500 0.10%, mid/small and BIST 0.20%,
  ETFs 0.05%) and say what the cost is in R when stops are tight.
- A trade statistic is not an account. Beside any per-trade figure give an
  account that holds a stated number of positions, marked daily, and what
  holding the same universe paid over the same days.
- Win rate, average win and loss in R, longest losing run, worst year.
- R is a unit, not money. Beside R a trade or R a month always say what
  share of the account 1R is and the money the positions tie up. Taking
  more signals raises R a month in proportion to the capital it needs.
- The money criterion (binding, plan.md): the account's yearly return on
  the money it ties up with idle money at the bill rate
  (`data/macro/TB3MS.csv`), beside (a) the universe held and (b) the
  universe held at the rule's own daily share invested. A rule adds money
  only if it beats (b); it replaces an index fund only if it is within a
  point a year of (a) with a shallower drawdown. Return and drawdown in
  one line use the same denominator. Never kill or keep on win rate alone.

## Research protocol (binding)

1. Write the rule in `plan.md` before the run: what is tested, on what
   data, the criterion that kills it. Then run. Then write the outcome
   under it, including when it fails. Never edit a rule after its result.
2. Placebo must be fair: same days, same universe filter, same exit and
   stop, random instrument. A placebo that drops a filter the rule uses
   credits the filter to the entry. (Phase 30 made this mistake.)
3. Score continuously or say what is left out. Block scoring in
   `trades.simulate` drops entries in the last `max_days` of a window.
4. Cluster before believing a t: trades opened in the same month are one
   bet. Report by entry year as well.
5. Count the search: how many variants, how many looks at each period.
   The best of thousands on the data it was chosen on is not a result.
   All of 2006-2025 has been used for S&P 500 long rules; only another
   universe or time after 2026-11 is unseen for them.
6. Before a rule is shown to the owner as something to trade, the auditor
   and the judge of the council read it, without being told the conclusion.
7. Report failures as plainly as successes. Do not present a result as
   confirmed when it failed its own written criterion.

## What is established (do not re-test without a new reason)

- Days-to-weeks rules on daily bars: +0.05 to +0.15R a trade at best
  (57 systems, 22,902 exit variants, combined score). Hourly bars: nothing
  survives (16,800 combinations). Shorts built from the same parts: all
  negative. Candlestick patterns and Hilbert-cycle entries: within 0.05R
  of a random purchase on the same days. The dip model as many small
  positions: no more than SPY bought on the same days.
- Entry timing adds about 0 to +0.1R over a random entry on the same days
  in the same kind of stock. What moves R per trade is selection (calm,
  trending stocks), the market gate, holding for months, and stop width.
- Long holds of calm trending stocks in an up market: about +0.4R a trade
  expected on unseen data, 42-45% winners, less return than the index with
  a much smaller drawdown.
- That rule on every signal (Phase 36): +0.59R a trade, 29 trades and
  +17R a month on 2017-2025, with 1R at 0.023% of the account: about 4%
  to 5.6% a year against 12% for holding the members, and half a point
  over the members held at the same exposure. No system's account grows
  by more than 4% a year on the money it ties up (48 systems).
- Calm stocks give more R because their stop is nearer, not more money.
  The market gate lowers drawdown and costs three to five points a year
  after 2016 (Phases 26, 39). Pyramiding doubles R per campaign and
  lowers the return on the money.
- A long/short trend portfolio of the 36 ETFs: Sharpe 0.63 over cash on
  2006-2016, 0.00 on 2017-2025 (Phase 37). Net issuance splits the trend
  book by +0.12R, t 1.0 (Phase 38). The company verdict and scores add
  nothing to long-hold trades.
- SPY bought after days of many oversold members (Phase 40): +0.21% over
  an average five days, t 1.4 by day; one point a year over the same
  share of SPY held always, all of it from 2024. Not confirmed.
- One R a trade at twenty trades a month with 1% of the account at risk
  is about 240% a year; nothing here or in the published record does it.

## Data limits

- `data/indicators/panel.npz` (S&P 500) includes delisted members from
  2017 only; earlier, names with no OHLC are missing. Mid/small, ETF and
  BIST panels are today's instruments (survivors). BIST is nominal lira
  and has a few unadjusted corporate-action bars.
- Intraday: one-hour bars reach back about three years; 5- and 15-minute
  bars 60 days. Crypto exchanges are blocked on the owner's work network;
  do not work around that.
- The outside dataset used to build `panel.npz` is unlicensed and partly
  CRSP-derived: read locally, never copied into the repository.

## Working rules

- Never send the owner's email or other personal data to an outside
  service; use a generic identity for data requests. Do not read `.env`.
- Nothing is committed or pushed unless the owner asks.
- The owner prefers decisions made and work carried through; ask only
  when the choice is his (what to build, which profile, a one-time read
  of a period kept aside).
