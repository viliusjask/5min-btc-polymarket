# Six strategies: implementation and interpretation

2026-09-07. Extension of the repaired standalone bot on `feat/six-strategies`.
The user authorized implementation of the four previously deferred experiments and comparison
of all six, using one coding agent and its own tests/review. The original research remains in
[the scientific register](research/scientific-strategy.md),
[community evidence](research/trader-sentiment.md), and
[the article assessment](research/inventory-strategy-ruling.md).
This document supersedes the latter's implementation deferrals. It does not establish profitability.

## Executable policies

1. **`momentum`** preserves the modified late-direction baseline: minimum USD70 BTC lead,
   90–150 seconds remaining, ask 0.70–0.95, depth/cost constraints and shared hard exits.
2. **`value`** estimates the final contract payout probability from the settlement reference,
   remaining time and observed volatility. It buys only when the conservative scenario value
   exceeds executable entry cost plus fees/allowances. Both baselines retain their shared
   300/1800-second history requirements and entry confirmation rule.
3. **`fast_value`** keeps policy 2 but updates the last Chainlink spot using the relative Binance
   BTCUSDT move since an aligned exchange tick. The latest exchange tick must be newer than
   Chainlink and at most 1500ms old; the as-of alignment gap is at most 1000ms. Moves above 50
   basis points (0.5%) across that interval reject. Missing data rejects, with no silent baseline
   fallback. Raw exchange dollars never replace the official settlement reference. This is a
   proposed information improvement; exchange/oracle basis changes and quote latency can erase it.
4. **`model_exit`** uses exactly policy 2's entry calculation. While holding, it compares the
   executable sale proceeds after fees with the most optimistic value in its sensitivity scenarios.
   An extra 0.01/share sale advantage triggers a persistent `MODEL` exit. Hard stop, target and
   time exit remain available even if the model is unavailable.
5. **`passive_pairs`** starts with a five-share post-only limit buy below modeled value, then
   tries to buy the opposite token so completed equal quantities cost at most 0.97 per pair,
   including the first leg's actual fee-inclusive basis and the second leg's conservative reserve.
   Quotes expire locally after five seconds; unmatched inventory has a 30-second timeout.
   The entire round shares the USD5 spending cap and permits at most 24 order attempts.
6. **`inventory_pairs`** uses the same pair engine and limits. On the hedge leg it increases
   the quote by up to 0.04 × min(1, unmatched shares / 5) × 4p(1−p), still below the ask and
   within the pair-cost cap. Here p is the estimated Up probability; p=0.5 is used if the
   model is unavailable but a verifiably capped completion remains possible. This is a bounded
   experimental urgency rule, not fitted optimal market making.

