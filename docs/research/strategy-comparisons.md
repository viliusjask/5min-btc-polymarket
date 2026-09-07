# Using the strategy research page

Open **Experiments → Strategy research**, choose the original parameter study or order-flow
study, then select a strategy and comparison. This reads the existing 84 and 17 registered
variants. It produces comparisons immediately from their saved history; it does not start a
new wallet or change a trading rule. The six original portfolios remain in Paper.

The first paragraph explains the selected result in dollars. The page answers five questions:

| Question | Evidence to inspect | What a result can suggest |
| --- | --- | --- |
| Does it usually earn money, or occasionally earn a lot? | Per-market profit bars, median, win rate, average win/loss, profit factor | Distinguish frequent small gains from rare large payoffs. Neither profile is automatically better. |
| Does the profit depend on a handful of wins? | Remove the largest one/three wins; best and worst market times | Identify rounds that deserve reconstruction, and whether aggregate profit survives their removal. |
| Could ordinary trading costs consume it? | Before/after actual fees; extra 0.25/0.5/1¢ per executed share | Measure how sensitive the recorded result is to extra cost while holding its fills fixed. |
| Under which conditions does it work? | Fixed price, seconds-remaining, first-outcome and executed-exit groups | Generate a specific hypothesis to test on later data; every group shows its sample count. |
| Does it outperform another idea and repeat over time? | Same-market comparison, overlap, hourly contributions, 30/60-minute resampling ranges | Separate differences in activity from differences in profit, and inspect dependence on the sampled time periods. |

For reversal/continuation and absorption/flow-continuation, the initial comparison uses the
opposite signal with the same lookback and threshold when available. You can select any
registered comparator in the same phase. Displayed parameter differences are shown underneath;
matching that summary is not a substitute for checking the full registered definitions.

## Exact accounting and denominators

One result means one five-minute BTC market, combining all its fills and conversions. It is
complete only when no remaining position or unresolved order remains in the existing ledger's
`portfolio_results()` accounting. Only markets that have ended by both selected journals'
recorded time are considered. Held positions do not become zero-profit observations.

The individual distribution uses completed markets that used capital. Its net profit is the
existing ledger's realized net profit, including recorded fees and settlement/merge cash.
Win rate is positive markets / completed capital-used markets, with flat results included in
the denominator. Profit factor is total winning dollars / absolute losing dollars; it is
undefined when there are no losses. Median is the middle result, unlike the arithmetic mean.
Removal checks subtract only positive winning rounds, up to the requested count; removing
every observation is undefined. They do not replay how a changed balance would affect later orders.

Extra cost is `sum(all bought and sold filled shares) × added dollars per share`. It is charged
in addition to actual fees, once for each filled side. Splits/merges are not traded shares.
This is an algebraic sensitivity check: it does not change fills, price bounds, cash availability,
queue priority, exits or subsequent loss limits, and it does not estimate gas. The break-even
extra cost is positive net profit / executed shares, not an estimate of plausible venue costs.

Entry groups use the first **filled** BUY price and seconds remaining at that fill. Price bands
are [0,.1), [.1,.3), [.3,.7), [.7,.9), [.9,1]; time bands use 60/90/120/150/180-second boundaries.
An inventory strategy's two sides are not averaged into a fictional entry. Split-funded rounds
use Unknown / conversion. Executed exit reason is known only afterwards: filtering profitable
exit categories is not an implementable entry signal.

Same-market comparisons intersect exact market identifiers and include observed flat rounds as
zero. Missing observations, incomplete rounds and filtered flags are excluded from **both** sides;
excluded counts are visible. Profit difference is selected minus comparator on that intersection.
Overlap is markets where both used capital / markets where either used capital. Correlation
measures how their market-level profits moved together when at least one traded; it is undefined
with fewer than three such markets or zero variance. This is not a combined portfolio simulation.

All recorded includes completed flagged results. Unflagged only removes flagged observations;
it does not reconstruct a world in which those earlier trades never affected cash, inventory or
loss limits. Missingness may depend on market conditions, so that subset may be biased. Looking
at both is useful; neither proves live execution quality.

## Time-period sensitivity and scientific basis

Hourly contributions use the market's opening hour in UTC. The table shows excluded capital-used
rounds and observed slots out of 12, so a partial hour is not presented as a full trading hour.

The descriptive resampling calculation uses nonoverlapping, UTC-aligned 30-minute and 60-minute
blocks. Each block requires every constituent five-minute slot to be observed and complete;
filtering one flagged slot removes the whole block from that calculation. We do not concatenate
across holes. Each replicate draws the available block totals with replacement, preserving the
number of blocks, and divides by their total market-slot count. The displayed range is the
2.5th–97.5th percentiles from 2,000 deterministic draws. Six complete blocks are a minimum display
threshold, not a scientific claim of adequate sample size. All-zero blocks report no variation.
The paired comparison resamples **within-market differences**, keeping the strategies paired.

Block resampling keeps neighboring observations together, unlike resampling each trade as
independent. The official [arch time-series bootstrap documentation](https://arch.readthedocs.io/en/stable/bootstrap/timeseries-bootstraps.html)
describes stationary, circular and moving-block variants and their boundary differences. Our
smaller implementation uses fixed nonoverlapping blocks, not those library algorithms. It adds
no dependency. We display both block lengths rather than choosing whichever looks strongest.

Interpret these ranges as sensitivity to the empirical sample under a simplifying assumption
that its blocks represent future conditions. Dependence longer than the block, changing market
conditions, arbitrary UTC alignment, missing-block selection and very few blocks limit that
interpretation. A range excluding zero is not a probability of future profit or a promotion gate.

Trying many settings on the same history increases the chance of selecting a lucky result.
[Bailey et al., The Probability of Backtest Overfitting (2015)](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
explains this multiple-testing problem and presents a specific cross-validation method. The
page shows the registered trial count but does **not** implement that paper's probability of
overfitting, adjust these ranges for selection, or make an annualized performance claim.
Existing registered later-data tests remain unchanged; repeated inspection or new grouping
choices are further exploration, not new independent evidence.

## First concrete finding

On the September 7 check through roughly 16:25 UTC, Reversal · 60s · z≥.5 had 29 completed
capital-used markets: **+$193.61**, a **−$2.00 median**, and 10 wins / 19 losses. Removing its
three largest winners left **−$34.72**. Entries below 10¢ contributed **+$175.51** across six
markets; all six carried execution-data flags. The unflagged subset was four markets totaling
**−$2.52**. These values will change as the continuous study advances.

This supports a concrete research question: can the cheap-contract reversal payoff repeat
with verified execution on later markets? It does not support treating the 29-round aggregate
as an established edge or automatically excluding cheap contracts. Inspect the identified
winning and losing rounds, then use an explicitly registered later comparison for any rule change.

## Reader and verification

The dashboard validates study/phase/variant membership and journal identity, opens paper SQLite
journals read-only, and reuses `Ledger.portfolio_results()` for cash accounting. Each journal is
read in a single transaction; two journals are separate snapshots, cropped to their common time
window. Older rows can update when settlement completes. A bounded eight-selection, 20-second
cache limits repeated calculations. The endpoint never opens the Real account or changes studies.

Tests cover dollar conservation, undefined statistics, outlier and cost arithmetic, excluded
rounds, group boundaries, paired comparisons, missing-block handling, repeatable resampling,
delayed settlement, read-only accounting, phase identity, query/path validation and API failures.
Desktop/mobile browser checks exercise both studies, every grouping, automatic/manual comparisons,
cohort switching, downloads and the original portfolio view without Real-account requests.
