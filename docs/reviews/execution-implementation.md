# Task 3 report — durable execution and recovery

Status: DONE_WITH_CONCERNS. Task 3 implements the scoped execution layer. Funded account operation, order acceptance and actual claims were not exercised. No credentials were inspected, no user account was initialized, and no real order/approval/transfer/deployment/redemption/API-key mutation occurred. No agents/reviewers were spawned. No dependency or approved producer interface changed.

Worktree: `/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone`; branch `feat/standalone-btc5m`. Root owns research/design/progress documents and has committed concurrently. Only the nine owned source/test files below were staged for this task. This report and scratch evidence remain in the ignored workflow directories.

## Files and commits

- `src/btc5m/execution_types.py`: concrete frozen execution/evidence/status records.
- `src/btc5m/ledger.py`: wallet lock, SQLite journal, accounting, risk, stop control and safe observations/report queries.
- `src/btc5m/rpc.py`: allowlisted read-only Polygon balances, receipt decoding, deployed exchange order hash and finalized binary resolution.
- `src/btc5m/broker.py`: pinned SDK no-deploy construction, account preflight, holdings discovery, prepare/post/reconciliation.
- `src/btc5m/engine.py`: actual core decisions, experimental confirmation gate, held-position exits and lifecycle coordination.
- `tests/test_ledger.py`, `tests/test_rpc.py`, `tests/test_broker.py`, `tests/test_engine.py`: real SQLite/core/SDK with synthetic external transport/receipt fixtures, crash processes and public independent vectors.

Local checkpoint `7de9b7f` — `feat: add durable execution ledger and verified broker evidence` (53 focused tests passing at checkpoint).
Final local checkpoint: `c05efcbc251f4984e74d2958455bdeee5ee22021` — `feat: coordinate protected execution and confirmed entry recovery`. No push or merge.

## Concrete CLI-facing interfaces

All timestamps are integer milliseconds unless named `_s`; monetary amounts/prices/shares are `Decimal`. `Market`, `Book`, `Snapshot`, `Decision`, `Side` and `Config` are the approved producer types. Safe exception text is a reason code (`BrokerError`, `LedgerError`, `RPCError`); do not print underlying network/request exceptions.

```python
# btc5m.broker
async def create_secure_client(
    *, private_key: str, wallet: str, credentials: ApiKeyCreds
) -> AsyncSecureClient: ...

Broker(client: AsyncSecureClient, rpc: ReadOnlyRPC, ledger: Ledger, config: Config,
       *, http: httpx.AsyncClient | None = None,
       clock: Callable[[], float] = time.time)
async def preflight(self) -> PreflightEvidence: ...
async def prepare(self, intent: Intent, market: Market) -> PreparedOrder: ...
async def post(self, prepared: PreparedOrder) -> OrderAck: ...
async def reconcile(self, order: Intent) -> OrderEvidence: ...
async def resolve(self, market: Market) -> ResolutionEvidence | None: ...
async def close(self) -> None: ...

# btc5m.rpc: constructor does not initialize an account
ReadOnlyRPC(*, http: httpx.AsyncClient | None = None,
            clock: Callable[[], float] = time.time)

# btc5m.ledger
runtime_path(repository: Path, wallet: str) -> Path
normalize_wallet(wallet: str) -> str
Ledger(path: Path, wallet: str, *, readonly: bool = False)
start_or_resume_session(config: Config, *, new_session: bool = False) -> str
check_entry(decision: Decision, market: Market, session_id: str, now_ms: int) -> None
reserve_entry(decision: Decision, market: Market, session_id: str, now_ms: int) -> Intent
reserve_exit(position: Position, quantity: Decimal, price_limit: Decimal,
             reason: str, session_id: str, now_ms: int) -> Intent
prepare(intent_id: str, prepared: PreparedOrder) -> None
abandon(intent_id: str, reason: str) -> None
mark_submitting(intent_id: str) -> None
record_ack(intent_id: str, ack: OrderAck) -> None
apply_evidence(intent_id: str, evidence: OrderEvidence) -> None
observe_account(cash: Decimal | None, tokens: dict[str, Decimal],
                discrepancies: tuple[str, ...], *, now_ms: int) -> None
note_exit(position_id: str, reason: str, problem: str | None, now_ms: int) -> None
apply_resolution(market: Market, evidence: ResolutionEvidence, now_ms: int) -> None
order(intent_id: str) -> Intent
unresolved_orders() -> tuple[Intent, ...]
owned_hashes() -> frozenset[str]
positions() -> tuple[Position, ...]
open_position() -> Position | None
known_inventory() -> dict[str, Decimal]
summary(now_ms: int | None = None) -> LedgerSummary
record_observation(record: dict[str, object]) -> None
record_snapshot(snapshot: Snapshot, config: Config) -> tuple[Decision, Decision]
record_clock(now_ms: int) -> None
observations() -> tuple[dict[str, Any], ...]
measurements() -> tuple[dict[str, Any], ...]
decisions() -> tuple[dict[str, Any], ...]
request_stop() -> None
# static control writer: no owner lock; existing DB only
Ledger.request_stop_at(path: Path) -> None
stop_requested() -> bool
clear_stop_request() -> None
close() -> None

# btc5m.engine
Engine(broker: Broker, ledger: Ledger, config: Config, session_id: str)
async def step(snapshot: Snapshot | None, exit_book: Book | None,
               now_ms: int) -> EngineResult: ...
async def reconcile() -> PreflightEvidence: ...
async def shutdown(snapshot: Snapshot | None, now_ms: int) -> EngineResult: ...
```

