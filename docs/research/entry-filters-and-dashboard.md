# Entry filters and misleading one-sided books

2026-09-07. Follow-up to the [execution audit](execution-and-entry-audit.md), based on merged
PR5 (`c851d83`). Public observations and paper journals only; no funded orders or new dependencies.

## Removing the Value floor

The earlier fixed-capture price-band comparison found29 qualifying Value screens instead of2,
and10 Fast value screens instead of0, when the lower band was reduced from0.60 to0.01. These
were correlated candidate checks across three rounds, not confirmed orders, fills or profits.
One recorded Down ask was0.41 against a conservative modeled payout of0.4783, leaving a0.02385
per-share surplus after the reserved costs. A high contract price was not needed for that test.

The new default is `value_min_ask = 0`, disabling the arbitrary floor for `value`, `fast_value`
and `model_exit`. Actual book prices remain strictly positive. The0.92 maximum signed limit,
0.03 spread limit,0.02 modeled surplus requirement, fees, depth, confirmation and cash budget
remain. An explicitly configured positive floor still works. Cheapness alone does not qualify.

The existing stop requests a sale when the bid is at least0.08 below gross entry. Below0.08
entry, that threshold cannot be reached before zero. The USD5 spending budget limits the cash
committed, while time/model/other applicable exits remain available. More shares for the same
cash also mean more exit-depth demand. This change does not validate the stop or guarantee fills.

## Why the original Momentum candidates did not become orders

The fixed capture ends at observation event383273 and begins at1788749571647ms UTC. It contains
85 checks meeting theUSD70 lead in three rounds; the maximum lead was aboutUSD117.24. Only two
observation screens also reported `ENTRY`, both in the same round (`btc-updown-5m-1788750000`).

The execution journal supplies the missing distinction:

- At03:02:52.541UTC, event22565 waited on its first eligible screen. The book source was
  1199ms ahead of the Chainlink spot source, so this was not permission to post immediately.
- At03:02:52.882, event22568 still waited for spot to reach that original book timestamp.
- At03:02:53.236, event22570 cancelled the candidate with `SPREAD_TOO_WIDE` (limit0.03).
- Another candidate at03:02:58.607 waited with the book2270ms ahead, then was rejected at
  03:02:58.948 with `BELOW_MINIMUM_SIZE`. The retained screen history is insufficient to
  attribute that particular sizing rejection conclusively to the earlier repaired sizing bug.

Thus two `ENTRY` observations were repeated preliminary checks, not two submitted trades.
Lowering the BTC move threshold does not bypass confirmation or execution rejection.

## Momentum threshold sensitivity

Using the same recorded probability scenarios and the latest preceding captured full books,
394 checks were reconstructable. Another751 were excluded because their captured books were
not usable/fresh. The recorder did not save every book the execution engine read. For screens
whose original move already exceededUSD70, the reconstructed price-gate result had to agree
with the original. Earlier `MOMENTUM_MOVE` rejections have no quote result to match, so their
new eligibility is conditional on the captured books. Corrected sizing was held constant.

| Minimum BTC lead | Raw checks meeting lead / rounds | Reconstructed eligible checks / rounds |
| --- | --- | --- |
| USD70 | 85 / 3 | 2 / 1 |
| USD50 | 258 / 5 | 23 / 3 |
| USD35 | 407 / 9 | 45 / 7 |

USD50 is the selected coarse intermediate setting for the paper experiment. The ask band
0.70–0.95,90–150-second window, spread, history, budget and confirmation rules are unchanged.
This is a candidate-frequency comparison, not an execution replay or an optimization of returns.
**Every eligible Momentum check at all three thresholds had a nonpositive conservative terminal
surplus proxy.** Momentum does not use Value's model-surplus gate. The comparison therefore
provides no evidence of better expected returns; the broader policy still needs prospective data.

The ignored `entry-filters/work/momentum_thresholds.py` and `momentum-thresholds.json` retain
the replay and observations. Result SHA256:
`3c6c2b3b441f912a4d4d97c0bd0004867946b24b7f059cc5f17aad52ee35bf73`.

## Explaining the dashboard screenshot

At about04:44:26UTC, in round `btc-updown-5m-1788756000`, the recorded Up book had bids at0.99
and no asks; Down had asks at0.01 and no bids. Source1788756266060ms, received1788756266459ms.
The best complementary levels both contained9320.92 shares. All99 price levels had mirrored
prices/quantities, including0.98/0.02 and0.01/0.99. This matches the screenshot's raw feed; those
99/0 figures counted price levels and did not describe a model's probability or number of trades.

The bid is the available selling price; the ask is the buying price. Opposing binary orders
can create complementary token pairs when their prices add toUSD1. These mechanics are
documented by Polymarket in [Prices & Orderbook](https://docs.polymarket.com/concepts/prices-orderbook)
and [Order Lifecycle](https://docs.polymarket.com/concepts/order-lifecycle). The exact mirrored
quantities above are an observation, not a claim that every API response always mirrors orders.

The UI nevertheless had defects: rows reordered by latest receipt, and `MISSING_BOOK_SIDE`
obscured that every configured entry window had already closed with about35seconds left.
It now keeps Up before Down, labels executable Buy/Sell prices and explains missing liquidity,
with price-level counts in collapsed depth details. Flat portfolios outside their entry window
show the window schedule. Held positions, unresolved orders, halts, stale decisions, unavailable
config or missing liquidity inside an entry window retain their original warnings. Raw decision
records and strategy gates are unchanged.

## Verification

The entry-filter changes passed548 tests, including all four directional engines confirming,
submitting and filling synthetic affordable entries. Cases also cover an explicit positive floor,
cheap-but-insufficient model surplus, theUSD50 boundary and retained rejection gates. The13
dashboard tests passed after the schedule payload change. Headless Edge verified all six cards,
stable book ordering, Buy/Sell labels, closed/early windows, preserved actual/stale/held-position
warnings, absent config, collapsed depth details, no JavaScript errors and no overflow at390px.
These tests establish mechanical behavior, not profitable execution on future public data.
