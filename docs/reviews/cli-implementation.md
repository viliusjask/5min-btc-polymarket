# Task 4 report — native CLI, observation scheduling and operator integration

Status: **DONE_WITH_CONCERNS**. The scoped implementation and local checks are complete. No known
remaining implementation blocker was found in self-review; independent Task4/whole-branch review
and the root's final35-minute CLI observation are still required. Funded account operation remains
unverified. No actual credentials were inspected, no user account was initialized, and no funded
order, allowance, transfer, key creation/derivation, wallet deployment or redemption was performed.
No agents/reviewers were spawned and no dependency was added. No push/merge/branch deletion occurred.

Worktree: `/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone`.
Branch: `feat/standalone-btc5m`. All tools explicitly used that workdir.
Read the enriched task-4 brief, project instructions/memory/design, Task3 report and appended fix,
and the binding execution-input scheduling report. Root's concurrent research/bootstrap commits
were preserved. The legacy trading launchers were read as artifacts and removed, never executed.

## Scoped local commits

- `c711d3a` — `fix: consume fresh execution inputs and persist metadata diagnostics`.
  First reviewed local checkpoint: optional fresh Engine providers, SnapshotInput, safe public
  rejected-field diagnostics and focused producer/engine regressions.152 covering tests passed.
- `ac32575` — `feat: add explicit native trading workflow and durable operator reports`.
  CLI/operator surface, integration tests and docs/removal/CI, plus final input-reserve equality
  and original metadata-rejection precedence corrections. Final full suite381 passed.

Root independently committed the common journal ignores and evidence records between these
checkpoints; they are not worker changes. `git status --short` was empty after the final commit.
The workflow report/evidence files are deliberately ignored and were not staged.

## Delivered source/operator surface

New `src/btc5m/cli.py` and `__main__.py` provide the actual installed `btc5m` entry point and
`python -m btc5m` route already declared in the project. Commands are:

| Command | Authentication / mutations / bounds |
| --- | --- |
| `observe --duration SECONDS [--runtime PATH] [--config PATH]` | Anonymous only; separate observation journal. Default2100s; positive finite maximum86400s. Records source observations, raw paired screens, calibration and official delayed final references. |
| `doctor --duration SECONDS` | Anonymous source/discovery diagnosis; default15s. Success means spot/TWAP/discovery observed, not a trading-ready snapshot/account. |
| `doctor --account [--env-file PATH] [--wallet ADDRESS] [--config PATH]` | Explicit authenticated reads. Existing journal is readonly, or an isolated temporary journal is used if none exists. No live session/cash baseline/stop reset. |
| `run --execute --duration SECONDS [--shutdown-seconds SECONDS] [--env-file PATH] [--wallet ADDRESS] [--config PATH]` | Explicit funded mode. Canonical wallet journal owner lock first; clear only prior stop once before awaited account setup. Default additional shutdown window60s; daily trade cap comes from validated Config. |
| `stop --runtime PATH [--wallet ADDRESS]` | Existing journal's dedicated concurrent stop write, no auth/owner takeover. Preserves order/inventory evidence. |
| `status --runtime PATH [--wallet ADDRESS]` | Readonly safe LedgerSummary, concurrent with active owner. |
| `report --runtime PATH [--wallet ADDRESS] [--records]` | Readonly summary, raw screen/confirmation counts, first eligible per mode/round, calibration, one official final-reference record per round, recent public diagnostics. `--records` includes all safe observations/raw decisions. |
| `reconcile [--env-file PATH] [--wallet ADDRESS] [--config PATH]` | Venue-read-only order/account reconciliation, but a live journal writer requiring the exclusive owner lock. No stop/session/day-budget reset. Requires an existing live session. |

`--execute` is explicitly required by argparse and rechecked by run_live. Long-option abbreviations
and unknown/inapplicable flags reject. Help, observe, public doctor, stop/status/report do not call
load_credentials or construct an authenticated client. No secret-valued argument is supported.

`default_config()` resolves from the installed editable package source to this checkout's
`config/btc5m.toml`, not CWD. `--config` accepts another complete validated TOML. There are no new
strategy CLI overrides or second configuration scheme. README explicitly documents native editable
checkout installation; a separately installed wheel with bundled configuration is not advertised.