`Engine.preflight` and `Broker.last_preflight` retain latest typed account evidence. `Engine.pending_candidate: PendingCandidate | None` is transient observational state, not a trading intent. `ReadOnlyRPC.last_resolution_reason` exposes why a resolution read could not confirm.

The concrete records, defined in `execution_types.py`, have these fields:

- `Intent`: intent_id, session_id, saved market/token_id/wallet, BUY/SELL side, principal, quantity, price_limit, reserved_cash, created_ms, original reason, source decision, position_id, state, order_hash, cumulative confirmed_quantity/principal/fee, outstanding_quantity, remaining_reserve, trade_ids, pending_fill_ids, submission_reason and discrepancies. It never includes the signed payload. BUY quantity is the conservative signed minimum receipt quantity; confirmed actual shares can exceed it.
- `PreparationMarket`: entry_tick, book_tick, current_tick, reason, protected_price. `SigningDomain`: fixed name/version/chain_id/exchange. Both persist with preparation evidence.
- `PreparedOrder`: intent_id, order_hash, private signed_payload, reserved_cash, reserved_quantity, optional market_metadata, signing_domain. The payload has `repr=False` but `dataclasses.asdict` would still expose it: never log/return this record from CLI status/report. Only the private SQLite column stores the serialized signed object.
- `OrderAck`: accepted/rejected/unknown classification, order_hash, provisional trade_ids, reason. An accepted or unknown post is not a fill.
- `ConfirmedFill`: chain_id, transaction_hash, log_index, order_hash, token_id, wallet, side, quantity, principal, fee, canonical block timestamp_ms, block_number/hash.
- `OrderEvidence`: cumulative confirmed fills, pending_fill_ids, terminal, collateral_balance, token_balances, discrepancies. Ledger deduplicates `(chain, transaction hash, log index)`.
- `ResolutionEvidence`: condition_id, chain_id, explicit finalized block_number/hash, denominator, two raw numerators, token_payouts, source (`CTF_FINALIZED`), observed_ms.
- `Position`: position_id, saved Market/token/wallet/source Decision, actual quantity, fee-inclusive cost_basis, gross_entry_price, ACTIVE/CLAIMABLE/WORTHLESS status, exit_reason, exit_problem, claimable_value.
- `PreflightEvidence`: wallet, signer, wallet_type, chain_id, collateral_balance/allowance, token_balances, token_approved, foreign_order_ids/token_ids, discrepancies, discovery_complete, limitations. `entry_ready` requires complete clean evidence; Ledger still applies cash and risk checks independently. Limitations explicitly identify the index gap, dedicated-wallet assumption, ordinary CTF scope, unsupported session/scoped signers, conservative SELL minimum and lack of a protocol-enforced all-in fee cap.
- `LedgerSummary`: wallet, session_id, cash, cash_movement, realized_net_pnl, fees, inventory, risk_reserve, position_risk, claimable_value, unresolved_orders, halts, daily_entries, daily_realized_net_pnl, session_realized_net_pnl, stop_requested. `cash` is reconciled initial cash plus actual receipt cash movements, never claimable value. It can be unknown before baseline.
- `EngineResult`: action, reason, optional intent_id. SUBMITTED only reports submission classification; inspect orders/positions/summary for finality and exposure.
- `PendingCandidate`: slug/side/config fingerprint, condition/selected token, round boundaries, reference price/timestamp/settlement source, initial spot source, immutable original book source, original decision time.

