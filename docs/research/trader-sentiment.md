# Trader experience and evidence: BTC 5-minute Polymarket bots

Research date: 2026-09-06. This is a purposive sample of public trader/developer discussions, not a representative survey. No accounts were accessed, traders contacted, or orders submitted. Claims about the supplied @igus_ai screenshot remain claims; this research did not identify an independently confirmed wallet or trading record tying its $250 → $13,000 result to Novals83's code or the alleged Claude modifications.

## Assessment

The public material supports investigating execution, accounting, and late-reversal risk before trusting a near-expiry momentum backtest. It does **not** establish that this specific $70–$100 BTC-move / approximately 120-seconds-remaining / $0.80–$0.99 entry strategy is profitable or unprofitable. Positive screenshots, public wallet profits, and an executable strategy are three different levels of evidence. The negative studies below test related strategies and have meaningful limitations too.

Among the selected firsthand accounts, recurring complaints concern late reversals, stops that cannot get a fill, paying a worse price than the observed quote, partial fills and balance races, and discrepancies between a local ledger and venue cashflows. There are also success claims and research suggesting some highly priced contracts may be favorable. Neither the frequency of selected complaints nor Reddit votes establish a population-wide consensus. Separate posters are not automatically independent datasets; cross-posts and repeated commenters are identified below.

## Evidence register

### 1. Original repository: concrete integration problems, no performance verification

**Primary artifact; high confidence in existence, no profitability evidence.** GitHub's public Issues API returned these dated reports:

