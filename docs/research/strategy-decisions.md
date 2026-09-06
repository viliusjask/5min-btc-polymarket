# What to change in the strategy

Research date: 2026-09-06. This is a reasoned experiment design, not a profitable backtest.

The original idea is plausible: buy the likely winner late, while enough price upside remains,
and exit when the position deteriorates. A high contract price alone does not establish value.
The useful question is whether the available price is low enough for the actual chance of winning,
after fees and execution costs. A stop changes realized win/loss sizes, so settlement-only loss
arithmetic does not evaluate this proposed strategy.

## Decisions for the first implementation

| Change | Why it could improve returns | Evidence and limit |
|---|---|---|
| Replace a fixed BTC-dollar move with distance relative to recent volatility and remaining time | A USD 90 lead is very different in quiet and fast markets; skip expensive weak leads | Conditional probability math supports the distinction. The probability model remains uncalibrated. |
| Model the 60-second settlement average and capture the correct opening average | Avoid buying on a spot-price signal that is misaligned with the contract | Current contract rules and our two-boundary anonymous probe support this reference policy. |
| Require a margin above executable cost | Fewer trades with more room for fees, spread and model error | Actual fee formula and depth are measurable; the initial two-cent margin is a hypothesis. |
| Confirm a candidate after the underlying feed reaches its original book timestamp | Reduce entries whose apparent value comes from newer market information missing from our model | A captured repricing event motivates the rule. It can miss short-lived opportunities; higher ROI is unproven. |
| Keep price-protected stops, a profit target and an expiry exit | Bound ordinary losing trades and free capital without waiting for every resolution | Stops can help or hurt depending on the price process. Only filled sales reduce exposure. |
| Fixed small spending, one opening intent per round | Prevent churn, duplicate orders and accidental compounding from dominating the experiment | Operational control, not a forecasting edge. Actual received shares drive exit size. |
| Record both candidate decisions but execute one configured strategy | Compare the modified upstream rule with the value candidate on the same rounds | Decision records cost little. They do not claim hypothetical fills or paper profit. |

For a concrete illustration, a USD 90 lead with two minutes left corresponds to approximately
99.91%, 94.05% or 78.21% Up probability under the proposed averaged-price model when one-minute
price-change volatility is respectively USD 25, USD 50 or USD 100. These are model outputs, not
measured success rates. Paying 90c is a very different proposition across those three scenarios.
The implementation also checks a higher-volatility scenario and an adverse reference shift;
these are sensitivity checks, not statistical confidence bounds.

Default value entries require 60–180 seconds remaining, a 60–92c ask, sufficient actual depth,
and at least 2c of terminal valuation surplus after modeled entry fees, a conservative sell-fee
allowance and 1c additional allowance. The momentum comparison uses a USD 70 minimum lead,
90–150 seconds remaining and 70–95c prices, with the same execution safeguards. That is a modified
reference, not a literal reproduction of the screenshot or an independently reproduced strategy.

The value metric estimates the final payout's value. Because we also stop, take profit and exit
before expiry, it is not a forecast of the complete strategy's profit. Measured stopped-trade
outcomes stay separate from probability calibration. Default exits are an 8c drop from actual
entry price, a 98c depth-weighted bid, or 20 seconds remaining. Those numbers are initial hypotheses.

Both executable modes now require a second information check before reserving money: the underlying
source must advance to at least the original candidate's book timestamp, and the same side must still
qualify against the current book/model. Any observed invalidation cancels that pending candidate.
The original timestamp stays fixed, so the bot does not endlessly chase a newer book. This removes
the initial observed information gap; a gap to the newest book can remain and is reported.

In the35-minute public run, the sole value-eligible snapshot showed a61c Up ask and a96.8% central
model probability, using a BTC source timestamp about2.2seconds older than the book. Later-arriving
Chainlink points for times before that decision showed an approximately18-dollar BTC drop; the next
snapshot no longer qualified. A generic next-snapshot check also rejects this one event, so it does
not prove the chosen rule superior. No order, hypothetical fill or trade profit is inferred.