## CLI lifecycle and concurrency handoff

1. Help, anonymous observation and public doctor must not call the secure factory or initialize an account. Public observer storage is separate from live wallet storage. The Ledger itself accepts a chosen path and wallet identity and never reads credentials; CLI owns mode/path validation.
2. Explicit execute resolves the canonical `runtime_path(repository, normalized_funder)`, whose location is the common Git root `.runtime/<wallet>/ledger.sqlite`. Open `Ledger` to acquire the exclusive owner lock before any account setup. Other worktrees resolve the same location. Leaf directory is 0700; SQLite, lock, WAL and SHM are 0600. Lock contention is `WALLET_LOCKED`.
3. After owner lock acquisition, execute calls `clear_stop_request()` exactly once, **before any awaited account setup**, to acknowledge only the old stop. It must never clear the flag again during that run. A newer concurrent stop during setup/preparation therefore survives. Neither session startup nor readonly modes clear stop. CLI must record startup/error state if startup fails after the explicit clear, as agreed with root.
4. Start/resume the configured session and construct the no-deploy secure client with all existing credentials explicitly. Factory requires exact SDK0.9.0, disables SDK request logging and auth validation mutation, uses private `_create`, and rejects unrecognized owner/funder relationships including the SDK's fallback DEPOSIT_WALLET+SESSION_KEY classification. It does not approve, deploy or repair/derive/create credentials.
5. Construct `ReadOnlyRPC`, `Broker`, and `Engine`. `await engine.reconcile()` reconciles surviving SUBMITTING/ACK/UNKNOWN orders and reads account evidence; the engine applies baseline/discrepancy observation only when appropriate. `Broker.preflight()` alone performs reads and returns evidence, without adopting balances into the ledger. For account doctor the caller reports this evidence and closes resources.
6. Feed observation/snapshot production must continue independently of account requests and entry decisions. Pass `ledger.record_observation` as the synchronous MarketData observer, call `ledger.record_snapshot(snapshot, config)` immediately for each paired complete snapshot, and `record_clock(now_ms)` while no complete snapshot arrives. This is necessary to preserve the fixed sample interval despite slow account reads. Engine also records its decision-time paired snapshot, but first-eligible/calibration keys do not move already captured records.
7. Independently fetch the held token book from `ledger.open_position().token_id` using the approved `MarketData.book(token_id)`. Call serialized `engine.step(latest_snapshot_or_none, held_book_or_none, actual_now_ms)`. Stored position Market controls exit/resolution even after discovery moves to another round. Missing reference/history may prevent entries while held-book exits remain possible. Do not let slow discovery or observation block delivery of held books. Avoid overlapping direct `reconcile()` with `step()`; step already invokes it.
8. Each step reconciles before deciding. No new entry while exposure/account/risk is uncertain. Actual current time is checked after awaited reads and again after preparation. Pending candidate waiting creates no reserve or intent. After confirmation, reserve commit precedes sign; exact signed payload/hash/domain commit precedes SUBMITTING commit; only then one HTTP POST is possible. BUY preparation rechecks stop/window/freshness before marking/submission.
9. `Ledger.request_stop_at(existing_path)` is the independent CLI control write; readonly status/report use `Ledger(..., readonly=True)` without the owner lock or session initialization. A stop halts entries and requests protected existing-position exit; it never erases unknown orders.
10. `engine.shutdown(...)` persists stop and makes one bounded reconciliation/close attempt, using the last held book or a matching snapshot book. It does not close resources, loop until flat, or promise finality. CLI continues observing/reconciling while exposure remains and must show unresolved/dust/resolution states if the process ends. After worker completion, close Broker (owns SDK/RPC/its public HTTP) and Ledger (releases owner lock), and independently close MarketData. Reopening retains all durable risk and uncertainty.