Credentials are a frozen `Credentials(private_key [repr=False], wallet, api [repr=False])` value.
`load_credentials(env_file, wallet)` reads only the five explicitly whitelisted process variables
and optional explicit env-file:

- POLYMARKET_PRIVATE_KEY
- POLYMARKET_FUNDER
- POLYMARKET_API_KEY
- POLYMARKET_API_SECRET
- POLYMARKET_API_PASSPHRASE

Files accept literal KEY=value lines with optional matching single/double quotes, comments/blank
lines, a16KiB cap and duplicate/unknown-key rejection. No source/eval/interpolation/export syntax.
An explicit public wallet can override the funder field. Errors print reason codes or sanitized
exception class names, without raw request/auth/SDK exception text. Existing CLOB credentials are
passed to the already reviewed no-deploy factory; no create/derive/approval convenience path exists.

The retained `scripts/btc5m_ctl.sh` is a7-line quoted native `uv run --locked --project ... btc5m`
delegate. It uses uv on PATH or the normal `$HOME/.local/bin/uv` fallback, and passes arguments
unchanged. Actual wrapper help succeeded, and wrapper run without execute returned2 before auth.
The original seven orphaned strategy/report/watch/hot/Docker scripts, profile YAML and compose file
were removed. README, SKILL.md, CONTOUR.md, examples and AGENTS commands describe only the new route.
CI is configured for Python3.12 and the locally used uv0.11.24, with lock sync/consistency, pytest,
Ruff lint/format and mypy. CI itself has not run remotely; these exact commands ran locally.

## Journal ownership, startup and shutdown

Live operations use the existing `runtime_path(repository(), normalized_wallet)` common Git-root
helper: `<common-root>/.runtime/<wallet>/ledger.sqlite`, independent of worktree/CWD. Anonymous
observations default to `<common-root>/.observations/<unique-id>/ledger.sqlite`, or an explicit path
outside the live namespace with the all-zero anonymous wallet identity. The Ledger's existing
wallet check prevents opening a live wallet journal as anonymous. Runtime leaf permissions were
observed as0700; SQLite and lock files0600; existing Ledger behavior also protects active sidecars.
Root added both tracked feature ignores and common `.git/info/exclude` rules without editing the
protected main checkout's tracked files.

For observation only, `ledger.config = validated Config` is bound before the observer starts,
following root's explicit ruling. This supplies discovery-before-snapshot calibration fingerprints
without creating any session, account baseline or live runtime. A focused real-adapter regression
requires the fingerprint while `session_id` and cash remain absent.

Only run acquires the owner lock and clears the persisted old stop once, before session/account
setup awaits. A stop arriving during setup remains set and prevents submission. Startup config
conflict or account-construction failure records a visible safe lifecycle error and preserves stop.
Known setup failure and close-failure regressions require that ownership is released. AsyncExitStack
ensures the journal/control handlers still close when a transport close fails.

Run's control task persists stop on SIGINT/SIGTERM, operator stop, or duration expiry and starts a
bounded additional shutdown deadline. Engine/account work remains serialized while snapshot/feed
production and clock/calibration updates continue independently. Repeated shutdown passes use the
same fresh held-book provider. If finality/exposure remains unresolved at the deadline, the worker
is cancelled with durable boundaries intact and exit2 is returned. Cancellation of a submitted
request retains SUBMITTING/UNKNOWN evidence; no second POST is issued. Report/status remain usable
following abrupt process exit. Confirmed noncash claimable inventory remains distinct from active
uncertainty and cash. A successful flat shutdown does not promise that every historical position
row disappeared; zero-quantity audit rows remain in summaries.

Reconcile applies order/account evidence without running the exit/resolution lifecycle itself.
Held-position resolution continues in the running Engine. It does not post, claim or approve.
The operator docs make this boundary explicit. Account doctor can read an existing running owner's
journal and uses a temporary journal for the first diagnosis, without adopting the initial balance.

## Fresh execution input API and scheduling

`execution_types.SnapshotInput` is frozen:

```python
@dataclass(frozen=True)
class SnapshotInput:
    snapshot: Snapshot | None
    invalidation_generation: int
```

