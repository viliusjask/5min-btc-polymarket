# Zero passive fills: verified matching omission

2026-09-07. The user's dashboard first showed 0/24, then 0/64 fills/orders. The stopped original
capture ultimately contained **66 orders, all in passive_pairs/inventory_pairs, and zero fills**.
Those are order attempts, not 66 settled trading positions.

The first audit checked only SELL trades in the quoted outcome. That was too narrow. Polymarket
also matches complementary BUY orders: a BUY Up bid at 0.48 can match a BUY Down at 0.52.
The [official orderbook explanation](https://docs.polymarket.com/concepts/prices-orderbook)
describes creation of the complete pair. The [V2 exchange's Trading.sol](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Trading.sol)
implements BUY/BUY MINT matching. A public trade's opposite-outcome price therefore maps to
`1 - price` on our bid side. The old simulator omitted that flow entirely.

## Recorded discriminating example

In the 01:15–01:20 UTC round, an Up quote submitted at **01:17:05.577 UTC** bid **0.48** for
**5 shares**. Queue activation was 01:17:06.422; effective cancellation was 01:17:08.246.
The observed queue ahead was **11 shares**. The opposite book independently showed the same
11 shares offered at 0.52, consistent with complementary book representation.

There were no qualifying same-outcome SELL records, but **12 opposite BUY records totaling
190.557542 shares** met the price/time conditions. To verify trade identity, the anonymous
[Data API](https://data-api.polymarket.com/trades) was queried for that condition. All **18** public
messages in the short window, including nonqualifying trades, were matched to transaction hashes
by recomputing their original SHA-256 stream identity. A separate 15-second raw market subscription
also observed 60 trade messages with transaction hashes.

Replaying the one saved order with those exact timestamped messages through the corrected broker
produced **5 simulated filled shares, USD2.40 principal**, versus the original zero. This is a
single-order execution regression, not a complete strategy backtest: an earlier fill would change
later inventory decisions. Neither replay nor tests establish profitability or actual venue fills.
The production journals were not rewritten with counterfactual cash or trades.

## Correction and boundaries

- Passive bids consume same-outcome SELL flow and complementary opposite-outcome BUY flow.
- Transaction hashes are retained in public trade records. At each normalized price, the simulator
  takes the larger accumulated total of the two reporting routes for a transaction, avoiding
  double-counting mirrored messages. Distinct independent flow within one transaction can be
  undercounted; public aggregate data does not reveal exact queue position.
- Opposite flow without a transaction hash is skipped and marks the round uncertain. Same-side
  BUY and opposite-side SELL are not buyer-matching flow. Wrong condition/generation, insufficient
  price, activation timing and effective cancellation checks remain enforced.
- New orders record `COMPLEMENTARY_FLOW_V2`. Older passive orders remain visible and are flagged
  in the dashboard/report as results of the earlier matching model. Their zero fills cannot assess
  the corrected policies. Actual execution outcomes replace misleading `Settled / Entry` labels.
- Most of the first twelve unique quote windows lasted roughly 0.3–2.5 seconds before replacement.
  Six orders were cancelled before a subsequent book could establish their queue. Rapid
  quote cancellation remains a strategy concern; thresholds were not loosened to manufacture fills.

Strategies 1–4 had different blockers during the entry windows inspected: momentum had insufficient
price movement; value/model_exit mostly failed price-band or terminal-surplus requirements;
fast_value also had occasional stale/unaligned exchange inputs. Only one recorded value/model_exit
screen passed, without subsequent execution confirmation. They did not produce the repeated
passive orders shown in the screenshot. The corrected passive simulator does not validate these
strategies' thresholds or expected return.

Local, ignored evidence in the paper-service worktree: `work/complement-flow-audit.json`,
`work/recovered-public-order.json`, `work/captured-order-replay-result.json`, and
`work/raw-public-trade-probe.json`. The full original capture remains in the dashboard worktree;
the continued runtime lives outside worktrees as described in [the service guide](../paper-service.md).

## Second failure: cancelling a quote because a new quote would differ

The later 0/98 screenshot contained corrected V2 orders too. The matching repair above did not
fix the entire experiment. `Engine._manage_resting` cancelled an unfilled quote whenever a new
`pair_decision` preferred a different price or outcome. This discarded queue priority even when
the existing quote retained its required model surplus. Reranking new opportunities is not the
same decision as evaluating an already owned quote.

The audit of 25 V2 orders submitted between 02:02 and 02:14 UTC reconstructed the available
oracle history and published books at cancellation. Most early cancellations still had enough
surplus at the original price. For example, a Down bid at 0.70 submitted at **02:03:22.047 UTC**
was cancelled after 1.113 seconds when the recalculated bid rose to 0.71; the original bid
still had a scenario floor of approximately 0.731. Its original queue estimate was 56.2 shares.

Separate original-order replays kept 17 quotes longer and filled one order: the 0.70 Down bid
received **five simulated shares, USD3.50 principal**, from recorded trade volume arriving at
02:03:26.008 UTC. The other 24 remained unfilled. These replays use original queue estimates,
250ms controller checks, observed price history/books and identified trades. They do not
reconstruct unpublished temporary book invalidations or repeat subsequent portfolio decisions.
They are evidence about quote handling, not a portfolio backtest or a forecast of fill rate.
The active paper journals retain their original results.

The corrected controller (`KEEP_VALID_V1` on new quote decisions) keeps an existing quote until
its five-second lifetime ends or a specific risk/data condition requires cancellation. An
opening quote, including its remaining quantity after a partial fill, must retain the original
minimum model surplus. A hedge keeps its originally reserved pair-cost cap; changing the best
bid alone does not invalidate that price. Stops, unknown orders, changed market terms, invalid
inputs and entry/exit windows still cancel. No pricing, budget or matching thresholds were relaxed.

New cancellations persist their trigger against the order identity. The dashboard shows
Resting → Cancelling → Cancelled unfilled, with a cause such as Quote expired, Quote edge lost,
or No snapshot. Historical rows without a recorded trigger keep the generic terminal reason;
the system cannot recover an exact past trigger from that message alone.

Many recorded bids were also far below the best bid: one offered 0.06 while the market bid 0.31.
The model's stressed valuation cap produces such quotes, and tick rounding can change which
outcome has the largest small surplus. New decisions record best bid/ask and distance below
the bid so this can be measured. Stable quote handling does not establish that these valuation
caps produce competitive quotes. Evaluating quote placement and model calibration remains
necessary before treating the strategy as demonstrated or increasing real exposure.

Ignored evidence: `work/current-quote-audit.json`, `work/reconstructed-cancellations.json`,
`work/quote-controller-replay-results.json`, and the isolated replay journals alongside them.
