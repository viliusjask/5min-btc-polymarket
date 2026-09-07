# Research ruling: a measurable Polymarket strategy lab

September 7, 2026. Scope: the five priorities in [the implementation plan](../plans/experiment-lab.md).
The scientific papers below support the evaluation method. They do not supply profitable
parameters for current BTC five-minute contracts. The existing source register in
[scientific-strategy.md](scientific-strategy.md) remains relevant, particularly its horizon caveats.

## Evidence, limitation, engineering consequence

| Source | Supported finding | Consequence in this implementation |
|---|---|---|
| [Gneiting & Raftery, JASA 2007](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf) | Proper scores evaluate probability forecasts; calibration and sharpness are distinct. | Brier loss (squared probability error), logarithmic loss and reliability bins for the **central** forecast. Compare the same rounds with contemporaneous Up midpoint. Test pessimistic scenario settings separately; never call the floor a confidence bound. |
| [Bailey et al., Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) | Searching many configurations selects noise; repeated tuning can contaminate nominal holdouts. | Register all trials, freeze a shortlist before its next full round, use later time blocks, and retain failures. Exploratory rankings have no claim of statistical significance. A newly inspected test becomes development evidence for the next study. |
| [Bailey & López de Prado, Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) | Selection and non-normal returns distort apparent performance. | Show trial count, distinct rounds and days. Do not annualize a few hours of binary outcomes or manufacture a precise Sharpe/significance estimate from correlated variants. The initial lab does not claim to implement DSR or PBO. |
| [Politis & Romano, Stationary Bootstrap](https://www.stat.purdue.edu/docs/research/tech-reports/1991/tr91-03.pdf) | Dependent time series require dependence-aware resampling assumptions. | Treat a round as the elementary outcome and display calendar-day blocks. Descriptive bin intervals assume independent rounds and are explicitly labeled; overlapping evaluations are never counted as new outcomes. No unsupported iid trade-level profit interval. |
| [Kaminski & Lo, 2014](https://www.sciencedirect.com/science/article/pii/S138641811300030X) | Stop-rule value depends on the underlying return process. The accessible abstract supports comparison with and without the rule; the empirical setting is much longer than this task. | Compare the actual protected stop, wider/narrower stops, time-only and hold-to-settlement exits on common inputs. Record executable exits, including unsuccessful attempts; never equate a stop trigger with a guaranteed sale. |
| [Barucci et al., Digital Finance 2023](https://link.springer.com/article/10.1007/s42521-023-00095-9) and [Gould & Bonart, 2016](https://arxiv.org/abs/1512.03492) | Crypto market/quote-currency effects and stock next-tick queue effects depend on market and horizon. | Test lagged continuation and reversal as competitors. Do not transplant fitted coefficients or confuse a contemporaneous explanation with a future forecast. Queue predictors are deferred until adequate event-level execution evidence exists. |
| [Polymarket order lifecycle](https://docs.polymarket.com/concepts/order-lifecycle), [prices and orderbook](https://docs.polymarket.com/concepts/prices-orderbook), [fees](https://docs.polymarket.com/trading/fees) | FOK orders must fill completely; crossing costs spread/depth and market-specific taker fees. Midpoint is not an execution price. | Reuse the existing Engine, PaperBroker, Decimal sizing, confirmation, FOK/FAK and fee accounting. Each variant is a separate counterfactual, so their results cannot be added as simultaneously executable profit. |
| [Polymarket Chainlink TWAP documentation](https://docs.polymarket.com/market-data/chainlink-twap) | Source time differs from publisher time; reconnecting restores subscription without replaying missed updates. | Persist exact source/receipt timestamps. Keep the verified opening reference and official final-average labels. Missing frames cancel confirmation and mark affected exposure uncertain; no interpolation to create fills. |
| [SQLite WAL](https://sqlite.org/wal.html), [savepoints](https://sqlite.org/lang_savepoint.html), [synchronous](https://sqlite.org/pragma.html#pragma_synchronous) | WAL permits readers alongside a writer; FULL synchronizes commits; nested savepoint release does not independently commit the outer transaction. | Separate the collector tape from evaluation journals. Atomically commit each replay frame, account changes, pending confirmation and cursor. A crash replays a whole uncommitted frame. No shared account connection, no credential access, no per-variant feed subscriptions. |

## Selected experiments and interpretation

- Start with $10 lead steps from $10 to $100 across three entry windows. A dense 1–100
  grid is supported as an explicit new study, not silently added to inflate the search.
- Compare cost-adjusted surplus thresholds and scenario buffers separately. Central model
  accuracy does not establish profitable entries after execution costs or early exits.
- Compare Chainlink and aligned Binance-assisted valuation, with slower execution controls.
  Recorded sampling limits the temporal resolution; it cannot prove real network latency.
- Normalize opening lead by `short_sigma * sqrt(seconds_to_settlement - 40)` for the
  supported future 60-second average. This is a unitless signal under the existing model,
  not a fitted forecast. Recent-return competitors use only points already received,
  a bounded lookback endpoint tolerance, and both signs of the recent move.
- Equal initial capital and fixed budget expose allocation, cash and risk-limit blocking.
  Changing bankroll is a separate experiment; do not silently scale order sizes or erase
  losses to keep weak strategies trading.

The forecast sample is fixed at end-minus120 seconds, with at most two seconds of lateness,
independent of whether an entry qualifies. Missing rounds and missing labels remain visible.
Log-loss display clips probabilities at 1e-6 for numerical stability and reports the clipping;
Brier uses the original probability. The market baseline is a forecast benchmark only.

The lab must report all registered variants, raw and quality-filtered results, orders/fills,
completed and unresolved rounds, costs, exposure and drawdown. A drawdown based on realized
cash alone misses held losses: show inventory at executable bid depth where observable and
make missing marks explicit. Do not select a winner from an incomplete or uncertain sample.

The first 84-variant disk benchmark took 2.53 seconds per frame when each derived journal
forced a disk synchronization. The shared input tape and study registry retain FULL
durability. Replay journals use WAL/NORMAL: a power loss can discard a committed suffix
of this **derived cache**, but its cursor and accounting roll back together and replay
from the durable tape. No externally submitted order can be duplicated because the lab
only uses PaperBroker. This choice does not apply to baseline or live account journals.
The subsequent active synthetic benchmark took 0.085 seconds per frame across 84 variants,
including 55 simulated opening fills. That establishes local processing capacity, not returns
or the ability to obtain those fills at the venue. SIGKILL and deliberately lost-cache-suffix
tests verify atomic recovery independently of normal graceful shutdown.

## Residual evidence gaps

No reproducible evidence here proves a durable Polymarket edge, the community article's wallet
attribution, exchange queue priority, or live execution quality. The old journals did not save
every exact decision snapshot; historical screens can support forecast diagnostics, but cannot
be retroactively presented as full-fidelity lab executions. Fresh common-tape data is required
for the new execution comparisons. Defaults and sample gates are predeclared operating choices,
not power calculations or promises that a particular number of rounds proves profitability.