Engine retains positional `step(snapshot, exit_book, now_ms)` and `shutdown(snapshot, now_ms)`.
Its constructor adds only the approved optional read-only providers:

```python
Engine(broker, ledger, config, session_id, *,
       read_exit_book: Callable[[str], Awaitable[Book | None]] | None = None,
       read_snapshot: Callable[[], SnapshotInput] | None = None)
```

`Engine.candidate_identity(market, side)` exposes the existing shared identity semantics instead of
duplicating the strategy. Market/round/selected-token/reference value/source/settlement identity
is shared with the CLI cell; side and config fingerprint are included at the caller/confirmation
boundary. Equal reference value/timestamp with merely changed descriptive provenance does not
start a material excursion.

`LatestInput` owns one immutable latest cell and monotonic generation. It records MarketData
observations synchronously and records both decisions immediately on publication through
Ledger.record_snapshot. It invalidates every observed missing/unavailable input, current selected
raw core rejection, stale input at consumption, material identity excursion and required spot/TWAP
stream-unavailable or conflict event. Nonselected-mode rejection alone does not invalidate.
Ordinary eligible same-identity updates replace the snapshot without incrementing generation.
The poll-start generation is captured; a completion from before an intervening invalidation is
still recorded as a raw snapshot but cannot restore executable readiness. A new validated poll
must do that. Thus invalid→valid and A→B→A overwrites cannot erase the intervening episode.

Engine samples the provider after account reconciliation under its lock; a new generation cancels
the old pending candidate and the latest eligible snapshot can only arm afresh. Positional None
placeholders do not spuriously cancel when a provider exists. Engine selects the actual current
held token after reconciliation, then awaits the independent held-book read and advances actual
time before exit/expiry routing. No gather(snapshot,book) or second account reconciliation ages
the book before use. Missing/stale provider results still reject; crossing expiry during the
provider await still routes to verified resolution. Shutdown uses that same path.

After BUY preparation, Engine resamples snapshot/generation and reevaluates the real selected core
at current time. Any intervening generation, missing/stale/rejected input or material identity
change abandons the known-unposted intent. Current principal and reserve must equal the prepared
authorization, while the prepared signed price may be stricter than the current permissible bound.
A newly higher reserve is not silently authorized merely because rounded principal stayed unchanged:
the regression changes fee rate0.0700→0.0701, keeps principal4.67, and requires abandonment before
POST. Normal valid updates and a looser current price limit still permit the original safe order.
There is no repricing loop and no retry of a submitted/ambiguous order.

## Public metadata diagnostics

Before each existing TRADING_METADATA_CHANGED rejection, MarketData emits `metadata_rejected`
with the compared field, normalized expected/actual values, endpoint and round/condition identity,
and selected token identity for book mismatches. Unsupported ticks additionally record the
accepted set. No full raw payload or new source is exported and no entry check is relaxed.

The narrow Ledger.record_observation normalization accepts only approved comparison fields and
bounded scalar values/supported-tick strings for this kind, rejecting arbitrary comparison
payload dictionaries and discarding unrelated secret/signed fields. The producer-to-journal
round trip is verified; `report --records` exposes the resulting safe diagnostics. Original
rejection precedence is preserved: an already invalid tick still raises the metadata mismatch
before a later malformed field is parsed. Two final regressions found that an eager tuple parse
would otherwise replace the original reason with INVALID_NUMBER; the final implementation uses
sequential original-order comparisons.

## Behavioral/TDD and verification evidence

New behavior was specified before implementation. Initial12 Engine provider cases failed because
those constructor/SnapshotInput contracts did not exist; six real producer-to-journal tests failed
because rejected-field records were absent. CLI tests were authored before its module existed.
Subsequent meaningful observed red cases included: startup config-failure leaked the owner lock;
transport-close failure skipped journal release; first anonymous discovery had a null calibration
fingerprint; preparation accepted an increased required fee reserve; and diagnostic eager parsing
changed the first rejection reason. Each was corrected and its focused cases rerun green.
A test fixture used an unavailable helper name once and was corrected before relying on its result.
New acceptance checks also confirmed existing reviewed accounting behavior instead of rewriting it.

Final additions total55 cases beyond the326-test Task3 gate:

