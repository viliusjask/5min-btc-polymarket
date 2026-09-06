Research date: 6 September 2026. This report concerns an experimental BTC five-minute Up/Down strategy with entries near 120 seconds remaining, expensive favourite contracts, and early exits. It is a strategy research specification, not a finding of profitability. No strategy was backtested and no live orders were placed in this research subtask.

**Recommendation: replace the fixed $70–$100 BTC-move trigger with a model of the actual settlement quantity, scaled by recent volatility, and trade only a sufficiently large discrepancy between that model and executable contract prices. Preserve and measure the exit policy.** The model should initially be a transparent, explicitly uncalibrated candidate. Momentum and order-flow features deserve a separate incremental test; the literature does not establish that a recent BTC move continues over the next 120 seconds on this venue. The strongest potential improvement is finding contracts priced below a conditional valuation, rather than buying favourites simply because their winning probability is high.

The immediate contract-definition finding changes the mathematics. The Rules on a 5 September market specify a Chainlink time-weighted average and link to `btc-usd-twap-60s-streams`; an older 8 May market specifies the endpoint BTC/USD price. The newer page's generated FAQ still describes an endpoint comparison. Store and use each contract's actual rules, settlement feed, exact opening reference value, and averaging convention. The mathematical proposal below is conditional on a verified ending 60-second arithmetic average; the prose and URL alone are insufficient to establish every sampling convention or whether the opening reference is a spot or averaged observation. [Polymarket, 5 September 2026 contract](https://polymarket.com/event/btc-updown-5m-1788631200), [Polymarket, 8 May 2026 contract](https://polymarket.com/event/btc-updown-5m-1778257200).

Evidence and its limits are as follows. A finding about a different venue or horizon supplies a hypothesis, not a coefficient to copy into this bot.

| Question | Primary evidence | What it supports here |
|---|---|---|
| Are expensive favourites systematically overpriced? | Page and Clemen, published 1 May 2013, find that prediction-market calibration worsens with distance to expiration in the direction of favourite–longshot bias. In its conventional meaning, favourites are underpriced and longshots overpriced. [Economic Journal / author's institution](https://scholars.duke.edu/publication/765630) | Do not reverse the direction of the named bias. It could support selective favourite buying, but cannot establish an edge in modern two-minute crypto trading. |
| Is there recent Polymarket-specific calibration evidence? | Le, 23 February 2026 preprint, studies Kalshi and Polymarket and reports substantial domain/horizon variation. Its Polymarket timestamps have about three hours of noise; it expressly excludes the shortest two horizon bins from cross-platform conclusions. Primary price filtering is 5–95 cents. [Paper](https://arxiv.org/html/2602.19520v1) | No defensible two-minute calibration correction, and especially none for 96–99-cent contracts, follows from this study. Its large trade count does not repair timestamp uncertainty. |
| Can crypto prediction prices diverge from option benchmarks? | A June 2026 preprint studies three 2023 BTC threshold markets at hourly observations. Its Binance panel reports a 6.3-percentage-point mean price wedge, but the 16-trade proxy backtest's pooled net-alpha confidence interval includes zero. The author distinguishes risk-neutral option values from real-world probabilities. [Paper](https://arxiv.org/html/2606.19517v1) | External probability benchmarks are a plausible research direction. This small, old, differently settled sample does not validate five-minute arbitrage or a blanket longshot/favourite rule. |
| Does BTC have intraday momentum? | Shen, Urquhart and Wang, May 2022, show that a volume-defined first half-hour predicts a last half-hour. [Financial Review](https://onlinelibrary.wiley.com/doi/10.1111/fire.12290) | Evidence for session effects, not an estimate of continuation from the third to fifth minute of an arbitrary round. |
| Momentum or reversal? | Wen et al., November 2022, examine March 2013–May 2020 BTC data, finding both intraday patterns and variation with jumps, announcements, liquidity and COVID. Their analysis includes half-hour/hour constructions. [Paper](https://www.sciencedirect.com/science/article/abs/pii/S1062940822000833) | Make the sign of any momentum adjustment empirical and allow it to fail across market conditions. A large move is not automatically continuation evidence. |
| What about larger moves reversing? | De Nicola, 2021, finds negative first-order return correlation at one-, two- and four-hour horizons, with stronger proportional reversals after larger moves. [Ledger](https://ledger.pitt.edu/ojs/ledger/article/view/213) | A reversal competitor is reasonable, but applying the result to 120 seconds would be an untested transfer. |
| Are there studies closer to minute horizons? | Barucci, Giuffra Moncayo and Marazzina, 16 September 2023, examine 2019–2020 data at 1, 5, 10 minutes and longer frequencies, finding differences between USD and crypto/stablecoin markets. [Digital Finance](https://link.springer.com/article/10.1007/s42521-023-00095-9) | Venue, quote currency and horizon matter. Distinguish regressions explaining current order flow from regressions predicting future returns; they are not interchangeable. |
| Does order-flow imbalance help? | Cont, Kukanov and Stoikov, 2014, study 50 US stocks and find a strong contemporaneous relationship between price changes, order-flow imbalance and depth. Silantyev, 2019, finds trade-flow imbalance explains contemporaneous BitMEX changes better than aggregate order-flow imbalance. [Cont et al.](https://arxiv.org/abs/1011.6402), [Silantyev](https://link.springer.com/article/10.1007/s42521-019-00007-w) | Useful candidate features and execution diagnostics. Contemporaneous explanation is not advance prediction. |
| Can book imbalance actually predict a next move? | Gould and Bonart, 2016, report predictive information about the next mid-price move for ten Nasdaq stocks, with results depending on tick size. [Paper](https://arxiv.org/abs/1512.03492) | Supports testing a lagged book feature against a precisely defined future target. It does not establish a 120-second BTC signal or profitable Polymarket fills. |
| Do recent sophisticated crypto models survive costs? | Pindza, 11 June 2026, studies minute observations from August 2025–February 2026 on Binance. The paper reports weak predictive information, substantial nonlinear-model overfitting under leakage controls, and no tested strategy surviving its retail-fee assumptions. [Frontiers](https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2026.1811716/full) | A useful negative comparator, not proof that selective Polymarket trading cannot work. Its perpetual/spot payoff, turnover, feature proxies and fees differ from this task. |
| Can stops improve returns? | Kaminski and Lo, March 2014, show stop-rule value depends on the return process. Their specified rules can add value under momentum and hurt under random-walk assumptions. Their empirical study concerns index futures at much longer horizons. [Publisher](https://www.sciencedirect.com/science/article/pii/S138641811300030X), [author's publication page](https://alo.mit.edu/publications/page/13/) | Evaluate the bot's actual exits. The result neither grants stops an automatic edge nor licenses treating every stopped trade as a full settlement loss. |

**A transparent settlement-probability candidate.** A digital contract pays one unit if a specified condition is true and zero otherwise. Its expected terminal payoff under a real-world probability model is that probability. This is different from a risk-neutral option price, which incorporates pricing assumptions and risk compensation. An arithmetic Brownian approximation means future dollar price changes have a local drift plus correlated normally distributed shocks. It is simple enough to audit, although it omits BTC jumps and changing volatility. Short-time Bachelier approximations have a mathematical literature; that does not establish calibration for this product. [Schachermayer and Teichmann, 2007 working paper](https://arxiv.org/abs/0711.1272).

Let the current instant be `t`, settlement time `T`, and `τ = T − t` in seconds. Let `S_t` be a contemporaneous estimate of the raw underlying price represented by the settlement feed; `K` is the contract's verified opening reference. Define local future dynamics

`S_(t+u) = S_t + μu + σW_u`,

where `μ` is dollars per second, `σ` is dollars per square-root second, and Brownian shocks have covariance `Cov(W_u,W_v)=min(u,v)`. Start with `μ=0`. Extrapolating the last $90 move as another $60 of expected movement would insert a strong momentum assumption without evidence.

For an endpoint contract only,

`P(Up | information at t) = Φ((S_t − K + μτ)/(σ√τ))`,

where `Φ` is the normal cumulative probability function. This formula must not be used unchanged for an average-price contract.

For a terminal arithmetic average of width `w` seconds,

`A_T = (1/w) ∫[T−w,T] S_u du`.

Set `b=τ`, `a=max(0,τ−w)`, `L=b−a`, and

`I_known = ∫[T−w,min(t,T)] S_u du`,

with `I_known=0` when the final averaging interval has not begun. Conditioning on all observations already available gives

`M = E[A_T | information at t] = [I_known + L S_t + μ(b²−a²)/2] / w`,

`V = Var(A_T | information at t) = σ²[aL² + L³/3] / w²`,

`p_Up = Φ((M−K)/√V)`.

These are derived from integrating `min(u,v)` over the future portion of the averaging window. The future price samples are strongly correlated. Treating 60 one-second prices as 60 independent future prices would produce an unjustifiably small variance.

The useful special cases for `w=60` are

| Time remaining | Conditional variance of ending average |
|---|---|
| `τ ≥ 60` | `σ²(τ−40)` |
| `0 < τ < 60` | `σ²τ³/(3×60²)` |

In the last minute the known part of the average matters directly. For example, with 30 seconds left, a known first-half average `$60 above K` and current spot `$30 below K` gives a zero-drift predicted final average `$15 above K`: `(30×60 + 30×(−30))/60 = 15`. A bot following only current spot direction could buy the wrong side of its own model.

For unequal sampling weights or overlapping windows, use the discrete form. Represent the difference being settled as `D = Σ_i c_i S_(t_i)`, with positive ending-average weights and negative opening-average weights. Observed values contribute fixed terms. For future times `u_i=t_i−t>0`,

`E[D | information] = Σ_known c_i S_(t_i) + Σ_future c_i(S_t+μu_i)`,

`Var(D | information) = σ² Σ_future_i Σ_future_j c_i c_j min(u_i,u_j)`.

An equivalent and convenient implementation uses independent future increments. At interval `j`, let `H_j` be the sum of all future price weights at or after that increment. Then `Var(D)=Σ_j σ_j² H_j² Δt_j`. Overlapping opening/ending weights cancel where appropriate. If the opening reference has already been observed exactly, it is a conditioned constant: do not add an independent opening-window variance. Five-minute-separated 60-second opening/ending windows do not overlap, but current and future rolling averages may.

The exact averaging feed may use discrete times, preprocessing, or a representative reported value different from the continuous arithmetic model. Match its documented weights and timestamps. A current rolling TWAP is not a substitute for `S_t`; it contains older observations. Estimating volatility from a smoothed TWAP and feeding it into this raw-price formula can double-count smoothing and overstate confidence. If only the averaged feed is available, fit a model directly to its future settlement differences, or explicitly model the hidden instantaneous price. Do not silently substitute a Binance price for Chainlink; estimate the simultaneous basis, meaning their price difference, and retain uncertainty about it. Normal models assign zero probability to an exact tie, while rounded feed values can tie. Preserve the contract's `Up`-on-equality rule and handle a fully observed final average directly rather than dividing by zero variance or manufacturing 100% certainty from missing observations.

As an illustration, suppose the raw price is $90 above the known reference with 120 seconds left and zero drift. These are model calculations, not observed BTC probabilities:

| Standard deviation of a one-minute raw-price change | Endpoint probability | Ending 60-second-average probability |
|---|---:|---:|
| $25 | 99.45% | 99.91% |
| $50 | 89.85% | 94.05% |
| $100 | 73.77% | 78.21% |

The same $90 signal can therefore correspond to materially different valuations. At a 90-cent ask, it may indicate a candidate discrepancy in one volatility state and none in another. This is why a fixed dollar trigger throws away useful information. The calculation alone is not evidence that the model is more accurate than the order book.

**Volatility, uncertainty and actual strategy decisions.** Estimate raw-price variation on observations aligned by event time, using only information received before the decision. A practical initial hypothesis is five-second returns with both 5-minute and 30-minute rolling estimates, retaining jumps, with 30 minutes of clean warm-up or equivalent historical observations. Use `σ² = Σ(ΔS)² / elapsed_seconds` with consistent units as a simple local variance-rate estimate; do not apply an annualized volatility as though it were a per-second number. Compare the scales to expose unstable conditions. These horizons are proposed defaults, not values established as optimal by a paper.

Very-high-frequency variance estimates are affected by bid/ask bounce, price discreteness and observation noise. Aït-Sahalia, Mykland and Zhang show that naïvely sampling more frequently can worsen an estimator when noise is ignored, while modelling the noise can make more data useful. Sampling five seconds is a modest initial design choice, not a universal answer. [Review of Financial Studies, 2005](https://www.princeton.edu/~yacine/sampling.pdf).

Evaluate several predeclared scenarios: both volatility estimates, a 25% higher-volatility stress, and adverse basis/reference shifts based on measured feed disagreement. For each side, take the minimum probability across its scenarios, and label it `scenario_probability_floor`. This is a sensitivity floor, not a statistical confidence bound. The two side-specific floors need not sum to one because they may arise under different worst-case scenarios. A Student-t predictive residual model or block-resampled empirical residual paths is a later competitor; adding a Student-t distribution without fitting scale and tails does not magically make a forecast conservative at every distance.

For `Q` shares, let `A(Q)` be the total cost of walking the actual ask levels for that quantity, and `F_buy(Q)` its fee. The terminal-value candidate filter is

`terminal_surplus_per_share = p_floor − [A(Q)+F_buy(Q)]/Q − additional_cost_allowance`.

Use both sides' real books and choose the best positive surplus subject to the risk allocation. An illustrative initial required margin is two cents per share after explicit entry fees and estimated additional costs. It is an experimental margin, not an estimated confidence interval or an empirically optimal threshold. Buying near 99 cents will rarely pass a meaningful uncertainty allowance; that is a result of the valuation comparison, not evidence of favourite overpricing. Do not increase the accepted ask merely to force a trade when the margin disappears.

This terminal surplus is only a screening proxy for a strategy with early exits. The actual quantity to maximize is

`policy_surplus(X,Q) = E[net cash received from the complete exit policy | state X, actual fill] − entry cash paid`.

Here the exit policy includes take-profit, stop, partial sales, expired orders, and any remaining settlement payment. Changing these rules changes that expectation. A bot that reports terminal surplus as expected stopped-trade profit misstates what it has modelled. In an initial small experiment, report the terminal proxy and measured policy outcomes separately; estimating a richer future order-book process is optional research work, not a prerequisite for collecting a small amount of live execution evidence.

Current published Polymarket documentation gives `fee = shares × feeRate × p × (1−p)` and lists a crypto taker parameter of `0.07`; makers have no fee. Read each market's actual parameters and reconcile actual fills, since schedules change. [Polymarket fee documentation, retrieved 6 September 2026](https://docs.polymarket.com/trading/fees).

Using that fee schedule solely for an illustrative full-fill calculation, buying at `.90` and selling at `.98` nets `.072328` per share; buying at `.90` and stopping at an actual sale price of `.75` loses `.169425`. If those were the average realized win and loss, the break-even win rate would be `loss/(win+loss) = 70.08%`. It would not be 90%. In practice use volume-weighted fills and actual fees; gaps and unfilled stops can produce a much larger average loss. This calculation evaluates an early-exit policy rather than replacing it with a settlement-only strategy.

A useful exit candidate compares the updated expected future payoff to the executable exit. When net bid proceeds exceed the updated central terminal valuation, selling has positive estimated value relative to holding to settlement. This can be either a profitable exit or a loss. Entry cost is already spent and does not determine that comparison. A hard loss limit separately controls risk when the model may be wrong. Preserve the user's intended hard-stop policy as a baseline and test changes independently; the literature supplies no defensible universal 10%, 15%, or fixed-cent stop for this product. Avoid repeated exit/re-entry churn until its added value is measured.

An opposite-outcome purchase is not inherently useless, but it should have a stated economic purpose. With `qU` Up shares and `qD` Down shares, terminal payout is `qD + (qU−qD)Y`, where `Y` is the Up outcome. The paired part locks payout; the remainder is directional exposure. Its value depends on both purchase prices, fees and timing. A fixed tiny hedge can consume scarce capital without improving expected return. For reducing exposure, compare a direct sale's net bid with buying the complement and, where supported, merging/redeeming the matched pair. The economically preferable route depends on live depth and total costs. Do not call two non-atomic purchases a guaranteed arbitrage.

Adverse selection means fills preferentially arrive when information has moved against the resting quote. Maker fees of zero therefore do not make a maker strategy free. Record the contract bid/mid and underlying feed after each fill at 1, 5 and 15 seconds, plus cancellation attempts and quote age. This post-fill price change, often called a markout, helps distinguish an information edge from being filled only on bad states. Evaluate filled orders separately from all proposed orders. A backtest that fills every touched limit price at full size misses this selection.

**Candidate comparison for the experiment.** The following are separate hypotheses; they should not all become interacting knobs in the initial bot.

| Candidate | Concrete rule | Proposed falsifier |
|---|---|---|
| Original baseline | Near 120 seconds remaining, original dollar move and favourite-price band, same measured exits. | Net trade outcomes fail to cover costs; stops systematically fill materially worse than assumed. |
| Recommended probability candidate | Same decision time, settlement-aware valuation and volatility scaling, actual ask/depth/fees, predeclared scenario margin; no drift boost initially. | Forecast scores do not improve over the market; apparent excess probability vanishes on later rounds or under measured basis uncertainty; selected actual fills have nonpositive net policy outcomes. |
| Momentum addition | Add lagged 15/60-second return and signed trade-flow features to a regularized probability model after controlling for settlement distance, volatility, time and current contract price. | No incremental future predictive improvement on held-out chronological data; coefficient changes sign or the benefit disappears after fill delay. |
| Reversal addition | Same features allowed to have a negative coefficient, especially following unusually large volatility-scaled shocks. | Same tests; do not infer two-minute reversal from an hourly paper. |
| Earlier, cheaper directional contracts | Separately test 90–180 seconds remaining and a lower price band, for example `.60–.90`, using the same valuation/cost hurdle. | Higher upside comes with enough extra errors, spreads or stop losses that net return per allocated dollar falls. These ranges are hypotheses. |
| Passive value orders | Place a short-lived bid below estimated value with a price cap and cancel on new adverse information. | Negative post-fill markouts or low fill rate remove the fee/spread benefit. |

The original favourite strategy may have plenty of potential if it identifies underpriced favourites and its stops preserve that advantage. Increasing payout potential by lowering the entry price is not, by itself, increasing expected ROI. Increasing frequency also increases the number of opportunities to pay fees. Prefer measured net value per trade and return per allocated dollar over win rate or gross daily profit projections.

For a fitted model, an interpretable example is

`logit(p) = α + β logit(p_structural) + γ logit(p_market) + θ1 r15_scaled + θ2 r60_scaled + θ3 flow + θ4 spread`,

where `logit(p)=log(p/(1−p))`, structural probability is the settlement model, and market probability is a clearly defined contemporaneous price benchmark. The coefficients must be estimated on prior data with regularization, meaning a penalty against unjustifiably large coefficients. This is a later model candidate, not a suggestion to set all coefficients positive by intuition. Compare the structural model alone, market alone, and combination; if the combination gives zero weight to structural or momentum terms, accept that result. Limit feature proliferation because each additional choice increases the opportunity to fit noise.

**Testing that can change the decision.** Store one immutable decision record per round for calibration at the designated time, plus event-level records needed for actual orders and exits. Necessary fields are the contract identifier and rule version, exact strike/reference, settlement window and outcome, event and receipt timestamps, raw and averaged reference prices, volatility inputs, predicted probabilities/scenarios, both books, requested and filled quantity, fees, lifecycle events, and realized cash flows. Preserve rejected/no-trade candidates as well as trades. Repeated ticks in one market do not provide independent terminal outcomes.

Use chronological development, validation and untouched evaluation periods. Never put observations from the same round into both train and test. If windows or future labels overlap, remove the overlapping labels from training at the boundary. Choose the purge from the actual look-ahead horizon; a fixed 60-minute gap is not a universal requirement. Feature normalization, thresholds, calibration and model selection must use training data only. Reassessing the held-out sample repeatedly turns it into training data.

Report calibration, meaning whether probabilities agree with outcome frequencies, by price/time/volatility bins. Report Brier score `mean((p−Y)²)` and log loss, which penalizes highly confident wrong predictions strongly, against the simultaneous market benchmark and a simple structural benchmark. They assess probability forecasts separately from execution. Proper scoring rules reward accurate probabilities rather than overconfident storytelling. [Gneiting and Raftery, March 2007](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf).

Report net mean cash profit, dollar-weighted return, average win and loss, tail losses, maximum drawdown, actual stop slippage, fill rate, unfilled/partial orders, holding time, and capital still locked pending redemption. Compare proposed versus actual executed prices. Use day/block resampling for uncertainty rather than treating thousands of correlated ticks as independent bets. Round-level clustering removes within-round duplication; day blocks also account for common volatility episodes. With few days, report that uncertainty is poorly estimated rather than printing a precise-looking interval.

Keep a record of every strategy variant tried. A winning choice selected from many thresholds needs a new evaluation period or a selection-aware statistical correction; standard-looking backtests can become unreliable through selection. [Bailey et al., 2017](https://escholarship.org/uc/item/4w1110bb). If checking performance after every trade and stopping when it looks significant, conventional fixed-sample intervals are inappropriate for that rule; time-uniform confidence sequences are a principled alternative when their assumptions hold. They do not automatically remove market dependence or changing conditions. [Howard et al., 2021 publication / preprint](https://arxiv.org/abs/1810.08240).

A $100 bounded live experiment can rationally be cheaper than constructing a sophisticated fill simulator. It can establish that the bot finds the right contract, computes an auditable decision, submits correctly, exits as designed, accounts for balances, and observes real slippage. It cannot quickly establish a small durable probability edge. For scale only, a 95%-probability bin with 100 independent outcomes has a normal-approximation standard error of about 2.18 percentage points. Under ideal independent assumptions, obtaining a roughly ±2-point 95% interval would require about 456 observations near 95% probability, and about 865 near 90%; market dependence and selection increase the evidentiary burden. These are calibration illustrations, not minimum required trade counts or a demand to postpone the user's experiment.

Authoritative raw data can help fit volatility and prospective momentum without paying for trades. Binance's official public archive contains trades and klines, with spot timestamps from January 2025 onward in microseconds. It can test Binance price patterns, not substitute for Polymarket books or the Chainlink settlement outcome. [Official Binance public-data repository](https://github.com/binance/binance-public-data). Historical market trades alone generally do not reconstruct available depth, queue position or an executable stop; live quote/order records supply information those records omit.

The principal scientific unknowns remain the exact settlement-feed construction, the candidate model's probability calibration under current conditions, and the complete exit policy's net value conditional on actual fills. The next useful evidence is a comparison of those quantities on the intended contracts. The recommendation is to implement that comparison transparently alongside the repaired bot, with every default above identified as an experiment hypothesis and no advertised expected ROI until observed evidence supports it.
