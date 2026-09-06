# Task 2 implementation report

Status: implemented and locally verified; independent task review remains with root.
Base: 500f591. Worktree: /home/vilius/projects/5min-btc-polymarket/.worktrees/standalone.
Branch: feat/standalone-btc5m. Local commit: `2e5cd8429b6c66942e4cf5828103b62f460a4c85` (`feat: add anonymous market data and verified TWAP anchors`).

## Scope and public API

Changed only `src/btc5m/market_data.py`, `tests/test_market_data.py`, and attributed
public fixtures under `tests/fixtures/market_data/`. All scratch scripts, raw smoke
observations and this report are ignored. Root-owned research/design changes were
left untouched and unstaged. No domain/config interface changes, runtime
requirements, auth/account access, orders, approvals, transfers or pushes.

```python
MarketData(
    config: Config,
    *,
    client=None,                 # AsyncPublicClient by default; SDK I/O injection
    http_client=None,            # httpx.AsyncClient by default
    clock=time.time,            # seconds since UTC epoch, injectable
    monotonic=time.monotonic,   # elapsed seconds, injectable
    observer=None,              # Callable[[dict[str, object]], None]
)
async with MarketData(config, observer=persist) as data:
    snapshot = await data.snapshot(now_ms=None)  # Snapshot or DataUnavailable(code)
    held_book = await data.book(token_id)        # independent Book, same outcome exception
await data.close()                              # idempotent, normally via context manager
```

The adapter owns/closes injected transports too. Entering starts both subscription
consumers and returns without pretending warm-up is complete. Snapshot may initially
raise `STREAM_WARMUP`. Snapshot returns actual partial history and a missing/conflict
anchor state when current feeds/books exist; the pure strategy exposes the resulting
skip. No warm-up history is synthesized. A valid held-token book may contain an empty
ask side; entry strategy rejects missing sides, while exits can use actual bids.

`book(token_id)` does not take the snapshot lock, discover a market, poll delayed
metadata, or require stream health/history/current-round identity. It returns fresh
held-token bids even while a separate current-discovery request is blocked. Tests
exercise that concurrency and the no-feed/no-valid-discovery path.

### Required CLI integration

Call `snapshot()` regularly even after `DataUnavailable`: it drives bounded delayed
metadata polling before discovery/freshness gates. When holding a position, keep the
snapshot/poll operation separately in flight and fetch/evaluate `book(held_token)`
independently. Awaiting `gather(snapshot(), book())` before acting on a due exit would
reintroduce coupling at the caller. Root has acknowledged this Task 4 requirement.

One active snapshot has up to two sequential delayed SDK GETs (5 seconds each), then
one Gamma GET (5 seconds), then four concurrent CLOB/book reads (5 seconds total):
**up to approximately 20 seconds of bounded network wait**, plus local parsing and
observer work. Snapshot calls serialize. An independent held-token book has its own
**5-second deadline**. Stream subscribe has a 5-second deadline; waiting for a message
uses the configured price-age budget (default 5 seconds), then closes/retries after
one second. All these deadlines use asyncio's monotonic event-loop clock. Internal
last-new-source receipt uses injected `time.monotonic`, independently of UTC wall time.
Shutdown cancels consumers and delegates public transport close to the SDK/httpx.

## Actual SDK and HTTP choices

- Pinned `polymarket-client==0.9.0`, `AsyncPublicClient` only.
- `await client.subscribe(CryptoPricesSpec(topic="prices.crypto.chainlink", symbols=("btc/usd",)))`.
- `await client.subscribe(CryptoPricesChainlinkTwapSpec(window_seconds=60, symbols=("btc/usd",)))`.
- SDK `CryptoPricesChainlinkEvent` and `CryptoPricesChainlinkTwapEvent`; use payload
  source timestamp and full Decimal payload value, never the envelope receive time.
  The SDK's TWAP normalization retains `full_accuracy_value` precision.
- `await client.get_order_book(token_id=...)` returns the actual pinned SDK
  `OrderBook` model. Asset/condition/timestamp/tick/minimum/risk and price levels are
  validated; both outcome books are requested concurrently and explicitly sorted.
- Thin existing-dependency httpx GETs read official wire Gamma
  `/events/slug/{slug}?include_chat=false`, CLOB `/markets/{condition}` and
  `/clob-markets/{condition}`. **Why:** SDK Gamma normalization discards required
  `eventStartTime`; the public SDK also does not expose both raw CLOB flag/fee routes.
  Raw presence is therefore checked directly, without treating normalized defaults
  or signing-cache values as authoritative.
- Delayed reconciliation uses ordinary SDK
  `get_event(slug=..., include_chat=False)`, without cache-busters, and checks event/
  condition identity, start/end, descriptions and resolution source before labels.