-13 Engine provider/current-authorization cases:6s account latency, fresh/stale held books,
  blocked independent discovery, expiry during await, shutdown delivery, overwritten generation,
  preparation invalidation/missing/identity/rejection/budget/fee changes and normal update controls.
-8 MarketData diagnostic cases: book condition/tick/minimum, flags tick/minimum, unsupported tick,
  and original rejection precedence; real observer→Ledger persisted fields are checked.
-1 Ledger safe-comparison normalization/rejection case.
-31 CLI cases covering strict argument/auth boundaries, literal env parsing, canonical config,
  invalidation excursions and stream latching, silent aging, concurrency, first/existing account
  doctor, stop during setup, abrupt termination reports, bounded unresolved shutdown, startup/close
  cleanup and actual independent scheduling.
-2 end-to-end cases using real core/Engine/SDK/RPC/Ledger and synthetic external venue transports.

The actual CLI scheduling acceptance runs the real MarketData book parser and Broker/SDK SELL
path with Gamma discovery blocked and6s added account latency. It observes one TIME SELL POST
before discovery can complete, then an independent stop returns unresolved2 with no replay.
A separate real-adapter test supplies attributed SDK stream models and current books at the
predefined calibration instant while Engine's account read is blocked; paired decisions and
that exact observed calibration are already durable before the account task can finish.

The full accounting E2E creates a real-core eligible candidate, waits for confirmation, signs/posts
once with an unknown transport result, confirms BUY5 shares/principal3.50/fee0.0735, then confirms
SELL2 at0.80/fee0.0224 and SELL3 at0.80/fee0.0336. The partial state is quantity3, basis2.1441,
realized net0.1482. Final cash100.3705, realized net0.3705, fees0.1295, zero quantity/cost/reserve and
no unresolved orders are asserted from public reports. Raw screens and confirmation counts remain
separate. The restart scenario retains4.9969 reserve with zero fictional cash movement until actual
receipt evidence arrives; stop never replays the BUY and missing exit book preserves5 owned shares.

Final commands/results (uv0.11.24, Python3.12.13, pytest9.0.3):

| Command | Verified result / evidence |
| --- | --- |
| `uv sync --locked` |45 resolved registry/project entries,44 installed packages checked; no lock change |
| `uv lock --check` |Passed |
| `uv run --locked pytest -q` |**381 passed in24.89s**, `work/task4-full-tests.txt` |
| `uv run --locked ruff check src/btc5m tests` |All checks passed, `work/task4-lint.txt` |
| `uv run --locked ruff format --check src/btc5m tests` |21 files already formatted, `work/task4-format.txt` |
| `uv run --locked mypy src/btc5m tests/test_cli.py tests/test_end_to_end.py tests/test_engine.py tests/test_market_data.py tests/test_ledger.py` |17 files clean, `work/task4-types.txt` |
| `git diff --check` / staged diff check |Passed |
| actual wrapper `--help` / `run --duration 1` |Help0; missing execute2 before auth |
| actual `btc5m report --runtime work/task4-observe/ledger.sqlite` |Exit0, `work/task4-public-report.json` |
| runtime stat |Leaf0700, ledger/lock0600 |

## Bounded anonymous public evidence and final root capture commands

No extra long process remains. Three bounded public invocations were awaited and closed:

1. Initial doctor12s:11 spot,12 TWAP,36 book observations,15 paired missing-reference screens,
   exit0/no stderr. It revealed the normal-close CLOSED diagnostic race and discovery-only null
   config fingerprint. Those were fixed before the later probes.
2. Observe25s at `work/task4-observe/ledger.sqlite`:24 spot,24 TWAP,74 book observations,
   34 paired missing-reference screens, exit0/no stderr, configuration present and no spurious CLOSED.
   Evidence `work/task4-public-observe.jsonl`, `.stderr`, and `work/task4-public-report.json`.
3. Final advertised public doctor15s:15 spot,15 TWAP,46 book observations,21 paired
   missing-reference screens, exit0/no stderr. Ordinary output now deduplicates repeated anchor
   state and ends with concise source/screen counts and a safe summary; every normalized source
   observation remains in SQLite. Evidence `work/task4-final-doctor.jsonl`, `.stderr`.

