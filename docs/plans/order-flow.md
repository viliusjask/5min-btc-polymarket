# Order-flow and pair experiments

Authorized 2026-09-07: implement the five forum-research ideas in paper mode,
single-agent, from merged PR8. Preserve the existing six portfolios and 84-trial
study. New work runs on `feat/order-flow-experiments`; no funded transactions.

## Delivery

- [ ] Capture Binance executed volume/direction, full top-20 book snapshots and
  Polymarket public trade events with receipt times, continuity and durable replay.
- [ ] Register absorption, pressure-directed pairing and early-pressure/later-price
  confirmation, with matched controls and small prespecified parameter comparisons.
- [ ] Scan compatible 5m/15m contracts, checking exact rules, anchors, depth and fees.
  Report quote candidates, never claim these are executed arbitrage profits.
- [ ] Simulate split, passive sales and merge with conservation of collateral,
  partial fills, expiry, cancellation and crash recovery. Rebates remain excluded
  until attributable receipts exist; no invented rebate income.
- [ ] Show the new study and scanner in the existing dashboard; test all paths,
  run public integration probes, install continuous collection/replay and open PR.

## Decisions fixed before observing returns

Use public spot exchange flow as an experimental predictor of the existing
Chainlink settlement model, not as a replacement settlement source. Preserve raw
trade quantities and maker-side flags; price-only historical tape cannot recover
them. Use Binance full partial-depth messages rather than inventing continuity from
incomplete depth deltas. Such messages lack exchange timestamps, so label their
age as receipt age and do not claim measured subsecond exchange latency.

Absorption compares sell/buy imbalance with failure to extend the price move.
Pressure chooses only the first leg; hedges retain fixed pair-cost and cash limits.
Confirmation records the first eligible early observation once, and requires a
later, more expensive quote. Retain controls that enter at the same later time
without the early signal. All quantities, fees and cash use Decimal.

Start a separately registered study with independent $100 wallets and existing
$5 trade / $10 loss settings. Baseline results and previously frozen evidence do
not change. All claims distinguish inputs, signals, orders, fills and completed
profit. A missing feed produces an explicit diagnostic, not an assumed zero.

## Research sources

- [Practitioner OBI pairing](https://www.reddit.com/r/PredictionsMarkets/comments/1vsfniw/using_orderbook_imbalance_obi_for_polymarket/): concrete hypothesis; timing/profit claims unverified.
- [Queue imbalance research](https://arxiv.org/abs/1512.03492): short-horizon equity evidence, not a Polymarket profitability result.
- [Absorption prototype](https://github.com/Odomushi/cvd-trading-bot): useful flow idea; its fixed payout assumption is unsuitable.
- [Early pressure then confirmation](https://www.reddit.com/r/PredictionsMarkets/comments/1uqjisf/the_futures_book_knows_first_finding_an_edge_in/): commercial source, exploratory claims.
- [Cross-duration construction](https://dev.to/bluewhale-quant-lab/the-polymarket-cross-cycle-sandwich-a-structural-arbitrage-in-updown-markets-387l): shared final variable required; both orders must fill.
- [Binance stream contract](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams): trade quantity, aggressor direction and depth payloads.
- [Official split/merge mechanics](https://docs.polymarket.com/trading/positions/manage).
- [Maker rebates](https://docs.polymarket.com/programs/maker-rebates): actual executed flow and variable pool allocation; no fixed bonus.
