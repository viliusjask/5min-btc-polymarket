# What the Polymarket experiments actually show

Audit dated September 8, 2026. Results frozen at **07:17 UTC / 10:17 Kyiv**: original six portfolios at 07:17:22.982, directional study at 07:17:10.192 (cursor 93533), order-flow study at 07:17:17.338 (cursor 93542). Later observations in this report concern collector health, not additional trading returns.

**There is a modest Momentum research lead, but no demonstrated profitable strategy yet. The first Paper tab has become a poor main view for answering the research question.** It still preserves useful financial and execution history.

This audit covers all **84 directional variants, 17 order-flow variants and six original portfolios**, plus the probability forecast comparison and simultaneous/cross-duration opportunity scanner. Net results already deduct recorded fees. All portfolios began with $100; experiment trade budgets were $5. Variants are separate simulations sharing market data and often the exact same trades. Their profits must not be added as if they were independent, simultaneously executable investments.

## Reading the evidence

“Unflagged” means a completed, traded round without recorded data/execution uncertainty. It does **not** certify perfect simulation or a real venue fill. A flagged round remains in the full financial history; it is not automatically a fake trade. Removing flagged rounds can itself bias the result if interruptions happen during volatile periods.

Round counts below count five-minute markets with completed exposure, not quote attempts or individual partial fills. An extra-cost check deducts the stated amount for every bought or sold share, in addition to recorded fees, while keeping fills fixed. It does not simulate worse latency or a different order queue. Removing largest winners also keeps the remaining recorded path fixed rather than recalculating risk limits.

## The shortlist and the apparent winners

| Experiment | All recorded net | Unflagged completed net / rounds | Assessment |
|---|---:|---:|---|
| Momentum: $20 opening lead, 90–150 seconds left | **−$1.65** | **+$3.42 / 9** | Best candidate for a fresh, fixed test; weak evidence so far |
| Momentum normalized for expected volatility: 0.5 threshold | −$0.26 | +$2.73 / 6 | Related comparator; five rounds overlap the candidate above |
| Reversal: 60 seconds, threshold 1 | **+$147.59** | **−$11.18 / 8** | Large-win hypothesis; highly concentrated and affected by gaps |
| Reversal: 60 seconds, threshold 0.5 | +$115.66 | −$2.52 / 4 | Same issue; shares the two largest wins with the row above |
| Recent continuation: 60 seconds, threshold 0.5 | +$24.96 | −$3.55 / 6 | Removing its largest win makes the full result −$20.61 |
| Value held to settlement | +$7.69 | +$7.69 / **1** | One successful event, insufficient replication |
| Absorption: 30 seconds, threshold 0.3 / 0.6 | −$6.96 / −$7.17 | +$2.72 / **2 each** | Both positive subtotals are the exact same two markets |
| Pressure-filtered pairs: threshold 0.5 | +$0.04 | No unflagged traded rounds | Tiny margin; an extra 0.5¢/share makes it −$0.21 |
| Split collateral, then sell both outcomes | −$5.79 | −$3.13 / 20 | Most useful negative evidence in the order-flow suite |

### Why lower-threshold Momentum earns another test

The exact candidate is `momentum-20-90-150` (`5a4f77ddfd7ff6566998`). It follows the side favored by BTC's distance from the market opening reference, requires at least a $20 lead, enters with 90–150 seconds remaining at 70–95¢, and uses the existing 8¢ stop, 98¢ target and 20-second time exit. This is the original opening-reference experiment, **not** the revised recent-move Momentum implementation now used by the first Paper tab.

Its nine unflagged traded markets produce seven wins and two losses, +$3.419748 after $0.558315 in fees. Median result is +$0.314475. Removing the biggest win leaves +$1.991526; removing the biggest three leaves +$0.529502. Adding 1¢ of cost per traded share leaves +$2.464449. That is more encouraging than a result resting on one lucky payout.

Neighboring $10/$30/$40 lead settings in the same entry window also have small positive unflagged subtotals, but only 3/5/4 rounds. They overlap the candidate and all have negative full-history results. The normalized 0.5 setting is similarly interesting but shares five of its six unflagged rounds with the $20 candidate. Neither is independent confirmation.