Final generated anonymous default namespace:
`/home/vilius/projects/5min-btc-polymarket/.observations/d774354efa3d4962b1c76d0ed32ecdb6/ledger.sqlite`.
This confirms the actual common-root default rather than the worktree/CWD. Reports can be read with:

```bash
/home/vilius/.local/bin/uv run --locked btc5m report --runtime /home/vilius/projects/5min-btc-polymarket/.observations/d774354efa3d4962b1c76d0ed32ecdb6/ledger.sqlite
```

The advertised finite final35-minute command, from the explicit standalone worktree, is:

```bash
/home/vilius/.local/bin/uv run --locked btc5m observe --duration 2100 --runtime work/observe-35m/ledger.sqlite
/home/vilius/.local/bin/uv run --locked btc5m report --runtime work/observe-35m/ledger.sqlite
/home/vilius/.local/bin/uv run --locked btc5m report --records --runtime work/observe-35m/ledger.sqlite > work/observe-35m-report.json
```

The explicit relative runtime resolves to
`/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/work/observe-35m/ledger.sqlite`.
The root plans that final capture alongside independent review and will record the exact SHA.
Short smoke durations did not establish30-minute warm-up availability, eligible entries or outcomes;
the existing root adapter research and the upcoming capture provide their separate evidence.

## Operator documentation and remaining limits

README leads with repaired standalone behavior and development-verified/funded-live-unverified
scope, then actual setup, public doctor and35-minute observe/report commands. It describes defaults,
supported TWAP settlement, both raw candidates, experimental confirmation and the research registers.
A40-minute funded example requires an already provisioned dedicated wallet and a complete copied
config with max_entries_per_day1, allowing full30-minute source history before any possible entry.
No funded actions were executed to validate the example. Graceful stop/report/reconcile, shared
runtime permissions/worktrees, existing credential parsing and manual claim distinctions are explicit.

Official account and claim documents were opened during this task:
- https://docs.polymarket.com/trading/wallets-auth — CLOB L2 credential provisioning is separate
  from website Relayer keys and Builder credentials; setup remains the operator's manual step.
- https://docs.polymarket.com/trading/quickstart — current trading-account prerequisites.
- https://docs.polymarket.com/trading/positions/manage — manual redemption/claim route.

Website-managed holdings must be claimed through the same account. A standalone externally owned
wallet is not promised visibility in another website wallet. Claimable tokens remain noncash,
manual claims/transfers remain discrepancies rather than automatically imported strategy profit.
The bot neither claims nor automatically accounts for redemption receipts.

Self-review inspected scope, no-secret flows, error/cleanup paths, ownership, signal/duration stop,
provider scheduling/generation/price-reserve authorization, raw-record independence, safe API-only
reports, removed legacy entry points, verified documentation and actual public output. Defects found
in that process were addressed with the focused regressions described above. Broker/RPC accounting,
receipt authorization, current metadata safeguards and persistent close rules were preserved.

Remaining limitations to retain in the root handoff:

- Funded credential/funder relationships, actual venue acceptance/finality, partial fills and claims
  are unverified. The dedicated-wallet/index-discovery and ordinary-CTF assumptions still apply.
- Missing references/history/quotes can prevent every entry; price-protected exits can still fail,
  leave dust or run past the bounded shutdown with durable unresolved inventory/orders.
- Confirmation is an experimental response to observed feed lag, not evidence of better ROI or
  fully synchronized current inputs. Reserves are conservative estimates, not a protocol fee cap.
- Public doctor is source availability only. The final long observation and independent review
  remain root stages; no profitable paper account or synthetic profitability result is claimed.
- Account-only reconcile does not run held-position exit/resolution logic; Engine run owns it.
- Safe record accessors materialize the bounded journal in memory. There is no retention/migration
  service or separately packaged wheel config. Native editable WSL/Linux is the verified path.
- CI is configured but has not run remotely. No Docker workflow or remote publication was tested.

Root was asked to incorporate the operator workflow and reusable cleanup/input lessons into its
final project-memory/CHEATSHEET pass, since root owns the final setup/memory handoff. No user approval
is needed for this local report; it presents the concrete result for independent gate review.

