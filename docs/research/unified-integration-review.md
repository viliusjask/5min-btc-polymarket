# Independent integration review, September 8, 2026

The four independently authored changes were reviewed together in
`feat/unified-research`, without changing the running services, experiment registrations,
account balances or historical quality flags. The four-way integration is
`8c652f7eef9778c53f8b338474e317e7748e590e`; the reviewed source, including the
catalog clock correction below, is `ac3d037f681e631ddf58a3c40c02dd64e2f8621d`.

| Original commit | Integrated commit | Responsibility |
| --- | --- | --- |
| `3b62f8feccb86cb6aa53f7bf9f4a6f12ddc6665d` | `756d8bf` | Due-only calibration expiry lookup |
| `e439aac905348fdf300a3d77c8a0875f7b842810` | `2d976e0` | Chronological retirement of recovered round references |
| `9a0693e729659b39d4e967f65735e5fc2fd748f8` | `f309b02` | Unified experiment list, comparison and detail |
| `47ae0ccc78a3923ecc9229d3689734065eae2ca5` | `8c652f7` | Request-independent dashboard history follower |

Only appended memory and progress notes conflicted. Both contributions were retained.
The four original branches and commits remain intact.

## Findings and resolutions

The experiment HTTP test used a `SimpleNamespace` with only `path` and `snapshot`.
The integrated server now correctly owns the real reader's `start` and `close` lifecycle,
so this incomplete fixture failed at server construction. The failure was reproduced
before replacing the fixture with a `DashboardReader` over a synthetic paper runtime.
Its response remains monkeypatched for the financial assertions, while the actual
history worker starts and must have stopped when the HTTP server closes.

The fixture correction is not a relaxation of the server contract.

Root's concurrent browser check then identified a catalog clock race. The response clock
was sampled before reading study statistics and capture quality. A collector could append
a valid newer capture during those reads, making its timestamp appear to be in the future
relative to the earlier response clock. The independent controlled-clock regression
reproduced both the false stale classification and the older generated timestamp. Sampling
the clock after reading capture quality resolves the race. A separate case retains rejection
of a genuinely future timestamp. This changes presentation only, not collector freshness
rules or accepted trading inputs.

No unresolved blocking production-code finding remains from this review.

## Reviewed interactions

- Dashboard requests and the background follower share one reader lock. The follower
  opens and closes its own read-only SQLite connection in each bounded batch; it never
  hands a connection between threads or scans the six account journals in its pump.
  Shutdown interrupts the scan and joins the worker. Failed partial aggregation resets
  its in-memory state before retry, preventing duplicated cumulative counts.
- Paper list/detail routes do not call the Real account reader. They retain the local
  host restriction, fixed asset mapping, mutation rejection and sanitized error responses.
  Journal reads validate the paper environment and registered variant/tape/phase identity;
  experiment identifiers cannot select arbitrary paths outside the study.
- Source, phase and variant form a distinct row identity. A later phase cannot overwrite
  its exploratory row. Unavailable reports retain registered rows where the catalog can
  be read. Current capture quality and historical reader progress remain different facts.
- Cash, fees and shares continue to use Decimal accounting. Selecting unflagged results
  changes completed-round subtotals, not the original allocation or all-realized return.
  A saved report that does not match the journal's completed results cannot supply a
  silently mixed set of financial statistics. Detail explicitly separates fresh round
  analysis from older saved orders and budget diagnostics during such a mismatch.
- Displayed daily/session budget headroom follows `Ledger.check_reservation`: realized
  losses, held risk and outstanding reservations reduce the limit before another order.
  This remains conditional on a verified session configuration fingerprint. Historical
  `LOSS_LIMIT` counts do not claim a present halt.
- The new partial index changes lookup work and expires only pending calibration rows
  strictly after their existing two-second allowance. It does not edit completed records,
  timestamps, balances or execution rules. Chronological round retirement preserves both
  active reference values and sticky contradictions; freshness checks are unchanged.

## Verification

Python 3.12.13, the existing locked environment, no added dependency:

- The corrected HTTP fixture plus the five history lifecycle/recovery cases passed:
  **6 passed in 26.75 seconds**.
- After the clock correction, all experiment-browser tests passed:
  **10 passed in 9.31 seconds**, including both new concurrent-clock cases.
- Ruff lint and formatting passed; **72 files** already formatted.
- Mypy passed for **34 source files**.
- `uv lock --check`, `btc5m --help` and `git diff --check` passed.
- The initial full run was deliberately interrupted after 443 passing cases when the
  clock correction changed source. It is not counted as a completed gate. The complete
  final-source rerun passed: **734 passed in 273.90 seconds**.

The root agent owns the final integrated browser checks, anonymous multi-round source
probe, preserved service cutover and PR. This review has not restarted a collector or
tested funded execution. The historical gaps remain recorded; neither this review nor
a finite recovery probe establishes profitability or permanent data availability.
