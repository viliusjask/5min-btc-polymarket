# Task4 integration: read execution inputs after reconciliation

**Existing APIs do not suffice for this latency case.** Independently polling books in the CLI cannot make an already-passed frozen `Book` newer. A narrow Engine integration change is needed. Keep reconciliation before selling and the five-second freshness check.

Source inspection: standalone worktree at HEAD `96361d7bbd38dcb7f8b38ff78b9ca3ce915afc03`; Task3 fixes may concurrently change these files. No code or tests were modified/run. Line references below describe the inspected source, not a review of the pending fix round.

## Evidence and failure mechanism

- [`domain.py:42`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/domain.py:42) declares `Book` frozen; replacement of the CLI's latest-book variable cannot change the object already passed to Engine.
- [`engine.py:56`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/engine.py:56) acquires its lock, awaits `reconcile()`, advances to real clock time, and passes that original book to `_exit`. [`engine.py:31`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/engine.py:31) reconciles outstanding orders and then awaits a complete account preflight. The latter has a 40-second bound and several sequential account reads ([`broker.py:196`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/broker.py:196)).
- [`engine.py:298`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/engine.py:298) compares both original book timestamps with actual current time; the default maximum age is 5000ms ([`config.py:91`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/config.py:91)). If each account pass takes 6000ms, a book fresh at every call still fails on every iteration.
- `await engine.reconcile(); fresh_book=...; await engine.step(...)` performs reconciliation twice. Queueing more steps still leaves the same await before consumption. Broker's later independent preparation-book fetch cannot rescue this: `_exit` rejects the stale input before creating an intent or reaching `prepare` ([`engine.py:267`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/engine.py:267)).
- Snapshot invalidation has the same ownership boundary: only the single passed `snapshot is None` cancels at step start. A gap overwritten by a newer valid CLI cache value may never reach the engine, allowing its old pending candidate to survive ([`engine.py:60`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/engine.py:60), [`engine.py:165`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/engine.py:165)). A FIFO avoids overwriting but builds stale work rather than current decisions.

## Smallest combined integration boundary

Keep current positional `step(snapshot, exit_book, now_ms)` for direct callers/fixtures. Add two optional read-only providers to Engine construction for the CLI mode:

```python
read_exit_book: Callable[[str], Awaitable[Book | None]] | None
read_snapshot: Callable[[], SnapshotInput] | None

@dataclass(frozen=True)
class SnapshotInput:
    snapshot: Snapshot | None
    invalidation_generation: int
```

No new producer protocol or persisted schema is needed. The exit provider wraps the existing [`MarketData.book(token_id)`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/market_data.py:408); unavailable reads return None with an independently recorded safe reason. It must not await current-round discovery. The snapshot provider synchronously returns a CLI-owned immutable latest-value cell, without I/O. Publishing a later valid snapshot retains prior invalidation history. Existing observation records preserve individual reasons. No queue of old snapshots is needed.

Define invalidation precisely at the CLI publication/observer boundary:

- Increment generation for every observed `DataUnavailable`, missing snapshot, or snapshot stale/invalid at actual consumption time; also for a completed snapshot whose **selected-mode raw core decision is not ENTRY**. Reuse the existing core evaluator/paired decision result, not a new eligibility implementation. Nonselected-mode rejection alone is irrelevant.
- Increment on intervening material identity changes between observed candidate inputs: configuration/mode, selected side, slug/condition/selected token/round boundaries, or reference value/source timestamp/settlement rule. Compare every observed complete input, not only engine-consumed ones, so A→B→A remains detectable. Match the current PendingCandidate identity semantics: equal-value reference provenance/status confirmation is not a material change merely because its descriptive provenance changed.
- **Invalidate immediately on required `spot` or `twap60` `stream_unavailable`/`price_conflict` observer events, before a later snapshot poll exposes the gap.** [`market_data.py:250`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/market_data.py:250) emits the failure synchronously after clearing stream readiness; [`market_data.py:303`](/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/src/btc5m/market_data.py:303) emits conflicting-price evidence. Set the latest snapshot unavailable until a newly validated complete snapshot is published. Do not let an in-flight poll that began before an invalidation silently clear this latch: capture generation at poll start and discard/retry completion if generation changed during its awaits. Unrelated delayed labels for old rounds do not alone invalidate current inputs.
- **Do not increment for every valid new quote or spot point.** Same-identity eligible updates replace the latest snapshot without invalidation. Required real-time freshness checks still catch silent aging; this counter preserves observed interruptions, not all ordinary market movement.

Engine alone changes pending candidates, ledger, or execution state under its existing lock. It samples the latest input/generation at serialized boundaries, especially after reconciliation. A new generation cancels the previous candidate before any confirmation; a later valid snapshot can only arm a new candidate with a new original watermark. Legacy placeholder arguments must not cause spurious cancellation when a provider is configured. For BUY, sample again after awaited preparation: an intervening invalidation or missing latest snapshot abandons the known-unposted intent before submission. Retain the existing current-time, identity and economic revalidation; do not replay an order already submitted.

After reconciliation and unresolved-order/account guards, select the **current ledger position's token**, then invoke the exit provider. Recompute actual time after that await and reapply expiry/resolution routing before `_exit`; a quote request crossing market end must not freeze time. An already-expired position can go straight to existing resolution handling. The same provider must apply through shutdown; cached `_last_exit_book` is not made fresh by reuse. Book freshness, token/depth checks, minimum/precision, tick/fee validation and broker preparation/post guards remain intact.

Ownership: after Task3's fix round finishes, explicitly give Task4 the narrow `engine.py` provider integration, `execution_types.py` SnapshotInput record, focused `tests/test_engine.py` regression(s), and its already-owned CLI/E2E scheduling tests. CLI owns publication and lifecycle wiring. MarketData/Broker/Ledger business behavior remains with its existing owners. This requires a small ruled interface extension, not private `_exit` calls, field mutation, skipped reconciliation, or another coordinator.

## Deterministic acceptance scenarios

Use the existing real SQLite/core/engine fixtures and simulated external clock/transport; no wall-clock sleeps:

1. Held 5-share position, valid account, end at `t+20s`, due TIME exit. Pass a book stamped `t`. Block preflight with an event; while blocked, advance fake venue time by 6000ms and keep publishing books. On release, current code returns `STALE_EXIT_BOOK`. With provider integration, assert account reconciliation completes **before** provider invocation, provider returns a book at `t+6000`, and SELL preparation/submission occurs before an independently blocked discovery task completes. Return a genuinely old provider book in a paired case and still require `STALE_EXIT_BOOK`. Unresolved account/order evidence must still prevent selling.
2. Arm candidate A. During the next blocked account pass publish missing snapshot (generation +1), then an eligible valid snapshot with newer spot satisfying A's old watermark. On release, assert cancellation of A and only fresh arming, **no reserve/sign/post**. A subsequent independent confirming point is required. Repeat with an intervening selected-mode rejection, A→different side/round/reference→A, and stream failure/recovery occurring wholly between snapshot polls. Repeat the gap during BUY preparation and assert abandonment before POST. A control publishes ordinary eligible same-identity updates during preparation and must not invalidate solely because another quote arrived.
3. Repeat held-book delivery through shutdown; separately advance across expiry while awaiting the provider and assert existing resolution routing. Assert at most one engine step/ledger writer owns execution throughout.

This removes account-read latency from quote age; it does not guarantee an exit when the book, reconciliation, metadata or signing path itself fails or the venue has already closed.
