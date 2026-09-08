# Discovery timeouts from synchronous measurement history scans

September 8, 2026. Base `8d12573`, branch `fix/discovery-recovery`.

The running paper collector continued recording heartbeats while Gamma discovery repeatedly
failed with `TimeoutError`. A fresh anonymous client returned the same current-round endpoint
with HTTP 200 in 0.149 seconds; subsequent requests on that client took 0.024 and 0.017 seconds.
This alone did not establish a faulty connection pool.

The collector's actual observer path was `MarketData._emit` → `Ledger.record_observation` →
`Ledger.record_clock`. Every tick selected and JSON-decoded **all** measurement rows merely to
find pending calibrations whose two-second observation window had ended. Completed calibration
and candidate records include large public depth and decision payloads. The master journal had
1,026 measurement rows totaling 10,567,084 bytes, with **zero due calibrations** at the read.
A read-only profile of that exact selection/predicate loop took 0.091 seconds, including
0.067 seconds in JSON decoding. The live collector's `/proc` counters showed about 202 MB of
logical reads in a half-second sample and no physical disk reads. These measurements explain
how the cost grows with history even when no expiry work remains.

An asynchronous feed can deliver already-buffered events without yielding between them.
Synchronous observer work then prevents pending HTTP operations and their timeout callbacks
from progressing. The five-second outer request deadline reports `TimeoutError`; it cannot
distinguish network delay from time spent blocked elsewhere on the event loop.

## Change and preservation

`pending_calibration_clock` is a SQLite partial index: it stores only pending calibrations,
ordered by their `target_ms`. Writer initialization adds it to existing journals. `record_clock`
queries only entries with `target_ms < now_ms - 2000`, then preserves the existing transactional
status update. Completed historical payloads and future deadlines are outside the read.
Changing a calibration to `observed` or `missing` removes its index entry in the same transaction;
rollback restores it. Read-only journal opens do not perform a migration.

No measurement, event, accounting, session, tape or strategy data is rewritten by index creation.
The exact two-second calibration window, first missing timestamp, public request deadline,
HTTP error handling, cancellation and shutdown behavior remain unchanged. There is no client
rotation or retry policy and no change to account/order requests.

## Before/after evidence

A scratch benchmark copied only the anonymous master measurement rows through a `mode=ro`
source connection. It opened separate writable scratch ledgers for the old and updated code.
Five expiry calls measured the no-due path. A 100-tick synchronous observation burst then ran
alongside the real `MarketData._raw` path with a synthetic healthy HTTP response delayed by
10 milliseconds and the unchanged five-second deadline.

| Same 1,026-row history | Before | After |
|---|---:|---:|
| Median `record_clock` time | 47.550 ms | 0.00274 ms |
| 100 public observations, including durable writes | 6.466 s | 1.750 s |
| Concurrent HTTP result | `HTTP_UNAVAILABLE`, caused by `TimeoutError` | HTTP payload returned |

The scratch writer open, including automatic index installation, took 0.157 seconds after the
change. Exact machine timings are interval evidence, not service guarantees. Durable public
observation writes still have a cost; this change removes the measured history-dependent scan.
The original process was not instrumented in place: the kernel rejected a bounded stack/syscall
attachment, and no permission bypass or service restart was attempted. Thus the reproduction
establishes this failure mechanism and the correction; post-deployment observation must verify
recovery of the original collector and must not assume all future timeouts have this cause.

Local, ignored evidence is in `work/discovery-recovery/{benchmark.py,before.json,after.json}`.
`tests/test_measurement_clock.py` first failed at the old full scan under a deterministic SQLite
instruction budget. It verifies expiry work with thousands of completed/future rows, migration
of the old table, historical preservation, exact window boundaries, an observed calibration,
and transaction failure followed by restart. Existing market-data tests cover hung requests,
external cancellation, independent held-book reads and lifecycle cleanup.

No production journal was opened for writing and no running service was changed by this worker.
The root task owns combined review, multi-round observation and deployment verification.
