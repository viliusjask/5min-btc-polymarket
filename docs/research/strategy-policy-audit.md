# Strategy policy and execution audit

2026-09-07. This audit corrects a signal definition and three execution defects. It does
**not** establish a profitable strategy. The earlier implementation confused a large BTC
lead over the round's opening reference with recent momentum. All changes use anonymous
paper trading, preserve the $100 portfolios/$5 trade budgets/$10 day and session allowances,
and retain the existing price bands and exit rules.

## Momentum: what changed and why

At 07:32 UTC the original policy bought Up with BTC $67.59 above the opening reference,
even though BTC had fallen roughly $20 over the preceding 30 seconds. Of eight reconstructable
entries among nine actual Momentum trades, six opposed the preceding 10-second move and
five opposed the 30-second move. These observations diagnose the signal definition; they
are neither independent statistical tests nor evidence that reversing those entries wins.

The new default, `recent_continuation`, uses:

```
move = current Chainlink BTC spot − last observed spot at/before 30 seconds earlier
relative_size = abs(move) / (short_sigma * sqrt(actual elapsed seconds))
entry direction = Up if move > 0, otherwise Down
require relative_size >= 0.5
```

`short_sigma` is the square root of summed squared observed dollar changes divided by
elapsed seconds over the existing 300-second sampling window. Existing coverage, gap,
freshness, book and market guards remain. The endpoint must be within two seconds before
its target and received by decision time. Missing points are not interpolated; future
source/receipt times and duplicate history timestamps reject. The ratio is a measure of
movement relative to observed variation, **not** a probability or confidence level.

This policy requires five minutes of usable price history. It does not need a terminal
payout model or the 30-minute model window. Probability, scenario floor and terminal
surplus are therefore absent from its decision. The selected ask must still be 70–95 cents,
with 90–150 seconds left, adequate depth, at most a three-cent spread, affordable signed
cash/share precision, and newer same-side confirmation before submission. Baseline exits
remain an eight-cent stop, 98-cent bid target, and 20-second time exit.

The explicit `opening_lead` comparator retains the earlier $50 reference-distance policy
and its historical model dependency. The registered dollar-lead grid explicitly uses that
comparator. Existing 84- and 17-variant studies remain pinned to their original code/config
and registration identities; they are not retrospectively relabelled.

