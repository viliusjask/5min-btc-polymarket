# Combined final integration fix

Initial BASE: `10817b7227b82fd255581510048d3b4354c8c3a3`.
Implementation commit HEAD: `3f49231b4a57cf6e00934dd86316317e3e275d19`.
Immediate parent: `1896890` (root's concurrent public-capture/shutdown-ruling documentation).
Branch: `feat/standalone-btc5m`.
Workdir: `/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone`.

One combined fix wave addresses all three confirmed findings. The commit changes only
`src/btc5m/cli.py`, directly required cleanup/submission paths in `broker.py`, `engine.py`,
`market_data.py`, their integrated coverage in `tests/test_cli.py`, and operator shutdown
text in `README.md` and `SKILL.md`. Root research/progress/memory changes were preserved.
No dependency, public flag/schema, strategy, account access, real network call, credential
inspection, order, push, merge, branch deletion, or additional agent was introduced/performed.
The root's public-capture process was not touched or duplicated.

## Findings and resulting behavior

- **I1/P1:** `LatestInput.observe` immediately clears the cached snapshot and advances its
  existing invalidation generation for an explicit anchor conflict or matched-round
  `metadata_unavailable/UNSUPPORTED_RULE`. It compares the event slug to the current cached
  market, so historical unrelated conflicts do not cancel the candidate. A later valid
  publication cannot erase the advanced generation. Actual SDK event parsing and
  `MarketData._poll_due` emissions pass through the real cache and Engine in 16 regressions:
  anchor/rule × account/preparation wait × later overwrite/no overwrite × current/historical.
  Current conflicts perform zero POSTs, cancel confirmation or reject known-unposted
  preparation, and release its reserve; historical controls still perform their one synthetic
  POST. No new entry policy was added.
- **I2/P2:** `run_live` now shares one absolute event-loop deadline between its controller,
  task drain, and all transport close operations. The duration deadline is not extended by
  controller polling. Flat early exits also spend only the remaining shutdown budget.
  Runtime tasks are cancelled and conclusively drained before transport shutdown and wallet
  owner release. A separately shielded finalization task prevents repeated caller cancellation
  from interrupting that ownership boundary. Cleanup expiration records SHUTDOWN_DEADLINE,
  returns exit2 for normal command completion, emits a final summary and releases ownership
  after drain. Caller cancellation continues to propagate after safe finalization.
  MarketData and Broker start independent subordinate closes together and collect their
  errors, so one delayed close cannot prevent other resources from being attempted.
  Engine records an interrupted POST as UNKNOWN before propagating cancellation, preserving
  its exposure and preventing replay.
  Regressions cover delayed public-client, secure-client, RPC and stream-handle close on flat
  early exit; cancellation during a submitted SELL with five reserved outstanding shares;
  repeated caller cancellation while submission cancellation is awaiting acknowledgement;
  and cancellation during reconciliation of an existing UNKNOWN BUY retaining USD4.9969
  cash risk reserve, stop, and the original single POST.
- **I3/P2:** The report reducer retains explicit producer conflict regardless of unchanged
  retained price, including a first-seen conflict and later apparently official observations
  from a restarted producer. Numeric comparisons reuse the producer's existing USD1e-8
  tolerance, so compatible duplicate representations do not invent conflicts. Safe original
  or explicit-conflict provenance remains in the report row. Tests reopen historical SQLite
  journals and exercise real metadata producers, compatible duplicates, producer restart,
  first-seen conflict, and later observations. Existing journals need no migration or backfill.

## Shutdown guarantee, cost and remaining limits

Root explicitly approved the policy after the lifecycle trace. The bounded behavior assumes
asynchronous operations promptly acknowledge cancellation. At the deadline, unfinished waits
are cancelled; final cancellation acknowledgement plus local reporting/SQLite/lock work still
need event-loop scheduling and synchronous execution. This is not a hard real-time guarantee.
Code which suppresses cancellation, blocks the event loop, or stalls synchronous storage/output
can delay termination. The implementation deliberately keeps ownership until execution has
conclusively stopped; it never detaches a possibly trading worker to make a timing fixture pass.

The opportunity cost is that reconciliation, protected unwind, and resource cleanup share the
same window. A slow cleanup can produce exit2 even when flat; reconciliation which consumes
the window leaves only cancellation attempts for transport cleanup. Interrupted cleanup may
leave resources for OS reclamation on process exit. README documents external termination of
an actually stuck process, confirming its exit, status/report inspection and explicit local
reconciliation before considering restart. No process-kill workaround or new supervisor exists.
Funded execution remains unverified; this change does not establish profitability or a
guaranteed liquidation price. Root's completed public capture used older source and is separate
evidence, not a test of this live teardown path.

## Retained verification

Meaningful tests were written before production changes. Initial red output included a fixture
time-field error; it was corrected from eventStartTime to the SDK Event's startTime before
implementation. The confirmed red run then failed for the intended behaviors.

| Check | Result | Retained output |
|---|---|---|
| New regression selection, initial red | 18 failed, 6 passed, 31 deselected, 6.09s; includes fixture correction above | `work/final-fix-red.txt` |
| New regression selection, confirmed red | 16 failed, 10 passed, 31 deselected, 6.67s | `work/final-fix-red-confirmed.txt` |
| CLI focused green | 57 passed, 12.34s | `work/final-fix-green-initial.txt` |
| CLI focused green with added stream/existing UNKNOWN cancellation controls | 59 passed, 12.92s | `work/final-fix-focused-final.txt` |
| ONE integrated `uv run --locked pytest -q` | 412 passed, 28.79s pytest time; 29.082s command wall time | `work/final-fix-suite.txt` |
| `uv run --locked ruff check src/btc5m tests` | Passed, 0.050s | `work/final-fix-lint.txt` |
| `uv run --locked ruff format --check src/btc5m tests` | 21 files already formatted, 0.033s | `work/final-fix-format.txt` |
| `uv run --locked mypy src/btc5m` | No issues in 12 source files, 0.589s | `work/final-fix-types.txt` |
| `uv lock --check` | Resolved 45 packages, 0.042s | `work/final-fix-lock.txt` |
| `git diff --check` | Passed, 0.004s | `work/final-fix-diff.txt` |

All integrated commands exited0. They ran once, sequentially, at
2026-09-06T20:08:25.806635Z through 20:08:55.607Z with `UV_OFFLINE=1`.
Exact absolute commands, UTC starts, durations and exits are retained in
`work/final-fix-verification.json`; the one-off runner is `work/final-fix-verify.py` and was
not committed. New-regression selection used:

```
/home/vilius/.local/bin/uv run --locked pytest -q tests/test_cli.py -k 'official_conflict or report_reduces_produced or report_final_reference or flat_run_bounds or cancelled_run_drains'
```

Both focused green commands were `/home/vilius/.local/bin/uv run --locked pytest -q tests/test_cli.py`.
The scoped production-readiness self-check found no additional confirmed blocker; the one
independent review assigned by root follows this report. No code changed after the integrated
verification. Explicit staging included only the seven owned files; root's
`.claude/memory/debugging-traps.md` edit remained unstaged at implementation commit completion.