The important objections: **39 of 48 completed candidate rounds are flagged**, its full result is −$1.652032, and all nine unflagged entries occurred on September 7 between 07:55 and 14:10 UTC. There is no later independent performance evidence. This merits a small, predeclared follow-up comparison; it does not merit funded promotion or declaring the $20 threshold optimal.

### Why the reversal profits are not simply dismissed

The two leading reversal settings share +$108.101070 and +$87.046326 wins. A previous detailed reconstruction verified the four entry/exit endpoint prices, displayed depth, fees and accounting, with nearby public trades supporting those prices. The audit does not establish that these were impossible fills.

However, gaps occurred while inventory was held, so the intervening decisions and exits cannot be fully reconstructed. The strategy could have behaved differently with continuous inputs. Both leading reversal variants have roughly 21–22% winning traded rounds and negative median outcomes. Removing their three biggest wins makes their respective full totals **−$118.35 and −$112.67**.

An occasional enormous win can be a legitimate strategy feature. Here, the combination of a short sample, shared exceptional events, missing paths and selection among many variants leaves that hypothesis unverified. Keep reversal as a secondary research hypothesis; do not treat its headline return as the strongest established result.

### What the other techniques taught us

- **Absorption** looks for strong traded flow without much accompanying BTC movement. All four current settings lose approximately $6.89–$7.18. The two positive unflagged 30-second settings both consist of the same +$3.052608 winner and −$0.332648 loser. Removing that winner makes both negative.
- **Flow continuation** follows the direction of traded flow. All four tested settings lose $5.70–$6.39, with only 1–3 unflagged traded rounds each. These settings have not earned priority.
- **Pressure filters** reduce some pairing/confirmation activity and losses, but less exposure can explain that difference. The +$0.042255 pair result comes from five flagged rounds and becomes negative with very small additional costs. It supports studying whether the filter avoids bad inventory, not claiming profit.
- **Split then sell both sides** has substantially more execution evidence: 86 completed markets, 20 unflagged, and 122 filled maker sale orders out of 687 attempts. Its unflagged win rate is 70%, but the average win is about $0.17 and the average loss about $0.91. It loses $3.125245 unflagged and still loses $2.95 before fees. The present policy's occasional larger losses overwhelm its frequent small wins.
- **Value, fast feeds, buffers and alternate exits** mostly have no unflagged traded sample, identical opportunities repeated across settings, or one successful market. The $7.69 settlement result is one round. No broad value/exit/feed improvement is established.
- **Simultaneous/cross-duration scanner** recorded 45,699 checks with zero candidates and no attempted execution. That is evidence of no detected opportunity under this scanner's rules and inputs; it neither validates an execution strategy nor proves those opportunities never exist.

The complete family breakdown and every variant's costs, outcome distribution, timing and parameters are in the accompanying audits and CSV.

## An actionable model finding

The main probability model has a worse average squared probability error than the contemporaneous market forecast on **the same 152 rounds**: 0.16443 versus 0.15414. Lower is better. The order-flow study's corresponding comparison also favors the market, 0.14258 versus 0.13900 over 121 rounds; those periods overlap and are not independent replications.

The fast model improves the main model slightly on their 78 shared observations (error difference −0.00203), but that does not show a profitable advantage over the market after execution costs. Raw fast and central averages use different available samples and should not be compared directly.

These are fixed observations at two minutes before market end, not a score restricted to actual entry candidates. They do not rule out a profitable narrow subset. They do mean that better fair-value forecasts have not yet been demonstrated, so increasing model confidence or relaxing every value threshold would have no evidential basis.

## What the original Paper tab currently tells us

| Original portfolio | Net | Completed traded rounds | Unflagged net / rounds |
|---|---:|---:|---:|
| Momentum | −$5.86 | 20 | −$0.40 / 18 |
| Value | −$0.20 | 2 | −$0.20 / 2 |
| Fast value | −$3.50 | 2 | −$3.50 / 2 |
| Model exit | −$0.15 | 2 | −$0.15 / 2 |
| Passive pairs | −$5.99 | 26 | −$6.24 / 25 |
| Inventory pairs | −$9.31 | 16 | −$10.55 / 15 |