Supported rule description and Chainlink BTC/USD TWAP60 source must match the
captured known rule, including Up-on-equality. Discovery validates exact slug and
300-second start/end, treating Gamma startDate as a listing date. Outcomes map by
Up/Down labels even when ordering reverses. Condition and CTF token IDs are checked.
Current raw CLOB flags must explicitly assert active/accepting/book-enabled and
non-closed/non-archived/non-negative-risk. Unknown/missing flags never become true.

Current fees come from `/clob-markets` `fd={r,e,to}`; require this recognized schema,
`takerOnly=true`, finite nonnegative rate <=1 and positive integral exponent <=10.
Only SDK-supported ticks are accepted. Fresh CLOB minimum/tick/token mappings must
agree across both raw metadata routes and both books. Fee/tick/minimum changes are
reflected in the next snapshot; inconsistent reads reject that snapshot. These are
snapshot inputs; Task 3 still rechecks before signing/posting.

## Anchor, history, and observations

- Only an exactly source-timestamped TWAP60 opening tick is a captured candidate.
  Reverse arrival order, repeated points and neighboring seconds cannot replace it.
- Captured anchors are enabled by Config's approved default and disabled by the
  explicit official-only setting. Raw history contains actual observations only.
- Later official opening data compares with absolute USD `1e-8` tolerance. A null
  never erases the existing official value. Any differing nonnull official value,
  captured/official disagreement or conflicting exact-boundary update marks the
  round conflicted persistently while retained. No automatic conflict recovery.
- Same-source duplicate points do not create history samples or refresh receipt
  health. Out-of-order points enter sorted history without replacing the latest.
  Conflicting source points reject snapshots while relevant; source gaps remain
  visible to the Task 1 sampler and its unchanged 95%/12-second historical policy.
- Price source/receive and book source/receive freshness stay 5 seconds by default;
  historical sample coverage never extends current-data freshness. Epoch units must
  be milliseconds; seconds/microseconds are not guessed into valid source times.
- Retain raw spot/TWAP observations for configured long window plus 60 seconds, with
  a hard count of `2*(long_seconds+60)+100` points per stream (default 3,820).
  Exact captured round values survive feed-history eviction in retained round state.
- Preserve at most 12 recently discovered round identities, retiring any older than
  one hour after expiry. Poll each at most once per 30 monotonic seconds and at most
  two per snapshot call. These are process-memory limits; no implicit history replay
  or anchor restoration across process restarts.
- Emit actual `final_reference` only when official `eventMetadata.finalPrice` appears
  after expiry; never create it from a TWAP boundary or guessed winning side. Later
  contradictory final values emit conflict. These labels support calibration and do
  not assert confirmed onchain resolution, settled cash or simulated PnL.
- Retired rounds emit `reference_retired` with opening/final status, including final
  `missing`. Late publication beyond count/time retention remains missing. Historical
  rounds never discovered by this adapter are not automatically backfilled.

Observer dictionaries are JSON-serializable copies with `kind`, UTC `received_utc`,
`received_ms`, `source_ms` when known, and `slug` for round outcomes. Kinds include
`spot`, `twap60`, `book`, `discovery` (received and validated stages), `anchor`,
`final_reference`, `reference_retired`, `snapshot_unavailable`, `metadata_unavailable`,
`stream_unavailable`, `price_conflict`, `http_unavailable`, `book_unavailable` and
`stream_close_failed`. Price/Decimal values are strings. Discovery preserves actual
public payloads and endpoint/query provenance, including rejected Gamma discovery.
Errors record safe outcome codes and exception classes, never private payloads.
The observer is synchronous and must return promptly; disk/observer failure blocks
entry snapshots with `OBSERVER_FAILED` but does not prevent held-token book reads.
Persistence/retention policy belongs to the CLI/ledger; callbacks do not run in a
second, potentially divergent feed path.

## External evidence and meaningful verification

Fixture attribution and explicit synthetic transformations are documented in
`tests/fixtures/market_data/README.md`; `SHA256SUMS` covers seven complete public
JSON fixtures. Current HTTP fixture capture is approximately 2026-09-06 16:24:01 UTC.
The discriminating 15:40:00 source TWAP is `79697.534252279656349696`; independent
normal SDK Gamma follow-up received 15:49:48.009652 UTC publishes
`79697.53425227966`. ±1-second values in the public fixture differ materially.
Origin/probe details: `docs/research/anchor-probe.md`,
`work/anchor-evidence/{boundary-events.json,metadata_validation.jsonl,analysis.json}`.
Tests translate timestamps explicitly for replay; no transformed case is claimed
as a real trade/observation. No fixture is an injected fake MarketData implementation.

Tests preceded implementation. Actual red/green progression, retained under ignored
`work/task2/`:

