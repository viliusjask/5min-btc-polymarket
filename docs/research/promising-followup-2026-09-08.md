# Follow-up on the promising strategies

September 8, 2026. This follows the [07:17 UTC experiment audit](experiment-results-2026-09-08.md).
The later-data comparison starts at **07:20 UTC**, the first complete market after that
cutoff. Directional results are frozen at **10:30:47.724 UTC**. The source and all existing
paper wallets/study registrations were read only; old losses and uncertainty flags remain.

**No profitable strategy is established. The $20 opening-lead candidate has new trades,
but its later result is fragile and none of those later trades is unflagged.** This audit
does not equate a missing clean sample with an absence of trading opportunities.

## What was fixed, and what was actually followed up

The preceding work repaired execution/collection paths, added a unified experiment view,
and made selected-date historical replay possible. That work establishes software behavior,
not improved trading returns. Existing exploratory studies deliberately run their pinned
implementations; a fix to today's original six does not silently change yesterday's study.
In particular, the original-six Momentum policy now follows a recent BTC move. The previously
promising `momentum-20-90-150` follows BTC's distance from the market opening reference.
These are different policies.

The previous audit did investigate fees, largest-winner dependence, shared markets,
uncertain holding paths and the probability model. It recommended a fixed Momentum
shortlist, but **that shortlist was not present in the automatic later-data phases**.
Both registered later-data phases contain only a Value control: the automatic qualification
rule found zero candidates with its required 30 unflagged completed markets. A research
comparison of a prior hypothesis need not pass a profitability promotion rule first.

This follow-up does three concrete things:

1. Reconciles the current saved summaries for all 84 directional and 17 order-flow variants
   against the prior audit, then reconstructs individual rounds for eight previously
   discussed policies. It separates subsequent markets from the original selected sample.
2. Reconstructs the first uncertainty event against the exact source frame and filled
   inventory, distinguishing real held exposure from a fractional unsellable remainder.
3. Runs a fixed five-policy comparison on the same subsequent source period with the
   current engine, preserving the existing $100 allocation, $5 order budget and $10 loss
   allowances. It is a retrospective implementation comparison, not a future holdout.

## Subsequent results from the existing pinned studies

All amounts below are net dollars after recorded fees. A round is a five-minute market
with completed traded exposure, not an order attempt. Each row has its own $100 simulated
wallet and $5 trade budget; the rows must not be summed as independent portfolios.

| Existing policy | Later net | Later completed rounds | Later unflagged rounds | Full-history net / unflagged net |
| --- | ---: | ---: | ---: | ---: |
| $10 opening lead, 90–150s | $0.0000 | 0 | 0 | −$6.0343 / +$1.9160 |
| **$20 opening lead, 90–150s** | **+$0.5449** | **5** | **0** | **−$1.1071 / +$3.4197** |
| $30 opening lead, 90–150s | −$0.9340 | 3 | 0 | −$2.1534 / +$0.9261 |
| Normalized opening lead, 0.5 | −$1.7104 | 2 | 0 | −$1.9654 / +$2.7333 |
| Pinned opening-lead Momentum control | +$0.4790 | 1 | 0 | −$3.2992 / +$0.1709 |
| 60-second continuation, 0.5 | +$8.6846 | 7 | 0 | +$33.6447 / −$3.5534 |
| 60-second reversal, 0.5 | $0.0000 | 0 | 0 | +$115.6597 / −$2.5238 |
| 60-second reversal, 1 | $0.0000 | 0 | 0 | +$147.5852 / −$11.1777 |

These 18 variant-rounds span **12 distinct markets**. The $20 candidate shares one of its
five later markets with normalized 0.5; the overlapping trade is the same −$1.4477 loss.
The candidate's original nine unflagged markets and +$3.419748 remain unchanged. Its
full-history sample has grown from 48 to 53 completed markets.

| Sensitivity, later completed sample | $20 opening lead | 60-second continuation |
| --- | ---: | ---: |
| Recorded fees | $0.599559 | $1.227834 |
| Wins / losses | 3 / 2 | 4 / 3 |
| Largest win / largest loss | +$1.6897 / −$1.4477 | +$12.7750 / −$2.8853 |
| Net after another 0.5¢ per bought or sold share | +$0.2570 | +$7.9546 |
| Net after another 1¢ per bought or sold share | **−$0.0310** | +$7.2245 |
| Net without largest winner | **−$1.1447** | **−$4.0904** |

The additional-cost checks hold the recorded fills fixed; they do not model a different
queue or slower execution. Removing winners is a concentration check, not a prediction
that winners disappear. These checks show why neither positive later subtotal establishes
an edge. In particular, the lower-threshold Momentum result no longer survives the same
1¢ cost check that its originally selected nine-round subtotal survived.

