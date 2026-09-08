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

## Root acceptance and preserved deployment

The parent independently reviewed the worker changes before this combined review and
fast-forwarded its feature branch to final source `b225bed`. No funded endpoint, credential
file, external historical import, cash reset or historical uncertainty rewrite was used.

An anonymous 75-second paper command into a new scratch directory exited successfully and
flushed its last archive frame. The captured receipt span was 78.352 seconds: 95 frames,
30,747 additional public events, and 1,962 events retained during seven unavailable-snapshot
frames. Spot/TWAP, Binance aggregate trades, Polymarket messages and public metadata were
present; local sequences were contiguous, receipts were causal and no buffer overflow occurred.
Both actual pinned readers (`experiment-lab` and `order-flow`) decoded all 95 real frames
with the same identity, 88 valid snapshots and unchanged reason counts.

Two actual-source original-six replays used six $100 wallets and the current
`paper-strategy-policy.toml`, on source `2342405`:

| Selected UTC entry interval, September 8 | Frozen source cap | Frames processed including warmup/later exits | Result |
| --- | ---: | ---: | --- |
| 09:00–09:10 | 102889 | 4,422 | 26 orders, no fills; all six finished without unresolved exposure. |
| 08:35–09:25 | 103222 | 6,602 | Five policies exercised fills/closures; Fast value had no entry. All completed rounds were flagged, so this is execution-path validation, not reliable profit evidence. |

Both studies resumed with zero new frames despite the source growing, retained their exact
registered manifest and phase results, and produced no automatic holdout. Every BUY order
timestamp stayed inside its entry interval. The final symlink correction changes metadata
path resolution only; its actual-source check counted the resolved source's database, WAL
and SHM correctly. Archive inspection itself took 0.44 ms in a warm read of the roughly 1 GiB
tape, without decoding payloads. This is a measured example, not a cold-start guarantee.
The stricter implementation identity still requires a new study after a code change.

At **09:42 UTC September 8**, collector/dashboard switched from `unified-research` to
`historical-archive`. Shutdown/start took 61.747 seconds. Source identity
`580e84ec4d184c35859a3c53e3c8413f`, seven session IDs and all prior fill/accounting prefixes
were verified retained. Both configuration files, both study manifests, both pinned units
and worker PIDs 3802676/3850281 were unchanged. Only collector/dashboard checkout paths changed;
the collector retained `--continuous --capture-flow`. Source frames 103669→103670 have a
**62.050-second** receipt gap, which remains recorded rather than repaired.

New service PIDs were collector 884297 and dashboard 884298. In the first 70 checked frames,
60 were eligible and 19,844 additional events were retained with contiguous local sequences,
no overflow and matching producer source hashes. Four services were active. The two five-second
collector samples were 23.4%→12.2% CPU and 870,922,064→312,509 logical bytes read. The workload
and moment differed; the controlled scaling benchmark establishes the specific removed scan,
while these samples show the deployed effect rather than guaranteeing a permanent rate.

Actual Chrome checks at port 8765 passed all 108 unique rows, numeric sorts, filters,
original/study detail, cohort views and 390-pixel containment, with zero JavaScript errors
and zero requests to the Real account endpoint. Background history loading caught up past
2.49 million observations. A transient stale spot input during browser QA remained correctly
shown as unavailable; this deployment does not eliminate external feed delays.

Ignored evidence is in `work/archive-integration/` (capture and historical reports, resume
checks and source-status measurements), `work/deployment/` (unit verification, financial
prefix hashes, pinned files, cutover and live checks), and the previously established
`unified-research/work/unified-research/` browser check outputs. No temporary test process
owns the ongoing paper run; the systemd services do.