- Initial minimal importable scaffold: `pytest tests/test_market_data.py -q --tb=short`
  => **29 failed in 0.94s**, adapter not implemented (`red-1.txt`). First implementation
  => **29 passed in 0.47s** (`green-1.txt`).
- Integration checks => **2 failed, 33 passed in 0.56s** (`red-2.txt`): adapter used
  a symbolic settlement-source string instead of the core's literal URL. Fixed the
  API mismatch. The test initially called the existing `ENTRY_WINDOW` reason
  `OUTSIDE_ENTRY_WINDOW`; corrected that expected label rather than changing core.
- JSON persistence check then => **1 failed, 34 passed in 0.54s**
  (`red-serialization.txt`): raw discovery Decimals were not JSON serializable.
  Observer copies now serialize Decimals as strings; **35 passed in 0.51s**.
- Rejected-discovery provenance => **1 failed, 39 passed in 0.61s** (`red-3.txt`);
  emitted received raw discovery before parsing; **40 passed in 0.65s**.
- Immediate round-retention boundary => **1 failed, 42 passed in 2.34s**
  (`red-4.txt`); trim upon discovery as well as polling; **43 passed in 2.23s**.
- Excessive-length invalid token and changed delayed rule => **2 failed, 48 passed
  in 2.38s** (`red-5.txt`); bounded token validation and rule checks before delayed
  labels; final **50 passed**.