Across all 101 exploratory variants, only **two additional unflagged completed observations**
appeared after the prior audit: $20 opening lead with 60–120 seconds remaining lost $0.6480,
and Value held to settlement lost $4.89489. They are different markets. The latter's
previous one-win +$7.6944 result is now **+$2.7995 over two markets**, with a large second
loss. No new broad unflagged success appeared in the order-flow suite.

The model comparison still favors contemporaneous market prices. On 168 matched forecast
rounds, the central model's average squared probability error exceeds the market's by
0.0097301. The flow suite's difference is +0.0036835 on 137 matched rounds. These overlapping
samples are not independent replications, and these forecast errors are not trading PnL.

## Why some apparent winners stopped trading

These are explicit risk-budget restrictions rather than a lack of eligible signals:

| Policy | Later `LOSS_LIMIT` checks | Recorded constraint |
| --- | ---: | --- |
| $10 opening lead, 90–150s | 682 | Session net −$6.0343; another roughly $5 position exceeds the $10 session allowance. |
| Normalized 0.5 | 292 | September 8 net −$5.7212; another roughly $5 position exceeds the $10 daily allowance. |
| Reversal 0.5 | 681 | September 8 net −$8.9827 despite a positive prior-day result. |
| Reversal 1 | 316 | Same −$8.9827 subsequent-day loss. |

The counters use complete post-cutoff round records through the frozen report; they are
repeated rejected checks, not independent opportunities. The ledger checks realized losses
plus existing/potential exposure. A positive lifetime balance therefore does not imply an
available daily risk budget. Existing budgets were not reset to make the experiment trade.

For future hypothesis measurement, a separate study should explicitly declare how much
simulated research capital it may lose. Increasing bankroll while retaining a $10 session
loss allowance will not solve this restriction. If the objective is a longer fixed-$5
signal sample, enlarge only the new study's stated loss allowance/capital, retain its
losses and report the $100-constrained question separately. That changes the experiment;
it must not be presented as the same historical wallet or as an approved funded setting.

## What the uncertainty reconstruction establishes

All five new $20 candidate rounds first became uncertain while holding **5–6.6714 shares**.
Four first failures were spot-source age and one was TWAP-source age. Their source ages
were 5.028–5.430 seconds against the configured five-second limit. Consecutive archive
frames were only 0.730–0.811 seconds apart. Thus these particular events were invalid
strategy inputs while exposure existed, not multi-minute gaps in recording. The later
10:15 round also has a dust-only rollover event, but an earlier material exposure failure
already flagged it. Inspecting only the last event would give the wrong explanation.

Two other later rounds have flags only after liquidation left a sub-cent remainder:

| Policy / market start UTC | Net | Maximum remaining binary payout at first flag |
| --- | ---: | ---: |
| $30 opening lead / 09:15 | −$0.455544 | $0.000810811 |
| 60-second continuation / 09:45 | −$1.001156 | $0.009014085 |

Both are losses, so adding these as a separate bounded-uncertainty sensitivity would
worsen the relevant unflagged subtotals. Neither rescues the $20 candidate's five new
flags. The bound is the remaining shares times the maximum $1 payout, not a claim that
all market-data errors are harmless. No existing flags were removed.

There is also a **confirmed mismatch between directional replay and live paper execution**.
`Replay` attaches `PublicStreams` only to pairing policies. Directional replay therefore
ignores the independent books in `frame.research.streams` when the combined strategy
snapshot is absent; its broker keeps only an earlier full-snapshot book. Live paper
attaches the public streams to every policy. In all **18 first-flag cases** reconstructed
above, the saved frame already contains the held token's independent exit book: positive
bids, no pending book invalidation, receipt ages of 3–40ms and source ages of 1.994–3.213s.
These satisfy the configured book freshness limits even though the oracle/metadata
snapshot does not. A stop, profit or time exit should be evaluated against that available
book under the same rules as live paper.

Fixing this for new studies is more useful than weakening every price-age check. A
regression should make the oracle stale while preserving a fresh independent book that
crosses a stop, and assert that replay uses that book. Companion cases must reject a
stale or explicitly invalidated book, preserve a missing model input for model-based
exits, and retain uncertainty if execution evidence is genuinely absent. Merely attaching
streams is insufficient to declare old flags clean: the gap classifier currently treats
any missing combined snapshot as a gap for all affected holdings. Book availability and
which inputs an exit actually needs must be classified explicitly. This branch reports
the defect and evidence; it does not alter shared execution code.

