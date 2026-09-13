# Plan: is there a defensibly profitable subset of short-term strategies?

2026-09-13. Branch `chore/btc-autopilot`, worktree `.worktrees/autopilot`, base `cb7827b`.
Authored by the PLAN stage of the unattended runner from the objective in the ignored inbox.
Evidence is in [the evidence register](../research/profitability-evidence-2026-09-13.md) and
[the photo register](../research/reference-photos-2026-09-13.md). No prior review of this
plan exists, so there are no earlier findings to answer.

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
| Clean traded rounds | at least 60 | Below that a single day dominates; this is an operating floor, not a power calculation |
| Net profit after the stressed cost model | greater than zero | The stressed model adds one cent per share and 750 ms latency to recorded fees |
| Dependence on outliers | net after removing the three largest wins is still greater than zero | Avoids a verdict resting on one lucky payout |
| Day-block bootstrap | fewer than 25% of resamples have negative mean net per traded round | Descriptive uncertainty; not a significance test |
| Overfitting estimate | probability of backtest overfitting below 0.5 on train plus validation | Bailey et al. combinatorially symmetric cross-validation over the registered grid |
| Beats the baselines | net per round exceeds every baseline on the same rounds | Otherwise the rule is only capturing what the market already prices |

Anything that fails is reported as a negative result with the same detail as a positive one.
A supported candidate earns a proposal for a bounded funded trial; it does not authorize one.

## What already exists and is reused

- `Tape.read_after` streams checksummed frames from `capture.sqlite`; each frame has the
  market with its fee parameters and opening reference, both full books, spot and TWAP
  points, 300 s spot history, exchange history and research records (`src/btc5m/lab_tape.py`).
- Official final labels arrive through the same tape and are read by `Tape.labels_at`.
- `research.summarize`, `research.block_sensitivity` and `research.compare_rounds` already
  compute medians, outlier removal, extra-cost sensitivity and block bootstraps on
  `RoundResult` rows (`src/btc5m/research.py`).
- `strategy.py` holds the settlement-average probability model, including the observed
  integral inside the final minute; `lab_scoring.score_forecasts` scores Brier and log loss.
- The lab, historical replay and experiment browser stay as they are. They remain the
  path-faithful simulator for policies with exits and for maker queues.

The new layer does not replace the simulator. It answers the first question quickly
(which rules survive costs on non-overlapping rounds) so that the slow simulator is spent
only on survivors.

## Increment B1: round dataset extraction

Add `btc5m dataset build --source capture.sqlite --output DIR [--start ISO --end ISO]`.
It opens the source read-only, streams frames from the first cursor to the frozen high-water
recorded in a manifest, and writes one SQLite file with:

- `rounds`: one row per market slug with start/end, verified opening reference and its
  status, settlement source, fee rate and exponent, tick size, minimum order, official
  final label and the receipt time of that label, and the count of valid frames.
- `ticks`: one row per frame per round with seconds remaining, spot, TWAP60, the observed
  final-minute integral, short and long sigma estimates as the engine computes them, best
  bid and ask and cumulative displayed depth at 5, 25 and 100 shares for both tokens,
  book source and receipt timestamps, exchange lead if aligned, frame cursor, and a
  validity flag with the recorded rejection reason when the snapshot was not tradable.
- `flow`: per round per frame the signed public trade volume over the previous 10, 30 and
  60 seconds and, only if the archived trade records carry a trader identifier, the number
  of distinct identifiers per side. If no identifier exists the columns are absent and the
  manifest says so.
- `manifest`: source path and identity, cursor range, high-water, code identity hash,
  build time, row counts, and the count of rounds without a label.

Rules: read-only source; bounded memory through cursor batches; resumable by cursor; never
interpolates across gaps; never derives a label from spot. Every derived number is computed
by the same functions the engine uses so the dataset cannot silently disagree with it.

Tests (synthetic tapes built the way `tests/test_lab_tape.py` builds them):
a three-round tape with a gap produces exact row counts and a null-label round; resume
after an interrupted build appends nothing twice; a frame after the manifest high-water is
ignored; a rejected snapshot yields a tick row flagged invalid, not a fabricated book; the
final-minute integral matches `strategy.py` on a hand-computed path.