The five-second order lifetime is implemented through explicit GTC cancellation. GTC means
"good till cancelled": an abrupt process failure can leave a venue order active. A cancel
acknowledgment does not release the journal's reservation; terminal order/fill evidence does.
See the [venue order lifecycle](https://docs.polymarket.com/trading/place-orders).
The bot does not use SDK convenience methods that can automatically approve token spending.

## Probability during the final averaging minute

The verified contract compares its opening reference K with the ending 60-second Chainlink
average. Under the arithmetic Brownian approximation dS = sigma dW, sigma is measured in
dollars per square-root second. With tau seconds left, before the final minute the future
average has mean S and variance sigma²(tau−40).

Inside the final minute, let I be the already observed price integral from the start of that
minute to the latest source timestamp. Conditional mean and variance become:

```text
mean = (I + S*tau) / 60
variance = sigma^2 * tau^3 / (3*60^2)
P(Up) = NormalCDF((mean - K) / sqrt(variance))
```

The implementation integrates actual observed points as a left-step approximation and rejects
gaps above 2500ms. Official metadata supplies eventual paper settlement labels; this numerical
integration never declares the winning token. Short/long volatility and reference perturbations
produce scenario floors/ceilings, **not calibrated statistical confidence bounds**. The model
omits jumps, volatility changes, predictable drift and settlement-feed imperfections.
[Settlement feed documentation](https://docs.polymarket.com/market-data/chainlink-twap).

## Inventory and execution

Equal Up/Down quantities in the same verified condition have a combined final payout of one
per pair. Unequal quantities contain a directional remainder. The engine keeps each token's
quantity and cost separately; hedging is a second genuine order with its own fill/cancel state.
It exits only the unmatched remainder when a stop/timeout requires it. Quantities below venue
minimums remain visible as unexitable remnants rather than being rounded up into fictitious sales.
Completed pairs are held for resolution. Live automatic merging/redemption is not implemented;
winning tokens remain claimable and capital can stay tied up until manual redemption.

Buying one side and hoping the other becomes cheaper is directional risk until the second leg
actually fills. Inventory-aware quoting can change execution probability and residual exposure;
it cannot manufacture a price reversal. The article's selected successful wallets and unshared
10M-execution dataset do not establish that this implementation has their edge. The strongest
reusable components are accurate settlement modeling, source alignment, executable-depth sizing,
durable partial-fill accounting and explicit inventory limits. Their ROI contribution remains
an empirical question. Broader cross-asset trading and learned sizing are not implemented.

## Fair comparison

`paper --strategies all` uses one public collector and six separate simulated journals. Total
configured allocation is split equally; with USD100 each portfolio starts at USD16.66. These are
independent counterfactual accounts: they do not compete with each other for the same liquidity.
Fixed USD5 maximum round spending makes raw capital use comparable, but each strategy can have
different fills, holding time, losses and skipped rounds. No parameter was chosen from observed
profits in this implementation run.

Funded `run --strategy compare --execute` instead assigns `STRATEGIES[(round_start/300) % 6]`
before inspecting signals. It keeps one shared wallet ledger and total allocation. This avoids
simultaneous conflicting strategies in one account, but the policies see different rounds and
unresolved earlier inventory can block later assignments. It is not an unbiased paired experiment.
Use the simultaneous paper records to study mechanism differences, then a separately specified
funded trial to assess real fills. External positions/account trading are an explicit blocker.

Report attempted rounds, filled rounds, completed rounds, fees, cash movement, realized PnL,
open basis, claimable value and unresolved orders. An unfilled cancelled order is an attempt,
not a winning trade. Exclude rounds marked uncertain from return conclusions. Repeated screens
and multiple fills of one order are not independent samples. Compare out-of-sample time blocks
and preserve unsuccessful variants; choosing the best of six on the same small sample biases
the apparent result. See [backtest selection research](https://escholarship.org/uc/item/4w1110bb).

## Simulation limits

- No account keys, signatures or venue orders exist in `PaperBroker`. Paper and live SQLite
  journals have different execution identities and cannot be interchanged.
- An order waits at least 250ms and needs a subsequently observed fresh book. A protected
  cash BUY must execute its full requested principal and receive the minimum protected shares;
  a protected share SELL can execute partially. Decimal arithmetic preserves cash accounting.
- Resting orders use the displayed same-price queue at simulated activation. Subsequent
  aggressive SELL trades at or below the limit deplete that queue before filling the order.
  Quote touches and cancellations ahead are not credited as executions. Queue estimates do
  not reproduce actual priority or the market impact of inserting our hypothetical order.
  Trades sharing the activation book's timestamp are excluded because their volume may
  already be reflected in that book.
- A cancellation has simulated latency and a five-second late-trade grace period. Stream
  discontinuity invalidates the queue and marks the round uncertain. A new process cannot
  inherit old queue continuity, even if its numerical connection counter happens to match.
- Recent public price history may be restored on paper restart with original timestamps,
  gaps and conflict markers. Both feeds must produce fresh updates before entry resumes.
  Stored held-market identities restart official final-label polling after a process restart.
- Paper credits automatic zero-cost redemption only after official final labels. Live cash
  recovery remains manual. Maker rebates, gas and hypothetical failed redemptions are omitted.
- Feed timestamps and quantity availability can change before an actual order reaches the
  venue. The 250ms setting is a simulation assumption, not a measured live round-trip guarantee.
  Live preparation performs additional account/metadata/RPC checks and can be much slower.

## Verification record

Behaviour tests cover all six entry paths, source guards, the conditional-average formula,
model-driven exits, genuine pinned-SDK post-only GTC signing and cancellation, delayed cash buys,
queue-volume fills, partial cancellation races, unmatched timeout, completed-pair settlement,
restart identity/history, account-index rounding and paper/live isolation. CLI tests prohibit
credential access from paper and check release of journal ownership after cleanup failure.
These checks establish tested behaviour under specified inputs, not probability calibration,
real exchange fill rates, uptime under all failures, or positive returns.
The current run and final command evidence are recorded in [progress](progress.md).
