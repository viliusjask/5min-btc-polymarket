# Plan: is there a defensibly profitable subset of short-term strategies?

> Reopened for Fable/Astra review after local-work reconciliation on 2026-09-13.
> The earlier approval predates the recovered history/storage implementation.
> Reassess reuse and acceptance checks before further BUILD work; see docs/progress.md.

2026-09-13, revision 5. Branch `chore/btc-autopilot`, worktree `.worktrees/autopilot`, base
`cb7827b`. Authored by the PLAN stage of the unattended runner from the objective in the
ignored inbox. Evidence is in [the evidence register](../research/profitability-evidence-2026-09-13.md)
and [the photo register](../research/reference-photos-2026-09-13.md). Revision 1 (`08fbf74`)
received seven findings, revision 2 (`6b7de88`) six, revision 3 (`f9bcc48`) three and
revision 4 (`23167db`) two from the independent PLAN review; every one is answered below and
the affected sections were rewritten.

## Answers to the review of revision 4

| Finding | Where it is answered | What changed |
|---|---|---|
| P2 the stressed exit fixture reused the standard timeline's first sale at `T + 600`, which under 750 ms latency precedes activation (`T + 750`) and carries a book stamped `T + 500` that fails book activation, so the second attempt at `T + 1,350` and the five-share residual could not occur | [Entry and exit transitions](#entry-and-exit-transitions-residual-inventory-and-attempts) | The stressed fixture has its own timeline. The `T + 600` frame yields nothing under stress (frame before activation and book before activation); the first sale is a `T + 900` frame with a book stamped `T + 850`; attempt 2 activates at `T + 1,650`; the remainder sells on the `T + 2,300` frame. The same six frames under standard latency sell at `T + 600` and complete at `T + 900`, which is the paired proof that stress delays the first attempt and the completion. The failing variant's book is now stamped `T + 1,600`, below the recomputed activation. Expected values (`exit_delay_ms` 900 versus 600, `exit_completion_ms` 2,300 versus 900) are stated for both runs. |
| P2 `day_bootstrap` had to report `partially_labeled` days but received only observed rows and the set of traded days, so a day holding labeled and unlabeled entered rounds was indistinguishable from a fully labeled day | [Day-block bootstrap](#day-block-bootstrap-new-function) | The `traded_days` set is replaced by `entered_by_day`, a mapping from UTC day to the number of entered rounds that day, which `summarize` already has. A day whose row count in the population is below its entered count is `partially_labeled`; a day with entered rounds and no rows is `unlabeled_only`; a day with more rows than entered rounds, or rows on a day absent from the mapping, raises `BOOTSTRAP_ROWS_MISMATCH`. `expected_rows` stays and must equal the sum of the mapping in the decision run. Paired fixture: adding one unresolved trade to an already traded day leaves the observed rows, `expected_rows`, coverage and included days unchanged and flips `partially_labeled` from 0 to 1; the same change in the decision run adds one full-loss row and leaves `partially_labeled` at 0. |

## Answers to the review of revision 3

| Finding | Where it is answered | What changed |
|---|---|---|
| P1 a frame inside the window could carry the decision-time book and pass the five-second freshness test, crediting liquidity a live order would never have seen | [Execution validity](#execution-validity) | Every order is a sequence of attempts with an `activation_ms`. A new fifth test, **book activation**, requires the consumed token's book to satisfy `min(timestamp_ms, received_ms) >= activation_ms`, the same lower bound `PaperBroker._immediate` applies (`src/btc5m/paper.py:245`). Freshness relative to the frame (test 3) is no longer enough. Failure reason `BOOK_BEFORE_ACTIVATION`; an entry whose whole window carries pre-activation books is `unfilled_book_before_activation` and counted. Fixtures: three frames carrying the decision-time book give no entry; the same followed by a genuinely newer, worse book fills at the worse price; the same with the newer book after the deadline gives no entry; a book with one stamp before activation fails; the stressed latency moves the boundary. |
| P2 exits had to be inside `decision + 2000` and also retry until expiry, which no frame could satisfy | [Execution validity](#execution-validity), [Entry and exit transitions](#entry-and-exit-transitions-residual-inventory-and-attempts) | Entry and exit timing are now separate rows of one table. An entry has one attempt, window `[decision + latency, decision + 2000]`. An exit's first attempt activates at `trigger + latency` and every later attempt (one per fill event) activates at the previous fill frame's `now_ms + latency`, paying latency again; the deadline of every exit attempt is the last frame before `end_s`. `exit_delayed` means the first fill came after `trigger + 2000` (or never); `exit_delay_ms`, `exit_completion_ms` and `exit_attempts` are recorded on every exited round. The book-activation test replaces the separate depth-consumption rule, because a retry's activation lies after the previous fill frame. Fixtures: a first exit fill at 2,400 ms; a 7-of-12 sale at 600 ms whose remainder sells at 2,300 ms without the delayed flag. |
| P2 the descriptive bootstrap received labeled rows but the row-count check used the entered count | [Day-block bootstrap](#day-block-bootstrap-new-function) | `day_bootstrap(rows, *, coverage, traded_days, expected_rows)` (revision 5 replaced `traded_days` with `entered_by_day`; see the table above). The decision run passes every entered round with `expected_rows = entered`; the descriptive run passes labeled entered rounds with `expected_rows = labeled`. A day in `traded_days` that has no row in the descriptive population is `unlabeled_only`: excluded and counted, neither a zero nor missing. The adapter asserts the decision run's `expected_rows` equals the decision table's `entered`. Fixtures: the mixed five-round fixture run through both calls (4 rows and 3 rows), a wrong count raising, and a day holding only unresolved trades. |

## Answers to the review of revision 2

| Finding | Where it is answered | What changed |
|---|---|---|
| P1 H6 coefficients were due before a cutoff that passes at the start of B1; B1 extracted holdout rows before B4 forbade reading them | [Freeze record and sequence](#the-freeze-record-and-the-four-step-sequence), [B1](#increment-b1-round-dataset-extraction), [B4](#increment-b4-chronological-protocol-and-the-first-report), [B5](#increment-b5-holdout-verdict-may-wait) | The freeze fixes what development may see (frame high-water, cutoff); it sets no deadline for any later step. `dataset build` writes train and validation rows only and stops at the freeze high-water. Holdout rows are extracted only by `dataset build-holdout`, which refuses to run without a committed selection record. Selection, including H6's final coefficients, runs on the fixed development dataset at any later time. Tests: development builds at freeze time and after 200 more rounds have the same SQLite content hash and row counts; holdout extraction is refused before the selection record and afterwards contains only rounds at or after `holdout_start_ms`; the freeze command refuses to overwrite; a selection made three days after the cutoff equals one made one minute after. |
| P1 fill eligibility omitted source age, the validity flag, crossed books and markets not accepting orders | [Execution validity](#execution-validity) | A fill frame must pass the engine's own `strategy._safety_reason` recomputed from the tape frame at fill time, plus the window, same-round and ladder-side tests. That function rejects stale or future source and receipt stamps for both books and both prices, inactive or non-accepting markets, wrong or expired rounds, token mismatch, a missing side and a crossed book. The `ticks.rejection` column is screening only. Fixtures: one valid decision followed by each of ten invalid execution snapshots, plus a hand-edited `rejection` column that changes nothing. |
| P1 partial depth left exit residuals, retries, proceeds and settlement undefined | [Entry and exit transitions](#entry-and-exit-transitions-residual-inventory-and-attempts) | Entry is one attempt. An exit sells what the bid ladder shows, keeps the residual as inventory, retries only on a frame whose book source timestamp is newer than the last consumed one, holds a residual below the five-share minimum to settlement, and accumulates proceeds. Net equals proceeds plus settlement payout minus cost basis; share conservation is asserted. Fixtures: 7 of 12 then 5; 9 of 12 with a 3-share residual under a matching label, a losing label and no label; an unchanged book yields no second fill. |
| P2 `RoundResult`/`performance` cannot carry a null net or count no-trade rows | [Result rows and the adapter](#result-rows-and-the-adapter-to-performance) | New `EvaluatedRound` rows with `observed_net: Decimal | None` and `sensitivity_net: Decimal`. `summarize` builds two `RoundResult` lists (labeled entered rounds; all entered rounds at sensitivity net) and passes only entered rounds to `performance`; not-entered rounds are counted apart. Costs are applied once inside the evaluator; the decision rule reads only the stressed run. One fixture holds a labeled win, a labeled loss, an unlabeled entry, a no-trade round and a partially exited round. |
| P1 H6 training admitted labels received after the fold's fitting cutoff | [H6 protocol](#h6-fitted-combination-separate-leakage-free-protocol) | Each fold has `fit_cutoff_ms` equal to its start minus the 30-minute purge. A round trains fold k only if it ended and its `label_received_ms` is at or before that cutoff; standardization uses the same set; late labels enter later folds. Test: a pre-fold round whose label arrived after the cutoff can have its label flipped without changing fold k's model, and the same flip changes fold k+1. |
| P2 the day bootstrap dropped traded low-coverage days | [Day-block bootstrap](#day-block-bootstrap-new-function) | Every day with an entered round is included whatever its coverage; the 144-slot rule decides only whether a day with no entered round is a genuine zero or missing. The bootstrap's entered-round total must equal the decision table's count (the function raises otherwise). The decision run uses sensitivity nets; the observed-only run is descriptive. Fixture: a 100-slot day holding one USD -4.50 loss is included and raises `negative_fraction`. |

## Answers to the review of revision 1

| Finding | Where it is answered | What changed |
|---|---|---|
| P1 holdout begins before validation ends; no approval commit exists | [Freeze record](#the-freeze-record-and-the-four-step-sequence), [B4](#increment-b4-chronological-protocol-and-the-first-report) | One persisted freeze record, written by the first BUILD action, defines the cutoff. Validation is capped strictly before the purged cutoff by round start, frame cursor and label receipt. Tests cover capture advancing between freeze, extraction and selection. |
| P1 depth summaries cannot reconstruct USD-sized book walks | [B1 ticks](#increment-b1-round-dataset-extraction), [B2 fill walk](#fills-walk-the-full-ladder) | Fills read the full price/size ladders from the checksummed tape frame through a verified route (tape identity, frame ident, frame checksum). Summary columns are for screening only and are tested to have no effect on fills. Each baseline walks its own outcome token's ladder. |
| P1 no decision-to-fill deadline, stale books, expiry, partial depth, residual positions | [B2 execution validity](#execution-validity) | An entry order is live from decision plus latency to decision plus 2,000 ms, only on fresh books of the same market before expiry; exit orders have their own attempt timing (revision 4). Unfilled entries leave no position. Every entered round is preserved: delayed exits fill at the next valid frame or hold to settlement. Unlabeled entered rounds enter a full-loss sensitivity that the decision rule must pass. |
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
| Entered rounds | at least 60, every one preserved in the result, including partial, delayed, forced-settlement and unlabeled ones | Below that a single day dominates; this is an operating floor, not a power calculation |
| Net after the stressed cost model | greater than zero | The stressed model adds one cent per share and 750 ms latency to recorded fees; it is applied once, inside the evaluator |
| Missing-outcome sensitivity | the stressed run's `sensitivity` net is still greater than zero when every unlabeled entered round pays nothing at settlement | A missing label must never remove a possible loss from the verdict |
| Dependence on outliers | net after removing the three largest wins is still greater than zero | Avoids a verdict resting on one lucky payout |
| Day-block bootstrap | on sensitivity nets: status `descriptive` (at least six included days, at least 60 entered rounds) and fewer than 25% of resamples have a mean net per entered round at or below zero | Descriptive uncertainty; not a significance test |
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

## The freeze record and the four-step sequence

A read-only reviewer creates no commit, so approval time cannot be the boundary. The
boundary is a committed freeze record, and BUILD follows one sequence:

| Step | Command | Reads | Writes | Refuses when |
|---|---|---|---|---|
| 1 Freeze | `btc5m dataset freeze --source capture.sqlite --output docs/research/freeze-<date>.json` | tape `meta` only | the freeze record, committed | the output path exists (`FREEZE_EXISTS`) |
| 2 Build development | `btc5m dataset build --source capture.sqlite --freeze FILE --output DIR` | frames with ident at or below the freeze high-water | `dataset.sqlite` with train and validation rows only | the tape identity differs from the record, or the record's stored SHA-256 does not match its content |
| 3 Select | `btc5m dataset evaluate --split train`, `--split validation`, then `btc5m dataset select` | the development dataset only | `docs/research/selection-<date>.json`, committed | the dataset manifest does not name a committed freeze record |
| 4 Holdout | `btc5m dataset build-holdout --source capture.sqlite --freeze FILE --selection FILE --output DIR`, then `btc5m dataset evaluate --split holdout` | frames with ident above the freeze high-water, rounds at or after `holdout_start_ms` | `holdout.sqlite`, the verdict report | no committed selection record (`SELECTION_RECORD_REQUIRED`), or its rules, freeze or manifest hashes differ (`SELECTION_HASH_MISMATCH`) |

The freeze fixes what development may see. It sets no deadline for any later step. Steps 2
and 3 can run days or weeks after step 1 and read the same rows, because the development
build stops at the freeze high-water and at `validation_end_ms`. Holdout rounds accumulate
in the tape meanwhile (the collector keeps capturing), but no code extracts them until step
4, and step 4 cannot start without the committed selection record. Revision 2 required
H6's coefficients "before the freeze cutoff is crossed"; that requirement was unachievable
and is gone. The only ordering rule is: selection record committed before any holdout row
is extracted.

The freeze command opens the tape read-only and writes a record with the tape identity, the
tape high-water frame ident, the tape `last_ms`, the wall clock, the code identity, and the
record's own SHA-256 over the other fields. From those it derives and stores:

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
| Holdout | at or after `holdout_start_ms` | ident above freeze high-water, read only by `build-holdout` | any official label present at holdout build time |

A round whose label arrives after the freeze is *unlabeled* for train and validation, even
if a later tape has it. A round in progress at the freeze (start before `cutoff_ms`, end
after `last_ms`) is unlabeled in development and lies inside the purge, so nothing scores
it. Rounds captured between PLAN approval and the freeze fall in validation; nothing has
scored them because the evaluator does not exist until B2. The development file holds no
round at or after `validation_end_ms`; `evaluate --split holdout` runs only against a
`holdout.sqlite` produced by step 4. No selection, coefficient or report may be computed on
a dataset whose manifest does not reference a committed freeze record.

Tests for the sequence (B1, B4 and B5), all on synthetic tapes:

- Development determinism: freeze at high-water H; build; extend the tape by 200 rounds, a
  late label for a development round and a label for a holdout round; build again. The two
  development files have the same SQLite content hash, the same row counts and the same
  unlabeled count; the late-labeled round is still unlabeled.
- Holdout isolation: `build-holdout` on the extended tape without a selection record exits
  `SELECTION_RECORD_REQUIRED`; with a record whose rules hash differs, `SELECTION_HASH_MISMATCH`;
  with the matching record it holds only rounds starting at or after `holdout_start_ms`, and
  the intersection of its slugs with the development file's slugs is empty.
- Boundary immutability: `dataset freeze` against an existing output exits `FREEZE_EXISTS`
  and leaves the file unchanged; a record whose `cutoff_ms` was edited by hand fails the
  stored SHA-256 check in `build`; the manifest stores the record hash and `evaluate`
  recomputes it.
- Late BUILD: `select` run with a wall clock three days after `cutoff_ms` produces a record
  identical, apart from `created_ms`, to one run one minute after it, on the same
  development file.
- A dataset built without a freeze record is rejected by `evaluate`.

## Increment B1: round dataset extraction

Add `btc5m dataset build --source capture.sqlite --freeze FILE --output DIR` (step 2).
It opens the source read-only, checks the tape identity and the record hash against the
freeze record, streams frames from the first cursor to the **freeze high-water** (never the
tape's current high-water), keeps only rounds starting before `validation_end_ms`, and
writes one SQLite file with:

- `rounds`: one row per market slug with start/end, verified opening reference and its
  status, settlement source, fee rate and exponent, tick size, minimum order, official final
  label, `label_frame_ident` and `label_received_ms` (the `now_ms` of the tape frame that
  carried the label), the split name derived from the freeze record, and the count of valid
  frames.
- `ticks`: one row per frame per round with the frame ident, seconds remaining, spot, TWAP60,
  the observed final-minute integral, short and long sigma estimates as the engine computes
  them, best bid and ask for both tokens, cumulative displayed depth at 5, 25 and 100 shares
  (screening and reporting only), book source and receipt timestamps, exchange lead if
  aligned, and `rejection`, the value of `strategy._safety_reason` for that snapshot (null
  when tradable). The full ladders are **not** copied; they are read from the tape frame by
  ident at fill time (see B2), where `rejection` is recomputed rather than trusted.
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

`btc5m dataset build-holdout` (step 4) is the same extractor with the opposite bounds: frames
with ident above the freeze high-water, rounds starting at or after `holdout_start_ms`,
labels from any frame present at build time. It writes `holdout.sqlite` with the same
schema, and it refuses to run without a committed selection record whose hashes match. It
is implemented in B1 so that its refusal is tested from the start, but it is first run for
real in B5.

Tests (synthetic tapes built the way `tests/test_lab_tape.py` builds them):
a three-round tape with a gap produces exact row counts and a null-label round; resume
after an interrupted build appends nothing twice; a rejected snapshot yields a tick row
flagged invalid, not a fabricated book; the final-minute integral matches `strategy.py` on a
hand-computed path; the freeze-boundary tests listed above; a build against a tape whose
identity differs from the freeze record is refused.

Acceptance: a read-only development build against the real archive completes, its manifest
shows no round at or after `validation_end_ms`, and its counts (rounds, labeled rounds,
ticks, gap rounds, per split) are recorded in `docs/progress.md` together with the committed
freeze record's cutoff.

## Increment B2: rule evaluator, cost model and baselines

Add `btc5m dataset evaluate --dataset DIR --source capture.sqlite --rules FILE --split NAME --output DIR`.
`--split train` and `--split validation` open `DIR/dataset.sqlite`; `--split holdout` opens
`DIR/holdout.sqlite` and nothing else, so a development file can never be scored as holdout
and a holdout file can never be scored as development (the manifest names its own split
set and the evaluator checks it).
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

A fill frame is chosen from the tape, never from the `ticks` summaries. Every order is a
sequence of **attempts**. An entry order has exactly one attempt. An exit order has one
attempt per fill event (the next section explains how a partial sale opens the next one).
Each attempt has an `activation_ms`, the earliest instant a venue order could act on a book,
and a `deadline_ms`, the latest frame it may consider:

| Order | Attempt | `activation_ms` | `deadline_ms` |
|---|---|---|---|
| Entry | the only one | `decision_ms + latency_ms` | `decision_ms + 2000` |
| Exit | first | `trigger_ms + latency_ms`, where `trigger_ms` is the `now_ms` of the tick that fired the stop, target or time rule | the last frame with `now_ms < end_s * 1000` |
| Exit | each later one | the previous fill frame's `now_ms + latency_ms` | the same |

Latency is 250 ms (standard) or 750 ms (stressed) and is paid again on every attempt. The
entry deadline is tighter than the paper broker's execution-gap limit of `max_book_age_ms`
(5,000 ms, `src/btc5m/paper.py:241`); the evaluator prefers a not-entered round to a fill
that a live order would not have obtained.

The evaluator applies five tests to each candidate frame of an attempt, in this order, and
records the first failure as the reason:

1. **Window**: `activation_ms <= now_ms <= deadline_ms`.
2. **Same round**: the frame has a snapshot and its market slug equals the round's slug. A
   frame without a snapshot fails with `NO_SNAPSHOT`.
3. **Engine safety**: `strategy._safety_reason(snapshot, config)` returns `None`, computed
   from the tape frame at fill time with the evaluator's `Config` (defaults; the manifest
   records the values used). That function rejects, in order: an unsupported settlement
   source; a wrong or expired round (`start_s` must equal the round boundary containing
   `now_ms`, so a frame at or after `end_s` fails here); an inactive market; a market not
   accepting orders; a conflicting, missing, boundary-disabled or mis-timed opening
   reference; an unsupported tick; future-stamped metadata; any spot, TWAP or book whose
   source `timestamp_ms` or `received_ms` lies outside `[now_ms - max age, now_ms +
   future_tolerance_ms]` (5,000 ms for books, `max_price_age_ms` for prices); a book whose
   token id is not the market's; a book missing a side; and a crossed book
   (`src/btc5m/strategy.py:86`). `PaperBroker._book` applies the same age, future and
   crossed tests (`src/btc5m/paper.py:80`). The dataset's `ticks.rejection` column holds the
   same value for screening, but the evaluator never reads it for a fill.
4. **Book activation**: the book of the token being consumed satisfies
   `min(book.timestamp_ms, book.received_ms) >= activation_ms`. This is the lower bound
   `PaperBroker._immediate` applies before it walks a book (`src/btc5m/paper.py:245`). Test 3
   only proves the book is less than five seconds old relative to the frame. A frame at
   `decision_ms + 750` can still carry the book that was displayed at `decision_ms`, and
   that liquidity may be gone by the time an order arrives; crediting it would understate
   slippage. A book with either stamp before activation fails with `BOOK_BEFORE_ACTIVATION`.
   Because each later exit attempt activates after the previous fill frame's `now_ms`, and
   the book sold into on that frame has stamps at or below that `now_ms`, this test also
   guarantees that a retry consumes a strictly newer book. Two frames carrying the same book
   therefore yield one fill.
5. **Ladder side**: the side being consumed (asks for a buy, bids for a sell) has at least
   one level.

A frame failing any test is skipped and the next frame at or before the deadline is tried.
If no frame passes, an entry is `unfilled` with the reason `unfilled_no_frame` (no frame at
all in the window) or `unfilled_<last reason>` (for example `unfilled_book_before_activation`
when every frame in the window carried a pre-activation book), and the round is reported as
not entered. An exit attempt with no passing frame before `end_s` leaves the remaining
inventory to settlement (next section). Every report counts not-entered reasons separately,
because skipping rounds whose book did not refresh within two seconds selects on liquidity
activity and that selection must stay visible.

| Cost item | Standard | Stressed |
|---|---|---|
| Latency | 250 ms | 750 ms |
| Fee | `fee_for(shares, price, fee_rate, fee_exponent)` per level, taker on every leg | same |
| Extra slippage | none | one cent per share on each executed leg |

Tests: one valid decision at 90 s remaining followed by each of these execution snapshots
gives no entry fill and the named reason: book source timestamp 6,000 ms old with a fresh
receipt (`STALE_DATA`); receipt 6,000 ms old with a fresh source stamp (`STALE_DATA`); a
crossed book (`CROSSED_BOOK`); `accepting_orders` false (`MARKET_NOT_ACCEPTING`); `active`
false (`MARKET_INACTIVE`); the next round's market (`WRONG_ROUND`, which also covers a frame
after `end_s`); a book whose token id belongs to the other market (`BOOK_TOKEN_MISMATCH`);
an empty bid side on an exit (`MISSING_BOOK_SIDE`); a book received 1,000 ms in the future
(`FUTURE_DATA`); a frame without a snapshot (`NO_SNAPSHOT`). A frame whose `ticks.rejection`
was hand-edited to null is still rejected because the reason is recomputed from the tape; a
frame whose `rejection` was hand-edited to `STALE_DATA` still fills when the tape frame is
valid. The earlier fixtures stay: an outage spanning the entry window yields no position; the
fee on a 0.90 fill equals 0.0063 per share; a 750 ms latency picks a later frame with a
worse price; the same rule on the same dataset gives identical output twice.

Book-activation fixtures, all with one valid decision at `D` (90 s remaining) and standard
latency (activation `D + 250`): frames at `D + 300`, `D + 900` and `D + 1,500` whose up
book carries source and receipt stamps equal to `D` (the book never changed) give no entry
and the reason `unfilled_book_before_activation`, although every frame passes test 3; the
same three frames followed by a frame at `D + 1,800` whose up book is stamped `D + 1,700`
with a best ask one tick worse fill at that worse price, and the fill record names the frame
ident and both book stamps; the same frames with the fresh book on a frame at `D + 2,100`
give no entry (`unfilled_book_before_activation`, since the last frame fails the window
first and the recorded reason is the last frame inside the window); a frame at `D + 600`
whose up book has `received_ms` `D + 400` but `timestamp_ms` `D - 100` fails test 4 (both
stamps must reach activation); under the stressed model (activation `D + 750`) a frame at
`D + 800` carrying a book stamped `D + 700` fails and a frame at `D + 900` carrying a book
stamped `D + 850` fills.

### Entry and exit transitions, residual inventory and attempts

| Transition | Rule |
|---|---|
| Entry | One order, one attempt, at most one fill frame. Walk the asks level by level until the USD budget is spent; the quantity at each level is rounded down to whole shares. If the total is below `min_order_size` (5 shares) the entry is `unfilled_thin` and the round is not entered. Otherwise the position is the walked quantity; if the ladder ran out before the budget did, the round is flagged `partial`. There is no entry retry. Cost basis = principal + entry fees. |
| Exit trigger | The stop, target or time rule is tested on every valid tick after the entry fill frame. The first trigger opens one exit order for the whole inventory; `trigger_ms` is that tick's `now_ms`. Hold-to-settlement policies open no exit order. |
| Exit fill | The first attempt activates at `trigger_ms + latency_ms`. At the first frame passing all five tests, walk the bids: sell whole shares level by level until the inventory or the displayed depth is exhausted. Fees per level through `fee_for`. Proceeds accumulate. Inventory decreases by the shares sold. One frame yields at most one fill event. |
| Residual | If inventory remains and is at least 5 shares, the next attempt starts, activating at the fill frame's `now_ms + latency_ms`. It pays latency again and can fill only on a book whose stamps reach that activation (test 4), so it never sells into the ladder it already consumed. If inventory is below 5 shares, no venue order can sell it: it is flagged `residual_below_minimum` and holds to settlement. |
| Exit end | Attempts continue until the last frame before `end_s`. Inventory remaining then holds to settlement, flagged `exit_forced_settlement`. Exits have no 2,000 ms deadline; that number only defines whether the exit was prompt. |
| Exit timing record | Every exited round records `exit_attempts`, `exit_delay_ms = first_fill.now_ms - trigger_ms` and `exit_completion_ms = last_fill.now_ms - trigger_ms` (both null when nothing sold). `exit_delayed` is true when the first fill's `now_ms` exceeds `trigger_ms + 2000` or when no fill occurred before `end_s`. A later attempt that fills after `trigger_ms + 2000` does not set the flag by itself; its lateness is visible in `exit_completion_ms` and the report lists the distribution of both durations. |
| Settlement | Held inventory (forced, residual or hold-to-settlement) pays 1.00 per share if the official label matches the held side and 0 otherwise. With no label, the round's observed net is null and its sensitivity net treats the held inventory as paying 0. |
| Net | `observed_net = proceeds + settlement payout - cost basis`; `sensitivity_net` is the same with payout 0 when unlabeled. Both are `Decimal`. |
| Conservation | `entry_shares == sold_shares + settled_shares` on every round. The evaluator asserts it and every fixture checks it. |

Every entered round is therefore present in the result table exactly once. Nothing entered
is dropped for a gap, an outage or an expiry. Flags describe path quality; the decision rule
uses all entered rounds.

Tests, all with standard latency unless stated, `T` the trigger tick's `now_ms`:

- Two attempts, prompt first fill: a 12-share position; a frame at `T + 600` with a bid book
  stamped `T + 500` showing 7 shares sells 7 (attempt 1); attempt 2 activates at `T + 850`;
  a frame at `T + 1,200` carrying the same book (stamps `T + 500`) yields nothing
  (`BOOK_BEFORE_ACTIVATION`); a frame at `T + 2,300` with a book stamped `T + 2,200` showing
  5 sells the remaining 5 after the two-second mark. Expected: two fill events,
  `exit_attempts` 2, `exit_delay_ms` 600, `exit_completion_ms` 2,300, `exit_delayed` false,
  proceeds equal to both walks minus both fees, inventory 0.
- First fill after two seconds: frames at `T + 400`, `T + 1,200` and `T + 1,900` all carry a
  bid book stamped `T - 100`; the first fresh book (stamped `T + 2,350`) arrives on a frame at
  `T + 2,400` and holds the whole inventory. Expected: one fill event, one attempt,
  `exit_delayed` true, `exit_delay_ms` 2,400, `exit_completion_ms` 2,400.
- Stress delays the first attempt and the completion (latency 750, activation `T + 750`):
  a 12-share position and six frames. Frame `T + 600` carries a bid book stamped `T + 500`
  showing 7: nothing sells, because the frame precedes activation and the book fails test 4.
  Frame `T + 900` carries a book stamped `T + 850` showing 7: sells 7 (attempt 1). Attempt 2
  activates at `T + 1,650`. Frame `T + 1,200` carries the same `T + 850` book: nothing
  (`BOOK_BEFORE_ACTIVATION`). Frame `T + 2,300` carries a book stamped `T + 2,200` showing 5:
  sells the remaining 5. Expected under stress: two fill events, `exit_attempts` 2,
  `exit_delay_ms` 900, `exit_completion_ms` 2,300, `exit_delayed` false, proceeds equal to
  both walks minus both fees minus one cent per share on each leg, inventory 0. The same
  six frames under standard latency (activation `T + 250`) sell 7 on the `T + 600` frame,
  activate attempt 2 at `T + 850`, and sell the remaining 5 on the `T + 900` frame because
  its book stamp `T + 850` reaches that activation: `exit_delay_ms` 600,
  `exit_completion_ms` 900, `exit_attempts` 2. The fixture asserts both runs side by side;
  latency is the only input that differs.
- Remainder held under stress: the stressed timeline above with the `T + 2,300` frame's book
  stamped `T + 1,600` instead of `T + 2,200` does not sell (activation `T + 1,650`); if no
  later frame qualifies, the 5 shares are `exit_forced_settlement`, `exit_attempts` 2,
  `exit_delay_ms` 900, `exit_completion_ms` 900 and `exit_delayed` false. Under standard
  latency the same variant completes at `T + 900` as before, so the forced settlement is
  caused by the stress model alone.
- Residual below minimum: a 12-share position into depth of 9 leaves 3 shares
  (`residual_below_minimum`, `exit_attempts` 1), and the net is checked under a matching label
  (payout 3.00), a losing label (0) and no label (observed null, sensitivity payout 0).
- Same book twice: two consecutive frames with identical book stamps after one sale produce
  one fill event.
- Outage to expiry: an outage lasting to `end_s` after a partial sale yields
  `exit_forced_settlement`, `exit_delayed` false (the first fill was prompt), and the residual
  settled by label.
- Entry depth: a USD 20 entry into a three-level ladder showing 12 shares yields a 12-share
  `partial` entry whose cost basis equals the hand-computed walk; a ladder showing 4 shares
  yields `unfilled_thin`.
- Outage at the trigger: an outage during a stop trigger yields a delayed exit at a worse bid
  with `exit_delayed` true.
- A labeled loss is a full loss; an unlabeled entered round is counted and its sensitivity
  net equals minus its cost basis; share conservation holds on every fixture above.

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

Results are split by settlement distance (near-even versus decided) because of the
manipulation finding. Rows and summaries use the adapter below.

### Result rows and the adapter to `performance`

`RoundResult.net` is a `Decimal`, and `performance` sums every row's net and uses every row
as its denominator (`src/btc5m/research.py:25` and `:41`). It cannot carry a null net and
must not receive no-trade rows. The evaluator therefore has its own row type and a bounded
adapter, both in a new module `src/btc5m/rule_eval.py`:

- `EvaluatedRound`: slug, `start_ms`, split, rule id, cost model, `entered` (bool),
  `not_entered_reason`, `decision_ms`, side, entry fill (frame ident, shares, principal,
  fees), `trigger_ms`, exit fill events (list, each with frame ident, both book stamps,
  shares, principal, fees), `exit_attempts`, `exit_delay_ms`, `exit_completion_ms`,
  `settled_shares`, label, `observed_net: Decimal | None`, `sensitivity_net: Decimal`, total
  fees, and flags (`partial`, `exit_delayed`,
  `exit_forced_settlement`, `residual_below_minimum`, `unlabeled`).
- `summarize(rows)` returns counts (`rounds`, `entered`, `not_entered` by reason, `labeled`,
  `unlabeled`, each flag) and two `performance` results: `observed`, from `RoundResult` rows
  of labeled entered rounds with `net = observed_net`, and `sensitivity`, from `RoundResult`
  rows of all entered rounds with `net = sensitivity_net`. `RoundResult.uncertain` is set for
  flagged rounds; `used`, `complete` and `observed` are true for every adapted row so
  `research.usable` keeps them. Not-entered rounds never reach `performance`. The same
  adapter makes both `day_bootstrap` calls: the decision call with the sensitivity rows and
  `expected_rows = entered`, the descriptive call with the labeled rows and
  `expected_rows = labeled`, both with the same `coverage` and the same `entered_by_day`
  (the count of entered rounds per UTC day, which `summarize` computes from its own rows).
- The decision table shows `sensitivity.net / entered` (the strict form) beside
  `observed.net / labeled`.
- Costs are applied once. The stressed run is produced by the evaluator (750 ms latency plus
  one cent per share on every executed leg). `performance` also emits a `cost_stress` list;
  the report prints it only for the standard cost model, as headroom information, and the
  decision rule reads only the stressed run's `sensitivity.net`, `without_best_3` and the
  bootstrap on sensitivity nets.

Test: one fixture holding a labeled win (+4.00), a labeled loss (-3.00), an unlabeled entered
round with cost basis 5.00, a no-trade round, and a partially exited labeled round (7 shares
sold for 6.30 net of fees, 5 shares settled at 1.00, cost basis 9.60, so +1.70) gives
`rounds` 5, `entered` 4, `labeled` 3, `unlabeled` 1; `observed.rounds` 3 with net 2.70;
`sensitivity.rounds` 4 with net -2.30; `without_best_3` computed from the observed list; and
the stressed run's net lower than the standard run's by exactly one cent per executed share
plus the latency effect built into the fixture.

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

Protocol: five expanding chronological folds over the development rounds. Fold k scores
rounds starting in `[fold_start_k, fold_end_k)`. Its fitting cutoff is
`fit_cutoff_k = fold_start_k - 1800000` (the 30-minute purge). A round belongs to fold k's
training set only if all three hold: `start_ms + 300000 <= fit_cutoff_k` (it ended before the
cutoff); it has an official label; and `rounds.label_received_ms <= fit_cutoff_k` (the label
had arrived by then). Feature means, standard deviations and coefficients for fold k are
computed from that set alone. A round whose label arrived after `fit_cutoff_k` is unavailable
to fold k even if it started long before the fold, and becomes available to the first later
fold whose cutoff is at or after its receipt time. Fold k is scored on Brier versus the
market and on trading net under the stressed model, using the same evaluator and fill rules
as the fixed rules. The coefficients and standardization that go to the holdout are fitted
on every development round whose label frame ident is at or below the freeze high-water and
are written into the selection record in step 3 of the sequence, at whatever time step 3
runs. The falsifier is: Brier not below the market on the folds, or trading net not above
H1's best fixed rule on the same folds.

Tests: the H3 rule reads only ticks at or before its decision time (a leaked later tick
changes nothing); a rules file with a wrong trial count is rejected; CSCV on a synthetic
grid with one genuinely better rule returns a low probability and on pure noise returns
about 0.5. For H6: (a) a round starting before fold 3 whose `label_received_ms` is ten
minutes after `fit_cutoff_3` can have its label flipped without any change to fold 3's
means, standard deviations or coefficients, and the same flip does change fold 4's; (b) a
round starting inside fold 3's purge band is absent from fold 3's training set; (c) flipping
the label of a round inside fold 3's scoring block leaves fold 3's model byte-identical;
(d) the final coefficients ignore a development round whose label frame ident is above the
freeze high-water.

### Day-block bootstrap (new function)

`research.day_bootstrap(rows, *, coverage, entered_by_day, expected_rows)` where `rows` are
`(utc_day, net)` pairs, `coverage` maps UTC day to the number of observed round slots that
day, `entered_by_day` maps UTC day to the number of entered rounds that day (days with no
entered round are absent), and `expected_rows` is the count the rows must add up to. The
function compares each day's row count with its entered count, which is how it tells a
fully labeled day from a partly labeled one without seeing the unlabeled rows themselves.
The adapter in `rule_eval.summarize` calls it twice per rule, with different populations
and different expected counts:

| Run | Rows | `expected_rows` | Day in `entered_by_day` with fewer rows than entered rounds |
|---|---|---|---|
| Decision (sensitivity) | every entered round with its `sensitivity_net` | `summarize().entered` | cannot occur; every entered round has a sensitivity net, so every day's row count equals its entered count and the function raises `BOOTSTRAP_ROWS_MISMATCH` if `expected_rows` differs from the sum of `entered_by_day` |
| Descriptive (observed) | every labeled entered round with its `observed_net` | `summarize().labeled` | zero rows: `unlabeled_only`, excluded from the population and counted; some rows: `partially_labeled`, included with its labeled rows and counted; neither is a genuine zero nor a missing day |

- Unit: UTC day. Every day with at least one row is **included**, whatever its coverage;
  such a day with fewer than 144 observed slots is flagged `low_coverage_traded` and counted,
  and its rows stay in the population. A day with no entered round (absent from
  `entered_by_day`) is included as net 0, count 0 only if the capture observed at least 144
  of its 288 slots; otherwise it is **missing**, excluded and counted. The coverage rule
  therefore decides only whether a zero is a genuine zero. For a day present in
  `entered_by_day`, let `r` be its row count and `e` its entered count: `r == 0` makes it
  `unlabeled_only` (excluded and counted); `0 < r < e` makes it `partially_labeled`
  (included with its rows and counted); `r == e` is fully labeled; `r > e` raises
  `BOOTSTRAP_ROWS_MISMATCH`. Rows on a day absent from `entered_by_day` also raise.
- Invariant: `len(rows) == expected_rows`, or the function raises `BOOTSTRAP_ROWS_MISMATCH`.
  The adapter passes `entered` for the decision run and `labeled` for the descriptive run,
  and a test asserts that the decision run's `rows` output equals the decision table's
  `entered` count and the sum of `entered_by_day`, so the decision population, the decision
  table and the per-day counts cannot differ.
- Statistic: total net divided by the number of rows over the resampled days. A resample
  with zero rows counts as at or below zero.
- 2,000 seeded resamples of the included days with replacement.
- Output: included days, `low_coverage_traded` days, missing days, `unlabeled_only` days,
  `partially_labeled` days, `rows` (entered rounds for the decision run, labeled rounds for
  the descriptive run), mean per row, the 2.5th and 97.5th percentile of the statistic,
  `negative_fraction`, and a status that is `descriptive` only when at least six days are
  included and `rows` is at least 60; otherwise `insufficient_evidence`, which fails the
  decision criterion. The two runs may have different statuses.
- The decision criterion reads only the decision run, where an unlabeled entered round pays
  nothing at settlement. The descriptive run is printed beside it.

Tests: a fixture where a day with 100 observed slots holds one entered round with net -4.50
and five full-coverage days hold small wins: the low-coverage day is included and flagged,
the population contains the -4.50, and `negative_fraction` exceeds the value for the same
fixture with that round removed; a sparse fixture (nine days, three with one trade each)
reports the traded-round denominator and `insufficient_evidence`; a missing-day fixture with
no trade and 100 observed slots excludes that day and counts it; a row count that differs
from `expected_rows` raises; an all-negative fixture gives `negative_fraction` 1.0; a fixed
seed reproduces the percentiles; an included no-trade day lowers the mean per day but not
the mean per row. The mixed `summarize` fixture (five rounds, four entered, three labeled,
spread over three days with the unlabeled entry alone on its day) is run through both calls:
the decision call with `expected_rows` 4 includes three days and reports `rows` 4; the
descriptive call with `expected_rows` 3 includes two days and reports `unlabeled_only` 1 and
`rows` 3; the descriptive call with `expected_rows` 4 raises `BOOTSTRAP_ROWS_MISMATCH`; a
variant where the unlabeled entry is moved to the day of the labeled loss reports
`partially_labeled` 1, `unlabeled_only` 0 and two included days; and in the sensitivity
population the unlabeled day's rounds carry their full-loss nets. Paired fixture for the
flag: start from the mixed fixture's descriptive call (three rows on two days, `expected_rows`
3, `entered_by_day` `{A: 2, B: 1, C: 1}`, result `partially_labeled` 0, `unlabeled_only` 1).
Add one unresolved entered round to day A, so `entered_by_day` becomes `{A: 3, B: 1, C: 1}`
while the rows, `expected_rows`, `coverage` and included days are unchanged: the result is
`partially_labeled` 1, `unlabeled_only` 1, `rows` 3, the same included days and the same
percentiles for the same seed. The same added round in the decision call changes the rows
(five, with the new round at its full-loss net) and `expected_rows` (5) and leaves
`partially_labeled` 0. A descriptive call with `entered_by_day` `{A: 1, B: 1, C: 1}` against
the same three rows raises `BOOTSTRAP_ROWS_MISMATCH` (day A has more rows than entered
rounds), as does a row on a day the mapping does not contain.

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

Run step 4 of the sequence: `build-holdout`, then `evaluate --split holdout` once for the
selected rules and the baselines, and apply the decision rule. The entered-round count is
known only from that evaluation, so a short holdout is itself a read: the report is kept as
`insufficient_evidence` with the shortfall stated in rounds, the author returns `waiting`,
and a later evaluation on a longer holdout is allowed only with the same rules file, the
same selection record and the same freeze record (every holdout report is committed and
listed in progress). No rule change after reading the holdout is allowed without a new
registered rules file, a new selection record and a new freeze record, and any such restart
uses a holdout that begins after the new freeze.

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
- **Optimistic fills**: taker only, full-ladder walk from checksummed frames, a 2,000 ms
  entry deadline, latency paid on every attempt, a book-activation bound on every fill,
  extra slippage, no maker credit, preservation of every entered round with delayed or
  forced exits, a full-loss sensitivity for unlabeled entries, and a live-stage risk register
  covering ghost reverts
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