Acceptance: a read-only build against the real archive completes, and its manifest counts
(rounds, labeled rounds, ticks, gap rounds) are recorded in `docs/progress.md`.

## Increment B2: rule evaluator, cost model and baselines

Add `btc5m dataset evaluate --dataset DIR --rules FILE --split NAME --output DIR`.
A rule is a pure function over one round's tick sequence returning at most one entry
(side, time, size in USD) and an exit policy from a fixed set: hold to settlement, fixed
stop and target, or time exit. The evaluator applies one cost model to every rule:

| Component | Standard model | Stressed model |
|---|---|---|
| Fill timing | first frame whose receipt time is at least entry time plus 250 ms | plus 750 ms |
| Fill price | walk displayed ask depth for the requested USD; skip if depth is short | same |
| Fee | recorded `fee_rate x p x (1 - p)` per share, taker on both legs | same |
| Extra slippage | none | one cent per share on each executed leg |
| Exit | bids walked the same way at the first frame after the trigger plus latency | same |
| Settlement | official label only; unlabeled rounds are excluded and counted | same |
| Evidence class | settlement-hold: valid entry frame and label; exit policies: additionally no gap above 5 s while held | same |

Maker fills are not credited in this layer. Maker economics are handled only by the
existing queue simulator and by the H7 sensitivity below.

Baselines registered with every run:

- **No trade** (zero).
- **Market favorite at T** for T in 120, 60 and 30 seconds: buy the token whose ask is
  above 0.5, hold to settlement. This measures what the market already prices.
- **Random side at the rule's own entry times and prices**, seeded, averaged over 200
  draws. This separates timing skill from side skill.
- **Screenshot literal**: enter with 120 to 90 seconds remaining when the spot move from the
  opening reference is between USD 70 and 100, buy with the move at 0.80 to 0.99, hold to
  settlement; a variant adds the 95/5 partial cover. This is the gus rule as written.

Outputs reuse `RoundResult` so the existing summaries, outlier removal, extra-cost
sensitivity and block bootstraps apply unchanged. Results are split by settlement
distance (near-even versus decided) because of the manipulation finding.

Tests: a hand-built round where the ask depth is short skips the entry; the fee on a
0.90 fill equals 0.0063 per share; a 750 ms latency picks a later frame with a worse price;
a labeled loss is a full loss; an unlabeled round is excluded and counted; the random
baseline is reproducible from its seed; the same rule on the same dataset gives identical
output twice.

Acceptance: all baselines evaluated on the real dataset's training split with counts and
net results recorded in progress; the market-favorite baseline's realized win rate by price
band is compared with the fee break-even table in the trader evidence register.

## Increment B3: registered hypotheses and overfitting estimate

Register the following families in one `rules.json` with an explicit trial count. The
grid is deliberately small; every cell counts as a trial.

| Family | Rule | Falsifier |
|---|---|---|
| H1 opening lead | lead in USD 20, 30, 50, 70; entry windows 90 to 150 and 120 to 180 s; ask 0.70 to 0.95; hold to settlement (8 trials) | net per round not above the market-favorite baseline on the same rounds |
| H2 normalized lead | lead divided by sigma times root of remaining seconds at 0.5, 1.0, 1.5; same windows; hold (6 trials) | same |
| H3 final-minute lock-in (new) | with 15 to 60 s remaining, the conservative scenario probability from the observed TWAP integral is at least 0.97 and the ask is at most 0.95; hold (thresholds 0.95/0.97/0.99 by windows 15 to 30 and 30 to 60 s: 6 trials) | fills are unavailable in the last minute, or net is not positive after the stressed model |
| H4 cheap reversal held (secondary) | ask at most 0.10 on the side against a 60 s move above 1 sigma, 60 to 150 s remaining; hold (2 trials) | positive net depends on fewer than four rounds |
| H5 favorite bands | buy the favorite at T-60 only when the ask is in 0.90 to 0.95 or 0.95 to 0.99; hold (2 trials) | realized win rate below the fee break-even for the band |
| H6 fitted combination | logistic model with structural probability, market probability, 15 s and 60 s scaled returns, signed flow and, if available, wallet breadth; fitted on train only with L2 penalty; trade when the model's probability exceeds the ask by 0.02 (1 trial plus the forecast score) | Brier not below the market on validation, or trading net not above H1 |
| H7 maker sensitivity (not a trial) | re-report the existing pair strategies' recorded results with the maker fee at zero and a 20% rebate credited on the taker leg only; no new fills | informational only; a positive sensitivity does not make a candidate |

