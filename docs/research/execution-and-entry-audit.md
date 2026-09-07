# Why six portfolios showed almost no trades

September 7, 2026. Investigation of the running USD100-per-portfolio experiment.
This separates simulator defects, entry constraints and the meaning of dashboard counters.
No funded orders or account credentials were used. Original paper records remain unchanged.

## Reproducible execution defects

**Source and receipt clocks were mixed.** A book produced at venue time +300ms and received
locally at +1000ms set a single +1000ms queue cutoff. A later trade produced at +500ms and
received at +1100ms was rejected, although it followed the book in both respective clocks.
`SOURCE_ORDERED_FLOW_V3` compares source with source and receipt with receipt. Equality,
earlier receipt, future messages, discontinuous streams and effective cancellations still
exclude volume. New orders retain the original queue size and both book timestamps. Legacy
states without those timestamps retain the stricter cutoff; unknown historical times are
not inferred. Book observation logs also now preserve the actual receipt, rather than the
later time the controller happened to publish the book.

**A trade through the bid still depleted an obsolete queue.** For example, the experiment's
0.67 Up hedge began behind 522.87 shares. Subsequent executions below 0.67 demonstrated that
matching had passed that price. The simulator nevertheless subtracted their volume from the
old 0.67 queue and declared the hedge unfilled. Under price priority, a hypothetical bid at
0.67 would intercept that subsequently observed volume. The correction clears the old queue
only on a qualifying trade strictly through the bid, fills at our own bid, and credits at most
the observed volume. Same-price trades still deplete the queue first; a quote touch or a book
cancellation alone never produces a fill. Both direct SELL and complementary opposite BUY
routes use this logic, with transaction-based mirror deduplication preserved.

