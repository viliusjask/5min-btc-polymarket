# Paper journal storage

Paper observations and experiment decisions are retained exactly, but old JSON payloads
can be compressed together. Nothing is sampled, rounded, or expired. All source and receipt
timestamps, event IDs, order evidence, uncertainty flags, sessions and financial rows survive.
This change does not alter `capture.sqlite` or its format.

The policy is a two-hour recent JSON window, capped at 64 MiB of uncompressed event payload.
Older events, or the oldest events exceeding that byte budget, rotate into lossless zlib chunks.
Each chunk contains at most 512 records by default and never more than 4 MiB before compression.
Rotation is bounded per maintenance invocation; these are targets, not an instantaneous memory
or disk guarantee if collection outpaces maintenance or the maintainer stops. Compressed history
is retained indefinitely. A longer archive still grows, so disk capacity must be monitored.

The normal collector does no compression work in its feed callback. A separate maintenance
process performs compression before taking a brief SQLite write transaction. It checks the
serialized chunk and its SHA-256 digest before inserting it and replacing the exact original
payloads in one transaction. An interrupted transaction rolls back; committed chunks remain
readable after restart. A maintenance lock prevents competing maintainers, and SQLite lock waits
are bounded to one second. A busy maintenance invocation can be retried by the scheduler.

SQLite reuses freed pages as collection continues. It does not automatically return those bytes
to the filesystem. Preparing a compact copy performs `VACUUM` on the independent destination to
rebuild its file without those empty pages. It never vacuums the active collector database.

## Compatibility and integrity

Compaction is explicitly enabled per database. Opening an old database with `Ledger` does not
enable it. Live/funded journals are rejected. Paper journals may contain financial state; rotation
only changes the event representation, and copied journals retain all financial tables.

The physical `event_records` table retains one row per original ID, kind and local timestamp.
`event_chunks` stores compressed original rows and a manifest containing first/last IDs, count,
uncompressed byte length and SHA-256 digest. `event_storage` holds the format version and recent
payload counters. Its source manifest identifies a prepared copy's original path, filesystem
identity, wallet, original event count, highest ID and complete ordered event digest.

The `events` SQL view exposes the original four columns. `Ledger` registers its decoding function
on every connection, including readonly readers. Existing bounded ID queries and maximum-ID
lookups still use the primary key; a separate receipt-time index supports restart history reads.
Decoded chunk caching retains at most two chunks. Missing chunks, invalid references, changed
identity, oversized decoded content and corrupt hashes fail visibly. They do not produce empty
events or silently advance a reader's cursor.

An older executable, or bare SQLite connection without `register_event_reader`, cannot query this
view's payload: it receives a missing-function error. Therefore every reader/writer of a selected
database must support the format before that database is switched. Existing pinned experiment
workers must not be silently upgraded or have their experiment implementation identity bypassed.
Registering the standalone standard-library decoder does not change their strategy implementation.
Any such compatibility change still needs its own explicit review and identity treatment.

All chunks remain inside the same SQLite file, so the SQLite online backup API produces a complete
snapshot. Copying only the main file while a writer is active can omit its WAL (the recent committed
write-ahead log); use SQLite backup, and include WAL/SHM when reporting current disk footprint.

## Maintenance interfaces

`btc5m.storage` provides these interfaces for the CLI and service integration:

- `storage_status(path)`: format, highest event ID, recent and archived counts, payload bytes,
  compressed bytes, reusable database bytes, and main/WAL/SHM sizes. It does not decode history.
  Legacy hot payload bytes are unavailable rather than triggering a multi-gigabyte scan.
- `verify_storage(path)`: full SQLite integrity, chunk digest, reference/counter and ordered-event
  verification. This is an explicit offline-style scan, not a dashboard polling operation.
- `compact_copy(source, destination, before_ms=...)`: creates a new file using SQLite backup,
  compacts it, rebuilds its file and verifies identical event count, IDs and ordered digest. A
  pre-existing destination is rejected. An interrupted copy is left for inspection, never selected
  as the active database automatically.
- `sync_compact_copy(source, destination)`: requires the original and destination writer locks,
  checks filesystem/wallet identity and both copies' exact original event prefix, appends the final
  event tail, and copies the current non-event tables transactionally. It performs full verification
  and returns the appended count. The collector must stay stopped through the caller's final
  cutover. The function never replaces either file.
- `maintain_storage(path, now_ms=..., max_chunks=16, hot_ms=7200000,
  max_hot_bytes=67108864)`: one bounded maintenance pass on an already enabled journal.
- `register_event_reader(db)`: install the standalone decoder on a replaced/custom connection.

Initial migration should prepare and verify the independent copy while the existing collector is
running, then stop the selected writer only for final synchronization and controlled replacement.
The caller must verify session, accounting and study identities, preserve the original until that
verification succeeds, and record the resulting collection gap. This module neither restarts
services nor removes the original. Operational text logs require a separate bounded rotation policy;
they must not become an excuse to delete unique source or experiment evidence.