## Fix round 1 — I1/P2: preserve raw snapshot publication time

The independent Task4 review reproduced an Important observational defect, superseding the
initial self-review's clean assessment: Engine provider consumption recorded an already-published
cached snapshot again after replacing its timestamp with current execution time. An input published
500ms before the fixed calibration point could become an observed calibration500ms after the point,
and one publication produced four raw paired decisions. Root supplied the finding and reproduction
in `.superpowers/sdd/standalone/task-4-review.md` and `work/task4-review/`.

**Fixed in local commit `2e830258c0a759a7172d71ee164f85bb6d584776` —
`fix: keep cached execution inputs out of calibration observations`.** Only `src/btc5m/engine.py`
and `tests/test_engine.py` changed. No public interface, schema, CLI publication, account/RPC,
strategy policy, credentials or teardown behavior changed. No subagent, network/account action,
full-suite rerun, push/merge or branch deletion occurred. Root's running35-minute anonymous
observation session42800 was not interrupted; it uses publication-only observation and never
calls Engine.step, so its public measurements are unaffected by this Engine-only fix.

Short contract:

- With `read_snapshot` configured, CLI publication remains the single owner of raw paired-screen
  and calibration writes. Engine creates a current-time copy for the existing pure selected-core
  `evaluate` call, without calling `Ledger.record_snapshot` on that cached receipt. The immutable
  source cell and its original publication timestamp remain unchanged.
- Without `read_snapshot`, the supported direct-call path deliberately retains its existing
  behavior: each applicable step is its observation boundary and records paired screens at the
  current step time. A regression preserves this and verifies stale input still cancels pending
  execution. CLI live execution always uses the provider path.
- Current-time evaluation, clock-driven missing-calibration marking, monotonic input generation,
  pending-candidate identity, post-preparation principal/reserve/price bounds, account checks,
  stop handling and fresh held-book scheduling remain intact. Execution confirmation/order records
  remain distinct from publication records. No new observational receipt is invented by consumption.

Tests were added before the change. Two provider cases initially failed with `observed != pending`;
the explicit direct-call compatibility control already passed. The no-publication case now keeps
calibration pending at target+500ms and missing at target+2500ms, with exactly the original two raw
decisions and the original target−500ms timestamp. The genuine-publication control adds one snapshot
at target+1000ms, captures that exact sample, retains exactly four decisions for two publications,
and still reaches one protected synthetic BUY after confirmation at the later execution step.
These use actual LatestInput, Engine, core, Broker/SDK and SQLite with existing synthetic external
transport fixtures; no wall-clock sleeps or injected ledger money are used.

| Command | Observed result / retained output |
| --- | --- |
| `uv run --locked pytest tests/test_engine.py -q -k 'never_moves_publication or direct_step_retains'` before fix |2 failed,1 passed,55 deselected; `work/task4-fix1-red.txt` |
| Same focused command after fix |3 passed,55 deselected in0.84s; `work/task4-fix1-green.txt` |
| `uv run --locked pytest tests/test_engine.py tests/test_cli.py tests/test_end_to_end.py tests/test_ledger.py -q` |**124 passed in14.54s**; `work/task4-fix1-covering.txt` |
| `uv run --locked ruff check src/btc5m tests` |All checks passed; `work/task4-fix1-lint.txt` |
| `uv run --locked ruff format --check src/btc5m tests` |21 files already formatted; `work/task4-fix1-format.txt` |
| `uv run --locked mypy src/btc5m tests/test_engine.py tests/test_cli.py tests/test_end_to_end.py tests/test_ledger.py` |16 files clean; `work/task4-fix1-types.txt` |
| Working/staged `git diff --check` |Passed |

All commands used `/home/vilius/.local/bin/uv` from the explicit standalone worktree. The earlier
381-test full-suite evidence remains the baseline; this round adds three cases and runs only the
root-requested covering suite and static checks. Self-review of the final narrow diff confirmed
that the sole execution change selects pure evaluation for providers and preserves the direct
branch. Independent rereview and root's remaining public/whole-branch/memory stages remain pending.
The review's unproven pathological teardown hard bound is retained for root's final review, not
claimed fixed or expanded into this narrowly authorized finding.