## Reporting and observations

Use only the explicit public accessors above; no Task4 dependency on SQLite tables or private connection is needed.

- `decisions()` returns every persisted paired screen in source order: kind candidate, slug, mode (`value` then `momentum` per call), now_ms, safe Decision object, config_fingerprint. This includes ineligible reasons and creates no paper fill. Paired raw screening may be eligible while account/confirmation/execution blocks actual entry.
- `measurements()` returns the first eligible screen per round/mode (with market, spot, TWAP, both books and timestamps), and calibration records. Fixed calibration is the first complete sample within `[end-120s, end-120s+2s]`; missing is explicitly recorded after that interval. Discovery starts the pending record even if no complete snapshot ever exists. Fields include target_ms/status observed|pending|missing, configuration fingerprint and captured features. Safe final_reference observations support later official labels.
- `observations()` returns only whitelisted public records, including source observation events and `execution_confirmation` waiting/cancelled/confirmed events. These contain original candidate identity and immutable watermark, current spot/book timestamps and current book-minus-spot gap. No signer/private payload reaches this API.
- `exit_quote` observations report held_quantity, covered_quantity, full_depth, gross_price/proceeds, estimated_sell_fee, estimated_net_proceeds and source timestamps. Source is explicitly `stored_market_fee_estimate`; it is a quote based on stored market fee metadata, not a guaranteed current charge. Price triggers still use gross whole-held depth. Partial quotes do not imply full liquidation. Actual receipt fees and PnL stay exclusively in summary/accounting.
- Final status/report must separately show cash movements, realized net PnL, actual fees, estimated quotes, active risk/reserves, unresolved orders and noncash claimable holdings. Safe dictionaries serialize Decimal values as strings. User-funded data and exact signed payload must not be dumped through a generic database/asdict export.

## Implemented safety/accounting behavior

Restart tests cover RESERVED/PREPARED known unposted abandonment and SUBMITTING/ACK/UNKNOWN uncertain retention, including actual child-process SIGKILL at persistence boundaries. Unknown post response is never replayed, and an owned-order404 plus no visible trade remains inconclusive. Known rejection may settle absent exposure; a mismatching acknowledgment hash freezes entries. Duplicate receipt polls cannot alter money twice. Provisional/new-schema/MATCHED_NOT_BROADCASTED/MINED/RETRYING statuses retain pending evidence; all pages are bounded, overlapping and deduplicated. Confirmed account trade status and a canonical successful matching receipt are both mandatory. Unrelated batch logs are ignored; malformed tracked logs block.

The independently specified arithmetic is exact: BUY5 @0.70 with fee0.0735 debits3.5735. SELL2 @0.80 with fee0.0224 credits1.5776. Three shares retain basis2.1441; realized net PnL0.1482. Gross entry stays0.70, distinct from fee-inclusive0.7147. Partial BUY replaces only corresponding reserve with actual basis; a real reserve breach remains a sticky entry halt. Transfers/account differences do not become profit. Transient account/receipt gaps can clear only when later complete evidence explains them. Session/day budgets survive restart; explicit new session does not erase UTC daily loss/count; carried midnight inventory still consumes loss risk.

BUY is exact core principal, protected FOK, no max_spend resizing. SELL uses actual reconciled holdings, protected FAK, shares floored to0.01. Full held bid depth determines STOP/PROFIT; TIME/SHUTDOWN permit protected available partial depth. Missing/stale/crossed/no bids, mismatching token, missing account shares, precision dust and conservative venue minimum are explicit. No fabricated sale, zero-price liquidation, unprotected fallback or endless dust intents exists.

SELL tick handling follows root's sourced ruling. Current supported book/forced SDK agreement may supersede historical saved tick. A mismatch only permits supported finer SDK tick dividing the book tick. Consumed SDK book levels and the protected floor are validated on that grid; rounding the raw slippage floor is upward. Entry mismatch stays blocked. Preparation persists historical/book/current tick and reason. Raw metadata checks preserve condition/token/negative-risk/acceptance/minimum/fee guards despite SDK MarketInfo omissions.