Total registered trials: 25. The evaluator refuses a rules file whose trial count differs
from its registered header.

Overfitting estimate: implement combinatorially symmetric cross-validation in pure Python.
Split train plus validation rounds into 16 chronological blocks; for each of the 12,870
half-splits, rank trials by net per round in-sample and record the out-of-sample rank of
the in-sample best. The probability of backtest overfitting is the share of splits where
that rank falls below the median. Report it with the trial count and the ranked table.

Tests: the H3 rule reads only ticks at or before its decision time (a leaked later tick
changes nothing); a rules file with a wrong trial count is rejected; CSCV on a synthetic
grid with one genuinely better rule returns a low probability and on pure noise returns
about 0.5; the H6 fit uses only training rows (a validation row with a distinctive label
does not move the coefficients).

## Increment B4: chronological protocol and the first report

Splits are by round start time and are recorded in the dataset manifest:

- **Train**: capture start (September 7) to 2026-09-11 00:00 UTC.
- **Validation**: 2026-09-11 00:00 to the last labeled round at the time of the B1 build.
- **Purge**: 30 minutes on each side of a boundary, matching the longest volatility window.
- **Holdout**: every round that starts after the commit time of the reviewer's approval of
  this plan and is captured afterwards. It is evaluated once per registered rules file, only
  after at least 60 clean rounds exist for the three pre-selected rules. Selection happens
  on train plus validation before the holdout is read; the selected identifiers are written
  to `docs/progress.md` before evaluation.

The historical replay's `lab freeze` refuses historical studies; this layer follows the
same principle by recording the holdout start in the manifest before any holdout row exists.

Uncertainty: day-block bootstrap ranges from `research.block_sensitivity`, with the number
of blocks shown. Negative results are written with the same fields as positive ones.

Deliverable: `docs/research/rule-evaluation-<date>.md` with the baseline table, every
trial's train and validation results, the overfitting estimate, the selected identifiers,
and the count of holdout rounds still needed. Progress records the exact dataset manifest.

## Increment B5: holdout verdict (may wait)

When the holdout contains at least 60 clean traded rounds for each pre-selected rule,
evaluate once and apply the decision rule. If the capture is too short, the author returns
`waiting` with the shortfall stated in rounds. No rule change after reading the holdout is
allowed without a new registered rules file and a new holdout start.

## Increment B6: external history probe (bounded, optional)

Download one PMXT hourly file for a chosen hour, check whether the BTC five-minute tokens of
that hour appear, and measure gap counts. Record the result. If coverage is good, propose a
later increment that evaluates only market-price rules (H5 and the market baselines) over
months, with official labels from the public Gamma API. Spot-versus-reference rules cannot
use that source because it has no opening reference. No bulk import in this plan.

## Deferred and out of scope

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

- **Selection bias from many trials**: fixed grid of 25 trials, trial count in the file,
  overfitting estimate, one holdout read.
- **Optimistic fills**: taker only, walk displayed depth, latency, extra slippage, no maker
  credit, exclusion of gap-affected exits, and a live-stage risk register covering ghost
  reverts (more than 24% of filled orders reverted at peak hours in the cited study).
- **Label leakage**: labels come only from official final references; the H3 rule is
  tested against a leaked future tick.
- **Reference drift**: rounds whose opening reference status is not official or boundary
  are excluded from every rule and counted.
- **Rule change at the venue**: the settlement rule was rechecked today; the dataset stores
  it per round, and a rule with a different settlement source is excluded rather than
  approximated.
- **Sample size**: at current entry rates the holdout may take weeks. The plan returns
  `waiting` rather than lowering thresholds.

## Integration verification

Each increment runs `bash scripts/autopilot-gate.sh` through the shared verification
semaphore: lock check, full pytest, Ruff lint and format, mypy and shell syntax. Reviewers
also expect: no file under `/home/vilius/.local/share/btc5m` modified (compare modification
times before and after a real-archive build), no new runtime dependency in `pyproject.toml`,
and a progress entry with the manifest counts for every real-archive run.
