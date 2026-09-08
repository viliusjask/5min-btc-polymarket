# Historical replay from the public archive

`lab run --start ... --end ...` runs a finite, exploratory backtest using the existing
`Study`, `Tape`, `Replay` and paper execution engine. It does not fetch external history,
contact an account, or alter the collector, the original six wallets or existing studies.
The source is opened read-only; results go into a new, separate study directory.

## Inspect saved data and choose configurations

```bash
.venv/bin/btc5m archive status \
  --source /home/vilius/.local/share/btc5m/paper-six-100-each/capture.sqlite

.venv/bin/btc5m lab variants --suite original-six \
  --config /home/vilius/.config/btc5m/paper-strategy-policy.toml
```

Status reads indexed first/last receipt times, tape identity, the last committed frame ID
(the **highwater**, a fixed upper limit for a replay), recorded gap counters, the first
research frame and the latest capture session's declared capabilities. It does not decode
or scan historical frame payloads. Counters describe only their explicitly instrumented
ranges; missing old counters are `not_instrumented`, not evidence of continuous coverage.
Database/WAL/SHM file sizes are sampled separately and can change while capture continues.
Status neither verifies every checksum nor certifies complete market history.

`lab variants` prints exact registered IDs and configurations without creating a runtime.
Choose `directional` for the existing 84 variants (`--dense` gives 354), `order-flow` for
the existing 17 variants, or `original-six` for the current six strategy modes. The last
suite copies the supplied `Config.strategy` with only `mode` changed; current Momentum
remains the configured recent-continuation strategy. It does not substitute an opening-lead
experiment. Execution settings stay unchanged.

Replay continues to use the existing snapshot/research inputs. Passive and inventory
simulations need the recorded public trade/queue evidence supported by that simulator;
older snapshot-only intervals cannot supply missing trade continuity. Additive raw archive
records preserve evidence but do not turn a rejected snapshot into a tradable one or
automatically reconstruct previously missing research inputs.

Original-six risk settings match `paper --strategies all`: total allocation divided by
six, rounded down to cents, and each daily/session loss limit capped at that wallet's
allocation. Thus the installed total-$600 configuration yields six $100 wallets, while
the repository's default total-$100 configuration yields six $16.66 wallets. Filtering
IDs does not redistribute capital. Other suites retain their existing independent $100
wallets. Results from overlapping variants are not a combined portfolio return.

## Run and resume a selected interval

First check that the desired interval is saved. This example selects entries from 06:00
through 06:59:59 UTC on September 8; both bounds must align to five-minute boundaries.

```bash
.venv/bin/btc5m lab run \
  --source /home/vilius/.local/share/btc5m/paper-six-100-each/capture.sqlite \
  --runtime /home/vilius/.local/share/btc5m/backtests/2026-09-08-six-0600-0700 \
  --config /home/vilius/.config/btc5m/paper-strategy-policy.toml \
  --suite original-six \
  --start 2026-09-08T06:00:00Z --end 2026-09-08T07:00:00Z

.venv/bin/btc5m lab report \
  --runtime /home/vilius/.local/share/btc5m/backtests/2026-09-08-six-0600-0700
```

Optionally add `--variants ID,OTHER_ID` using IDs from `lab variants` with the same suite,
configuration and dense setting. Unknown, duplicate or empty selections are rejected before
a manifest is written. Both times require an explicit timezone; `09:00:00+03:00` and
`06:00:00Z` are equivalent. Start is inclusive and end is exclusive. Reversed, unaligned,
empty or unsaved ranges are rejected; the end must already be at or before the archive's
last receipt. Existing non-study runtime directories are rejected. Historical runs cannot
use `--continuous` or `--explore-rounds`.

Resume with the same source, runtime and configuration, omitting the selection and bounds
or repeating them exactly. A different range, trial set, source identity or semantic code
requires a new study. The original default run/continuous behavior is unchanged. Pinned
old workers and their existing registrations remain on their own implementations.