Residual resolution reads one explicit finalized block, rechecks hash, requires binary exact numerator pattern and derives indexsets1/2 tokens using underlying USDC.e. It matches token identity independently of label/order. Only verified result moves winners to CLAIMABLE (quantity+basis retained, value noncash) or writes losing basis off once (known tokens remain tracked). Unknown order/account state prevents transition. Later rounds can proceed after reconciled resolution without inventing redemption or cash.

Experimental confirmation is shared by both selected modes. Same-side independently current eligibility, strictly newer spot and spot source >= original book source are required with exact milliseconds. Material identity/config/side/round/reference changes rearm at most; missing/stale/window/stop/account/exposure blocks cancel. Same-value provenance confirmation retains the original watermark. It uses the new decision price/sizing. Restart discards pending state but retains safe events. Synthetic delayed18USD shock invalidation and persistent changed-price confirmation are tested. This is an experimental lag safeguard; the one public event does not establish better ROI or complete synchronization of current feeds.

## TDD and verification evidence

All tests use actual core/SQLite/SDK behavior with external HTTP/ABI/receipt fixtures. Synthetic SDK construction rejects any network; account fixtures explicitly reject mutation endpoints except the single synthetic order POST under test. Fixed bytes/vectors and expected Decimal totals are independent assertions, not a second trading implementation.

Recorded development red evidence in ignored `work/task3/`:

| Log | Observed red result / behavior |
| --- | --- |
| ledger-red.txt | 14 failures after minimal import scaffolding; durable/accounting APIs absent |
| rpc-red.txt | 20 failures; receipt/hash/resolution contract absent |
| broker-red.txt | 19 failures; actual pinned adapter contracts absent |
| engine-red.txt | 9 failures; real integration behavior absent |
| refinement-stop-red.txt | 8 failed,4 passed,28 deselected; refinement and stop race |
| recovery-red.txt | 4 failed,26 deselected; accounting/recovery corrections |
| current-floor-red.txt | 1 failed,14 deselected; historical tick created invalid exit floor |
| crash-control-red.txt | 1 failed,7 passed,16 deselected; explicit stop-clear missing; crash checks already held |
| account-resolution-red.txt | 2 failed,52 deselected; missing balance/resolution guard |
| metadata-measurement-red.txt | 2 failed,4 passed,44 deselected; raw min and never-complete sample |
| domain-red.txt | 1 failed,25 deselected; durable signing domain guard |
| final-guards-red.txt | 2 failed,60 deselected; wrong-chain/clock reversal |
| confirmation-red.txt | 11 failed,16 deselected; pending confirmation gate absent |
| exit-quote-red.txt | 2 failed,34 deselected; expected-fee quote observations absent |
| decisions-red.txt | 1 failed,27 deselected; safe readonly paired-screen accessor absent |

Each red behavior was implemented and rerun green before the broader checks. Earlier transient test setup mistakes were corrected before relying on red evidence (e.g. the final accessor test first used a nonexistent fixture name). Additional adversarial cases were included for raw identities, tick precision, repeated pages, receipt identity, reversed resolution labels, exact milliseconds and material candidate changes.

Latest completed combined command `.venv/bin/python -m pytest -q`: **300 passed in14.31s**, output `work/task3/final-tests.txt`. This includes all approved core/data tests and118 new execution tests. The final narrow readonly decisions accessor was subsequently added by root ruling and verified with the complete affected Ledger test file: **28 passed in3.45s** (119 execution cases now,301 total collected tests). No other runtime change followed the combined run.

Static checks after final changed code: `.venv/bin/python -m ruff check src/btc5m tests`; `.venv/bin/python -m ruff format --check src/btc5m tests`; `.venv/bin/python -m mypy src/btc5m tests/test_ledger.py tests/test_rpc.py tests/test_broker.py tests/test_engine.py`; `git diff --check`. **All checks passed;17 files already formatted; mypy clean across14 files; diff check clean**. Branch verified `feat/standalone-btc5m`; staged paths reviewed explicitly.

