# Intraday signal study

A separate question from the rest of this repository: does anything
computed from five-minute bars of price and volume say where the next bar
goes, by enough to pay for trading it? It shares nothing with the
fundamental engine except the tools that count tests (`src/multitest.py`).

It is not a search for the best indicator. Indicators, parameters, parts of
indicators and timeframes multiply into millions of variants, and among
that many some will look excellent on any history whether or not anything
is there. The study is therefore small on purpose and fixed in advance.

## What is tested

One signal for each kind of information a bar chart carries, each with the
parameters it is conventionally published with and none of them tuned.

| Signal | Definition, at the close of bar t | Sign expected |
|---|---|---|
| `trend` | MACD histogram (12, 26, 9) of the close, over the close | + (continuation) |
| `reversion` | −(close − 20-bar mean) / (2 × 20-bar standard deviation) | + (return to the mean) |
| `breakout` | +1 above the highest high of the previous 20 bars, −1 below the lowest low, else 0 | + (continuation) |
| `volume` | sign of the bar's return × excess of its volume over the previous 20-bar mean, floored at 0 | + (continuation) |
| `flow` | (taker buys − taker sells) / volume over the last 5 bars | + (continuation) |

`flow` needs trades signed by aggressor. Yahoo's bars do not carry it, so it
is defined here and not run on equities.

Timeframes: 5 minutes, 15 minutes, 1 hour, the longer ones joined from the
five-minute bars inside a session. Twelve tests on equities.

## How a signal is scored

- Position: the sign of the signal, long, short or flat, taken at the open
  of bar t+1 and held to the open of bar t+2. Nothing is held overnight.
- Gross return of a bar: position × (open t+2 / open t+1 − 1).
- Cost: 2 basis points on every unit of position changed, including the
  entry at the start of a session and the exit at its end.
- A day's return is the sum over its bars, averaged across the symbols. The
  statistic is the mean of that daily series with a Newey-West t (lag 1).

A signal **carries information** if the gross mean differs from zero with
|t| at or above the Bonferroni line for the twelve tests (2.87). It is
**tradable** if the net mean is above zero with t ≥ 2.

## Data, and which part may be believed

Universe: the 100 largest S&P 500 members on 2026-11-13, fixed in
`universe.json`. Bars: Yahoo, five minutes, regular session.

Yahoo keeps 60 days. The bars collected on the first day, 2026-08-20 to
2026-11-12, are the **design set**: `study.py` runs on them to prove the
machinery and its output decides nothing. Every bar dated 2026-11-13 or
later is the **test set**. It is read once, when 60 sessions of it have
been collected, and that reading is logged in `data/intraday/looks.json`.
`bars.py collect` has to run at least every eight weeks for the test set
to exist; weekly is the intended rhythm.

## Combining signals

Only after the test set has been read, and only among signals that carried
information on it: the equal-weight sum of their positions, nothing fitted.
That combination is itself a new hypothesis and is tested on bars collected
after it is written down, not on the bars that selected its parts.

## Crypto

Planned the same way with `flow` included: exchanges publish bars with
taker volume and years of history at no cost. It has not been started. The
network this was written on blocks exchange sites by policy, and that was
not worked around; it needs a machine where the data can be fetched.

## Running

```bash
python intraday/bars.py collect     # merge Yahoo's last 60 days into data/intraday/
python intraday/study.py            # design set
python intraday/study.py --test     # the one logged reading of the test set
```