Tests also cover real parser ordering/precision/null/conflict/unsupported metadata,
book freshness and timestamp units, live trading-parameter changes, source versus
receipt age and monotonic silence, empty asks, independent held books, blocked
concurrent discovery, bounded external hangs, failed observer, delayed final/missing
retirement, hard point/round bounds, actual disconnect/reconnect and a 65-second
source gap. The gap's real pure-strategy diagnostic is `long_sampling_status =
EXCESSIVE_GAP`, preventing a false pass from merely short history.

Final exact checks:

- `.venv/bin/python -m pytest tests/test_market_data.py -q` => **50 passed in 2.22s**.
- `.venv/bin/python -m pytest tests/test_config.py tests/test_strategy.py tests/test_market_data.py -q`
  => **172 passed in 2.36s**.
- `.venv/bin/python -m ruff check src/btc5m/market_data.py tests/test_market_data.py`
  => **All checks passed!**
- `.venv/bin/python -m ruff format --check src/btc5m/market_data.py tests/test_market_data.py`
  => **2 files already formatted**.
- `.venv/bin/python -m mypy src/btc5m/market_data.py tests/test_market_data.py`
  => **Success: no issues found in 2 source files**.
- `sha256sum --check tests/fixtures/market_data/SHA256SUMS` => **7 OK**.
- `git diff --check` => exit 0. Staged diff/ownership checks recorded at checkpoint.

## Anonymous smoke and remaining limits

First public adapter smoke: **2026-09-06 16:34:05.885077–16:34:42.896421 UTC**.
16 successful snapshots, 35 actual points per reference stream; current slug
`btc-updown-5m-1788712200`. Source price ages 2,326–3,583 ms; book ages 933–1,153 ms.
Live fee rate `.07`. Initial `STREAM_WARMUP`; remaining strategy decisions
`MISSING_REFERENCE`, correctly reflecting process start after the opening boundary.

Final code smoke: **2026-09-06 16:40:12.788085–16:40:49.790988 UTC**.
16 successful snapshots, 33 actual points per stream, 34 successful book reads;
current slug `btc-updown-5m-1788712800`. Source price ages 2,453–3,996 ms; book ages
926–1,572 ms. Same live fee `.07`, initial warm-up then honest missing-reference skip.
The normal delayed SDK metadata read also ran during each smoke. Both processes
closed cleanly with exit 0. **No HTTP/access errors or stream disconnects observed.**

Scripts and complete public observations: ignored
`work/task2/{smoke.py,smoke.jsonl,smoke-summary.txt,smoke-final.py,smoke-final.jsonl,smoke-final-summary.txt}`.
These bounded adapter smokes did not include an opening boundary or 1,800-second
warm-up; do not claim either was newly live-verified here. Exact-boundary evidence
comes from the independently captured discriminating probe plus fixture replay.
The pure sampler's longer availability evidence is root-owned research. Actual
final publication timing, outages beyond the captured samples and future schema/
rule stability remain external uncertainties. Unsupported inputs fail closed.
No profitability, live execution, fills, accounting or funded-order claim is made.

Checkpoint: `git diff --cached --check` passed; staged names were exactly the 11 owned adapter/test/fixture files. `git commit` succeeded. Post-commit status contains only root-owned docs/research/sdk-contract.md and docs/research/strategy-decisions.md changes. No push performed.

## Independent review fixes — round 1

Base: `fefdc75` (the Task 2 implementation plus root-owned research checkpoint).
Fix contract: `.superpowers/sdd/standalone/task-2-fix-1.md`; full findings:
`.superpowers/sdd/standalone/task-2-review.md`. Only the adapter and its test module
were changed. Root-owned docs/design.md, docs/progress.md and
`docs/research/sdk-contract.md` changes remained untouched and unstaged.

### P1: advancing freshness with explicit now_ms

Confirmed the explicit argument selected `final_now = now`, freezing source/book
age, the end-of-round check and returned Snapshot.now_ms after network work.
`now_ms` now chooses the initial discovery round only. Final validation always
reads the injected UTC clock again, exactly as the existing no-argument path did.
Callers that need deterministic time should inject the clock; passing an initial
instant does not freeze elapsed I/O. Monotonic stream receipt checks are unchanged.

Four fixture regressions block the last CLOB metadata response until both books
have completed, then advance external wall and monotonic clocks. They verify:

- a one-second delay advances the returned snapshot instant and measured price age;
- a four-second delay rejects the now-seven-second-old price with STALE_DATA;
- a two-second delay rejects a formerly four-second-old book with STALE_DATA;
- work that crosses the next five-minute boundary rejects ROUND_CHANGED.

These use real SDK book models, transport fixtures, parsers and adapter state;
only external I/O and clocks are substituted.

### P1: incompatible delayed official rules persist

Confirmed `_poll_due` detected a changed rule for a matched slug/condition but
recorded only a retryable metadata error. It now sets that retained round's
conflict state before emitting UNSUPPORTED_RULE. Later raw or SDK cached supported
responses cannot clear it. The existing pure core consequently returns
REFERENCE_CONFLICT, while the independent held-token book path remains usable.
No domain fields or new configuration were introduced.

Four regressions cover description and resolutionSource changes separately on the
SDK event and its market, while raw discovery remains an older supported payload.
They advance fresh external feeds/books, exercise the delayed polling schedule,
assert the conflict and real strategy rejection, restore supported cached data,
advance to another actual SDK poll, and assert persistent conflict with SDK
provenance. Two control cases retain a usable captured anchor through ordinary
network failure and absent optional opening metadata. Those cases remain retryable.

### P3: empty-ask assertion and actual core gate ordering

The review's assertion-strength concern was valid: `side is None` did not name the
intended reason. The claim that ENTRY_WINDOW runs first was not accurate for the
unchanged core: `evaluate` calls `_safety_reason`, which checks missing book sides,
before its entry-window gate. The owned empty-ask test now explicitly asserts
`MISSING_BOOK_SIDE` and passes without modifying the strategy or fixture clock.
Root authorized this assertion improvement. No unrelated implementation changes.

### Exact red/green and final checks

Before either P1 fix:

- `.venv/bin/python -m pytest tests/test_market_data.py -q -k 'explicit_snapshot_time or delayed_current' --tb=short`
  => **8 failed, 2 passed, 50 deselected in 0.65s**. The four explicit-time and four
  incompatible-rule variants failed for the reviewed behavior; retryable-error
  controls passed. Full output retained in ignored `work/task2/fix-1-red.txt`.

After fixes, with persistence through a later supported SDK poll and the P3
assertion strengthened:

- `.venv/bin/python -m pytest tests/test_market_data.py -q -k 'explicit_snapshot_time or delayed_current or empty_asks' --tb=short`
  => **11 passed, 49 deselected in 0.49s**.
- `.venv/bin/python -m pytest tests/test_market_data.py -q`
  => **60 passed in 2.28s**.
- `.venv/bin/python -m pytest tests/test_config.py tests/test_strategy.py tests/test_market_data.py -q`
  => **182 passed in 2.46s**.
- `.venv/bin/python -m ruff check src/btc5m/market_data.py tests/test_market_data.py`
  => **All checks passed!**
- `.venv/bin/python -m ruff format --check src/btc5m/market_data.py tests/test_market_data.py`
  => **2 files already formatted**.
- `.venv/bin/python -m mypy src/btc5m/market_data.py tests/test_market_data.py`
  => **Success: no issues found in 2 source files**.
- `git diff --check` => exit 0.
- `git branch --show-current` => `feat/standalone-btc5m`.

No further public smoke was needed for these local time/state corrections; no
transport API, endpoint, fixture or dependency changed. Existing smoke limits and
later CLI scheduling/persistence requirements still apply. Both P1 findings are
addressed; independent re-review remains with root. The general regression lesson
is to test an optional time argument across awaited work, and to distinguish a
transient missing response from incompatible authoritative evidence followed by
an older cached response.

Fix commit: `05c808e38890f1457058d53be6b8776b4a510a20`
(`fix: preserve market data freshness and rule conflicts`).
`git diff --cached --check` passed and only src/btc5m/market_data.py and
tests/test_market_data.py were staged. Local commit succeeded; no push.
Post-commit status contains only the three root-owned documentation changes above.
