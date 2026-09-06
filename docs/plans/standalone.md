# Standalone BTC five-minute implementation plan

> For agentic workers: use superpowers:subagent-driven-development. Each task has a bounded owner,
> meaningful failing tests, implementation, verification and an independent task review.

**Goal:** Repair the published repository into a self-contained, auditable bot for a bounded live experiment.
**Architecture:** Pure Decimal/domain/strategy core, official async public/account adapter, SQLite execution
state machine, and a small CLI. No subprocess trading engine and no LLM in execution.
**Tech Stack:** Python3.12, uv, polymarket-client0.9.0, SQLite, pytest, ruff, mypy.
**Spec:** docs/design.md (binding); source reports in docs/research/.

## Global Constraints

- User authorizes autonomous research/design/implementation, feature worktrees and subagents; routine choices are recorded, not blocked on repeated approval.
- No funded orders, credentials inspection, wallet approvals/transfers or automatic redemption during development.
- Decimal for prices, cash, quantities and fees; float restricted to probability/volatility math.
- Official SDK0.9.0 only; never use place_* convenience methods or blind POST retries.
- Terminal-surplus proxy is uncalibrated and is not expected profit under the exit policy.
- Unknown rules/anchor, stale data and uncertain order/account state stop new entries visibly.
- Main/develop are never pushed or merged; branches/worktrees are preserved. Workers never spawn their own agents.
- Tests use actual core/SQLite plus synthetic external account/HTTP fixtures; no source-text mirror assertions.
- Every configured safety rule has a consumer; secrets and signed payloads never enter ordinary logs.

## File and interface map

Task1 owns `src/btc5m/{__init__,domain,config,strategy}.py`, `config/btc5m.toml`, `tests/test_{config,strategy}.py`.
Task2 owns `src/btc5m/market_data.py`, `tests/test_market_data.py`, public fixtures in `tests/fixtures/`.
Task3 owns `src/btc5m/{broker,ledger,engine}.py`, `tests/test_{broker,ledger,engine}.py`.
Task4 owns `src/btc5m/{cli,__main__}.py`, CLI/E2E tests, wrappers, docs, container/CI cleanup.
Root owns design/research/plan/progress and package/bootstrap metadata until final integration.

Domain interfaces established by Task1 (other tasks consume these names):

```python
class Side(str, Enum):
    UP = "UP"
    DOWN = "DOWN"

@dataclass(frozen=True)
class PricePoint:
    kind: Literal["spot", "twap60"]
    timestamp_ms: int
    received_ms: int
    price: Decimal

@dataclass(frozen=True)
class Level:
    price: Decimal
    size: Decimal

@dataclass(frozen=True)
class Book:
    token_id: str
    timestamp_ms: int
    received_ms: int
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]

@dataclass(frozen=True)
class Market:
    slug: str
    condition_id: str
    start_s: int
    end_s: int
    up_token: str
    down_token: str
    reference_price: Decimal | None
    reference_source: str | None
    settlement_source: str
    tick_size: Decimal
    min_order_size: Decimal
    fee_rate: Decimal
    fee_exponent: int
    active: bool
    accepting_orders: bool
    reference_status: Literal["official", "boundary", "missing", "conflict"]
    reference_timestamp_ms: int | None
    metadata_received_ms: int
    metadata_provenance: str
    def token(self, side: Side) -> str: ...

@dataclass(frozen=True)
class Snapshot:
    market: Market
    up_book: Book
    down_book: Book
    spot: PricePoint
    twap60: PricePoint
    history: tuple[PricePoint, ...]
    now_ms: int

@dataclass(frozen=True)
class Decision:
    slug: str
    side: Side | None
    reason: str
    price_limit: Decimal | None
    buy_principal: Decimal
    max_total_reserved: Decimal
    expected_shares: Decimal
    minimum_receive_shares: Decimal
    estimated_buy_fee: Decimal
    probability_up: float | None
    scenario_floor: float | None
    terminal_surplus_proxy: Decimal | None
    features: dict[str, float | str]
```

`Config` has nested frozen `strategy`, `risk`, `data`, `execution` settings; `load_config(path: Path)->Config`
validates complete TOML. `evaluate(snapshot: Snapshot, config: Config)->Decision` has no side effects.
`fee_for(shares: Decimal, price: Decimal, rate: Decimal, exponent: int=1)->Decimal` supplies the pricing fee.
The ellipsis in the type sketch denotes a method body owned by Task1, not unfinished plan requirements.