A USD 5 all-in spending target can be too small to satisfy the exchange's minimum shares at a high
price. The bot skips those entries; it never rounds the order up beyond its reservation. The
USD 100 dedicated experimental allocation is distinct from per-trade sizing. An unknown submission
keeps its cash reservation, and remaining holdings continue consuming the persisted loss budget.

## What the human evidence actually says

The research deliberately included positive accounts as well as losses. One discussion claims
that 99c favorites won 99.8% of the time in a very large trade sample. Several builders report
profitable prototypes or screenshots. Other builders report fee drag, failed exits, misleading
paper fills and accounting bugs. None of the accessible evidence reproduced the exact screenshot
strategy, its complete account cash flows, or a transferable profitable configuration.

The positive favorite result is worth investigating. Millions of trades in shared five-minute
rounds are not millions of independent outcomes, however, and obtaining the historical prices is
part of the strategy. The most detailed negative repositories also did not provide the datasets
their headline results would require for independent reproduction. Their concrete accounting and
execution mistakes are useful engineering evidence; their broad profitability claims remain claims.
See the source-by-source [trader evidence register](trader-sentiment.md).

Academic findings also need boundaries. Favorite–longshot bias conventionally means favorites
are underpriced and longshots overpriced; it does not justify calling expensive favorites
inherently bad. Much of the BTC momentum/reversal literature studies half-hour or hourly periods.
A recent prediction-market calibration paper has timestamp uncertainty far longer than this
strategy's holding period. Those studies supply hypotheses, not a two-minute trading coefficient.
See the [scientific report](scientific-strategy.md) for primary sources and derivations.

## Changes to defer until the first real observations

A model-driven exit could sell whenever the executable net bid exceeds the updated value of
holding. That may improve on a fixed profit target, but needs a correct model inside the final
averaging minute and evidence that its revisions help. Preserve the simpler exit as a measured
baseline before adding another forecast-dependent rule.

Passive maker orders can reduce explicit fees. They also introduce queue position, missed fills
and fills that occur preferentially when the quote has become bad. A measured price-feed lead
is not sufficient evidence of a profitable maker strategy. Do not make latency optimization or
a language rewrite the first project.

Our public probe also measured roughly two to three seconds between source timestamps and local
receipt, including any clock offset. Fresh order-book prices may incorporate information that the
underlying feed has not delivered yet. This can create an apparent valuation advantage that disappears
when the newer information is included. A faster underlying feed, aligned and compared with Chainlink,
is a useful next competitor if recorded fills indicate this problem. It must preserve the actual
Chainlink settlement reference and measure the price difference between feeds; blindly substituting
an exchange price would change the modeled contract. The first version keeps one verified source.

Fitted momentum, reversal, heavy-tail models and order-flow features are sensible competitors
only after a chronological dataset exists. A more complex model should improve later predictions
and realized policy outcomes after costs, not merely fit the collected sample. Avoid optimizing
many thresholds against the first USD 100 run. Do not add an LLM to a sub-second execution path.

A tiny opposite-side hedge has no automatic benefit. It buys away directional exposure at an
additional price. Compare that cost with directly selling part of the position before adding a
second execution route. The first implementation uses actual exits and no automatic hedge.

## A useful small live experiment

The first funded run should answer whether the implementation can discover the right market,
obtain its intended entry, exit held shares and reconcile exact cash/fees across restart. A USD 100
allocation can provide valuable execution evidence without a separate paper platform. One good
or bad session cannot establish a stable expected return.

Freeze the configuration for a run; record all considered rounds, skip reasons, attempted orders,
actual fills, fees, open inventory and net realized cash profit. Report sample size by unique round.
Preserve failed orders and losses instead of selecting the best screenshots. Compare probability
calibration separately using a predeclared two-minute observation, including missing observations.
Only increase size or integrate with Alpha-Sentry once execution works and the evidence supports
keeping the strategy. Alpha-Sentry's current equity-research workflow does not supply this bot's
venue-specific matching, custody or settlement machinery; standalone remains the appropriate scope.
