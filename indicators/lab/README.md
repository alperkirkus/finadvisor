# Indicator lab

Testing one indicator at a time, as a ranking, at two horizons, misses most
of what indicators are used for: conditions ("a pullback inside an
uptrend"), events (a breakout, a squeeze, a climax) and combinations of
different kinds of information. This lab is for those.

## How it works

1. **Components** (`components.py`). The mathematical cores of the
   indicator families — trend, trend strength, momentum, stretch,
   volatility and its change, volume, volume against price, bar shape —
   each one formula on daily bars. Thirty-one of them.
2. **Hypotheses**. A formula over components, an expected holding period
   of 5, 20 or 60 trading days, and the reason it should work. Two kinds:
   a `rank` gives every company a number, an `event` is true or false.
   `engine.py catalog` prints the vocabulary.
3. **An author**. Hypotheses come as a JSON file from anyone: a person, or
   a model given the catalog and asked to combine families with a market
   mechanism in mind (`hypotheses/`). A formula is checked to be nothing
   but arithmetic on known names before it runs.
4. **A ledger** (`data/indicators/ledger.jsonl`). Every trial is recorded,
   so the number of things tried is always known.

## Why many backtests are allowed here

The danger was never the number of backtests. It is searching and
confirming on the same data. So the data is cut in three, and a hypothesis
earns each stage:

| Stage | Signal dates | Who gets in | Passes when |
|---|---|---|---|
| `discover` | 2006-2016 | anything | \|t\| >= 3 and positive after costs |
| `validate` | 2017-2021 | what discovery promoted | same direction, \|t\| >= 2, positive after costs |
| `sealed` | 2022-2025 | what validation passed | read once, logged |

The direction of a signal (which end is long, or whether an event is
followed by more or less) is read off discovery and may not change after.
With M discovery trials about M × 0.003 are promoted by chance, and of
those about one in forty passes validation by chance: the ledger's counts
say how much of what survives to believe.

## How a hypothesis is scored

The universe is the S&P 500 members of the day, companies since acquired
or failed included; one that stops trading is held at its last price. A
signal is read at the close every fifth trading day, entered at the next
open and exited at the close h days later. Costs are 10 basis points a
side.

- `rank`: the rank IC against the forward return, Newey-West t; and the
  top fifth against the bottom fifth, rebalanced every h days, with the
  cost of the names replaced.
- `event`: the flagged companies' forward return against the day's
  members, on days with at least five flags, Newey-West t; net of a round
  trip.

## Running

    <research venv>/python -I indicators/lab/panel.py <dataset directory>   # once
    <research venv>/python -I indicators/lab/engine.py catalog
    <research venv>/python -I indicators/lab/engine.py discover indicators/lab/hypotheses/round1.json
    <research venv>/python -I indicators/lab/engine.py validate
    <research venv>/python -I indicators/lab/engine.py sealed
    <research venv>/python -I indicators/lab/engine.py ledger

## Results so far (2026-11-13)

Three rounds from a hypothesis author (a model given the catalog, then the
results of the rounds before): 60 mixed, 60 informed by round 1, 60 at the
60-day horizon only. With smoke, sanity and one diagnostic trial, 188
discovery trials on the S&P 500 and 184 on mid/small.

| | S&P 500 | mid/small |
|---|---|---|
| Scored in discovery | 188 | 178 |
| \|t\| >= 2 (by chance) | 10 (8.6) | 12 (8.1) |
| \|t\| >= 3 (by chance) | 3 (0.5) | 2 (0.5) |
| Promoted | 3 | 2 |
| Passed validation | 0 | 0 |

- **Nothing is confirmed.** All five promoted hypotheses failed on
  2017-2021, three with the sign reversed. The sealed years are unread.
- **The horizon decides more than the idea.** After costs, 2 of 31
  five-day hypotheses are positive on the S&P 500, 12 of 48 at 20 days,
  71 of 109 at 60 days (medians -7.7%, -1.7% and about +1% a year).
- **The discovery years do hold structure, at 60 days.** Across the two
  universes, which share no company, the t-statistics of the same
  hypotheses correlate at 0.64 at 60 days (75% the same sign) against 0.23
  at 5 and 20 days. The one theme significant in both: a twelve-month loser
  that rallies above an average went on to trail (t -3.2 to -3.7 in three
  forms), against the author's expectation each time. It did not hold after
  2016 in either universe. So the search finds things that were true of a
  period across stocks, and that is not the same as true of the next one.
- **The calendar was the one place the pieces agreed**: quarter-end winners
  trailing (t -3.0), half-year-end losers leading (t 2.0), ordinary month
  ends showing nothing (t 0.5). It was prompted by a look at the whole
  period, so it is tracked forward instead (`src/calendar_test.py`).

### Risk hypotheses

A third kind, `risk`: a number that is higher the likelier a fall of more
than 25% within 250 trading days, scored by AUC against the daily range
alone (0.744 in 2006-2015). The last 250 days of each stage give no signal
dates, so an outcome never reaches into the next stage. To pass is to beat
the range, not to match it.

63 trials. Seventeen had a positive gain, two were promoted, one passed
validation and the sealed years:

| `rank(range14) + 0.3 * rank(ts_min(range14, 60))` | AUC | Range alone | Gain (t) |
|---|---|---|---|
| Discovery 2006-2015 | 0.748 | 0.744 | +0.0045 (4.1) |
| Validation 2017-2020 | 0.710 | 0.704 | +0.0061 (3.0) |
| Sealed 2022-2024 | 0.695 | 0.692 | +0.0026 (3.4) |

The lab's one confirmed result, and a small one. Everything that added
another kind of information lost: trend, volume, weak closes, gaps,
drawdown and liquidity at a 0.3 weight changed nothing or cost a little,
as products they cost 0.04 to 0.13, and the best measure built without a
range reached 0.742. What helped was the same quantity over a longer
memory. The 60-day mean of the range, not promoted (gain +0.008, t 2.6),
is what the product now uses: not worse in the later stages and a fifth as
changeable from week to week (plan.md, Phase 22).

What has been seen before: `indicators/test.py` scored eight family
representatives alone over 2006-2025, so those single rankings are not
unseen in the later stages. No combination, event or horizon under 20 days
has been.

## Trading systems, trade by trade

Everything above scores a signal at a fixed horizon against the other
companies. A system on a chart is a different object: it gets in on one
rule and out on another, on one instrument, and is judged by its trades.
`trades.py` simulates that and keeps every trade. The criterion was the
owner's, asked and answered: profit per trade after costs, with the win
rate and the average win and loss; days to weeks in a position; US stocks,
ETFs and Borsa Istanbul.

A system is `{"id", "entry", "exit", "stop_atr", "max_days"}`. `entry` and
`exit` are true/false formulas over the components, read at the close. The
position opens at the next open and closes at the open after `exit` turns
true, at the stop (`stop_atr` average true ranges under the entry price,
hit during a day), or after `max_days`. Long only, one position per
instrument. Costs per side: 10 bp S&P 500, 20 bp mid/small and BIST, 5 bp
ETFs.

Beside the profit per trade stands what the same instrument returned over a
holding period of the same length on an average day of the stage. In a
rising market a purchase on any rule is profitable on average, and in lira
almost any purchase is; the difference, the `edge`, is the system's own
contribution. The lab's rule for "confirmed" is unchanged: positive profit
per trade and an edge with t >= 3 (by month of entry) in 2006-2016, t >= 2
in 2017-2021, then the sealed years.

    <venv>/python indicators/lab/trades.py --universe etf discover indicators/lab/hypotheses/systems_classic.json
    <venv>/python indicators/lab/trades.py --universe etf validate | sealed | ledger
    <venv>/python indicators/lab/trades.py --universe etf show sys_golden_cross SPY    # its trades, one by one

### What 57 systems did (2026-11-13)

17 classic systems (moving-average crosses, MACD, Donchian breakouts, RSI
and Bollinger dips: `hypotheses/systems_classic.json`) and 40 combinations
written by the hypothesis author after reading the classic results
(`hypotheses/systems_round1.json`), on four universes.

| 2006-2016 | Profitable per trade | Edge over random entry | Promoted (t >= 3) | Confirmed 2017-2021 |
|---|---|---|---|---|
| S&P 500 | 49 of 57 | 22 | 2 | 0 |
| S&P 400/600 | 51 of 57 | 21 | 5 | 1 |
| ETFs | 47 of 56 | 26 | 0 | - |
| BIST | 44 of 57 | 32 | 1 | 0 |

So "profitable per trade" is the easy half: nearly everything is, because
the instruments rose. The edge splits by kind. On US stocks trend and
breakout entries did worse than a random entry of the same length (Donchian
55/20 -0.83% a trade, 52-week high -0.84%, both t below -4) and buying
weakness did better. On BIST it is the reverse: trend and breakout systems
have a positive edge of 1 to 5% a trade in all three periods, carried by a
few very large winners, with t under 1.

The one system the lab confirmed through validation,
`sys_no_news_dip` on mid/small (close two standard deviations under its
20-day mean, no volume spike and no gap down in the last five days; out at
the mean, stop 2.5 ATR, 15 days), kept its edge in the sealed years
(+0.22% a trade, t 3.0) and lost it to costs (net -0.05%). The same system
has a positive edge in every period of every US universe:

| `sys_no_news_dip`, net per trade / edge (t) | 2006-2016 | 2017-2021 | 2022-2025 |
|---|---|---|---|
| S&P 500 | +0.30% / +0.16% (2.7) | +0.68% / +0.42% (3.7) | +0.09% / +0.10% (3.0) |
| S&P 400/600 | +0.26% / +0.19% (3.1) | +0.67% / +0.49% (2.2) | -0.05% / +0.22% (3.0) |
| ETFs | +0.11% / +0.03% (0.5) | +0.50% / +0.38% (2.0) | +0.29% / +0.17% (2.9) |

Small, and the most repeatable thing the lab has found about returns: a
tenth to half a percent a trade over about eight days, which a wider
spread or a worse fill removes.

A t here is of monthly means, each month one observation; the edge is the
mean over trades. They can disagree in sign when a few months hold most of
the trades (March 2020), which is why both are printed.

### What the application shows

"Shown" is weaker than "confirmed" and is called so (plan.md, Phase 23,
fixed before the list existed). `trades.py seen` scored every system once
on 2017-2021; a system is shown for a market when profit per trade and
edge are both positive in 2006-2016 and in 2017-2021, with no t asked.
`trades.py product` then read the shown systems once on 2022-2025. One
that lost there stays visible, marked, and is left out of the daily list.

| | Tried | Shown | Still positive 2022-2025 (listed) |
|---|---|---|---|
| S&P 500 | 57 | 8 | 1 (`sys_no_news_dip`) |
| ETFs | 57 | 8 | 4 (`sys_bollinger_uptrend` +1.00% a trade, edge +0.74%; `sys_no_news_dip`; two at an edge of +0.01%) |
| BIST | 57 | 22 | 17 (trend and breakout systems) |

By chance alone an eighth of the systems would have a positive edge three
times, about seven of 57. The BIST seventeen are one finding, not
seventeen: they are the same trend read in different ways and hold the
same positions. The BIST panel holds only companies still listed, in
nominal lira.

`signals.py` runs the shown systems on fresh daily bars (Yahoo; today's
S&P 500 members, the 36 ETFs, the 51 BIST names) and writes
`data/signals/<market>.json` (systems, their three-period record, the
instruments in a position or with a signal on the last bar) and one
journal per instrument with every trade since 2006. The application reads
those files under "Sinyaller"; "Veriyi yenile" runs the job.

    .venv/bin/python indicators/lab/signals.py refresh         # fetch bars, rebuild (about five minutes)
    .venv/bin/python indicators/lab/signals.py build etf       # rebuild from the bars already fetched

The list was fixed on 2026-11-13 with all three periods read. Nothing in
it is unseen any more; the trades that open after that day are counted
apart as `forward`, and they are the only test left.

## Stops, exits and R

A system used to trade with the stop its author typed beside the entry.
`stops.py` asks the question on its own (plan.md, Phase 24, rules written
before any variant was scored): which way of getting out leaves the most
in the account, over every system with an edge in a market.

`trades.py` walks a trade day by day under a stop policy: an initial stop
(ATR multiple, percent, lowest low of n days, or a formula for the
distance), a trailing stop (highest high minus k ATR, lowest low of the
previous n days, percent under the highest close), a move to break-even
at +xR, a target at +xR for all or part of the position, a stall limit,
and the system's own exit rule kept or dropped. The stop for a day is
fixed from the days before; an open under the stop leaves at the open; a
stop and a target inside one bar count as the stop. The walk is compiled
with numba when it is installed and runs as plain Python when it is not.

R is the entry price minus the stop of the entry day. A trade's result in
R is its net result over that risk. R alone always prefers the nearest
stop, because it lets the position grow without limit as the stop closes
in, so a variant is ranked by `sized`: what a trade adds to an account
that risks 1% of itself per trade and never puts more than a fifth of
itself in one position, after costs and after what the instrument pays on
an average day anyway. A variant with no stop is carried at the fifth.

    <venv>/python indicators/lab/stops.py excursions --universe etf   # how far trades run against and for
    <venv>/python indicators/lab/stops.py grid discover --universe etf
    <venv>/python indicators/lab/stops.py effects | top --universe etf
    <venv>/python indicators/lab/stops.py finalists indicators/lab/hypotheses/stops_round1.json --universe etf
    <venv>/python indicators/lab/stops.py choose | sealed | restate | account --universe etf

### What 22,931 variants did (2026-11-13)

The grid is every combination: 16 initial stops x 10 trails x 3 break-even
rules x 8 targets x own exit kept or dropped x 3 stall limits, 22,902
variants, on every system and universe; beside it 29 designs by the
hypothesis author that the grid cannot express (stop distance by formula,
an extra exit when the trade turns into something else), each with its
arithmetic in R (`hypotheses/stops_round1.json`). The pool of a market is
the systems whose authored edge on 2006-2016 is larger than a round trip's
cost, split into `dip` (they buy under the 20-day average) and `strength`.
The twenty best per family on 2006-2016 went to 2017-2021, where one was
chosen if it beat the authored stops, and that one was read once on
2022-2025. No authored design reached a family's twenty.

Sized result per trade, basis points of the account:

| Family (pooled systems) | Chosen on 2017-2021 | | 2006-2016 | 2017-2021 | 2022-2025 |
|---|---|---|---|---|---|
| S&P 500 dip (12) | 15% under the highest close, break-even at +2R, target 2R | chosen | +0.25 | -3.9 | -0.6 |
| | | authored | +3.0 | -12.4 | +0.5 |
| | | no stop | +4.7 | -13.8 | -0.4 |
| ETF dip (13) | 5% stop, then 3 ATR under the highest high, break-even at +1R, target 3R, own exit dropped, stall 10 | chosen | +3.0 | -1.9 | +2.3 |
| | | authored | +4.8 | -7.9 | +4.9 |
| | | no stop | +6.7 | -9.4 | +6.7 |
| ETF strength (6) | 2.5 ATR stop, then 15% under the highest close, own exit dropped | chosen | +6.9 | +0.4 | -16.9 |
| | | authored | +7.6 | -4.2 | -12.4 |
| | | no stop | +11.5 | -1.0 | -15.8 |
| BIST dip (3) | 15% under the highest close, break-even at +2R, stall 10 | chosen | +1.3 | -4.0 | +4.4 |
| | | authored (none has a stop) | +7.0 | -18.6 | +15.9 |
| BIST strength (19) | none beat the authored stops; best finalist: 5% stop, own exit dropped, stall 10 | best finalist | +19.4 | +6.2 | +35.7 |
| | | authored | +8.9 | +8.8 | +22.1 |
| | | no stop | +15.4 | +13.8 | +32.4 |

S&P 500 strength has fewer than three pooled systems and was not decided.
Mid/small, the second opinion: its twenty finalists are 12% stops and
none beat the authored stops on 2017-2021.

What it says:

- A stop costs money on these systems. On 2006-2016 no stop at all was
  ahead of every finalist with a defined R in four of the five families.
  Every chosen variant beat the authored stops on 2017-2021, which is how
  it was chosen, and none did on 2022-2025.
- Near stops are the worst choice for a dip system. With no stop, 57% of
  S&P 500 dip trades went 1 ATR against the entry and 43% of those still
  ended in profit; at 2 ATR it is 33% and 25% (`stops.py excursions`, on
  the pool as first drawn). A stop under the lowest low of the last days
  sits at the entry of a dip: on ETFs the variants that use one won 34% of
  their trades, where the same systems win about 65% with no stop.
- What a stop does deliver, in every period, is a smaller bad trade: the
  worst hundredth of ETF dip trades lost 6% with the chosen stop against
  13 to 26% without one. Not when the price opens under it: an S&P 500
  company that went to zero in 2022-2025 cost 99.7% with a 15% stop.
- On BIST `strength` a 5% stop with the trade left to run (out after 10
  days if under the entry, otherwise up to the time limit) earns in R what
  a trend system is expected to: a quarter of the trades win, the average
  winner is +5 to +10R, the average loser -0.8R, +0.7 / +0.9 / +1.9R a
  trade in the three periods, in nominal lira.
- The periods agree only loosely on which variant is best: rank
  correlation of the whole grid between 2006-2016 and 2017-2021 is +0.52
  (dip) and +0.19 (strength) on ETFs, +0.80 and +0.58 on BIST
  (`stops.py agreement`).

What the application does with it: a stop that does not beat the
incumbent on the years kept for that purpose does not replace it, so every
system with an authored stop keeps it. The systems written with no stop
(three shown on ETF, five on BIST) take their family's finalist of
2017-2021, so that every trade has a stop and an R; their three-period
records are restated with it (`stops.py restate`), and the list of systems
is the one fixed in Phase 23. `signals.py` prints each trade's stop, its
risk as a share of the price, and its result in R.

An account cannot take every signal. One that holds five positions of a
fifth each took about one ETF dip signal in eight on 2006-2016, and the
ones it took were worse than the average signal (+0.36% a trade against
+0.64%): signals cluster in selloffs, the account fills in the first days
of a cluster and is full for the rest (`stops.py account`). Per-trade
averages assume every signal is taken.

Limits. With daily bars the order of a day's high and low is unknown and
is resolved against the trade. The BIST panel has a handful of bars that
are corporate actions Yahoo did not adjust (AKSA 2006-11-13, -74% in a
day), which pass through any stop; they are in every variant alike. The
grids of the systems outside the pools decide nothing and were run for
ETF and BIST in full, for S&P 500 and mid/small as far as time allowed.
Replacing the simulator changed 151 of 1.6 million earlier trades: bars
missing inside a history used to make an exit rule be skipped, and are
now waited out.

## One algorithm out of the systems

Twenty-two systems listed side by side on an instrument is not an
algorithm. `combine.py` (plan.md, Phase 25, rules written before any
combination was scored) asks which agreement among the systems is worth
trading, and the product leads with the answer: one signal and one record
per instrument.

A candidate is an instrument-day on which at least one system of a family
signals (`dip`: 27 systems on S&P 500; `strength`: 30). Every candidate is
traded by one template per family (dip: out when z20 > 0, 2.5 ATR stop, 15
days; strength: out when bd20 < 0, 2.5 ATR stop, 40 days), so combinations
differ only in which candidates they take. A combination may read how many
systems signal today, how many did in the last five days, how many of the
other family did, the share of the market that is a candidate today, which
systems signal, and the 36 components. Seven variants per family and
market: at least 2, 3 or 4 systems; a ridge-regression score for the net
R, taken above its 50th, 75th or 90th percentile; a depth-3 regression
tree. Fitted on 2006-2016, one chosen on 2017-2021 (most net R per trade
with at least 45% winners, 20 trades a year, a positive edge and more than
"every candidate"), read once on 2022-2025.

    <venv>/python indicators/lab/combine.py fit | choose | sealed --universe sp500
    <venv>/python indicators/lab/combine.py fundamentals --universe sp500

| Net R per trade, winners, net per trade | 2006-2016 (fitted) | 2017-2021 | 2022-2025 |
|---|---|---|---|
| S&P 500 dip, linear score top 10% | +0.18R, 71%, +1.67% | +0.11R, 66%, +0.94% | +0.07R, 65%, +0.62% |
| every candidate | +0.02R, 61%, +0.13% | +0.00R, 61%, +0.09% | +0.00R, 60%, +0.09% |
| ETF dip, linear score top 25% | +0.16R, 69%, +0.80% | +0.04R, 62%, +0.19% | +0.05R, 62%, +0.26% |
| every candidate | +0.01R, 61%, +0.03% | +0.01R, 60%, +0.01% | +0.04R, 61%, +0.23% |
| BIST dip, one leaf of the tree | +0.06R, 64%, +0.70% | +0.06R, 61%, +1.44% | +0.13R, 72%, +1.54% |
| every candidate | -0.06R, 53%, -0.33% | -0.03R, 58%, -0.07% | +0.03R, 63%, +0.39% |
| BIST strength, linear score top 25% | +0.50R, 42%, +3.71% | +1.01R, 48%, +6.94% | +0.57R, 40%, +6.30% |
| every candidate | +0.18R, 36%, +1.42% | +0.42R, 36%, +3.11% | +0.49R, 34%, +4.92% |

No variant of S&P 500 or ETF `strength` reached 45% winners on 2017-2021,
so those have no combined algorithm.

- The S&P 500 dip score is the clearest result of the lab so far: its edge
  over a random entry is +0.73% a trade (t 3.1) and +0.63% (t 2.3) on the
  two periods it never saw, where every candidate has -0.05% and +0.13%
  and the best single system, `sys_no_news_dip`, +0.42% and +0.10%. On
  2017-2021 the order top 50% < top 25% < top 10% holds. On 2026, which no
  step read, 565 trades, 65% winners, +1.2% a trade.
- Counting agreement did not help anywhere: "at least 4 systems" is no
  better than one. What separates candidates is their state (where the
  price stands against its 50-day average, the last month's return, how
  much of the market is a candidate that day), not the number of systems
  pointing at them.
- ETF dip is ahead of "every candidate" by a hair on 2022-2025 and should
  be read as no gain. BIST dip rests on 122 and 298 trades. BIST strength
  took 99 trades on 2022-2025 with 40% winners, under the floor it was
  chosen with, and is in nominal lira.
- Mid/small, the second opinion: +0.13R where fitted, -0.01R on 2017-2021
  (every candidate -0.03R), +0.03R on 2022-2025 (-0.02R).
- Fundamentals: the chosen S&P 500 trades of 2017-2025 in companies the
  company side called investable made +0.06R, the others about +0.10R; t
  of the monthly difference 0.1. The two analyses do not inform each other
  at this horizon. The product shows them side by side as a short and a
  long horizon and filters neither by the other.

A loss is about 1R and not exactly: the median stop-out is -1.03 to
-1.08R (the excess is the cost), but 14 to 23% of stops are filled at an
open under the stop, and 0.5 to 1.7% of stops lose more than 2R. The
journal marks those as a gap.

`signals.py` runs `combine.take()` on the live bars with the stored model
(`data/indicators/combine/result_<universe>.json`), lists the combined
algorithm's signals with the systems that agreed that day, and keeps the
single systems behind it as evidence.

`signals.py` also writes, per combined algorithm, a `performance` block
for the application's "Performans" tab: the closed trades since 2017 on
today's instruments (the years the algorithm was not fitted on), with the
win rate against the break-even win rate, the average win and loss in
percent and in R, the result by year, by state of the market (share of
instruments above their 200-day average on the signal day), by instrument
and at other costs per side, and an account that holds at most five
positions and so cannot take every signal (`stops.account`). On S&P 500
that account made +8.8% a year with a deepest drawdown of -39% on closed
trades and half its capital invested on average, where holding SPY over
the same years made +14.9% a year with a drawdown of -34%; the BIST trend
account made +18.8% a year in nominal lira where the 51 listed names held
in equal parts made +40.4%. The per-trade edge is real and thin, and as an
account neither algorithm has beaten simply holding.

## After the council: long holds

Three independent agents reviewed the combined algorithms (plan.md,
"Council review"; their standing definitions are in
`.claude/agents/finadvisor-*.md`). Verdict: not worth trading. The edge
is real and small, most of it is the choice of days and not of stocks,
and a five-position account made +2.4% a year since 2017 where holding
every member made +12.5%. The application now says so above the list.
One correction to this file: the S&P 500 panel includes delisted
companies from 2017; before that, 155 of 989 members with no
open/high/low in the source are missing.

The researcher's diagnosis is that payoff per trade here is drift times
days held, so a hold of days cannot pay half an R. `position.py` (plan.md,
Phase 26) tests the one direction with the shape the owner asks for: ten
slots; at a month's end, while the equal-weight index is above its 200-day
average, buy members above their own 200-day average from the calmest
fifth by daily range; sell at a 15% stop or after 250 trading days.

| | 2006-2016 | 2017-2021 (read once) |
|---|---|---|
| Calm account, a year / deepest drawdown | +7.3% / -22% | +11.3% / -14% |
| Its trades | 121, 74% win, +0.48R (+0.91R / -0.78R) | 65, 77% win, +0.58R (+0.93R / -0.59R) |
| 500 accounts picking at random, medians | +7.2% / -32%, +0.48R, 52% win | +10.9% / -21%, +0.64R, 54% win |
| Index held | +9.6% / -58% | +16.1% / -40% |
| Index held while above its 200-day | +8.1% / -24% | +9.4% / -24% |

It was not killed by either of the tests written beforehand. It has the
shape asked for and it does not make more than holding the index; it loses
far less on the way.

A 15% stop is a large unit for stocks that move 1% a day. A scan of 144
variants on 2006-2016 (stop, time limit, a trend exit, four selections;
`position.py scan`) shows R per trade rising as the stop narrows while the
account's return stays where it was. The variant taken on, calmest fifth
with an 8% stop, 250 days and 1% of the account at risk per trade:

| | 2006-2016 | 2017-2021 (second reading) | 2022-2025 (read once) |
|---|---|---|---|
| Trades, winners | 127, 67% | 71, 69% | 54, 46% |
| Average win / loss | +1.85R / -1.02R | +1.64R / -0.97R | +2.20R / -0.96R |
| R per trade | +0.90R | +0.83R | +0.50R |
| Account, a year / deepest drawdown | +8.2% / -17% | +12.0% / -12% | +4.9% / -19% |
| Index held | +9.6% / -58% | +16.1% / -40% | +6.7% / -21% |
| Index held while above its 200-day | +8.1% / -24% | +9.4% / -24% | +1.5% / -24% |
| Random accounts, same rules (median) | +0.55R, 36% win | +0.77R, 37% win | +0.17R, 26% win |

By the rule written before 2022-2025 was read it is killed there: fewer
than half its trades won. It stayed ahead of the timed index and of the
random accounts in that period, and it is recorded as not confirmed.

    <venv>/python indicators/lab/position.py discover | validate | scan | chosen | sealed

## Hourly bars: a system as four parts

`hourly.py` (plan.md, Phase 27) splits a system into a daily context, an
hourly trigger, a stop and an exit, and scores every combination: 5 x 7 x
5 x 32 = 5,600 per market, on one-hour bars from 2023-12 (as far back as
the source serves them; five- and fifteen-minute bars exist for 60 days
only). Every system stands beside its placebo: the same context, stop and
exit entered every thirteenth bar with no trigger.

| R per trade | Median of the search | Best of the search | Twenty finalists, search / choice period | Still positive |
|---|---|---|---|---|
| 99 large US stocks | -0.02R | +0.50R | +0.37R / -0.11R | 2 of 20 |
| 36 ETFs | -0.09R | +0.90R | +0.41R / -0.11R | 5 of 20 |
| 51 BIST names | -0.03R | +0.38R | +0.29R / -0.08R | 1 of 20 |

One finalist passed the choice period (US, +0.67R with 23% winners) and
made -0.89R a trade with 8% winners on the last period. No market has an
hourly system. The best of the search all had one shape, a 1% stop and a
quarter of the trades winning +5 to +7R, and that shape did not persist.

    <venv>/python indicators/lab/hourly.py fetch | grid | choose | sealed [sp100|etf|bist]

## Consistency over the whole span

After the owner rejected a single holdout as the measure, `consistent.py`
(plan.md, Phase 29) scores a rule on 2006-2025 in four five-year blocks,
in R, beside its placebo (the same exit and stop entered every eleventh
day), and keeps it only if every block has 100 trades, a positive R and
more than the placebo. Each of the 57 systems on its own with a 2.5 ATR
stop: 52 positive per trade, 31 in all four blocks, 11 consistent, all of
them buying weakness inside an uptrend; volume in the entry makes no
difference (median +0.011R above the placebo with it, +0.009R without).

The core then, 3,402 variants of entry, stop, trail, target, exit rule and
limit, 1,484 consistent. The best by its worst block: 50-day above
200-day, price above its 200-day, RSI under 40, while more than half the
members are above their 200-day; out when the price is 2% under its
200-day average or after 250 days; stop 2 ATR.

| | 2006-10 | 2011-15 | 2016-20 | 2021-25 | 2006-2025 |
|---|---|---|---|---|---|
| R per trade | +0.81 | +0.91 | +0.66 | +0.57 | +0.74 (9,379 trades, 29% win, +4.97R / -0.97R) |
| Placebo | +0.06 | +0.39 | +0.13 | +0.08 | |
| Ten-position account, a year / drawdown | +3.3% / -18% | +7.9% / -11% | +5.7% / -11% | +4.3% / -18% | +6.3% / -30% |

A 10% stop with a 3R target and no exit rule wins more often (46%) for
less R (+0.57). The account is bounded by capital, not by signals. All
twenty years are used: nothing here is out of sample.

    <venv>/python indicators/lab/consistent.py

## The short side, and the rule-driven exit

`shorts.py` (plan.md, Phase 31) runs every system as its mirror image on
inverted prices and converts each trade to what a short made, less costs
and a 1% a year borrow fee. Over 2006-2025 none of the 57 is positive per
trade (-0.01R to -0.42R); the random short with the same exit and stop
makes -0.05R to -0.39R.

The rule-driven exit (trend dip, out when the price is 2% under its
200-day average, stop 2 ATR), scored continuously: 11,000 trades, 28%
winners, +5.05R / -0.98R, +0.69R a trade. A random stock already in the
trend, bought on the same days with the same exit, makes +0.81R. An
account at 1% risk holds five positions and made about +5% a year with
losing runs of 17 to 20 trades.

    <venv>/python indicators/lab/shorts.py

## A book held until the trend ends

`book.py` (plan.md, Phase 32, designed by the council's strategist) is an
account marked every day: ten positions, 1% at risk each, filled at
random on any day the market gate is on among calm members in a trend
(50-day above 200-day, price above its 200-day, calmest two fifths), stop
5 ATR, sold at the open after the 50-day average falls under the 200-day
or after 500 days. No entry trigger and no target.

| Mean of 20 fills | S&P 500 2006-2016 (seen) | S&P 500 2017-2025 | S&P 400/600 2011-2025 |
|---|---|---|---|
| Account a year / deepest daily drawdown | +8.6% / -20% | +7.2% / -27% | +6.3% / -32% |
| Trades a year, winners | 13, 48% | 14, 43% | 13, 40% |
| R per trade (win / loss) | +0.98 (+2.97 / -0.88) | +0.73 (+2.88 / -0.86) | +0.63 (+2.88 / -0.88) |
| Same stocks, target 4R and 250 days | +8.3% / -20%, +0.71R | +6.5% / -22%, +0.49R | +6.3% / -27%, +0.51R |
| Any member, same rules | +7.1% / -21%, +0.37R | +5.7% / -27%, +0.24R | +5.4% / -33%, +0.24R |
| Index held | +9.7% / -58% | +12.0% / -40% | +12.1% / -45% |

Killed by its written criteria: its return over drawdown is not above the
target-4R account's on either reading. Its trades did keep +0.63R to
+0.73R at the level of the account on data it was not designed on. It
makes about half of what holding the index makes.

    <venv>/python indicators/lab/book.py seen | read

## The dip model as a wide account; candlesticks and cycles

`book.py wide` (plan.md, Phase 33): the stored S&P 500 dip model as 80
positions of 1.25% each, marked daily. 2017-2021: +7.1% a year, deepest
drawdown -39%, 697 trades a year, +0.09R a trade; SPY bought on the same
days +5.1% / -28%. 2022-2025: +5.0%, -6%, 581 trades, +0.07R; SPY on the
same days +6.7%, random members on the same days +4.6%. Killed in both
periods by its written criteria.

`patterns.py` (Phase 34): the bullish reading of each of TA-Lib's 61
candlestick patterns and three Hilbert-cycle entries, stop 2.5 ATR, out
after 10 days, each beside random members bought on the same days. Of 43
with 300 trades, the entry's own part is between -0.03R and +0.05R and
none is positive in all four five-year blocks.

    <venv>/python indicators/lab/book.py wide
    <venv>/python indicators/lab/patterns.py

## Which term carries the result

`terms.py` (plan.md, Phase 35, the owner's design): every member bought on
every fifth day and held under an exit with no rule in it, at 10 days
(stop 2.5 ATR) and at 120 days (stop 5 ATR); for each of the 36
components the day's members are cut into fifths and the fifths compared
on the same days. A purchase of any member held 120 days made +4.0% net,
+0.30R, half of them winning.

At 10 days no term separates by more than 0.03R. At 120 days only the
volatility terms do (calmest fifth by daily range +0.40R, most volatile
+0.19R), and that is the unit: in percent the calm fifth made +3.2% and
the volatile +5.2%, with 1R at 8.4% and 21.1% of price. RSI, MACD, the
Bollinger position, the average gaps, momentum and every volume term are
within 0.03R of no effect. The two terms that separated on 2006-2015
reversed on 2016-2025; no composite came out of it.

    <venv>/python indicators/lab/terms.py

## Every signal at a fixed risk: the owner's scorecard

`breadth.py` (plan.md, Phase 36, proposed by the red team). The owner
counts in R a month at a fixed sum at risk. A ten-slot account takes a
random tenth of a rule's signals; this takes all of them (one position
per instrument at a time, through `trades.simulate`), risks 100 dollars
on each, marks the positions daily and states the money that ties up.
The rule is Phase 32's: gate on, 50-day above 200-day, price above its
200-day, calmest two fifths; stop 5 ATR; out when the 50-day falls under
the 200-day, or after 500 days.

| 100 dollars at risk on every signal | S&P 500 2006-2016 (seen) | S&P 500 2017-2025 | S&P 400/600 2011-2025 |
|---|---|---|---|
| Trades a month | 23 | 29 | 27 |
| R per trade, winners (win / loss) | +0.99, 46% (+3.14 / -0.86) | +0.59, 38% (+2.96 / -0.89) | +0.44, 37% (+2.65 / -0.88) |
| R a month (worst month) | +23.0 (-192) | +17.1 (-398) | +11.9 (-427) |
| Longest losing run | 51 | 89 | 136 |
| Most money in positions | 415,000 | 432,000 | 406,000 |
| So 1R is, of the account | 0.024% | 0.023% | 0.025% |
| On that money: a year / deepest daily drawdown | +6.7% / -13% | +4.8% / -23% | +3.5% / -23% |
| As a growing account, idle money earning nothing | +5.1% / -10% | +4.0% / -18% | +2.9% / -14% |
| Placebo: uptrend of any range | +0.81R, +7.2% / -13% | +0.53R, +5.5% / -25% | +0.36R, +3.5% / -24% |
| Placebo: 50-day over 200-day only | +0.70R, +7.2% / -14% | +0.46R, +5.5% / -25% | +0.31R, +3.4% / -24% |
| Members held, equal weight | +9.7% / -58% | +12.0% / -40% | +12.1% / -45% |

Killed by its written criterion on both readings (38% and 37% winners
against 40%); R per trade stayed above +0.4. In R the owner's target is
nearly met: 29 trades and +17R a month. In money that R is 0.023% of the
account and the account makes under half of what holding the same stocks
made, with a bit over half the drawdown. With the idle 45% of the money
at the bill rate it makes +5.6% a year, against +5.0% for the members
held at the book's own share invested (`capital.py`). The selection adds +0.06R to +0.13R a
trade over its placebos and nothing per dollar. These years had been read
for this rule in Phase 32; this is the same reading on another scorecard.

`breadth.py table` puts the 48 systems that have a stop (45 of the 57 and
the three long-hold rules) on the same scorecard (S&P 500 2017-2025,
years read for all of them, so the best row is not a result). Highest R a month: profile A +28.0R from 49 trades
(+0.57R, 28% winners, 798,000 dollars, account +3.6% a year, -11%); the
20-day Turtle +17.9R from 265 trades (+0.07R, account +1.8%); profile B
+8.3R from 16 trades (+0.52R, 42%, 236,000 dollars, +3.7%, -15%). No
system's account grows by more than +4.0% a year on the money it ties up;
43 of the 48 are positive.

    <venv>/python indicators/lab/breadth.py seen | read | table

## Trends across asset classes as one portfolio

`trend.py` (plan.md, Phase 37, proposed by the red team): the 36 ETFs,
each +1, 0 or -1 by the signs of its 252- and 63-day returns at the
month's last close, sized by inverse volatility, scaled to 10% yearly
volatility, gross at most 2, traded a day later, 0.05% a side, 0.5% a
year short borrow. Idle money earns the 13-week bill rate (Yahoo ^IRX,
`trend.py cash`), borrowed money pays it plus 1.5%. It is a portfolio of
weights with no stop, so it has its own loop and one fill: the close.

| | 2006-2016 (seen) | 2017-2025 (read once) |
|---|---|---|
| Trend portfolio: a year / Sharpe over cash / drawdown | +7.3% / 0.63 / -14% | +1.8% / 0.00 / -29% |
| Always long, same sizing | +4.5% / 0.36 / -28% | +4.9% / 0.25 / -36% |
| Random signs, median Sharpe | -0.41 | -0.69 |
| SPY held | +7.7% / 0.42 / -55% | +15.1% / 0.72 / -34% |
| 36 ETFs equal weight | +5.6% / 0.36 / -43% | +8.6% / 0.52 / -28% |
| In R, before financing (1R = entry weight x 3 ATR = 0.20% of the account) | 5.5 positions a month, +0.93R, 46% | 6.5 a month, +0.38R, 40% |

Killed on all three written criteria (Sharpe under 0.4, return over
drawdown under the always-long placebo's, drawdown beyond -20%). The
short side lost 31% over 2017-2025 and the long side made 65%. The red team's own figures for
2006-2016 (+7.8% a year, Sharpe 0.77 without interest) reproduce.

    <venv>/python indicators/lab/trend.py cash | seen | read

## Judged in money: issuance, a calm account, dip days

`capital.py` (plan.md, "The money criterion" and Phases 38-40, the three
directions of the council's researcher). From here every study is read
beside the universe held and beside the universe held at the rule's own
daily share invested, with idle money at the 3-month bill rate.

**Net issuance inside the every-signal book (Phase 38).** The trades of
the book above, cut each entry month into thirds by the company's net
share issuance (latest row before the entry, at most 200 days old).

| | S&P 500 2017-2025 | S&P 400/600 2013-2025 |
|---|---|---|
| Lowest third: R, winners, net | +0.64, 40%, +6.5% | +0.50, 39%, +6.6% |
| Highest third | +0.52, 37%, +5.1% | +0.33, 36%, +4.4% |
| Difference by entry month | +0.12R (t 1.0) | +0.12R (t 1.0) |
| Lowest third as a book, idle money at bills | +5.9% / -18% | +4.5% / -22% |
| Members at the same share invested | +5.3% / -16% | +3.6% / -18% |
| Members held | +12.0% / -40% | +11.7% / -45% |

Killed: +0.2R with t 2 was required. The sign is the expected one.

**Calm members, fully invested under the gate (Phase 39).** Monthly, the
calmest two fifths in equal weight at 1.5 times the account while more
than half the members are above their 200-day average, bills otherwise;
traded a day after the month's last close; borrowed money pays bills plus
1.5%.

| A year / drawdown | S&P 500 2006-2016 (seen) | S&P 500 2017-2025 | S&P 400/600 2011-2025 |
|---|---|---|---|
| Calm, gate, 1.5x | +11.4% / -24% | +8.6% / -34% | +6.4% / -40% |
| Calm, gate, 1x | +8.6% / -17% | +7.2% / -22% | +5.4% / -27% |
| All members, gate, 1.5x | +10.7% / -32% | +10.5% / -34% | +6.0% / -46% |
| Calm, always held, 1x | +9.3% / -45% | +10.5% / -34% | +10.2% / -40% |
| Members held | +9.8% / -58% | +11.9% / -40% | +11.7% / -45% |

Killed on both readings: 3.3 and 5.3 points a year under the members
held (2.8 and 4.9 when the members are not rebalanced daily for free). The gate was out for the recoveries of 2019, 2020 and 2023. Traded
at the signal's close the seen years read +13.5%; two points of that were
the first day of the month.

**Dip days at index level (Phase 40).** A trigger day: at least 7.1% of
S&P 500 members close two deviations under their 20-day mean and the gate
is on (the threshold is the 80th percentile of that share on 2006-2016).
SPY is bought at the next open and sold at the close five days after.

| | 2006-2016 (seen, threshold chosen here) | 2017-2025 (read once) |
|---|---|---|
| Trigger days, separate windows | 348, 94 | 325, 86 |
| SPY over the five days: trigger days / all days | +0.36% / +0.05% | +0.38% / +0.16% |
| Winners; mean monthly excess (t) | 64%; +0.65% (3.4) | 62%; +0.38% (2.2) |
| Day-weighted difference (t, months as clusters) | +0.31% (1.8) | +0.21% (1.4) |
| SPY inside a window, bills outside: a year / drawdown / Sharpe | +7.9% / -13% / 0.82 | +8.0% / -10% / 0.65 |
| The same share in SPY all the time | +3.4% / -18% / 0.42 | +7.0% / -13% / 0.72 |
| SPY held | +7.7% / -55% / 0.42 | +15.1% / -34% / 0.72 |

It met its criterion as coded (each month weighted equally: +0.38%, t 2.2)
and is not confirmed: the account earns the day-weighted difference,
+0.21%, whose t with months as clusters is 1.4 (the auditor: 1.4 to 1.8
by every clustering tried). The effect is in months with one or two
trigger days and absent in months with six or more; it disappears at the
70th and 75th percentile of the share and at a three-day hold. In money it is one point a year over holding the same share
of SPY all the time, at a lower Sharpe, and seven points under SPY held;
the last four years are weaker than the first five. It has no stop and so
no R. The judge's reading: not worth trading. The one point is 2024 alone
(without it +5.2% a year against +6.5% for the constant share), the
yearly difference has t 0.4, and at 0.10% a side it is gone (6.95%
against 7.03%). The criterion written for it was too easy: it did not ask
for the excess over constant exposure by year.

    <venv>/python indicators/lab/capital.py issuance | calm seen | calm read | dips seen | dips read
