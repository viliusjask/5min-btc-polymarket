# BTC five-minute bot: research and repair

Research and development on 2026-09-06. Upstream inspected at
`1c9aa81ec64cdf62895b155ed64dc8e88c013102`. The working copy is
`/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone`, branch
`feat/standalone-btc5m`. The original upstream history is preserved.

## Assessment

There is a plausible trading idea here: buy a likely winning binary contract late enough that
its outcome is becoming clearer, while the executable price still leaves room for a profitable
exit or payout. The published repository did not establish that edge, and its actual entry rule
was much simpler than the screenshots implied. It depended on a missing external trading
engine, had obsolete execution integration, and did not consume the advertised risk settings.
I found no obvious credential-exfiltration routine in the inspected first-party source. That
is narrower than certifying the repository and its dependencies safe. See the
[original-code assessment](research/upstream-assessment.md).

The screenshots and positive trader accounts are interesting leads, not a reproduced strategy
or complete account reconciliation. Detailed negative accounts are also selected reports;
several did not supply the data required to reproduce their headline results. The research
includes both sides and separates executable code, measured data, firsthand reports and
promotion. See the [scientific report](research/scientific-strategy.md) and
[human evidence register](research/trader-sentiment.md).

A stop changes the actual outcome distribution. The repair therefore evaluates executable
sales and their fees, partial fills and unsold remainder, rather than treating every losing
signal as a hold-to-resolution loss. A triggered close persists until the position is closed
or conclusively resolved; a stop trigger still cannot guarantee its original sale price.

## Strategy implemented

The experimental default compares the available contract price with a probability estimate
based on the BTC lead, time remaining and recent volatility. It models the contract's final
60-second average and checks less favorable volatility/reference scenarios. A USD 90 lead
with two minutes remaining is a different signal when one-minute volatility is USD 25 versus
USD 100. No academic coefficient has been transplanted from hourly research into a two-minute
forecast.

Entries require actual depth and room for fees, spread and model error. The initial value
window is 60–180 seconds remaining with asks of 60–92 cents; the modified momentum comparison
uses a USD 70 lead, 90–150 seconds remaining and 70–95-cent asks. Both decisions are recorded
on the same public observations, while only the configured mode can execute.

An information-confirmation step waits for the BTC source to reach the original candidate's
order-book timestamp, then requires that the same side still qualifies. This was motivated by
one public-data event where a striking apparent advantage disappeared after earlier BTC price
moves arrived late. It is an experiment, not a demonstrated increase in returns.

Initial exits are an eight-cent drop from actual entry, a 98-cent depth-weighted bid, or
20 seconds remaining. Current prices protect each sale attempt. The default allocation is
USD 100, with roughly USD 5 all-in per opening attempt, a persisted USD 10 loss/exposure
budget, at most 20 opening intents per UTC day, one active unresolved position and one opening
intent per round. Entry size never rounds up beyond its reservation to satisfy venue minimums.

The probability estimate concerns terminal payout. Because this strategy also exits early,
its valuation margin is **not** a forecast of stopped-policy profit. The model, thresholds,
confirmation rule and exit parameters remain hypotheses. Their motivation, alternatives and
opportunity costs are in [strategy decisions](research/strategy-decisions.md).

## Additional article: useful mechanisms, separate hypotheses

The full Daniro article and nine new screenshots were reviewed, with independent scientific and
public/community evidence research. Current public API checks support substantial venue-reported
profits at the five named example accounts, and about USD 40,352 at AdanaKebab. They do not prove
which private algorithm, outside hedge or model produced those profits. The article's claimed
10M-execution dataset was not publicly reproduced. The separate AdanaKebab screenshots were not
conflated with the August 19 article.

A public quote experiment compared selling a held token with buying its complement and releasing
a complete pair. Across 332 matched book pairs in two conditions, 642 five-share depth comparisons
produced identical calculated proceeds under current V2 cash fees, before merge/funding costs.
These were correlated quotes, not fills or returns. Sequential passive entries and inventory
adjustments remain plausible experiments; the comparison does not test their profitability.

I kept the two existing candidate modes and one executable mode, and documented a staged six-policy
research menu. No six-funded-portfolio engine, passive order/cancel system, automatic merge or LLM
loop was added. A faster aligned underlying feed is the next research priority, followed by a
model-based exit and then a controlled passive-inventory comparison. The reasons and opportunity
cost are in the [inventory strategy ruling](research/inventory-strategy-ruling.md). The separate
8-page research PDF includes primary papers, positive and negative operator accounts, account
verification, payoff derivations and explicit evidence limits.

## What would have the highest research value next

1. Measure actual execution with a fixed small configuration: intended versus filled entry,
   stop fill price, missed/partial exits, fees and fully reconciled cash. A separate paper
   platform is not a prerequisite for a bounded USD 100 trial.
