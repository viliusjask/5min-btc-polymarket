# Bound order checks as archived intents grow

September 8, 2026. Branch `fix/ledger-history-read`, base `ebdfae9` (deployed source `ac3d037`
plus documentation). This follows the measurement-expiry repair described in
[discovery recovery](discovery-recovery.md).

## Diagnosis

After that repair, the root task's five-second collector samples reported CPU falling from
54.82% to 18.20% and logical reads falling from 1,224,823,402 to 803,383,858 bytes. Discovery
was again usable across rounds. These were deployed-process measurements supplied by root;
the investigation below used read-only source connections and separate scratch databases.

The remaining large reads include a confirmed cost that grows with order history. Every
`Engine.step` reconciles account state before deciding whether a new snapshot is usable.
An idle cycle calls `Ledger.unresolved_orders` eight times through reconciliation, paper
preflight, summaries, inventory comparison and resting-order handling. It also computes the
daily-entry count twice. Both queries scanned all `intents` rows.

The actual passive-pair journal contained 955 intents, all `SETTLED`; inventory-pair contained
641, also all `SETTLED`. Their intent JSON totaled 5.69 MB. The default SQLite page cache is
about 2 MB, so repeated scans reread these tables even when all orders are already closed.
No unresolved order was returned. `EXPLAIN QUERY PLAN` confirmed `SCAN intents`.

This particular cost grows with retained **order** history. Adding price/tape history to a
separate archive does not by itself enlarge these intent scans. The smaller existing position
and accounting history reads remain separate work; this change does not claim they are bounded
forever or replace their current accounting semantics.

## Implementation and compatibility

Writer initialization adds two internal SQLite indexes:

- `unresolved_intents` contains states other than `SETTLED` and `REJECTED`.
- `daily_buy_intents` indexes BUY creation timestamps for the requested UTC-day interval.

Index creation alone was insufficient in the scratch experiment: SQLite still preferred the
full table scan for unresolved orders to satisfy `ORDER BY rowid`. Analyzed statistics changed
that choice, but production correctness must not depend on one favorable planner decision.
The updated queries use `INDEXED BY` explicitly when the corresponding index exists. Sorting
the small unresolved result still preserves the original insertion order exactly.

Each `Ledger` instance discovers available indexes at open time. This caches only schema
capability, never order, account or risk data. Read-only legacy journals without the indexes
continue using their original queries and are not migrated. A reader opened before a writer
migrates the journal remains usable; a new reader uses the installed indexes. Old pinned code
continues to understand the unchanged tables and rows. Existing SQLite writes maintain the
indexes transactionally, including state and creation-time changes and rollbacks.

The daily count still includes all sessions, counts distinct round slugs, includes the UTC
day's first millisecond and excludes the next day's first millisecond. Closed zero-fill orders
do not consume a slot; positive confirmed quantity still uses exact `Decimal` comparison.
Unknown/open orders retain their existing reserve and reconciliation behavior regardless of
their age. No stale summary cache, accounting rewrite, public schema or API change was added.

## Bounded scratch evidence

The source journals were opened with `mode=ro`. Scratch copies included only the paper state
needed for an idle engine cycle; archival events and signed payloads were omitted. The 10×
case added synthetic copies of **old, closed** intents without increasing current exposure or
current-day activity. Five warm idle cycles ran per case and all returned `SKIP/NO_SNAPSHOT`.
Source-process tracing was not used; these are controlled scratch results.

| Portfolio / retained intent count | Old logical reads per cycle | Updated logical reads per cycle | Old median cycle | Updated median cycle |
|---|---:|---:|---:|---:|
| Passive pairs / 955 | 39.98 MB | <1 KiB | 38.72 ms | 17.85 ms |
| Passive pairs / 9,550 | 392.89 MB | <1 KiB | 186.20 ms | 19.36 ms |
| Inventory pairs / 641 | 26.69 MB | <1 KiB | 29.55 ms | 18.43 ms |
| Inventory pairs / 6,410 | 263.63 MB | <1 KiB | 99.54 ms | 16.42 ms |

The updated run used the actual new code, automatic writer migration and no `ANALYZE`.
Writer opens including index creation took 193–237 ms in these four scratch cases. Every
intent's stored ID, state and JSON remained equal before and after migration. The sub-KiB
figures describe warmed database caches and include profiling overhead; they are not a claim
that first reads or future active workloads require no I/O. Machine timings are interval
evidence, not service guarantees. They show that adding closed archival intents no longer
forces these idle queries to read the entire archive.

Ignored evidence locations:

- `.worktrees/discovery-recovery/work/discovery-recovery/remaining-reads.py` and
  `remaining-reads.json`: old-source query trace, scaling and index/statistics experiment.
- The same directory's `remaining-reads-no-analyze.json`: why index creation alone failed.
- `.worktrees/ledger-history-read/work/ledger-history-read/benchmark.py` and `benchmark.json`:
  actual updated-code migration and scaling results.

## Verification and operating boundary

Six regression cases in `tests/test_ledger_history_reads.py` cover thousands of past/future
orders, missing and pre-existing unanalyzed indexes, all unresolved states and their insertion
order, exact day boundaries, session independence, duplicate rounds, tiny positive quantities,
legacy read-only opens, migration preservation, rollback and restart. The tests first failed
under a deterministic SQLite instruction budget at the unresolved scan; after that repair,
they independently failed at the daily-entry scan before its correction.

**119 focused tests passed in 87.16 seconds**, including ledger, engine, comparison and
measurement-expiry tests. Ruff lint/format, mypy (34 source files), dependency lock consistency
and whitespace checks passed. Root and the integration reviewer own the combined full suite,
deployment and a fresh deployed-process I/O/capture check. No running code, service, production
journal, configuration, credentials or funded endpoint was changed by this worker.