### Task 1: Domain, configuration and strategy candidate

Read design contract/model/sizing sections. Public behaviour is deterministic decisions and reason codes.

- [ ] Write tests first for unknown/invalid configuration, nonfinite numbers, quantity budget vs minimum,
  stale/crossed/missing-side books, missing anchor, wrong rule, wrong round and insufficient history.
- [ ] Add independently derived numerical tests, including:

```python
assert fee_for(Decimal('5'), Decimal('.70'), Decimal('.07')) == Decimal('.07350')
# sigma=50/sqrt(60), delta=90, tau=120, 60-second-average model:
assert probability_up == pytest.approx(0.9405, abs=0.0001)
# Equal current price and reference with positive variance yields .5; UP/DOWN central probabilities sum1.
# A future-dated tick and a 61-second gap cannot make a fresh, valid history.
```

- [ ] Observe failing behavioural tests. Implement domain validation, frozen config, TOML and pure strategy.
  Value mode uses zero drift, two variance windows + stress, adverse reference scenario, actual depth,
  selected-side spread, fee allowance and terminal proxy. Momentum mode implements original move/timing
  comparison with same safety (the design labels it a modified upstream reference). Reject extra config keys and incompatible timing; no simulation fills.
- [ ] Test spend-based depth and tick rounding; small USD5 caps must never round up to exchange minimum.
  Decision principal is the exact BUY cash amount, estimates are not authoritative holdings. Derive
  minimum shares from principal/limit with conservative supported rounding; reserve worst-case buy fees.
  Assert improved asks deliver more estimated shares without increasing signed principal or reservation.
  Require explicit reference status and market flags; unknown status never permits an entry.
- [ ] Verify pytest scoped tests, ruff and mypy on owned files; record exact test output and commit.
- [ ] Independent task review checks maths/units, configuration consumption and real decision failure paths.

### Task 2: Anonymous market data and trustworthy anchors

Consumes Task1 types and config. Produces `MarketData` async context manager with
`async snapshot(now_ms: int | None=None)->Snapshot`, plus observation/persistence hook, explicit
`DataUnavailable(code)`, independent `async book(token_id)->Book` and `close()`. Worker may add small internal helpers, not change domain silently.

- [ ] Create realistic pinned SDK payload fixtures for a current TWAP market, opposite token ordering,
  missing metadata, wrong listing/start date, changed rules, empty asks and timestamp units.
- [ ] Write failing tests for exact boundary selection, duplicate/out-of-order points, missing boundary,
  post-disconnect warmup gaps, source-vs-receive freshness and fee/tick changes. Anchor comparison must
  distinguish exact match, mismatch and official metadata still missing.
- [ ] Implement two official streams (Chainlink spot and TWAP60), bounded history, current market discovery,
  concurrent book snapshot, metadata normalization and explicit source provenance. Use actual SDK methods.
  Capture source-time boundary points only; do not assume first-received point is correct. Safe default
  leaves captured-anchor live use disabled until reviewed empirical probe passes.
- [ ] Inject public client/clock at boundary for tests; use real parsers/state with complete external fixtures.
  Do not inject a fake implementation of the component itself.
- [ ] Run scoped tests and anonymous smoke against current market/streams. Record UTC window and access errors.
  Validate unsupported cases fail closed. Commit and obtain task review.

### Task 3: Durable order execution, cash accounting and recovery

Consumes Task1 domain/config/decision and Task2 snapshots. Produces `Broker`, `Ledger`, `Engine` APIs
specified concretely in a task brief after public SDK inspection, including async sign/post/reconcile
and engine step/shutdown. No CLI behaviour may hide unresolved exposure. The task brief fixes the adapter protocol before dispatch; the concrete contracts below bind it.

