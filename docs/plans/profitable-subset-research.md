# Plan: is there a defensibly profitable subset of short-term strategies?

2026-09-13, revision 2. Branch `chore/btc-autopilot`, worktree `.worktrees/autopilot`, base
`cb7827b`. Authored by the PLAN stage of the unattended runner from the objective in the
ignored inbox. Evidence is in [the evidence register](../research/profitability-evidence-2026-09-13.md)
and [the photo register](../research/reference-photos-2026-09-13.md). Revision 1 (`08fbf74`)
received seven findings from the independent PLAN review; every one is answered below and
the affected sections were rewritten.

## Answers to the review of revision 1

| Finding | Where it is answered | What changed |
|---|---|---|
| P1 holdout begins before validation ends; no approval commit exists | [Freeze record](#the-freeze-record-one-persisted-boundary), [B4](#increment-b4-chronological-protocol-and-the-first-report) | One persisted freeze record, written by the first BUILD action, defines the cutoff. Validation is capped strictly before the purged cutoff by round start, frame cursor and label receipt. Tests cover capture advancing between freeze, extraction and selection. |
| P1 depth summaries cannot reconstruct USD-sized book walks | [B1 ticks](#increment-b1-round-dataset-extraction), [B2 fill walk](#fills-walk-the-full-ladder) | Fills read the full price/size ladders from the checksummed tape frame through a verified route (tape identity, frame ident, frame checksum). Summary columns are for screening only and are tested to have no effect on fills. Each baseline walks its own outcome token's ladder. |
| P1 no decision-to-fill deadline, stale books, expiry, partial depth, residual positions | [B2 execution validity](#execution-validity) | An order is live from decision plus latency to decision plus 2,000 ms, only on fresh books of the same market before expiry. Unfilled orders leave no position. Every entered round is preserved: delayed exits fill at the next valid frame or hold to settlement. Unlabeled entered rounds enter a full-loss sensitivity that the decision rule must pass. |
| P2 `research.block_sensitivity` cannot supply the day-block statistic | [Day-block bootstrap](#day-block-bootstrap-new-function) | A new `research.day_bootstrap` with a traded-round denominator, observed no-trade days as zeros, missing days excluded and counted, a six-day minimum, an explicit insufficient-evidence status, and sparse-day and missing-day fixtures. |
| P1 H6 fitted on train, then ranked in cross-validation over train plus validation | [B3 H6](#h6-fitted-combination-separate-leakage-free-protocol) | H6 leaves the combinatorial cross-validation matrix. It is evaluated by expanding chronological folds with fold-local standardization and fitting. A test changes an out-of-fold label and asserts identical coefficients. |
| P2 the hedge variant of the screenshot baseline cannot be represented | [Baselines](#baselines-registered-with-every-run) | The hedge variant is deferred with the evidence that its size is undefined (the sentence is truncated in the photo). The remaining baseline is labeled an approximation without the hedge. A bounded interpretation is recorded for a later, separately registered trial. |
| P2 H7 credits a maker rebate on the taker leg | [H7](#h7-maker-rebate-sensitivity-not-a-trial) | Rebates apply only to filled passive (maker) orders identified by the lab ledger's `passive` flag. The pool formula from the official program page is used with a stated allocation assumption and the USD 1 daily minimum. Hypothetical accrual is reported apart from paper cash. Maker-only, taker-only and mixed-leg fixtures are required. |

## The question and the decision rule

The project exists to find whether some subset of automated, short-horizon strategies on
the Polymarket BTC five-minute market earns money after real costs, reliably enough to run
as a background bot. Six days of capture, 107 registered variants and two automatic holdout
selections have produced no candidate. The reason is not a shortage of ideas. It is that
the evidence pipeline yields too few clean rounds per strategy, the full-engine lab replay
runs about three days behind the tape, and no rule has been scored on data it never saw.

This plan therefore builds a fast, reproducible offline evaluation layer on the archive
that already exists, pre-registers a bounded set of hypotheses and baselines, and applies
one decision rule to a held-out period that nobody inspects before the verdict.

A rule set is a **supported candidate** only if, on the untouched holdout, all of these hold:

| Criterion | Threshold | Why |
|---|---|---|
| Entered rounds | at least 60, every one preserved in the result | Below that a single day dominates; this is an operating floor, not a power calculation |
| Net after the stressed cost model | greater than zero | The stressed model adds one cent per share and 750 ms latency to recorded fees |
| Missing-outcome sensitivity | net is still greater than zero when every unlabeled entered round is counted as a full loss of its cost | A missing label must never remove a possible loss from the verdict |
| Dependence on outliers | net after removing the three largest wins is still greater than zero | Avoids a verdict resting on one lucky payout |
| Day-block bootstrap | status `descriptive` (at least six included days) and fewer than 25% of resamples have a mean net per entered round at or below zero | Descriptive uncertainty; not a significance test |
| Overfitting estimate | probability of backtest overfitting below 0.5 over the registered fixed-rule grid on train plus validation | Bailey et al. combinatorially symmetric cross-validation |
| Beats the baselines | net per entered round exceeds every baseline evaluated on the same rounds with its own outcome book | Otherwise the rule is only capturing what the market already prices |

Anything that fails is reported as a negative result with the same detail as a positive one.
A supported candidate earns a proposal for a bounded funded trial; it does not authorize one.
The thresholds are author-chosen operating thresholds and are stated as such.

## What already exists and is reused

- `Tape.read_after` streams frames from `capture.sqlite` and raises `TAPE_CORRUPT_FRAME`
  when a frame's SHA-256 checksum does not match (`src/btc5m/lab_tape.py:415`). Each frame
  holds the market with its fee parameters and opening reference, both full books as
  captured (`book_from` rebuilds every price/size level, `src/btc5m/lab_tape.py:38`), spot
  and TWAP points, 300 s spot history, exchange history and research records. The tape has
  a stable `identity` in its `meta` table; `lab.freeze` already refuses a study whose tape
  identity changed (`src/btc5m/lab.py:108`).
- Official final labels arrive through the same tape and are read by `Tape.labels_at`.
- `research.performance` computes net, outlier removal and fixed extra-cost stress on
  `RoundResult` rows (`src/btc5m/research.py:41`). `research.block_sensitivity` resamples
  complete 30- and 60-minute blocks and is kept for the existing lab reports; it is **not**
  the day-block statistic (see below).
- `strategy.fee_for` is the venue fee formula (`src/btc5m/strategy.py:34`);
  `strategy._realized_integral` and `conditional_probability_up` are the final-minute
  settlement model; `lab_scoring.score_forecasts` scores Brier and log loss.
- The lab ledger records each order's `passive` flag and per-fill `fee`; passive fills carry
  a zero fee (`src/btc5m/paper.py:217`). That flag identifies maker legs for H7.
- The lab, historical replay and experiment browser stay as they are. They remain the
  path-faithful simulator for policies with exits and for maker queues.

The new layer does not replace the simulator. It answers the first question quickly
(which rules survive costs on non-overlapping rounds) so that the slow simulator is spent
only on survivors.

## The freeze record: one persisted boundary

A read-only reviewer creates no commit, so approval time cannot be the boundary. Instead
the first BUILD action after PLAN approval, before any extraction or evaluation code runs,
is:

```
btc5m dataset freeze --source capture.sqlite --output docs/research/freeze-<date>.json
```

It opens the tape read-only and writes, then commits, a record with the tape identity, the
tape high-water frame ident, the tape `last_ms`, the wall clock, and the code identity.
From those it derives and stores:

- `cutoff_ms = (max(wall_clock_ms, last_ms) // 300000 + 1) * 300000`, the next round
  boundary after everything the tape already holds (the same construction `lab.freeze`
  uses, `src/btc5m/lab.py:110`).
- `validation_end_ms = cutoff_ms - 1800000` and `holdout_start_ms = cutoff_ms + 1800000`.
  The 30-minute purge on each side matches the longest volatility window.

Split membership is then mechanical and testable:

| Split | Round start | Frames used | Label counted only if |
|---|---|---|---|
| Train | capture start to 2026-09-11 00:00 UTC minus purge | ident at or below freeze high-water | label frame ident at or below freeze high-water |
| Validation | 2026-09-11 00:00 UTC plus purge to `validation_end_ms` | same | same |
| Holdout | at or after `holdout_start_ms` | any ident above freeze high-water | any official label |

A round whose label arrives after the freeze is *unlabeled* for train and validation, even
if a later tape has it. Rounds captured between PLAN approval and the freeze fall in
validation; nothing has scored them because the evaluator does not exist until B2, and B2
refuses any round at or after `validation_end_ms` unless invoked as the holdout run in B5.
No selection, coefficient or report may be computed on a dataset whose manifest does not
reference a committed freeze record.

Tests for this boundary (B1 and B4): a synthetic tape is frozen, then extended by two rounds
and a late label for an earlier round; the extraction must place the two rounds in holdout,
report the earlier round as unlabeled in validation, and keep validation row counts equal to
the pre-extension extraction. A selection record made on the pre-extension dataset must be
byte-identical to one made after the extension. A dataset built without a freeze record is
rejected by `evaluate`.

## Increment B1: round dataset extraction

Add `btc5m dataset build --source capture.sqlite --freeze FILE --output DIR`.
It opens the source read-only, checks the tape identity against the freeze record, streams
frames from the first cursor to the tape's current high-water, and writes one SQLite file
with:

- `rounds`: one row per market slug with start/end, verified opening reference and its
  status, settlement source, fee rate and exponent, tick size, minimum order, official final
  label, the frame ident and receipt time of that label, the split name derived from the
  freeze record, and the count of valid frames.
- `ticks`: one row per frame per round with the frame ident, seconds remaining, spot, TWAP60,
  the observed final-minute integral, short and long sigma estimates as the engine computes
  them, best bid and ask for both tokens, cumulative displayed depth at 5, 25 and 100 shares
  (screening and reporting only), book source and receipt timestamps, exchange lead if
  aligned, and a validity flag with the recorded rejection reason when the snapshot was not
  tradable. The full ladders are **not** copied; they are read from the tape frame by ident
  at fill time (see B2).
- `flow`: per round per frame the signed public trade volume over the previous 10, 30 and
  60 seconds and, only if the archived trade records carry a trader identifier, the number
  of distinct identifiers per side. If no identifier exists the columns are absent and the
  manifest says so.
- `manifest`: source path, tape identity, freeze record path and its SHA-256, cursor range,
  high-water at build, code identity hash, build time, row counts per split, and the count of
  rounds without a label per split.

Rules: read-only source; bounded memory through cursor batches; resumable by cursor; never
interpolates across gaps; never derives a label from spot. Every derived number is computed
by the same functions the engine uses so the dataset cannot silently disagree with it.

Tests (synthetic tapes built the way `tests/test_lab_tape.py` builds them):
a three-round tape with a gap produces exact row counts and a null-label round; resume
after an interrupted build appends nothing twice; a rejected snapshot yields a tick row
flagged invalid, not a fabricated book; the final-minute integral matches `strategy.py` on a
hand-computed path; the freeze-boundary tests listed above; a build against a tape whose
identity differs from the freeze record is refused.

Acceptance: a read-only build against the real archive completes, and its manifest counts
(rounds, labeled rounds, ticks, gap rounds, per split) are recorded in `docs/progress.md`,
together with the committed freeze record's cutoff.

## Increment B2: rule evaluator, cost model and baselines

Add `btc5m dataset evaluate --dataset DIR --source capture.sqlite --rules FILE --split NAME --output DIR`.
A rule is a pure function over one round's tick sequence up to a decision time, returning at
most one entry (side, decision time, size in USD) and an exit policy from a fixed set: hold
to settlement, fixed stop and target, or time exit. The rule sees only ticks with receipt at
or before its decision time.

### Fills walk the full ladder

At fill time the evaluator reads the fill frame from the tape by ident through
`Tape.read_after(ident - 1, limit=1)`, which verifies the checksum, and confirms the tape
identity equals the dataset manifest's. It then walks the complete ladder of the outcome
token being bought (asks) or sold (bids), level by level, until the requested USD (entries)
or share quantity (exits) is met. Quantity is rounded down to whole shares and prices are
used as recorded (tick 0.001). The `ticks` depth summaries are never consulted for a fill.

Tests: a five-level synthetic ladder with a hand-computed walk for 4, 30, 100 and 240
shares (beyond every summary point) gives exact quantities, principal and fees; an exit walk
across three bid levels matches by hand; corrupting the summary columns changes no fill; a
tampered frame payload raises `TAPE_CORRUPT_FRAME` and the run stops; a dataset whose
manifest identity differs from the tape is refused.

### Execution validity

| Rule | Standard | Stressed |
|---|---|---|
| Order live window | from decision time plus 250 ms to decision time plus 2,000 ms | plus 750 ms to plus 2,000 ms |
| Fill frame | first frame in the window whose `now_ms` is before the market's `end_s`, whose snapshot is for the same market, and whose book `received_ms` is within `max_book_age_ms` (5,000 ms) of `now_ms` | same |
| No such frame | the order is unfilled: no position, counted as `unfilled_no_frame` or `unfilled_stale`; the round is still reported (as not entered) | same |
| Partial depth | if the walk yields fewer than `min_order_size` (5) shares, unfilled; otherwise the walked quantity is the position and the round is flagged `partial` | same |
| Fee | `fee_for(shares, price, fee_rate, fee_exponent)` per level, taker on every leg | same |
| Extra slippage | none | one cent per share on each executed leg |
| Exit trigger | stop, target or time exit is evaluated on each valid tick; the exit order opens a live window like the entry | same |
| Exit not fillable in its window | the position is kept; the exit retries at each later valid frame with the then-current bids and is flagged `exit_delayed` with the delay in ms; if no valid frame remains before `end_s`, the position holds to settlement and is flagged `exit_forced_settlement` | same |
| Settlement | official label only; an entered round without a label is reported with net `null`, counted, and enters the full-loss sensitivity | same |

Every entered round is therefore present in the result table exactly once. Nothing entered
is dropped for a gap, an outage or an expiry. Flags describe path quality; the decision rule
uses all entered rounds.

Tests: an outage spanning the entry window yields no position; an outage during a stop
trigger yields a delayed exit at a worse bid and the flag; an outage lasting to expiry yields
`exit_forced_settlement` with the label's payout; a stale book (`received_ms` older than
5,000 ms) is skipped as a fill frame; a frame after `end_s` is never a fill frame; a
three-level partial walk of 12 shares against a USD 20 request is flagged `partial`; the
fee on a 0.90 fill equals 0.0063 per share; a 750 ms latency picks a later frame with a
worse price; a labeled loss is a full loss; an unlabeled entered round is counted and its
sensitivity net equals minus its cost; the same rule on the same dataset gives identical
output twice.

### Baselines registered with every run

Each baseline is evaluated on its own outcome token's ladder at its own fill frame, never on
the rule's price.

- **No trade** (zero).
- **Market favorite at T** for T in 120, 60 and 30 seconds: buy the token whose ask is
  above 0.5, hold to settlement. This measures what the market already prices.
- **Random side at the rule's own decision times and sizes**, seeded, averaged over 200
  draws; each draw walks the drawn token's ladder. This separates timing skill from side
  skill.
- **Screenshot literal, no hedge (approximation)**: enter with 120 to 90 seconds remaining
  when the spot move from the opening reference is between USD 70 and 100, buy with the move
  at 0.80 to 0.99, hold to settlement. The gus post also says to "cover just a small part of
  the position only if the market gets too imbalanced"; the example in parentheses is cut off
  in the photo, and the only other trace is one log row reading `book flipped 95/5 ->
  micro-hedge -1.69` on a 48-share 0.81 fill. Neither the trigger nor the hedge size is
  defined, so the hedge variant is **deferred**. If a later objective wants it, the bounded
  interpretation to register is: trigger when the held token's best bid falls to 0.05 or
  below while holding; buy the opposite token for 10% of the held shares at its ask; both
  legs pay taker fees; the residual inventory settles by label. That interpretation is not
  part of this plan and would need its own registered trial and accounting tests for
  completed and incomplete hedges.

Outputs reuse `RoundResult` so `performance` (net, outlier removal, extra-cost stress)
applies unchanged; the day-block bootstrap is the new function below. Results are split by
settlement distance (near-even versus decided) because of the manipulation finding.

Acceptance: all baselines evaluated on the real dataset's training split with counts and
net results recorded in progress; the market-favorite baseline's realized win rate by price
band is compared with the fee break-even table in the trader evidence register.

## Increment B3: registered hypotheses, uncertainty and overfitting estimate

Register the following families in one `rules.json` with an explicit trial count. The grid
is deliberately small; every cell counts as a trial.

| Family | Rule | Falsifier |
|---|---|---|
| H1 opening lead | lead in USD 20, 30, 50, 70; entry windows 90 to 150 and 120 to 180 s; ask 0.70 to 0.95; hold to settlement (8 trials) | net per round not above the market-favorite baseline on the same rounds |
| H2 normalized lead | lead divided by sigma times root of remaining seconds at 0.5, 1.0, 1.5; same windows; hold (6 trials) | same |
| H3 final-minute lock-in (new) | with 15 to 60 s remaining, the conservative scenario probability from the observed TWAP integral is at least 0.97 and the ask is at most 0.95; hold (thresholds 0.95/0.97/0.99 by windows 15 to 30 and 30 to 60 s: 6 trials) | fills are unavailable in the last minute, or net is not positive after the stressed model |
| H4 cheap reversal held (secondary) | ask at most 0.10 on the side against a 60 s move above 1 sigma, 60 to 150 s remaining; hold (2 trials) | positive net depends on fewer than four rounds |
| H5 favorite bands | buy the favorite at T-60 only when the ask is in 0.90 to 0.95 or 0.95 to 0.99; hold (2 trials) | realized win rate below the fee break-even for the band |

Fixed-rule trials in the overfitting grid: 24. H6 below is the 25th registered trial but is
evaluated by its own protocol. The evaluator refuses a rules file whose trial count differs
from its registered header.

### Overfitting estimate for the fixed-rule grid

Implement combinatorially symmetric cross-validation in pure Python over the 24 fixed
rules. Split train plus validation rounds into 16 chronological blocks; for each of the
12,870 half-splits, rank trials by net per entered round in-sample and record the
out-of-sample rank of the in-sample best. The probability of backtest overfitting is the
share of splits where that rank falls below the median. Report it with the trial count and
the ranked table. Fixed rules have no fitted state, so nothing in a block can leak into
another.

### H6 fitted combination: separate, leakage-free protocol

H6 is a logistic model with structural probability, market probability, 15 s and 60 s scaled
returns, signed flow and, if available, wallet breadth; L2 penalty; trade when the model's
probability exceeds the ask by 0.02. It is excluded from the cross-validation matrix
because fitting it inside every half-split would either leak labels (if fitted once) or
require 12,870 fits in pure Python (if fitted per split).

Protocol: five expanding chronological folds over train plus validation. For fold k, the
feature means and standard deviations and the coefficients are computed from rounds before
the fold only; fold k is scored on Brier versus the market and on trading net under the
stressed model. The coefficients that would go to the holdout are the ones fitted on all of
train plus validation and are written into the selection record before the freeze cutoff is
crossed. The falsifier is: Brier not below the market on the folds, or trading net not
above H1's best fixed rule on the same folds.

Tests: the H3 rule reads only ticks at or before its decision time (a leaked later tick
changes nothing); a rules file with a wrong trial count is rejected; CSCV on a synthetic
grid with one genuinely better rule returns a low probability and on pure noise returns
about 0.5; for H6, changing the label of a round inside a fold's scoring block leaves that
fold's standardization and coefficients byte-identical, and changing a label before the fold
does change them.

### Day-block bootstrap (new function)

`research.day_bootstrap(rows, *, coverage)` where `rows` are `RoundResult` rows for one
rule and `coverage` maps UTC day to the number of observed round slots that day.

- Unit: UTC day. A day is **included** if the capture observed at least 144 of its 288
  slots; an included day with no entered round contributes net 0 and count 0. Days below
  that coverage are **missing**, excluded and counted.
- Statistic: total net divided by total entered rounds over the resampled days. A resample
  whose entered-round count is zero counts as at or below zero.
- 2,000 seeded resamples of the included days with replacement.
- Output: included days, missing days, entered rounds, mean per entered round, the 2.5th
  and 97.5th percentile of the statistic, `negative_fraction`, and a status that is
  `descriptive` only when at least six days are included and at least 60 rounds were
  entered; otherwise `insufficient_evidence`, which fails the decision criterion.

Tests: a sparse fixture (nine days, three with one trade each) reports the traded-round
denominator and `insufficient_evidence`; a missing-day fixture excludes the day with 100
observed slots and counts it; an all-negative fixture gives `negative_fraction` 1.0; a fixed
seed reproduces the percentiles; an included no-trade day lowers the mean per day but not
the mean per entered round.

### H7 maker rebate sensitivity (not a trial)

Re-report the existing pair strategies' recorded lab results with a hypothetical maker
rebate credited **only** on fills of orders whose ledger `passive` flag is true (maker
fills, which already carry zero fee). Taker legs, including the hedge or exit legs of the
same strategy, keep their recorded fees and receive nothing. The official program pays a
per-market pool equal to 20% of crypto taker fees, allocated pro rata by each maker's
fee-equivalent `C x feeRate x p x (1 - p)` of executed liquidity, daily, with a USD 1
minimum before payout ([Maker Rebates Program](https://docs.polymarket.com/programs/maker-rebates)).
Because every taker fill has a maker counterpart, a maker's pro-rata share equals 20% of its
own fee-equivalent under the assumption that all matching takers paid the crypto rate; the
report states that assumption and treats the number as an upper bound. The daily accrual is
summed and shown against the USD 1 threshold; days below it show zero paid. The accrual is
a separate column, never added to realized paper cash.

Tests: a maker-only fixture (two passive fills) accrues 20% of their fee-equivalent; a
taker-only fixture accrues nothing; a mixed fixture with one passive entry and one taker
exit accrues only on the entry; a day whose accrual is USD 0.40 reports zero paid.

## Increment B4: chronological protocol and the first report

Splits come from the committed freeze record as described above. The selection step:

1. Evaluate every registered trial and baseline on train and on validation.
2. Compute the fixed-rule overfitting estimate and the H6 fold protocol.
3. Write `docs/research/selection-<date>.json` with the rules file SHA-256, the freeze
   record SHA-256, the three selected rule identifiers, and H6's final coefficients if H6
   is selected. Commit it before any holdout row is read.

`evaluate --split holdout` refuses to run unless the selection record exists, its rules
file hash matches, and the dataset manifest references the same freeze record. The
historical replay's `lab freeze` refuses historical studies; this layer follows the same
principle.

Deliverable: `docs/research/rule-evaluation-<date>.md` with the baseline table, every
trial's train and validation results (all cost models, all flags, unlabeled counts and the
full-loss sensitivity), the overfitting estimate, the H6 fold table, the day-block bootstrap
per rule, the selected identifiers, and the count of holdout rounds still needed. Progress
records the exact dataset manifest.

## Increment B5: holdout verdict (may wait)

When the holdout contains at least 60 entered rounds for each pre-selected rule, evaluate
once and apply the decision rule. If the capture is too short, the author returns `waiting`
with the shortfall stated in rounds. No rule change after reading the holdout is allowed
without a new registered rules file, a new selection record and a new freeze record.

## Increment B6: external history probe (bounded, optional)

Download one PMXT hourly file for a chosen hour, check whether the BTC five-minute tokens of
that hour appear, and measure gap counts. Record the result. If coverage is good, propose a
later increment that evaluates only market-price rules (H5 and the market baselines) over
months, with official labels from the public Gamma API. Spot-versus-reference rules cannot
use that source because it has no opening reference. No bulk import in this plan.

## Deferred and out of scope

- The screenshot hedge variant (see the baseline section) until a defined trigger and size
  exist.
- Other assets and the fifteen-minute duration would need collector changes, which are
  service changes and are not authorized. Recorded as a later objective; the manipulation
  paper's finding that fifteen-minute contracts show little settlement manipulation makes it
  worth a future comparison.
- Memecoin, launchpad and token-launch mechanisms from the reference photos are rejected.
- A language model in the trading loop, latency engineering and a Rust rewrite are not
  research questions and stay out.
- No funded trial, credential access, service restart or runtime write occurs. The lab
  worker's three-day lag is recorded, not fixed here; the dataset layer bypasses it.

## Risks and how the plan handles them

- **Selection bias from many trials**: fixed grid of 24 rules plus one fitted model, trial
  count in the file, overfitting estimate, H6 fold protocol, one holdout read gated by a
  committed selection record.
- **Optimistic fills**: taker only, full-ladder walk from checksummed frames, live windows
  with a 2,000 ms deadline, fresh-book requirement, latency, extra slippage, no maker
  credit, preservation of every entered round with delayed or forced exits, a full-loss
  sensitivity for unlabeled entries, and a live-stage risk register covering ghost reverts
  (more than 24% of filled orders reverted at peak hours in the cited study).
- **Label leakage**: labels come only from official final references; labels received after
  the freeze are invisible to train and validation; the H3 rule is tested against a leaked
  future tick; H6 is tested against a leaked out-of-fold label.
- **Reference drift**: rounds whose opening reference status is not official or boundary
  are excluded from every rule and counted.
- **Rule change at the venue**: the settlement rule was rechecked today; the dataset stores
  it per round, and a round with a different settlement source is excluded rather than
  approximated.
- **Sample size**: at current entry rates the holdout may take weeks. The plan returns
  `waiting` rather than lowering thresholds.
- **Rebate economics at small size**: a USD 5 maker fill at 0.50 is 10 shares with a
  fee-equivalent of USD 0.175 (10 x 0.07 x 0.5 x 0.5) and a hypothetical rebate of USD
  0.035, so about 29 such fills a day are needed to reach the USD 1 payout minimum. H7
  reports this explicitly.

## Integration verification

Each increment runs `bash scripts/autopilot-gate.sh` through the shared verification
semaphore: lock check, full pytest, Ruff lint and format, mypy and shell syntax. Reviewers
also expect: no file under `/home/vilius/.local/share/btc5m` modified (compare modification
times before and after a real-archive build), no new runtime dependency in `pyproject.toml`,
a committed freeze record before the first real-archive build, a committed selection record
before any holdout read, and a progress entry with the manifest counts for every
real-archive run.
