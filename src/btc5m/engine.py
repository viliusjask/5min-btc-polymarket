"""One strategy coordinator with durable sign/submit boundaries and held-token exits."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from btc5m.paper import PaperBroker

from btc5m.broker import Broker, BrokerError
from btc5m.config import PAIR_STRATEGIES, Config
from btc5m.domain import Book, Decision, Market, Side, Snapshot
from btc5m.execution_types import (
    EngineResult,
    Intent,
    OrderAck,
    PendingCandidate,
    Position,
    PreflightEvidence,
    SnapshotInput,
)
from btc5m.ledger import Ledger, LedgerError
from btc5m.pairing import pair_decision
from btc5m.strategy import evaluate, fair_value, fee_for

D = Decimal


class Engine:
    def __init__(
        self,
        broker: Broker | PaperBroker,
        ledger: Ledger,
        config: Config,
        session_id: str,
        *,
        read_exit_book: Callable[[str], Awaitable[Book | None]] | None = None,
        read_snapshot: Callable[[], SnapshotInput] | None = None,
        read_model_snapshot: Callable[[], Snapshot | None] | None = None,
        record_screens: bool = True,
    ) -> None:
        self.broker, self.ledger, self.config, self.session_id = broker, ledger, config, session_id
        self._lock = asyncio.Lock()
        self._read_exit_book, self._read_snapshot = read_exit_book, read_snapshot
        self._read_model_snapshot = read_model_snapshot
        self._record_screens = record_screens
        self._input_generation: int | None = None
        self._last_exit_book: Book | None = None
        self._shutting_down = False
        self.preflight: PreflightEvidence | None = None
        self.pending_candidate: PendingCandidate | None = None

    def _now(self, now_ms: int) -> int:
        return max(now_ms, int(self.broker.clock() * 1000))

    async def reconcile(self) -> PreflightEvidence:
        for order in self.ledger.unresolved_orders():
            if order.state in ("RESERVED", "PREPARED"):
                self.ledger.abandon(order.intent_id, "ABANDONED_BEFORE_POST")
            else:
                evidence = await self.broker.reconcile(order)
                self.ledger.apply_evidence(order.intent_id, evidence)
        result = await self.broker.preflight()
        self.preflight = result
        # A provisional transfer may already be visible onchain. It cannot be
        # booked as strategy cash until all associated account evidence settles.
        if not self.ledger.unresolved_orders():
            reasons = result.discrepancies
            if result.foreign_order_ids:
                reasons += ("FOREIGN_ORDERS",)
            if result.foreign_token_ids:
                reasons += ("FOREIGN_INVENTORY",)
            self.ledger.observe_account(
                result.collateral_balance,
                result.token_balances,
                reasons,
                now_ms=int(self.broker.clock() * 1000),
            )
        return result

    async def step(
        self, snapshot: Snapshot | None, exit_book: Book | None, now_ms: int
    ) -> EngineResult:
        async with self._lock:
            if snapshot is None and self._read_snapshot is None:
                self._cancel_pending("NO_SNAPSHOT", None, now_ms)
            if exit_book is not None:
                self._last_exit_book = exit_book
            await self.reconcile()
            now_ms = self._now(now_ms)
            if self._read_snapshot is not None:
                current_input = self._read_snapshot()
                snapshot = current_input.snapshot
                if current_input.invalidation_generation != self._input_generation:
                    self._cancel_pending("INPUT_INVALIDATED", snapshot, now_ms)
                self._input_generation = current_input.invalidation_generation
            if snapshot is None:
                self._cancel_pending("NO_SNAPSHOT", None, now_ms)
            self.ledger.record_clock(now_ms)
            model_snapshot = self._read_model_snapshot() if self._read_model_snapshot else snapshot
            resting = await self._manage_resting(model_snapshot, now_ms)
            if resting is not None:
                return resting
            if self.ledger.unresolved_orders():
                self._cancel_pending("ORDER_UNRESOLVED", snapshot, now_ms)
                return EngineResult("WAIT", "ORDER_UNRESOLVED")
            position = self.ledger.open_position()
            if position is not None:
                self._cancel_pending("POSITION_OPEN", snapshot, now_ms)
            if (
                position is not None
                and now_ms < position.market.end_s * 1000
                and self._read_exit_book is not None
                and position.decision.features.get("mode") not in PAIR_STRATEGIES
            ):
                exit_book = await self._read_exit_book(position.token_id)
                now_ms = self._now(now_ms)
            if position is not None and now_ms >= position.market.end_s * 1000:
                resolution = await self.broker.resolve(position.market)
                if resolution is None:
                    self.ledger.note_exit(
                        position.position_id, "RESOLUTION", "RESOLUTION_UNCONFIRMED", now_ms
                    )
                    return EngineResult("HOLD", "RESOLUTION_UNCONFIRMED")
                try:
                    self.ledger.apply_resolution(position.market, resolution, now_ms)
                except LedgerError as exc:
                    self.ledger.note_exit(position.position_id, "RESOLUTION", str(exc), now_ms)
                    return EngineResult("HOLD", str(exc))
                position = self.ledger.open_position()
            if position is not None:
                if position.decision.features.get("mode") in PAIR_STRATEGIES:
                    return await self._pair_step(model_snapshot, now_ms, exit_book)
                return await self._exit(exit_book, now_ms, snapshot=model_snapshot)
            if self.ledger.stop_requested():
                self._cancel_pending("STOP_REQUESTED", snapshot, now_ms)
                return EngineResult("STOPPED", "FLAT")
            if snapshot is None:
                return EngineResult("SKIP", "NO_SNAPSHOT")
            current = replace(snapshot, now_ms=self._now(now_ms))
            if self._read_snapshot is None:
                # Direct callers use step as their observation boundary.
                if self._record_screens:
                    self.ledger.record_snapshot(current, self.config)
                decision = evaluate(current, self.config)
            else:
                # Providers publish raw observations separately. Reusing their latest
                # receipt at a later execution time must not create a new sample.
                decision = evaluate(current, self.config)
            if decision.reason != "ENTRY":
                self._cancel_pending(decision.reason, current, current.now_ms)
                return EngineResult("SKIP", decision.reason)
            if self.preflight is None or not self.preflight.entry_ready:
                self._cancel_pending("ACCOUNT_NOT_READY", current, current.now_ms)
                return EngineResult("SKIP", "ACCOUNT_NOT_READY")
            if (
                self.ledger.config is None
                or self.ledger.config.fingerprint != self.config.fingerprint
                or self.broker.config.fingerprint != self.config.fingerprint
            ):
                self._cancel_pending("CONFIGURATION_CHANGED", current, current.now_ms)
                return EngineResult("SKIP", "CONFIGURATION_CHANGED")
            try:
                self.ledger.check_entry(decision, current.market, self.session_id, current.now_ms)
            except LedgerError as exc:
                self._cancel_pending(str(exc), current, current.now_ms)
                return EngineResult("SKIP", str(exc))
            if not self._confirm_candidate(current, decision):
                return EngineResult("WAIT", "ENTRY_CONFIRMATION_WAITING")
            try:
                intent = self.ledger.reserve_entry(
                    decision, current.market, self.session_id, current.now_ms
                )
            except LedgerError as exc:
                return EngineResult("SKIP", str(exc))
            return await self._submit(intent, current)

    @staticmethod
    def candidate_identity(market: Market, side: Side) -> tuple[object, ...]:
        return (
            market.slug,
            market.condition_id,
            market.token(side),
            market.start_s,
            market.end_s,
            market.reference_price,
            market.reference_timestamp_ms,
            market.settlement_source,
        )

    def _confirmation_event(
        self, status: str, code: str, snapshot: Snapshot | None, now_ms: int
    ) -> None:
        pending = self.pending_candidate
        if pending is None:
            return
        record: dict[str, object] = {
            **asdict(pending),
            "kind": "execution_confirmation",
            "received_ms": now_ms,
            "status": status,
            "code": code,
        }
        if snapshot is not None:
            book = snapshot.up_book if pending.side is Side.UP else snapshot.down_book
            record.update(
                spot_source_ms=snapshot.spot.timestamp_ms,
                book_source_ms=book.timestamp_ms,
                book_minus_spot_ms=book.timestamp_ms - snapshot.spot.timestamp_ms,
            )
        self.ledger.record_observation(record)

    def _cancel_pending(self, reason: str, snapshot: Snapshot | None, now_ms: int) -> None:
        self._confirmation_event("cancelled", reason, snapshot, now_ms)
        self.pending_candidate = None

    def _confirm_candidate(self, snapshot: Snapshot, decision: Decision) -> bool:
        assert decision.side is not None
        market = snapshot.market
        signal_source_ms = int(
            decision.features.get("exchange_source_ms", snapshot.spot.timestamp_ms)
        )
        pending = self.pending_candidate
        if pending is not None:
            prior = (
                pending.slug,
                pending.condition_id,
                pending.token_id,
                pending.start_s,
                pending.end_s,
                pending.reference_price,
                pending.reference_timestamp_ms,
                pending.settlement_source,
            )
            if (
                pending.side != decision.side
                or pending.config_fingerprint != self.config.fingerprint
                or prior != self.candidate_identity(market, decision.side)
            ):
                self._cancel_pending("CANDIDATE_IDENTITY_CHANGED", snapshot, snapshot.now_ms)
                pending = None
        if pending is None:
            book = snapshot.up_book if decision.side is Side.UP else snapshot.down_book
            self.pending_candidate = PendingCandidate(
                market.slug,
                decision.side,
                self.config.fingerprint,
                market.condition_id,
                market.token(decision.side),
                market.start_s,
                market.end_s,
                market.reference_price,
                market.reference_timestamp_ms,
                market.settlement_source,
                signal_source_ms,
                book.timestamp_ms,
                snapshot.now_ms,
            )
            self._confirmation_event("waiting", "FIRST_ELIGIBLE_SCREEN", snapshot, snapshot.now_ms)
            return False
        if (
            signal_source_ms > pending.initial_spot_source_ms
            and signal_source_ms >= pending.original_book_source_ms
        ):
            self._confirmation_event(
                "confirmed", "NEW_SPOT_REVALIDATED_SAME_SIDE", snapshot, snapshot.now_ms
            )
            self.pending_candidate = None
            return True
        self._confirmation_event(
            "waiting", "SPOT_HAS_NOT_CAUGHT_ORIGINAL_BOOK", snapshot, snapshot.now_ms
        )
        return False

    async def _submit(self, intent: Intent, snapshot: Snapshot | None = None) -> EngineResult:
        try:
            prepared = await self.broker.prepare(intent, intent.market)
            self.ledger.prepare(intent.intent_id, prepared)
        except BrokerError as exc:
            self.ledger.abandon(intent.intent_id, str(exc))
            if intent.side == "SELL":
                self.ledger.note_exit(
                    intent.position_id, intent.reason, str(exc), self._now(intent.created_ms)
                )
            return EngineResult("SKIP", str(exc), intent.intent_id)
        if intent.side == "BUY":
            reason = None
            if self.ledger.stop_requested():
                reason = "STOP_REQUESTED_BEFORE_POST"
            else:
                if self._read_snapshot is not None:
                    latest = self._read_snapshot()
                    hedge = (
                        intent.passive
                        and intent.decision is not None
                        and intent.decision.features.get("pair_role") == "HEDGE"
                    )
                    snapshot = (
                        self._read_model_snapshot()
                        if hedge and self._read_model_snapshot
                        else latest.snapshot
                    )
                    if not hedge and latest.invalidation_generation != self._input_generation:
                        reason = "INPUT_INVALIDATED_BEFORE_POST"
                if reason is None and snapshot is None:
                    reason = "NO_SNAPSHOT_BEFORE_POST"
                if reason is None and snapshot is not None:
                    assert intent.decision is not None and intent.decision.side is not None
                    selected_config = self._mode_config(
                        str(intent.decision.features.get("mode", self.config.strategy.mode))
                    )
                    live_snapshot = replace(snapshot, now_ms=self._now(intent.created_ms))
                    current = (
                        pair_decision(
                            live_snapshot, selected_config, self.ledger.active_positions()
                        )
                        if intent.passive
                        else evaluate(live_snapshot, selected_config)
                    )
                    if current.reason != "ENTRY":
                        reason = current.reason
                    elif current.side != intent.decision.side or self.candidate_identity(
                        snapshot.market, intent.decision.side
                    ) != self.candidate_identity(intent.market, intent.decision.side):
                        reason = "CANDIDATE_IDENTITY_CHANGED_BEFORE_POST"
                    elif (
                        current.price_limit is None
                        or current.buy_principal != intent.principal
                        or current.max_total_reserved != intent.reserved_cash
                        or (
                            current.price_limit != intent.price_limit
                            if intent.passive
                            else current.price_limit < intent.price_limit
                        )
                    ):
                        reason = "DECISION_CHANGED_BEFORE_POST"
            if reason is not None:
                self.ledger.abandon(intent.intent_id, reason)
                return EngineResult("SKIP", reason, intent.intent_id)
        # No network submission before both SQLite commits have succeeded.
        self.ledger.mark_submitting(intent.intent_id)
        try:
            ack = await self.broker.post(prepared)
        except asyncio.CancelledError:
            self.ledger.record_ack(
                intent.intent_id,
                OrderAck("unknown", prepared.order_hash, reason="POST_CANCELLED_UNKNOWN"),
            )
            raise
        self.ledger.record_ack(intent.intent_id, ack)
        return EngineResult(
            "REJECTED" if ack.classification == "rejected" else "SUBMITTED",
            ack.reason or ack.classification.upper(),
            intent.intent_id,
        )

    def _mode_config(self, mode: str) -> Config:
        return replace(self.config, strategy=replace(self.config.strategy, mode=mode))

    async def _manage_resting(self, snapshot: Snapshot | None, now_ms: int) -> EngineResult | None:
        for order in self.ledger.unresolved_orders():
            if not order.passive:
                continue
            due = (
                order.cancel_requested_ms is not None
                or order.state == "UNKNOWN"
                or self.ledger.stop_requested()
                or self._shutting_down
                or now_ms - order.created_ms >= self.config.experiments.pair_quote_seconds * 1000
            )
            if not due:
                if snapshot is None or snapshot.market.condition_id != order.market.condition_id:
                    due = True
                else:
                    assert order.decision is not None
                    desired = pair_decision(
                        replace(snapshot, now_ms=now_ms),
                        self._mode_config(str(order.decision.features["mode"])),
                        self.ledger.active_positions(),
                    )
                    # A partial first fill changes the desired side; retain its short
                    # lifetime unless the book/reference is invalid or a stop is due.
                    if order.confirmed_quantity == 0:
                        due = (
                            desired.side is None
                            or snapshot.market.token(desired.side) != order.token_id
                            or desired.price_limit != order.price_limit
                        )
                    else:
                        from btc5m.strategy import _safety_reason

                        due = (
                            _safety_reason(replace(snapshot, now_ms=now_ms), self.config)
                            is not None
                        )
            if due:
                pending = self.ledger.request_cancel(order.intent_id, now_ms)
                acknowledged = await self.broker.cancel(pending)
                self.ledger.record_observation(
                    {
                        "kind": "cancel_result",
                        "received_ms": now_ms,
                        "token_id": order.token_id,
                        "status": "acknowledged" if acknowledged else "unknown",
                        "code": "RECONCILIATION_REQUIRED",
                    }
                )
                return EngineResult("WAIT", "CANCEL_RECONCILIATION_REQUIRED", order.intent_id)
        return None

    async def _pair_step(
        self, snapshot: Snapshot | None, now_ms: int, fallback_book: Book | None
    ) -> EngineResult:
        positions = self.ledger.active_positions()
        total = {p.token_id: p.quantity for p in positions}
        first = positions[0]
        up, down = total.get(first.market.up_token, D(0)), total.get(first.market.down_token, D(0))
        if up == down:
            return EngineResult("HOLD", "PAIR_COMPLETE_AWAITING_RESOLUTION")
        token = first.market.up_token if up > down else first.market.down_token
        position = next(p for p in positions if p.token_id == token)
        book = fallback_book
        if snapshot is not None:
            book = next(
                (b for b in (snapshot.up_book, snapshot.down_book) if b.token_id == token), book
            )
        if self._read_exit_book is not None:
            book = await self._read_exit_book(token)
            now_ms = self._now(now_ms)
        mode = str(position.decision.features["mode"])
        rows = self.ledger.db.execute(
            "SELECT MIN(json_extract(data,'$.timestamp_ms')) FROM fills WHERE intent_id IN (SELECT id FROM intents WHERE json_extract(data,'$.position_id')=?)",
            (position.position_id,),
        ).fetchone()
        opened_ms = rows[0] if rows and rows[0] is not None else now_ms
        forced = (
            "UNPAIRED_TIMEOUT"
            if now_ms - opened_ms >= self.config.experiments.pair_max_unhedged_seconds * 1000
            else None
        )
        if (
            len(self.ledger.round_orders(position.market.slug))
            >= self.config.experiments.pair_max_orders_per_round
        ):
            forced = "PAIR_ORDER_LIMIT"
        closing = await self._exit(
            book,
            now_ms,
            position=position,
            maximum_quantity=abs(up - down),
            forced_reason=forced,
            snapshot=snapshot,
        )
        actual = next(p for p in self.ledger.positions() if p.position_id == position.position_id)
        if closing.action != "HOLD" or actual.exit_reason is not None:
            return closing
        if snapshot is None or snapshot.market.condition_id != position.market.condition_id:
            return EngineResult("HOLD", "PAIR_NO_CURRENT_SNAPSHOT")
        if self.preflight is None or not self.preflight.entry_ready:
            return EngineResult("HOLD", "ACCOUNT_NOT_READY")
        current = replace(snapshot, now_ms=self._now(now_ms))
        decision = pair_decision(current, self._mode_config(mode), positions)
        if decision.side is None:
            return EngineResult("HOLD", decision.reason)
        try:
            intent = self.ledger.reserve_entry(
                decision, current.market, self.session_id, current.now_ms
            )
        except LedgerError as exc:
            return EngineResult("HOLD", str(exc))
        return await self._submit(intent, current)

    async def _exit(
        self,
        book: Book | None,
        now_ms: int,
        *,
        position: Position | None = None,
        maximum_quantity: Decimal | None = None,
        forced_reason: str | None = None,
        snapshot: Snapshot | None = None,
    ) -> EngineResult:
        position = position or self.ledger.open_position()
        assert position is not None
        reason = (
            position.exit_reason
            if position.exit_reason
            in (
                "STOP",
                "PROFIT",
                "TIME",
                "SHUTDOWN",
                "MODEL",
                "UNPAIRED_TIMEOUT",
                "PAIR_ORDER_LIMIT",
            )
            else "SHUTDOWN"
            if self._shutting_down or self.ledger.stop_requested()
            else "TIME"
            if position.market.end_s * 1000 - now_ms <= self.config.execution.exit_seconds * 1000
            else forced_reason
        )

        def hold(problem: str) -> EngineResult:
            if reason is not None:
                self.ledger.note_exit(position.position_id, reason, problem, now_ms)
            return EngineResult("HOLD", problem)

        if (
            self.preflight is None
            or self.preflight.chain_id != 137
            or self.preflight.token_balances.get(position.token_id)
            != self.ledger.known_inventory().get(position.token_id)
            or not self.preflight.token_approved
            or self.preflight.foreign_order_ids
        ):
            return hold("ACCOUNT_EXPOSURE_UNRECONCILED")
        if book is None:
            return hold("NO_EXIT_BOOK")
        if book.token_id != position.token_id:
            return hold("EXIT_TOKEN_MISMATCH")
        if any(
            not -self.config.data.future_tolerance_ms
            <= now_ms - stamp
            <= self.config.data.max_book_age_ms
            for stamp in (book.timestamp_ms, book.received_ms)
        ):
            return hold("STALE_EXIT_BOOK")
        if not book.bids:
            return hold("NO_EXIT_BIDS")
        if book.asks and book.bids[0].price >= book.asks[0].price:
            return hold("CROSSED_EXIT_BOOK")
        held_quantity = (
            min(position.quantity, maximum_quantity)
            if maximum_quantity is not None
            else position.quantity
        )
        remaining = held_quantity
        gross = D(0)
        estimated_fee = D(0)
        consumed = []
        for level in book.bids:
            qty = min(remaining, level.size)
            if qty > 0:
                consumed.append((level.price, qty))
                gross += level.price * qty
                estimated_fee += fee_for(
                    qty, level.price, position.market.fee_rate, position.market.fee_exponent
                )
                remaining -= qty
            if remaining == 0:
                break
        covered = held_quantity - remaining
        self.ledger.record_observation(
            {
                "kind": "exit_quote",
                "received_ms": now_ms,
                "source_ms": book.timestamp_ms,
                "slug": position.market.slug,
                "token_id": position.token_id,
                "held_quantity": held_quantity,
                "covered_quantity": covered,
                "full_depth": remaining == 0,
                "gross_price": gross / covered,
                "gross_proceeds": gross,
                "estimated_sell_fee": estimated_fee,
                "estimated_net_proceeds": gross - estimated_fee,
                "source": "stored_market_fee_estimate",
            }
        )
        if reason is None:
            if remaining > 0:
                return hold("INSUFFICIENT_FULL_EXIT_DEPTH")
            price = gross / held_quantity
            if price <= position.gross_entry_price - self.config.execution.stop_loss_per_share:
                reason = "STOP"
            elif price >= self.config.execution.take_profit_bid:
                reason = "PROFIT"
            elif (
                position.decision.features.get("mode") == "model_exit"
                and snapshot is not None
                and snapshot.market.condition_id == position.market.condition_id
            ):
                value = fair_value(
                    replace(snapshot, now_ms=now_ms), self._mode_config("model_exit")
                )
                side = position.decision.side
                if value.reason == "VALID" and side is not None:
                    holding_ceiling = D(str(value.ceilings[side]))
                    net_sale = (gross - estimated_fee) / held_quantity
                    self.ledger.record_observation(
                        {
                            "kind": "model_exit",
                            "received_ms": now_ms,
                            "slug": position.market.slug,
                            "token_id": position.token_id,
                            "price": str(holding_ceiling),
                            "estimated_net_proceeds": str(net_sale),
                            "code": "SELL"
                            if net_sale
                            > holding_ceiling + self.config.experiments.model_exit_surplus
                            else "HOLD",
                        }
                    )
                    if net_sale > holding_ceiling + self.config.experiments.model_exit_surplus:
                        reason = "MODEL"
                else:
                    self.ledger.record_observation(
                        {
                            "kind": "model_exit",
                            "received_ms": now_ms,
                            "slug": position.market.slug,
                            "code": value.reason,
                        }
                    )
                if reason is None:
                    return EngineResult("HOLD", "NO_EXIT_TRIGGER")
            else:
                return EngineResult("HOLD", "NO_EXIT_TRIGGER")
        quantity = (held_quantity - remaining).quantize(D(".01"), rounding=ROUND_DOWN)
        if quantity <= 0:
            return hold("BELOW_SELL_PRECISION")
        if quantity < position.market.min_order_size:
            return hold("BELOW_VENUE_MINIMUM")
        floor = consumed[-1][0] - self.config.execution.sell_slippage
        if floor <= 0:
            return hold("EXIT_PRICE_TOO_LOW")
        self.ledger.note_exit(position.position_id, reason, None, now_ms)
        try:
            intent = self.ledger.reserve_exit(
                position, quantity, floor, reason, self.session_id, now_ms
            )
        except LedgerError as exc:
            return hold(str(exc))
        return await self._submit(intent)

    async def shutdown(self, snapshot: Snapshot | None, now_ms: int) -> EngineResult:
        """One bounded close/reconcile pass; caller keeps monitoring any remaining exposure."""
        self._shutting_down = True
        self.ledger.request_stop()
        book = self._last_exit_book
        position = self.ledger.open_position()
        if snapshot is not None and position is not None:
            for candidate in (snapshot.up_book, snapshot.down_book):
                if candidate.token_id == position.token_id:
                    book = candidate
        return await self.step(snapshot, book, now_ms)
