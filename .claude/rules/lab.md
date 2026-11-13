---
paths:
  - "indicators/lab/**"
---

# Lab checklist

Before running a study in `indicators/lab/`:

- The Phase entry is in `plan.md`, with the kill criterion, and was written
  before this run.
- The placebo shares every filter of the rule except the one being
  credited (same days, same universe filter, same exit and stop).
- Windows: `trades.simulate(..., live=False)` gives no entries in the last
  `max_days` of the window. Either score one continuous span or state the
  omitted years.
- R is defined: every policy has a stop. A stop within 0.1% of the price
  is no trade (`MIN_RISK`); check for stops wider than about 15% of price,
  where R stops meaning what the owner means by it.
- Costs are subtracted, and an `edge` from `trades.statistics` is before
  costs and against a drift known only afterwards; `over_members` is the
  after-cost figure against the members over the trade's own days.

Before reporting a study:

- Per-trade figures have an account beside them: stated number of
  positions (`stops.account(..., slots=n)` limits them; without `slots` it
  does not), drawdown marked daily or said to be closed-trade only, and
  the same span of holding the universe.
- Trades are counted as bets by entry month or year, not as independent.
- The number of variants searched and the periods already read are stated.
- The money criterion is stated (CLAUDE.md, "How results are measured"):
  the account with idle money at bills, the universe held, the universe
  held at the rule's own share invested; and what share of the account 1R
  is. `capital.money` computes it for a fixed-risk book from
  `breadth.ledger`.
- An explanation of a result ("because of 2008", "because open positions
  are counted") is a claim: check it with a number or do not write it.
- The outcome is written under its Phase in `plan.md` and in
  `indicators/lab/README.md`, failures included.
- If the rule is to be shown as tradeable: `finadvisor-auditor` and
  `finadvisor-judge` have read it.

One simulator: every study goes through `trades.py` (`_trade`, `simulate`,
`_grid`). Do not write a second fill model; extend the policy row instead.