At creation, the historical manifest freezes the source highwater and receipt endpoints.
An indexed timestamp seek skips old payloads before causal warmup: the longest selected
volatility window plus 60 seconds, normally 31 minutes. **Causal warmup** means using only
inputs already received before an entry; each snapshot keeps its originally visible
history. The report gives the requested warmup start, first available warmup receipt and
available receipt span. A short span or an internal gap is not fabricated into full coverage.
Order-flow warmup starts no earlier than actual research recording.

New entries stop at the selected end, but replay processes later already-recorded frames
through the frozen highwater for exits and official labels. It never substitutes a spot-price
guess for settlement. Runtime depends on the number of replayed frames and selected variants,
including this later exit/label suffix; the simulator has no artificial fast-forward fills.
Appended frames and labels, including malformed appended labels, are excluded on resume.

`report.json` includes `historical.complete`, frozen endpoints and `unresolved_variants`
with open-position, claimable-position and unresolved-order counts. A claimable payout
still awaiting paper redemption is reported as exposure with its claimable value.
Complete means all frozen frames were
processed; it does not mean every holding settled. An archive ending before the necessary
book/official label leaves exposure unresolved. Missing selected-round forecasts remain in
the denominator. The full report also retains uncertainty counts, reserves, open cost basis,
realized results and completed-round results. A gap cannot create an executable snapshot.

Historical results are always exploratory: automatic selection is disabled and `lab freeze`
rejects historical studies. Selecting old history cannot create a forward holdout (later,
unseen data reserved for testing). Start a separate ordinary study for that workflow.

## Explicit backup without deleting history

Nothing here prunes source data or backfills missing markets. Keep independent backups and
enough free disk space; the existing recorder and lab disk reserves remain active. For a
consistent backup while capture continues, use SQLite's backup API, not a plain copy of an
active database whose committed data may still be in its WAL file. Choose a new destination
on the backup filesystem; this example refuses to overwrite any existing file:

```bash
.venv/bin/python - <<'PY'
import os
import sqlite3
from contextlib import closing
from pathlib import Path

source = Path('/home/vilius/.local/share/btc5m/paper-six-100-each/capture.sqlite')
destination = Path('/path/to/independent-backup/capture-2026-09-08.sqlite')
fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(fd)
with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as src:
    with closing(sqlite3.connect(destination)) as dst:
        src.backup(dst, pages=256, sleep=0.05)
        assert dst.execute('PRAGMA integrity_check').fetchone() == ('ok',)
print(destination)
PY
```

A failed/interrupted backup may leave an incomplete destination; do not treat it as verified
or overwrite an earlier good backup. Also back up `observations.sqlite` separately: older accepted oracle ticks during invalid
snapshots can exist there even when absent from `capture.sqlite`. Preserve the configuration, pinned source and
derived study directories needed to explain existing results. The source tape backup is
not a transactionally coordinated backup of every independent study journal.

## Verification

Synthetic regressions cover finite entries with later settlement, unresolved archive-end
and claimable exposure, restart/cursor rollback, excluded appended malformed labels, exact original-six
risk/strategy/execution configuration, immutable selected IDs, invalid ranges, and bounded
status/seek/forecast operations. A 10,000-row fixture with a 1,000 SQLite-instruction budget
catches payload/forecast-table scans. Existing lab, tape, replay, split, scoring and CLI
tests remain the compatibility checks. Integration owns the combined full suite and the
read-only actual-source replay evidence; these synthetic tests are not live profitability
evidence. Do not edit semantic source files while study tests run: their intentional code
identity check rejects a resume if the implementation changes between test steps.

September 8 verification: 117 focused lab/replay/tape/variant/scoring/split/CLI tests
passed before the last reporting-edge regressions; the final historical/study group then
passed all 30 cases after those fixes. Ruff lint/format, mypy (35 source files), lock check,
CLI help and original-six listing passed. No running service or actual source archive was
modified during this implementation.