The future classifier can be more informative without manufacturing clean returns:
record the first affected input, start/end times, outstanding-order state, held shares
and maximum remaining payout when each uncertainty interval starts. Distinguish a holding
path with executable exposure from a fractional remainder below the venue's sell amount
precision. Continue marking unknown orders and pending entries uncertain. At an interval
crossing settlement, record separately whether the only missing input concerns an already
expired position. Do not propagate a global broker gap to unrelated positions merely to
attach a dust diagnostic, and do not silently rewrite old samples.

Before changing that classifier, meaningful tests should cover: a material holding at a
source-age failure; a fully liquidated position with only an unsellable fraction; a gap
that begins before expiry and ends after it; a first gap only after expiry; an unresolved
order despite tiny holdings; two policies sharing the same source gap; and a later
conflicting settlement label. Each must preserve accounting and distinguish the economic
bound from eligibility. The current audit adds the explanation, not that classifier change.

## Fixed comparison and prospective shortlist

The five policy definitions selected before the new replay are:

- $10, $20 and $30 opening-reference leads, each entering with 90–150 seconds remaining.
- Opening lead divided by expected remaining volatility, threshold 0.5.
- Today's Momentum control: 30-second BTC continuation, minimum signal strength 0.5
  times the volatility expected over its lookback. This is not the pinned $50 opening
  control in the table above.

All retain the configured 70–95¢ Momentum entry band, 3¢ maximum spread, 8¢ stop, 98¢
take-profit bid, 20-second time exit, 1¢ buy/sell price protection and 250ms simulated
latency. The actual current engine's sizing, minimum-size checks, confirmation and
accounting apply. Old persisted variant IDs cannot be reused to disguise changed code.
The raw old registrations and the new complete registrations are both retained.

The replay on source `cb7827b` processed **16,613 frames in 348.1 seconds**, including
causal warmup and later already-recorded exits/settlement. It froze at frame 108014:

Only 24 of the 38 selected calendar markets contain observed strategy screens. The other
14 remain absent data, not assumed flat trading outcomes. This is still a short, interrupted
test interval; imported longer histories remain necessary for a useful assessment.

| Current-engine policy | Eligible market rounds | Filled/completed rounds | Net | Net after extra 1¢/share |
| --- | ---: | ---: | ---: | ---: |
| $10 opening lead | 16 | 4 | −$1.0282 | −$1.4834 |
| $20 opening lead | 14 | 5 | +$0.5449 | −$0.0310 |
| $30 opening lead | 11 | 3 | −$0.9340 | −$1.2727 |
| Normalized 0.5 | 15 | 4 | −$3.1211 | −$3.5796 |
| Current recent-continuation control | 11 | 6 | +$0.2238 | −$0.4505 |

Those 22 completed policy-rounds span **10 distinct markets**. All are flagged; none
establishes profitability. The current Momentum control does generate entries and fills
on this saved period, but its small positive subtotal turns negative with an extra 0.5¢
per traded share already. The previously selected $20 policy is likewise cost-fragile.
Fresh isolated research wallets let the $10 and normalized policies exercise trades
that existing accumulated-loss wallets could not; this does not erase their old losses.
There were no unresolved variants or out-of-range BUY orders. A resume processed zero
new frames when the live source had grown to 108554, with the manifest and phase results
unchanged. The source-book mismatch described above still applies to this pre-fix replay.

A later prospective test should freeze these five after integration and begin on the next
complete market, with a fixed seven-day assessment period. Freeze before looking at that
period's results; compare daily blocks, count distinct markets, retain missing intervals,
include all and unflagged totals, and report the same fees/cost/winner-concentration checks.
A sample-size requirement can govern promotion later; it should not prevent collecting
that research comparison. Expanding to another hundred parameters now would provide more
ways to select the same short-lived noise.

## Reproduction and limitations

Ignored artifacts are under `work/promising-followup/` in the `promising-followup` worktree:
`catalog.json`, frozen `lab-*/order-flow-lab-*` study/report documents,
`all-101-followup.json`, `shortlist-audit.json`, `gap-reconstruction.json`,
`independent-exit-books.json`, `current-replay-check.json`,
`actual-daily-net.json`, `new-unflagged.json`, and the read-only `audit.py`/`gaps.py` checks.
`current-shortlist-definition.json` records the selected current policies before replay;
`current-shortlist-replay/` and `replay-shortlist.log` contain the isolated replay.

The detailed pinned-study reads retain each ledger's actual later clock but include only
completed markets through the frozen report and assert equality with its completed counts
and total net. The public live archive remains mutable, so the historical replay fixes its
own source-frame boundary, with later already-recorded frames available for exits/labels.
No runtime dependency, strategy production file, service, secret, account balance or old
study definition was changed by this research branch.