Its uses are preserving the original wallets' money trail, showing whether orders actually filled and exposing operational/risk issues. Its shortcomings as the landing research page are tiny samples, accumulated results spanning strategy changes, and no representation of the 101 experimental variants. Passive/inventory pairs have no completed traded markets since the September 7 18:44 UTC policy-change checkpoint; the original Momentum wallet has only one completed round starting after the later collection fix.

Its inactivity also has concrete causes. Original Momentum and both pairing wallets recorded `LOSS_LIMIT` outcomes. The guard adds already realized losses and the possible loss of a new position against a $10 session/day budget. A displayed loss near $6 plus a proposed $5 trade can therefore block an entry. The session limit can persist beyond a calendar-day change. These are portfolio rules, not evidence that the market offered nothing.

**Recommendation:** retain this tab as “Original portfolios” or “Baseline history,” and make an experiment comparison with dated strategy versions, actual filled rounds and evidence quality the primary research view. Preserve the old losses; start any changed-policy evaluation as a separately identified comparison rather than silently resetting the same curve. No UI or account changes were made in this audit.

## The collection issue still limits the conclusions

After the September 7 **23:08:33 UTC** collection repair, the original 84-variant suite recorded 35 completed variant-trades across eight distinct market rounds, with **zero unflagged completed trades** in that later subset. The first logged gap occurred during meaningful held inventory in all 35 cases: 25 metadata-expiry diagnoses, eight stale-spot diagnoses and two missing-round-state diagnoses. These repeat shared market events across variants, not 35 independent outages. They demonstrate missing strategy inputs during the holding path, not automatically impossible endpoint fills.

There is also a current outage: the collector's last displayed market/screen data are around **06:30 UTC / 09:30 Kyiv on September 8**. Its process keeps updating its heartbeat, but the running client's market-discovery requests repeatedly time out. A fresh anonymous request succeeded in about 70ms during this audit. That suggests a process/client recovery issue worth investigating; its cause is not established by this audit. A running heartbeat is consequently not evidence of accumulating usable strategy observations.

The earlier repair demonstrably improved coverage during its short probe, but it did not establish sustained reliability overnight. The 35 later flagged trades and current discovery failure are reasons to finish that reliability work before expanding the parameter search.

## What I would focus on next

1. Restore continuous usable market discovery and verify held-position intervals, with the present histories retained.
2. Freeze a small subsequent comparison: the $20 opening-lead Momentum candidate, one or two neighboring thresholds, normalized 0.5, and a dated Momentum control. Keep reversal as a clearly separate, secondary hypothesis requiring exceptional-win/path review.
3. Give that comparison an explicit paper research budget so early losses do not silently prevent later observations. Retain capital-constrained results as a separate question. Do not change existing risk histories or funded settings to accomplish this.
4. Evaluate the subsequent data in chronological blocks, including costs, largest-winner dependence, missing intervals and shared-round comparisons. Do not add more variants merely because a leaderboard has not produced a winner.

These are recommendations, not changes made during this audit. At the frozen cutoff both studies contain only their exploratory phase, with **no later validation phase**. Searching many parameter settings can select historical noise; that is why fixing a shortlist before reviewing its later results matters. [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf). This audit does not calculate a formal probability of overfitting or claim that an arbitrary number of trades guarantees profitability.

## Evidence files and reconciliation

- `paper.json`, `directional.json`, `order-flow.json`: frozen public dashboard payloads.
- `original-six.json`: original six portfolio totals and dated subsets.
- `original-loss-limits.json`: bounded read-only samples of actual loss-limit rejections.
- `current-source-failures.json`: sanitized recent collector discovery failures.
- `directional-audit.md` / `.json`: all 84 variants, exact registered parameters, sensitivity and gap timing.
- `flow-audit.md` / `.json`: all 17 variants and execution mechanisms.
- `all-107.csv`: comparable totals for every reviewed configuration, including the original six. Blank sensitivity fields for the original six mean not calculated, not zero.
- `summary.json`: machine-readable combined comparison.
- `build_summary.py`: one-off scratch reconciliation/export script.

All 101 experiment net totals, completed counts, unflagged totals/counts and fees were reconciled against the frozen reports. Later read-only ledger detail did not introduce post-cutoff trades. Source, runtime configuration, services, balances and study registrations were not modified. All audit artifacts live in ignored `work/results-audit/`.