The 30-second lookback and 0.5 ratio were selected from the already implemented continuation
hypotheses before this replay, rather than picked to maximize this tape's profit. Financial
research supports distinguishing a trend signal from volatility estimation and examining
turnover/costs, but its longer-horizon futures findings do not validate five-minute binary
contracts. See Baltas and Kosowski, [*Improving Time-Series Momentum Strategies*](https://www.cmegroup.com/content/dam/cmegroup/education/files/improving-time-series-momentum-strategies.pdf).

## Three reproduced execution defects

- **Pair opening funding:** an opening could fit its immediate reservation but leave too
  little remaining cash/loss allowance to buy the opposite side. Before opening, require
  headroom for `max(actual reservation, shares × pair_max_cost)` using the same existing
  risk checks. Reserve only the real order. For five shares and a 97-cent pair cap, the
  completion requirement is $4.85; this does not increase a $5 trade budget or credit a
  hypothetical payout. More requests may now be rejected *before* creating unhedged exposure.
- **Pair timeout behind a resting hedge:** a hedge placed at second 29 could hide the
  unmatched-inventory deadline at second 30 until its own five-second quote expiry.
  Cancel at the inventory deadline, latch the exit request, reconcile cancellation and
  late fills, then sell only the remaining unmatched quantity. Completed equal pairs
  survive cancellation races. An unmatched remnant below the venue minimum remains a
  visible residual; the simulator does not invent an executable liquidation.
- **Model exit after awaited I/O:** the model snapshot was read before book/settlement
  operations that could take several seconds. Reacquire it immediately before evaluating
  the model exit. Missing, conflicting, wrong-market and stale replacements remain
  invalid; do not reuse an older favorable snapshot as fallback.

These behaviors agree with the venue's distinction between resting, partial and completed
orders: cancellation cannot undo already filled shares, and an immediately executable
limit order is still constrained by available matching liquidity. See the official
[order lifecycle](https://docs.polymarket.com/concepts/order-lifecycle).

Value and Fast value were audited without changing their policy parameters. In the
observed capture, Value/Model exit each had 67 first-eligible rounds, four confirmed buys
and one filled round; Fast had 21 first-eligible rounds, six confirmed buys and two filled
rounds. Confirmation losses, missing/stale data and quote/price changes account for the
reduction. Model exit recorded 114 valid HOLD evaluations. Its identical trade to Value
was not evidence that the exit policy was disconnected. Pair strategies intentionally
share an opening rule; their difference is hedge urgency.

## Frozen causal comparison

Tape identity `580e84ec4d184c35859a3c53e3c8413f`, frames through **44,752**, ending
2026-09-07 **17:53:59.725 UTC** (first frame 07:26:27.319 UTC). Replay follows tape receive
order, as-of histories and delayed official labels using the existing Replay/PaperBroker.
No forced close, fabricated fill, loss-limit reset or removal of uncertainty flags.

| Policy | Candidate rounds | Confirmed buy orders | Filled/completed rounds | Unflagged completed | All net, including flagged |
|---|---:|---:|---:|---:|---:|
| Original immutable source | 18 | 11 | 7 | 2 | −$4.096193 |
| Revised explicit `opening_lead` | 18 | 11 | 7 | 2 | −$4.096193 |
| Revised `recent_continuation` | 66 | 3 | 3 | 0 | −$5.960736 |

The original and revised opening-lead runs match exactly on candidates, executions, fills,
reasons and profit. Both revised policies use the same frozen source hashes. Thus the
comparison isolates the Momentum signal change from the shared execution repairs.

Recent continuation creates more candidate rounds, **not more executed trades** in this
replay. Its three early trades all carry uncertainty flags; their recorded losses then
produce 1,022 repeated `LOSS_LIMIT` rejections because already lost cash plus the next
entry's reserve exceeds the unchanged $10 allowance. Raw entry screens continue recording
opportunities even while portfolio risk blocks orders. Repeated screens are not independent
trades. There are **zero unflagged completed recent-continuation trades**, so no profitability
inference is justified. The original's two unflagged trades total +$0.170907, also too little
evidence to select a profitable policy.

Actual ledger exits and counterfactual replay must remain distinct. The actual 07:32 stop
recovered $2.791857. Sparse captured books could not reproduce that intervening exit;
the replay records an uncertain full loss instead. Eight actual buys had official labels:
holding those same buys to payout gives +$0.458184 versus −$1.785888 actually realized.
That is a hindsight comparison of selected entries, **not** a capital-path strategy replay
or justification to remove stops. The nine actual trades comprise seven stop exits and
two profit-target exits, net −$2.253298.

Scratch artifacts under `work/momentum-exits/` retain the tape manifest, source module hashes,
full configurations, causal harness and individual replay journals. `work/value-audit/`
retains the model audit and session-preserving migration evidence. They contain public or
synthetic data and remain local. Fresh post-change observations, with reliable execution
coverage, are needed before any strategy ranking.

## Deployment and interpretation

The paper migration requires stopped owners and no unresolved execution or positive active
inventory. It backs up and validates the master plus six journals, changes only current
configuration fingerprints, and appends explicit `CONFIGURATION_CHANGED` records with
accounting baselines. Session identities, balances, fills, positions, accounting rows and
accumulated loss allowances remain intact. The dashboard identifies the cutover and warns
that lifetime totals include both policies.

Only collector/dashboard code and their config path change. The original `paper.toml` stays
unchanged for both pinned studies; corrected services use `paper-strategy-policy.toml`.
The shared source tape, registration identities and study workers are preserved. Ordinary
configuration mismatch remains an error; this is an audited one-off paper migration, not
an automatic permission to rewrite live configuration or reset risk state.