This is a simulator inference from best-price execution, not a receipt proving that our absent
order would have executed. The venue describes matching against the best available resting
orders and complementary pair creation in its [order lifecycle](https://docs.polymarket.com/concepts/order-lifecycle)
and [order-book explanation](https://docs.polymarket.com/concepts/prices-orderbook).
Unobserved queue priority and our hypothetical order's market impact remain limitations.

An immutable public capture ends at master event **280028**. It contains 56 completed passive
orders and 31,951 book/trade observations. Its SHA256 is
`75649915549cd12ba3577d5dc072915e5f0567045df281bf08c23354fb2269ac`.
The ignored scratch artifacts are `work/execution-public-prefix.json`,
`work/replay_execution.py` and `work/execution-replay-results.json` in the strategy-execution
worktree. The replay uses original cancellation times, transaction identities, generations
and source/receipt times. Initial queue size for each unfilled order is reconstructed from
its remaining queue plus the volume its original matcher consumed. It retains the old time
cutoff where the original activation-book source time was not recorded, isolating price
priority from the clock correction. The baseline replay reproduces zero fills in all 55
originally unfilled orders; the correction fills three of them with five shares each:

| Original order | Role / bid | Corrected fill receipt (UTC) |
|---|---|---|
| `bd34042aa033422ca196c83616bb631e` | Hedge / 0.67 | 03:02:14.833 |
| `12df10840f94492e95b3055124e8a6e0` | Opening / 0.17 | 03:13:01.196 |
| `a75065cbc7464afbaa22533cbcbca8f2` | Opening / 0.79 | 03:18:23.470 |

The hedge belongs to the recorded five-share Down purchase at 0.25. The original simulator
missed the 0.67 Up completion and later sold Down at 0.11, reporting a USD0.734265 loss after
fees in each pair portfolio. Those missed hedge shares would instead have completed five
pairs costing USD4.60 with a USD5 terminal payout. This independently replayed hedge is not
a whole-portfolio backtest or permission to replace historical losses with gains. Full
controller tests cover both pair modes filling a trade-through hedge and holding the pair
instead of stopping out its formerly unpaired leg.

## Affordable entries rejected by optional slippage

The USD5 cap reserved up to USD4.67 principal plus a conservative fee allowance. At a 0.93 ask,
adding the optional 0.01 slippage created a 0.94 limit and fewer than five protected shares,
so momentum rejected the trade. Likewise, the permitted 0.92 value ask was rejected after
slippage pushed its signed limit above the configured price band.

The limit now caps optional slippage at the configured ceiling and affordable share minimum.
The SDK rounds requested BUY shares upward; when necessary, the principal is reduced to a
cent amount that represents exact shares at the limit. This yields five shares / USD4.65
principal at 0.93, and five / USD4.60 at 0.92. The worst-case fee reservation stays in force;
no larger budget or rounded-down share protection is used. Depth and fees are recomputed for
the smaller principal. Tests use the actual pinned SDK with synthetic transport to verify
the signed cash/share amounts, and paper tests verify the resulting fills.

## What the strategy screens actually say

**The daily limit was also counting failed attempts as entries.** During diagnosis both pair
portfolios reached19 attempted rounds with only one or two filled rounds. At20, the collector
would continue but new rounds would be blocked until UTC midnight. The counter now counts
distinct rounds with a confirmed BUY fill or a still-unresolved BUY order. A definitive zero-fill
closure releases the slot; unknown submissions and partial fills retain it. All BUY intents
participate, including a pair's later successful quote without the first-order uniqueness key.
Historical order/attempt counts remain intact. The20-entry cap was our application default,
not part of any strategy or a venue restriction. The user rejected it during this diagnosis:
the default and ongoing six-portfolio experiment now disable the entry-count cap with
`max_entries_per_day = 0`. A regression executes25 filled and resolved rounds in one day and
preserves their count/cash through restart. If an operator explicitly configures a positive
cap, profitable closing does not erase a filled round from that count, and restart cannot
reintroduce definitively unfilled attempts. Dollar budgets and per-round limits are separate.

The recorded period after the history repair, through event280028, contains 3,702 value
screens. Empty books occurred in **288/1,582 entry-window screens (18.2%)** and **477/640
final-minute screens (74.5%)**. They were not empty throughout the run. The dashboard's
"99 bids / 0 asks" meant counts of distinct price levels, not probabilities or bot orders.
It now shows best bid/ask prices, outcome/round labels where captured, and explicitly named
price-level counts. A market rollover cannot combine the new market's one observed book
with a counterpart retained from the old condition.

Four fill records were one purchase and one sale in each of two independent portfolios,
not four independent trades. Both pair strategies share the first-entry rule. Their hedge
prices differ only when inventory adjustment has room below the ask and pair-cost cap;
identical capped hedge prices are also possible. Similarly, `value` and `model_exit` share
entry logic and differ only after a position fills. The six modes are controlled variants,
not six unrelated sources of predictions.

In the initial post-restart sample, 49/51 opening quotes were below the current best bid,
with a median gap of 0.12. Their model-capped limit is a conditional resting quote, not
immediately executable surplus at the current best price. Large order counts therefore
do not establish frequent capturable opportunities. The replay also shows some distant
quotes can fill during a move; they were not deleted merely to improve the displayed ratio.

Price-gate replay reconstructs the original model scenarios and as-of logged full depth,
then requires the original price-screen result to reproduce before counting a comparison.
It covers 85 momentum, 1,279 value and 1,097 fast-value screens; one value record is excluded
because its logged books cannot reproduce the original screen. The sizing correction turns
momentum's two eligible screens into nine, still in one round. This is screen eligibility;
it does not establish confirmation or a fill.

A separate, **undeployed sensitivity check** changes only the value minimum ask from0.60
to0.01 while retaining model scenarios, fees, depth, spread and edge requirements. Value
eligibility rises from2 to29 screens and fast value from0 to10, across three rounds. For
example, a0.41 Down ask with a0.4783 scenario floor has0.02385/share surplus after costs,
but the existing0.60 minimum rejects it. This makes a broader price range a concrete next
strategy experiment, rather than pretending the existing modes are inactive because every
execution path is broken. Lower-priced inventory changes share count and stopped-trade
behavior; it is not silently activated in the original immutable experiment configuration.
The scratch `work/analyze_screens.py` and `work/screen-diagnosis.json` retain the comparison.

All these counts are repeated, overlapping screens or original-order replays. None is an
independent-trade sample or evidence of profitable live operation. Historical undercounted
orders are labeled as using older matching rules. Ongoing records use the corrected matcher;
cash, history, exposure limits and the continuous service remain persistent.