- **2026-06-20:** alikopasa reports a missing `pm_live_trade_runner.py`. [Issue #4](https://github.com/Novals83/5min-btc-polymarket/issues/4).
- **2026-06-20:** jxu218382-spec reports that `py_clob_client 0.34.6` passes authentication but orders fail with `invalid order version`; attempts with the V2 SDK produce maker/signer errors. This is an unresolved user report, not a reproduced diagnosis. [Issue #5](https://github.com/Novals83/5min-btc-polymarket/issues/5).
- **2026-04-11:** the maintainer's change describes treating close-order `status=live` as unfinished, then polling/canceling/reposting when necessary, and defaulting to closing 20 seconds before expiry. A resting close order had evidently needed explicit handling. This confirms the implementation concern, not successful real fills. [PR #3](https://github.com/Novals83/5min-btc-polymarket/pull/3).

The two user issues had no comments in the retrieved API response. Stars, forks, and trending coverage were not used as validation.

### 2. Closest strategy match: a 99-cent near-expiry success headline, challenged by firsthand users

**2026-04-07 thread; comments April 7–9.** ArtNoLimit promotes another trader's claimed $19,000 earned over two months buying BTC contracts at 99 cents near expiry. The link goes to a Synthesis wallet page with a referral parameter, making this promotional third-party evidence. It identifies a public wallet, but no full account reconciliation was performed. [Thread](https://www.reddit.com/r/PredictionsMarkets/comments/1sfb092/he_made_19k_by_buying_btc_at_99_in_the_last/).

Distinct commenters provide useful firsthand counterexamples: `eve-collins` says a late reversal erased roughly 20 previous wins; `cs_legend_93` says repeated stop-outs cost dollars while wins earned pennies; `Pie_Dealer_co` describes 96-cent entries reversing in the final seconds. `Ok-Judgment-1181` describes working on 85–95-cent entries and stops but struggling to balance behavior. Others correctly question whether the stop can actually match. None supplies a complete trade export proving frequencies or results. Treat the complaints as failure scenarios to reproduce, not estimated probabilities. `tarel_` also comments negatively here and appears again in item 3; count that person once.

### 3. Oracle/display disagreement: firsthand frustration, not evidence of fraud

**2026-04-04.** `tarel_` says BTC appeared $20 above the reference for much of the final minute, then the contract lost after a last-second move, and alleges mismatch with exchange/Chainlink prices. `AlgoTrade` replies that their subscribed Chainlink data matches resolution, while the displayed graph may lag. [Discussion](https://www.reddit.com/r/Polymarket/comments/1sc18up/bitcoin_updown_5min_is_scam/).

**Evidence quality: low for the alleged discrepancy, moderate for identifying a user-facing failure mode.** No synchronized timestamped feed/settlement trace was supplied in the text reviewed. The allegations do not prove manipulation, incorrect settlement, or a custom Polymarket BTC price. Log the exact resolution feed, opening reference, event timestamp, receive timestamp, and final outcome; compare those before attributing a loss to the venue.

### 4. Simulation-to-live slippage complaint

**2026-04-07.** A builder reports 5-minute BTC simulations outperforming live execution, approximately 300 ms order execution, a Python-to-Rust rewrite, and reduced realized gains after slipping prices. Commenters dispute advice to send orders directly on-chain because matching occurs in the off-chain order book. [Original indexed post](https://www.reddit.com/r/polymarket_bets/comments/1sf1t5j/built_a_profitable_polymarket_bot_but_slippage_is/), [cross-post](https://www.reddit.com/r/PolymarketProtestClub/comments/1sf1ubk/built_a_profitable_polymarket_bot_but_slippage_is/).

**Evidence quality: low; cached firsthand report, no fills supplied.** The original direct open later returned 404; search still returned its text. Cross-posts are one account, not independent support. Comments claim a 250 ms taker delay and particular hosting locations, but these are dated, unverified statements and should not become present implementation assumptions. The transferable point is to measure signal-to-acknowledgment and signal-to-fill separately, including slippage and fill rate, before choosing a faster language or region.

### 5. Large self-reported negative strategy study, with useful exit detail

**Approximately July 2026; page exposed only a relative date.** `Roxas-M33` reports thousands of resolved windows and extensive tests. Its most relevant claimed comparison: entries in the $0.80–$0.95 favorite band had 84.7% wins across 958 observations against an estimated 88.3% break-even. The author also reports that tight stops often removed eventual winners, and that realistic fills, spread, and partial execution erased marginal simulated profits. [Post](https://www.reddit.com/r/Polymarket/comments/1un85mg/i_spent_7_months_testing_every_strategy_on/).

**Evidence quality: a detailed self-report, not independently reproduced.** Some tests use ETH candles and prior-window trends; those do not directly test the proposed within-window BTC strategy. No raw dataset was recovered here. Its fee coefficient is 0.072, whereas current official crypto documentation lists 0.07. The post also promotes a custom trading terminal. Claims that no retail strategy can work exceed what this selected study proves. Useful specific warnings include exiting into the bid, failed/partial FAK fills, balance/allowance races, and checking actual holdings instead of trusting a filled label.

### 6. Measured lead-lag, explicitly not claimed as a profitable strategy

**Measurement period 2026-06-19 to 2026-06-23; post approximately June 2026.** `itsyourdecide` reports synchronized quote measurements on about 1,160 windows per asset: Binance-derived fair probability leads Polymarket repricing by roughly 200–250 ms. Yet BTC taker markout—price movement after a hypothetical execution—is reported around −0.41/−0.43 cents after crossing the spread. Passive-side quote signals look more promising. [Post](https://www.reddit.com/r/Polymarket/comments/1udy8xe/measuring_binancetopolymarket_leadlag_on_5minute/).

**Evidence quality: methodological self-report, no reproduced fills.** The author explicitly does not simulate queue position, cancellations, fill selection, or full trading profit and loss. This is a useful distinction: a measurable lag is not automatically a tradable lag. It suggests testing stale-quote avoidance and cancel timing, but provides no validated maker strategy. The reported signal is stronger early and near the 50-cent region, so it is not direct validation of 80–99-cent late entries.

### 7. Positive counterevidence for favorites: large claimed trade analysis

**Data period 2026-06-01 to 2026-08-08; exact post date not reliably exposed.** `pablo2811` claims to analyze approximately 15 million trades in the final two minutes, reporting that 99-cent favorites resolved positively 99.8% of the time and that cheap late-comeback contracts lost money overall. [Post](https://www.reddit.com/r/Polymarket/comments/1vjzidp/the_late_comeback_bet_in_btc_5minute_markets/).

**Evidence quality: potentially material, currently unverified analysis.** No full dataset or executable notebook was recovered from the accessible post/comment text. A commenter points out that spread, trade direction, and opening versus closing trades need separating. Trades within one resolved window are correlated, so millions of fills are not millions of independent trials. The extraction exposed inconsistent relative timestamps; the data dates are clearer than the publication date. This could support investigating selected favorite prices, but does not prove that a new bot can obtain the same fills, that the specific BTC-movement filter adds value, or that results survive fees and out-of-sample testing.

### 8. Direct success claim with disputed ownership

**Approximately May 2026; exact date not recovered.** `FantasticConcept25` says their deployed 5-minute BTC prediction bot is doing well, using a screenshot. Commenters ask for fees, wallet identity, and trading records; another commenter later identifies a possible public account, `goingbackwards`, using apparent trade matches. [Discussion](https://www.reddit.com/r/PredictionsMarkets/comments/1ths8pl/my_5min_btc_bot_is_doing_well/).

**Evidence quality: low.** Ownership of that wallet is not established, the complete profit calculation is not supplied, and comments from the poster are inconsistent about copy trading. The public profile fetch timed out in this research; no unrelated wallet audit was pursued. Community accusations of fraud are also not proof. This is a positive anecdote with unresolved attribution, not independent evidence of a replicable bot.

### 9. A positive paper result and negative live result used to promote an article

**Approximately March–April 2026; exact publication date not recovered.** `Plastic-Act1507` claims 2,807 paper trades with 67.9% wins and +$570.88 from $100, followed by live execution failures. They offer a CSV but route readers to Medium for the detailed defects. Another commenter, `ValuableSleep9175`, says their own gross-positive strategy loses after fees and cannot sustain quick exits. [Discussion](https://www.reddit.com/r/PredictionsMarkets/comments/1s3rjkl/i_built_a_polymarket_scalping_bot_for_5min_btc/).

**Evidence quality: low, promotional.** The advertised CSV was not directly available in the retrieved material. The paper win rate does not establish predictive edge if paper fills were unrealistic. The firsthand reply is useful supporting sentiment about fee drag, but not a measured effect size. The post's broad claims about the percentage of all losing wallets were not adopted.

## Inspectable negative repositories: what the artifacts actually establish

### Zayan Salman's trading lab

The [README](https://github.com/zayansalman/polymarket-crypto) calls the research complete on **2026-07-10** and reports **−$19.35 over 351 fills**. It describes predeclared strategy variants, later-data evaluation, fee accounting, and an eventual decision to stop. Its strategies generally target fair value around the midrange; this is related evidence, not a replication of the proposed 80–99-cent entry rule. The GitHub repository itself was not technically archived at retrieval, despite the README's research status.

The [2026-07-02 postmortem](https://github.com/zayansalman/polymarket-crypto/blob/main/docs/POSTMORTEM_2026-07.md) gives a narrower June 15–24 result: **+$6.27 gross, −$23.51 taker fees, −$17.24 net**. Its pre-fix journal/ledger showed only −$8.01/−$3.10 because settlement accounting omitted fees. Other dates/manual activity explain separately labeled figures; do not combine them. It also reports a startup crash when a pruned order lookup returned nothing, a winning redemption missed after the process stopped, and operator restarts following a daily loss halt. It says matching live/shadow trades used identical prices after fee correction: this case therefore does **not** support blaming every loss on latency.

**Reproducibility check performed:** inspected GitHub's recursive tree at current `main` and release tag `v1.0.0`, the release assets, `.gitignore`, and reconciliation/replay inputs. There were no database, CSV, JSONL, Parquet, ZIP, or GZIP data artifacts in either inspected tree, and no attached release assets. [`.gitignore`](https://github.com/zayansalman/polymarket-crypto/blob/main/.gitignore) excludes `data/`, `*.db`, and `archive/`. This conflicts with the README's statement that the ledger and tick journal ship. **The reported monetary results were not reproduced.**

The [reconciliation tool](https://github.com/zayansalman/polymarket-crypto/blob/main/tools/reconcile_live_ledger.py) requires an already-fetched activity snapshot and local ledger; a positions snapshot can be fetched if missing. It groups buys, sells, redemptions, and open position value, removes assumed trades without corresponding venue buys, and checks snapshot freshness. Those are inspectable implementation facts. However, activity completeness is an input assumption, and its use of `usdcSize` must be checked against actual fee/collateral semantics. Inclusion of open `currentValue` means the total is partly marked to market, rather than entirely realized cash. No complete wallet/cashflow reconciliation was achieved here. Use it as a source of failure scenarios and accounting design, not audited performance.

### Fierdimo's separate analysis

Published on GitHub **2026-05-18**, this [analysis repository](https://github.com/Fierdimo/polymarket-analysis) reports that its order-book probability estimate predicts outcomes better than its public-feed model; adding a measured exchange-to-oracle lead does not improve its held-out results. It explicitly tests the idea of entering late when the outcome looks nearly decided. Its reported oracle sample is short: approximately **407 windows / 34 hours**, with roughly 11 days of trade-flow data. It admits approximating the Down book with `1 − Up`, which is not equivalent to observing actual executable quotes.

**Evidence quality: inspectable methodology, unverified performance.** The current tree has analysis/collector code but no CSV, Parquet, or database data exports; no releases were found. No independent rerun was possible from the inspected artifacts. Its universal claim that public-data takers cannot profit goes beyond a limited sample and model family. Nevertheless, the documented mistakes—linear BTC returns used for a binary payoff, wrong market discovery, and exchange prices used as labels instead of the resolution feed—are concrete checks worth incorporating.

## Cost and execution implications for the proposed implementation

Current [official fee documentation](https://docs.polymarket.com/trading/fees), retrieved 2026-09-06, specifies `fee = shares × feeRate × p × (1 − p)`, with crypto `feeRate = 0.07`, zero maker fees, and parameters available per market. Fetch applicable parameters and book actual fills. A limit order is not inherently a maker order; crossing an existing quote can make it a taker.

The following is arithmetic using that fee formula, not an empirical success estimate. For one share bought at executable ask `a` and held to resolution, expected profit before other costs is `q − a − fee(a)`, where `q` is the true chance of winning. Required win probability therefore exceeds the ask:

| Entry ask | Buy fee per share | Break-even win probability |
|---:|---:|---:|
| $0.80 | $0.011200 | 81.1200% |
| $0.90 | $0.006300 | 90.6300% |
| $0.95 | $0.003325 | 95.3325% |
| $0.99 | $0.000693 | 99.0693% |

At 99 cents, a full loss costs about **106.4 successful identical trades** after this buy fee, assuming no rebates or other costs. This is why a high observed win rate can be unprofitable. Near-certain contracts can still have positive expected value if the true probability is sufficiently higher than their executable price; that probability advantage must be demonstrated.

For a buy and early sell, use the actual exit **bid**: `bid_exit − ask_entry − entry_fee − exit_fee`. Buying at $0.90 and selling at $0.91 as taker on both sides produces approximately **−$0.002033 per share**, even before additional slippage. A displayed increase does not prove a profitable exit. No personal tax assumptions were made; these are trading economics before taxes.

Implementation and validation recommendations inferred from the evidence:

1. **Treat exits as attempts, then reconcile fills.** Distinguish submitted/resting, partially filled, filled, canceled, and settled states. Preserve remaining exposure after a failed exit. A stop price is a trigger, not a guaranteed sale price or guaranteed maximum loss.
2. **Use executable books in replay and paper mode.** Record both tokens' best bid/ask and depth at signal time, submission time, and fill time. Apply latency, missed orders, partial fills, spread widening, and fees; do not fill every signal at the last trade or midpoint.
3. **Measure whether the entry condition adds value over market price.** Compare the fixed-dollar momentum rule against matched price/time buckets and a no-trade baseline. Normalize BTC movement by measured volatility and time remaining as a candidate hypothesis, not an assumed improvement. Freeze choices before evaluating later windows.
4. **Stress the actual late-expiry failure case.** Replay a move back through the reference with seconds left, absent bids, unfilled/canceled close orders, stale feeds, duplicate callbacks, missing order lookups, and redemption after restart. Evaluate stop/no-stop/pre-expiry-exit variants net of costs; none is automatically superior.
5. **Keep accounting independent of the strategy loop.** Reconcile inventory and collateral, including buys, sells, fees, redemptions, split/merge if applicable, transfers/deposits, and unrealized inventory. Keep gross trading profit, net profit, fees, rebates, and capital additions separate. A balance-growth screenshot cannot distinguish them.
6. **Measure complete windows and actual risk.** Count all entries and missed fills; report net profit per window, confidence bounds, drawdown, worst loss, time exposed, and tail events. Do not treat multiple fills in one five-minute market as independent observations or use a winner-only trade sample.

These changes improve the ability to find out whether the strategy works. They do not create an economic edge by themselves.

## Search and access limitations

- Searches combined the exact repository and @igus_ai handle with BTC 5-minute, near-expiry/99-cent, loss, profitable, slippage, stops, oracle, and latency terms. Public Reddit discussions, GitHub issues/PRs, research repositories, and official fee documentation were inspected. Selected positive claims were sought deliberately to avoid only collecting losses.
- The exact September 5 @igus_ai post was not independently recovered in indexed text. Mirror searches surfaced other promotional Claude/Polymarket stories, which are not corroboration of this one and were excluded from the evidence register.
- Search indexes and direct pages sometimes differed; the slippage original returned 404, some Reddit dates were relative, and a public Polymarket profile timed out. The root researcher also reported a Gamma API 403. No logged-in workaround or private Discord/Telegram browsing was attempted.
- No complete account export or on-chain transaction set for the original claim was recovered; no original wallet ownership, initial bankroll, deposits, withdrawals, fees, rebates, or code-to-trade attribution was verified. The unrelated wallet links in discussions were not audited.
- Repository source is stronger evidence of how calculations are implemented than a screenshot, but neither inspected negative repository supplied the data required to independently reproduce its headline result. Their conclusions must remain attributed and limited to their tested samples.
- There is no basis here for a numerical estimate of community sentiment, trader profitability, or reversal probability. Cross-posts, promotional incentives, survivorship, deleted posts, unverified authorship, and selective screenshots all limit inference.