Anonymous public crosscheck used the implemented ReadOnlyRPC, with no signer/account construction: `PYTHONPATH=src:tests .venv/bin/python work/task3/anonymous-rpc-check.py` (scratch script). Chain137; deployed exchange hashOrder equals local fixed vector `0xf356f5e9c8b3c25ebd7e8734cf4c2925120f12bb9df8ff1c55847f6fbb99b22b`. Finalized block93341033 hash `0xf155e36b8f5cf6e7909a8a1fc66814bf3d9fccbe571d30d67f907142560993e6`, observed1788716587749ms, condition `0x36734a624c2b5aeee164162536fe811bb82677ad927050b50cc46838fe67d494`: denominator1, numerators(0,1). Derived token `93464131606378261331338471789927052245553593563803080458303202347805601920785` payout0; token `54587822891934720131108562415940344642217988714969692821005775518682216077925` payout1. Evidence `work/task3/anonymous-rpc-check.json`; error output empty. This independently exercised deployed hash and finalized residual identity mapping through implementation, not order acceptance.

## Self-review and remaining concerns

Reviewed source/diff for unauthorized mutations, credential/payload logging, hash and receipt identity, atomic reserve/cash changes, recovery after process death, risk budgets, protected exits and current metadata, control races and reporting leakage. Fixed issues found during this review within scope: temporary discrepancies previously sticking after confirmed explanation; missing actual token balance before exit; resolution while account uncertain; raw minimum and fee-key schema guard; stored signing domain; timestamp reversal; historical tick floor; missing calibration when discovery never yields a full snapshot; fee quote/report accessor omissions. No remaining known release-blocking implementation defect was identified by this self-review; root independent review is still required.

Bounded limitations to carry into Task4/user docs:

- Live funded credential/auth relationships, balance cache behavior, actual venue order acceptance/finality/partial fills and deposit/proxy signing behavior remain unverified. Only recognized owner signers are supported; SDK fallback session/scoped keys are deliberately unsupported.
- Public indexed holdings with sizeThreshold0/includeArchivedtrue and complete pagination remains candidate discovery, not an exhaustive at-block ERC1155 ownership proof. Dedicated wallet/no external trading and ordinary CTF assumptions are essential. External claims/transfers remain discrepancies, not automatic ledger import or strategy profit.
- SDK0.9 uses pinned private hooks. Version drift blocks rather than attempting repair. Actual tick-refined order acceptance and subminimum FAK behavior remain unverified; conservative minimum can leave explicit residual dust pending verified resolution.
- Fee reserves are conservative estimates; current deployed fee cap does not guarantee a protocol all-in maximum. Receipt fees are actual; breaches halt entries. Exit quote fee uses saved metadata and is explicitly an estimate.
- Confirmation adds latency and may suppress eligible trades; no evidence of ROI superiority, no eligible momentum public event in the supplied probe, and no claim that current feeds are fully synchronized.
- One engine step can await bounded account calls; Task4 must keep feed observation and held-book scheduling independent. Safe query accessors materialize their records in memory and journal rows currently have no retention job; suitable for the bounded experiment, not an unbounded analytics service.
- Ledger is the largest module (~959 lines); root explicitly approved separate typed/RPC modules earlier. Remaining Ledger size comes from one concrete schema/accounting/report responsibility, not multiple engines or a general framework. No further split was introduced speculatively.
- Root identified pytest8.4.2 CVE-2025-71176 after these checks and will update the root-owned test dependency to official9.0.3 and rerun the combined suite. No runtime dependency match was reported; this worker did not alter the environment.
- No prior user runtime migration was needed or performed; synthetic task databases are disposable. Production schema evolution must be explicit if later tasks change persisted fields.

No user approval is sought by this report; it hands a concrete locally verified implementation to root for independent review and then Task4 integration.

## Root dependency verification after handoff

Root updated only the development runner from pytest8.4.2 to9.0.3 for the verified temporary-directory advisory. Runtime dependencies are unchanged. uv sync --locked and uv lock --check passed. Full suite under pytest9.0.3: **301 passed in15.54s**, work/pytest-security-upgrade-tests.txt. OSV query of44 locked registry packages plus pinned build backend returned zero matches after the update; exact report docs/reviews/dependency-audit.md.
