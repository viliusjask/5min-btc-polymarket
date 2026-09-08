# Historical archive and replay integration review

September 8, 2026. Independent review in `fix/archive-integration`, starting from
`2342405`. This combines the public archive, bounded historical intent reads and finite
historical replay. The reviewer did not author those implementations and did not modify
running services, source archives, credentials, configurations or funded accounts.

## Reviewed interaction boundaries

- The archive adds a table and optional compressed-frame field without changing tape
  identity/version or rewriting earlier rows. Old snapshot/research fields remain the
  current simulator inputs. Independent raw records survive rejected snapshots but do not
  manufacture eligibility or clear uncertainty. Prior individual review included actual
  pinned-reader checks; this pass reviewed the combined constructor and decoder changes.
- Capture-session provenance and sequence gaps distinguish processes, dropped batches and
  source discontinuities. Graceful shutdown commits a final archive-only frame when needed;
  current and pinned readers correctly treat that frame as unavailable trading data.
  Abrupt termination can still lose the uncommitted wire-message tail.
- Ledger indexes affect query selection, not order states, insertion ordering, day limits,
  monetary calculations or transaction boundaries. Read-only journals without the new
  indexes remain readable and are not migrated by inspection or historical source opens.
- Historical entry bounds are aligned to complete five-minute rounds. An indexed seek
  starts at available causal warmup, and the manifest freezes a source frame limit.
  Following recorded frames remain available for exits and official settlement labels,
  but frames and labels appended beyond that limit are excluded, including on restart.
- Labels initialize at each replay cursor, rather than the live archive tip. A later
  malformed label cannot break a completed historical study. No synthetic final frame is
  added to obtain a desired payout. Open orders, open positions and positive claimable
  amounts remain explicit if recorded history ends before completion.
- Original-six configurations retain the supplied strategy and execution settings and
  the same per-wallet allocation calculation as `paper --strategies all`. Pair strategies
  use the existing inventory and passive execution paths; current Momentum retains its
  configured signal. Other registered suites keep their existing definitions.
- Historical studies cannot become forward holdouts. Selection/range changes require a
  new study. Missing selected-round forecasts remain in the denominator; terminal
  finalization is transactional with the study cursor and occurs once across restart.
- Archive status uses indexed endpoints and bounded metadata. It does not decode payload
  history, audit all checksums or assert that old coverage was continuous. Source capture
  and derived study backups are separate consistency boundaries.

## Confirmed integration finding

Archive status resolved a symbolic link when opening SQLite, but measured WAL/SHM files
beside the unresolved alias. A synthetic active WAL database occupied 144,016 bytes while
the alias reported only 4,096 bytes. This understated storage even though both outputs
identified the same source. The fix normalizes the source path once before all reads and
file-size measurements; a focused regression compares direct and aliased inspection.

## Verification and decision

**Approved for parent integration**, with the confirmed storage-accounting defect fixed.
No remaining confirmed release-blocking issue was found in the reviewed scope.

- Combined source `2342405` passed **776 tests in 400.83 seconds** on Python 3.12.13.
- The symlink regression failed before the fix, reproducing the missing WAL/SHM bytes.
  After the one-line path normalization, the historical replay, study, tape, public archive
  and ledger-history group passed **59 tests in 45.16 seconds**. The whole execution suite
  was not repeated after this file-size-only correction.
- Final-source Ruff lint and format checks passed for 77 files; mypy passed for all
  36 source files; the 45-package dependency lock remained consistent. Top-level, lab and
  archive CLI help and `git diff --check` also passed.

Actual-source replay, collector throughput and service-cutover evidence belong to the
parent task. Synthetic execution checks do not establish a profitable trading strategy,
full historical market coverage or lossless capture during sleep/disconnection.