`PreparedOrder` contains intent_id, order_hash, private signed payload and maximum reserved cash/quantity.
`OrderAck` contains accepted/rejected/unknown classification and any provisional trade IDs.
`OrderEvidence` contains cumulative deduplicated confirmed receipt fills, pending fill IDs, terminal
status, actual token/collateral balances and explicit reconciliation discrepancies.
`Broker` provides async preflight(), prepare(intent,market), post(prepared), reconcile(order) and close().
`Ledger` provides start_or_resume_session(config), reserve_entry(decision,market,session_id,now_ms),
prepare(intent_id,prepared), mark_submitting(intent_id), record_ack(intent_id,ack),
apply_evidence(intent_id,evidence), open_position(), unresolved_orders(), summary(), request_stop()
and stop_requested(). `Engine(broker,ledger,config,session_id)` provides async
step(snapshot_or_none,exit_book_or_none,now_ms), reconcile(), and shutdown(snapshot_or_none,now_ms).
Exit processing must remain possible when reference-feed/history is unavailable; it uses the stored
market/position and independently fetched bid book. Task2 also provides async book(token_id)->Book.

- [ ] Define observable ledger transitions RESERVED->PREPARED->SUBMITTING->ACK/UNKNOWN->SETTLED/REJECTED,
  separately tracking cumulative confirmed fills, outstanding quantity and risk reservations.
- [ ] Tests first: lost POST response after acceptance, restart after each persistence boundary, duplicate
  fill callback, partial sell then retry remainder, mixed failed/confirmed fills, receipt fee accounting,
  not-found order, exit without bids, foreign inventory, wrong chain/receipt and single-process lock.
- [ ] Include independent cash arithmetic:

```python
# Confirmed BUY receipt:5 shares, price.70, actual fee.0735 => inventory5, cash debit3.5735.
# Confirmed SELL receipt:2 shares, price.80, fee.0224 => inventory3, cash credit1.5776.
# Replaying the same (chain,tx,log_index) cannot alter those totals.
# Unknown buy with zero visible fills must retain reserve and prevent another entry after restart.
```

- [ ] Implement SQLite with atomic reserves/unique round intent and private signed payloads. No budget reset
  on restart. Default wallet-scoped common-root runtime, restrictive permissions and process lock.
- [ ] Implement secure SDK factory only on explicit live path, preflight balances/allowances/foreign orders,
  canonical EIP712 hash, protected FOK entry and FAK exit, persist-before-post, owned-order reconciliation.
  Receipt decoding filters chain/exchange/hash/token/wallet; actual fees finalize cash. Read-only RPC helper.
- [ ] Engine evaluates entry only while flat/reconciled; risk limits count unknown and provisional exposure.
  Actual held shares and depth drive exits. Stop/time/profit triggers share reliable close handling.
  No GTC/penny fallback, auto approval, auto redemption or false success on partial fills.
- [ ] Verify scoped tests, independently crosscheck hash vector or read-only hashOrder, replay crash scenarios;
  anonymous RPC check only. Commit and task review of safety/accounting and spec compliance.

### Task 4: CLI, operations, documentation and integration

Consumes MarketData/Broker/Ledger/Engine. Owns cli/__main__, tests/test_cli.py, tests/test_end_to_end.py,
README.md, SKILL.md, CONTOUR.md, examples/run-example.md, scripts/, docker-compose.yml/Dockerfile and CI.

- [ ] Tests first: help/observe do not read credentials or mutate wallet, missing --execute cannot trade,
  unknown flags fail, safe env-file parsing never evaluates shell, stop preserves unresolved inventory,
  two processes cannot own same live runtime, and reports work after abrupt termination.
- [ ] Implement commands observe, doctor, run --execute, stop, status, report, reconcile. Finite duration/trade
  limits. Stream public observations and snapshot skip reasons; do not fabricate paper PnL. Account doctor
  is explicit/read-only. Canonical config path resolves from package/repo, not accidental working directory.
- [ ] Replace unsafe shell control with thin quoted repo-local CLI delegation. Remove all orphaned legacy
  strategy/report engines and unused YAML; update docs and examples to actual verified commands.
- [ ] Retain Docker only with an explicit runtime mount and no parent directory or default secrets; document
  any unverified build. Add CI scoped to pytest/lint/format/type checks and dependency lock consistency.
- [ ] Synthetic E2E exercises real core+ledger+engine and fake venue transport, including entry->partial exits
  ->confirmed fees->flat report, then interrupted/unknown recovery. No source-string tests.
- [ ] Run full checks and bounded public observe/doctor. Produce concise research/strategy decisions and live
  experiment instructions, known limits and evidence. No actual funded orders in this task.
- [ ] Final independent whole-branch review and fixes. Update AGENTS verified commands and project memory.
  Preserve branches/worktrees. User merges; remote publication destination is not assumed to be upstream.