2. Test whether the value filter improves later outcomes relative to the recorded momentum
   comparison and market-price/time buckets. Count independent five-minute rounds, rather
   than treating every quote or partial fill as a new trial.
3. If the recorded opportunities keep disappearing before the underlying feed catches up,
   compare a faster independent price source while retaining the actual settlement reference.
   The observed lag makes this more relevant than adding an LLM or rewriting Python in Rust.
4. Consider model-driven exits or passive orders only with evidence of the specific benefit.
   Passive orders need queue/fill-selection analysis; a tiny opposite-side hedge has no free
   payoff advantage over reducing exposure directly.

Keep this standalone. Alpha-Sentry's inspected equity-research workflow has a different time
horizon and lacks this venue's account, order, collateral and resolution machinery. A later
integration can consume a concise reconciled result if the strategy earns its place.

## Implementation and verification

The original checkout could not supply a self-contained trading path because its external engine
was missing. The repair now supplies a Python package with one validated configuration, the pinned
SDK adapter, a private SQLite execution journal and explicit native commands. It signs and persists
an exact order before a single submission. An ambiguous response retains its reservation and cannot
silently cause a duplicate BUY. Actual confirmed receipts determine cash, fees and owned shares.

The CLI provides anonymous observation/diagnosis, explicit execution, stop, readonly status/report,
and owner-locked reconciliation. Wallet journals live in a common Git-root namespace across worktrees;
anonymous observation journals stay separate. Legacy Docker/YAML launchers and duplicate scripts were
removed. The operating guide documents the tested WSL/Linux route and a small initial funded protocol.

One synthetic end-to-end regression starts with USD100, confirms five shares bought for USD3.50 plus
USD0.0735 fee, then time-exits two and three shares at 80c. Confirmed sale fees are USD0.0224 and
USD0.0336. It requires the report to show USD100.3705 cash, USD0.3705 net profit, zero remaining shares
and zero reserved cash. These are deliberate fixture amounts used to verify accounting, not a
backtest or realized performance claim.

The final 35-minute anonymous CLI run completed with exit0 and empty stderr: 23,675 observations,
2,989 snapshots and 5,978 paired raw screens. Neither strategy found an eligible entry. Six opening
boundaries were captured; four later official comparisons agreed within published precision. Five
final prices arrived. Seven calibration-time snapshots were recorded, but only one had a model
prediction and its final label had not arrived before shutdown. There is no return or calibration
accuracy claim from this run. See [capture evidence](research/cli-public-capture.md).

The dependency check covered 44 locked registry packages plus the build backend. It found and fixed
one development-test-runner advisory by updating pytest to 9.0.3; the repeated 45-query check had no
advisory matches. That is a dated vulnerability database result, not a malware certificate. The
[dependency audit](reviews/dependency-audit.md) records versions, hashes and scope.

Final source checkpoint 3f49231 passed all **412 tests in 28.79 seconds**, Ruff lint/format, mypy and
lock consistency. The native locked install, help, a 15-second public doctor and retrospective public
report read also passed. The original no-conflict capture report was byte-identical after the
reporting fix. CI is configured but has not run remotely.

Each implementation task was independently reviewed, followed by a fresh full-system review. That
review reproduced three integration failures: a newly observed official conflict could leave cached
entry authorization valid; asynchronous cleanup could exceed the shutdown budget; and the report
could hide an explicit conflict behind its retained price. One combined fix wave added 28 regressions
and corrected those paths. The final scoped independent review approved all three fixes with no introduced defect found.
The [full review](reviews/final-review.md), [fix report](reviews/final-fix-report.md) and
[approval](reviews/final-rereview.md) retain the evidence and exact limits.

## Remaining boundaries

No credentials were inspected, no account was provisioned, and no funded order, approval,
transfer or redemption was sent during development. Public data and read-only chain calls
were used; account/fill behavior was exercised with synthetic external fixtures through the
actual core, SDK adapter and SQLite journal.

Actual venue order acceptance, funded fills, allowance readiness and cash reconciliation have
not been established for the user's wallet. Dependency advisory checks are a dated scan, not
a malware certificate. The pinned SDK's private order-construction entry point requires review
before upgrading. Native WSL/Linux is the verified target; Docker support was removed.

A dedicated wallet and persistent journal remain necessary. The public positions index is not
proof of exhaustive on-chain absence of unrelated holdings. External trading, transfers or
manual claims can create discrepancies; diagnosis must resolve them before further entries.
Resolved winners remain claimable holdings, separate from spendable cash; claiming is manual.
Poor depth, stale metadata, minimum order size or ambiguous execution can leave inventory open.

All autonomous design rulings and their costs are recorded in the
[decision register](reviews/decision-register.md). The complete source-file change index is
provided with the handoff, alongside the operating guide and review reports.
