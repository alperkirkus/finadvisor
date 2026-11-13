---
name: finadvisor-study
description: The fixed order of a FinAdvisor lab study, from idea to a result the owner can be shown. Use when a new trading rule, stop policy, selection or data source is to be tested, or when the owner asks to improve the algorithm.
---

# A study, in order

Do the steps in order. Do not report a result to the owner as tradeable
before step 7.

1. **Design.** For a new system or a structural change, delegate to
   `finadvisor-strategist` (give it the owner's request, not your idea of
   the answer). For a new panel, timeframe or market, delegate to
   `finadvisor-data` first.
2. **Register.** Append a Phase to `plan.md`: what the owner asked, what is
   already seen, the rule exactly as it will run, the data and spans, the
   fair placebo, the kill criterion, and the limits known beforehand.
3. **Build** in `indicators/lab/` on `trades.py`'s simulator. Reproduce one
   known number with the new code path before trusting a new one.
4. **Run** the search on the span where searching is allowed, then the
   confirming read once. Do not look at a kept-aside period before its
   rule is written.
5. **Measure for the owner**: R per trade and in money at 100 dollars a
   trade, winners, average win and loss in R, by entry year, longest
   losing run; an account with a stated number of positions marked daily;
   the same span of holding the universe; the rule minus its fair placebo.
   Then in money: what share of the account 1R is, the capital the
   positions tie up, the account with idle money at bills against the
   universe held and against the universe held at the rule's own share
   invested (`breadth.py`, `capital.money`). The kill criterion written in
   step 2 is in these terms, not in win rate.
6. **Record** the outcome under the Phase in `plan.md` and in
   `indicators/lab/README.md`, failure included, with the count of
   variants searched and periods read.
7. **Council.** `finadvisor-auditor` then `finadvisor-judge`, in parallel
   if independent, each given the files and the claim to test and not your
   conclusion. Fix what they find; record their findings in `plan.md`.
8. **Report** to the owner in Turkish: the answer first, the table, what
   failed, what it means for an account, and the one decision that is his.
   Only then change what the application shows.
