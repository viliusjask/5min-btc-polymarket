"""Paper-only split/sell/merge lifecycle using the shared broker and journal."""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from typing import Any

from btc5m.config import Config
from btc5m.domain import Book, Decision, Side, Snapshot
from btc5m.execution_types import EngineResult, Intent
from btc5m.lab_replay import LabEngine
from btc5m.lab_tape import encode
from btc5m.ledger import LedgerError, _market
from btc5m.paper import PaperBroker
from btc5m.paper_conversions import merge_pair, split_pair
from btc5m.strategy import _safety_reason, _skip

D = Decimal


class SplitEngine(LabEngine):
    broker: PaperBroker

    def _state(self) -> dict[str, Any]:
        return json.loads(self.ledger._meta("lab_split_state") or "{}")

    def _save_state(self, state: dict[str, Any]) -> None:
        self.ledger._set("lab_split_state", encode(state))

    def _evaluate(self, snapshot: Snapshot, config: Config) -> Decision:
        if (
            snapshot.market.start_s * 1000 < self.entry_start_ms
            or self.entry_end_ms is not None
            and snapshot.market.start_s * 1000 >= self.entry_end_ms
        ):
            return _skip(snapshot, "STUDY_ENTRY_WINDOW", {})
        safety = _safety_reason(snapshot, config)
        if safety:
            return _skip(snapshot, safety, {})
        tau = (snapshot.market.end_s * 1000 - snapshot.now_ms) / 1000
        if not config.strategy.entry_min_seconds <= tau <= config.strategy.entry_max_seconds:
            return _skip(snapshot, "ENTRY_WINDOW", {})
        if self.ledger.db.execute(
            "SELECT 1 FROM measurements WHERE key=?",
            ("paper_conversion:split:" + snapshot.market.slug,),
        ).fetchone():
            return _skip(snapshot, "ROUND_ALREADY_CONVERTED", {})
        return _skip(
            snapshot,
            "ENTRY",
            {
                "mode": config.strategy.mode,
                "lab_signal": "split_sell",
                "action": "collateral_conversion",
            },
        )

    def _closing_reason(self, now_ms: int) -> str | None:
        if self.ledger.stop_requested() or self._shutting_down:
            return "STOP_REQUESTED"
        saved = self._state()
        if saved.get("closing"):
            return str(saved["closing"])
        positions = self.ledger.active_positions()
        if not positions:
            return None
        market = positions[0].market
        if now_ms >= (market.end_s - self.config.execution.exit_seconds) * 1000:
            return "SPLIT_TIME_EXIT"
        first_sale = self.ledger.db.execute(
            "SELECT MIN(json_extract(f.data,'$.timestamp_ms')) FROM fills f JOIN intents i ON i.id=f.intent_id WHERE json_extract(i.data,'$.market.slug')=? AND json_extract(i.data,'$.side')='SELL'",
            (market.slug,),
        ).fetchone()[0]
        if (
            first_sale is not None
            and now_ms - first_sale >= self.config.experiments.pair_max_unhedged_seconds * 1000
        ):
            return "SPLIT_INVENTORY_TIMEOUT"
        if (
            len(self.ledger.round_orders(market.slug))
            >= self.config.experiments.pair_max_orders_per_round
        ):
            return "PAIR_ORDER_LIMIT"
        return None

    def _resting_cancel_reason(
        self, order: Intent, snapshot: Snapshot | None, now_ms: int
    ) -> str | None:
        if order.state == "UNKNOWN":
            return "ORDER_UNKNOWN"
        closing = self._closing_reason(now_ms)
        if closing:
            return closing
        if now_ms - order.created_ms >= self.config.experiments.pair_quote_seconds * 1000:
            return "QUOTE_EXPIRED"
        if snapshot is None:
            return "NO_SNAPSHOT"
        if snapshot.market.condition_id != order.market.condition_id:
            return "WRONG_ROUND"
        if any(
            getattr(snapshot.market, field) != getattr(order.market, field)
            for field in ("tick_size", "min_order_size", "fee_rate", "fee_exponent")
        ):
            return "QUOTE_MARKET_CHANGED"
        return _safety_reason(snapshot, self.config)

    async def step(
        self, snapshot: Snapshot | None, exit_book: Book | None, now_ms: int
    ) -> EngineResult:
        async with self._lock:
            await self.reconcile()
            self.ledger.record_clock(now_ms)
            state = self._state()
            closing = self._closing_reason(now_ms)
            if closing:
                state["closing"] = closing
                self._save_state(state)
            resting = await self._manage_resting(snapshot, now_ms)
            if resting is not None:
                return resting
            if self.ledger.unresolved_orders():
                return EngineResult("WAIT", "ORDER_UNRESOLVED")
            pending = state.get("pending")
            if pending:
                if now_ms < pending["activate_ms"]:
                    return EngineResult("WAIT", "PAPER_CONVERSION_PENDING")
                market, quantity = _market(pending["market"]), D(pending["quantity"])
                if pending["kind"] == "split" and (
                    closing
                    or snapshot is None
                    or self.candidate_identity(snapshot.market, Side.UP)
                    != self.candidate_identity(market, Side.UP)
                    or any(
                        getattr(snapshot.market, key) != getattr(market, key)
                        for key in ("tick_size", "min_order_size", "fee_rate", "fee_exponent")
                    )
                    or self._evaluate(snapshot, self.config).reason != "ENTRY"
                ):
                    state.pop("pending")
                    self._save_state(state)
                    return EngineResult("SKIP", "PAPER_SPLIT_CANCELLED")
                try:
                    if pending["kind"] == "split":
                        split_pair(self.ledger, market, quantity, self.session_id, now_ms)
                    else:
                        merge_pair(
                            self.ledger, market, quantity, self.session_id, now_ms, pending["id"]
                        )
                except LedgerError as exc:
                    state.pop("pending")
                    self._save_state(state)
                    return EngineResult("SKIP", str(exc))
                state.pop("pending")
                self._save_state(state)
            positions = self.ledger.active_positions()
            if not positions:
                if self.ledger.stop_requested():
                    return EngineResult("STOPPED", "FLAT")
                if snapshot is None:
                    return EngineResult("SKIP", "NO_SNAPSHOT")
                decision = self._evaluate(snapshot, self.config)
                if decision.reason != "ENTRY":
                    return EngineResult("SKIP", decision.reason)
                quantity = min(
                    self.config.experiments.pair_shares, self.config.risk.trade_budget_usd
                ).quantize(D(".01"), rounding=ROUND_DOWN)
                if quantity < snapshot.market.min_order_size:
                    return EngineResult("SKIP", "BELOW_VENUE_MINIMUM")
                summary = self.ledger.summary(now_ms)
                if summary.halts:
                    return EngineResult("SKIP", "ENTRIES_HALTED")
                try:
                    self.ledger.check_reservation(quantity, summary)
                except LedgerError as exc:
                    return EngineResult("SKIP", str(exc))
                tick = snapshot.market.tick_size
                up = snapshot.up_book.asks[0].price
                down = max(
                    snapshot.down_book.asks[0].price, 1 + self.config.experiments.pair_min_edge - up
                )
                floors = {snapshot.market.up_token: up, snapshot.market.down_token: down}
                floors = {
                    k: (v / tick).to_integral_value(rounding=ROUND_CEILING) * tick
                    for k, v in floors.items()
                }
                if any(p >= 1 for p in floors.values()):
                    return EngineResult("SKIP", "SPLIT_QUOTES_UNAVAILABLE")
                state = {
                    "slug": snapshot.market.slug,
                    "floors": {k: str(v) for k, v in floors.items()},
                    "pending": {
                        "kind": "split",
                        "id": snapshot.market.slug,
                        "quantity": str(quantity),
                        "market": asdict(snapshot.market),
                        "activate_ms": now_ms + self.variant.conversion_delay_ms,
                    },
                }
                self._save_state(state)
                self.ledger._event("PAPER_CONVERSION_REQUESTED", now_ms, state["pending"])
                return EngineResult("WAIT", "PAPER_CONVERSION_PENDING")
            market = positions[0].market
            if closing:
                paired = (
                    min((p.quantity for p in positions), default=D(0))
                    if len(positions) == 2
                    else D(0)
                )
                if paired:
                    state["pending"] = {
                        "kind": "merge",
                        "id": market.slug,
                        "quantity": str(paired),
                        "market": asdict(market),
                        "activate_ms": now_ms + self.variant.conversion_delay_ms,
                    }
                    self._save_state(state)
                    self.ledger._event("PAPER_CONVERSION_REQUESTED", now_ms, state["pending"])
                    return EngineResult("WAIT", "PAPER_CONVERSION_PENDING")
                if now_ms >= market.end_s * 1000:
                    resolution = await self.broker.resolve(market)
                    if resolution is None:
                        return EngineResult("HOLD", "RESOLUTION_UNCONFIRMED")
                    self.ledger.apply_resolution(market, resolution, now_ms)
                    return EngineResult("HOLD", "PAPER_RESOLUTION_RECORDED")
                position = positions[0]
                book = await self.broker.book(position.token_id)
                return await self._exit(
                    book, now_ms, position=position, forced_reason=closing, snapshot=snapshot
                )
            if snapshot is None or snapshot.market.condition_id != market.condition_id:
                return EngineResult("HOLD", "SPLIT_SNAPSHOT_MISSING")
            safety = _safety_reason(snapshot, self.config)
            if safety:
                return EngineResult("HOLD", safety)
            result = EngineResult("HOLD", "BELOW_VENUE_MINIMUM")
            for position in positions:
                quantity = position.quantity.quantize(D(".01"), rounding=ROUND_DOWN)
                if quantity < market.min_order_size:
                    continue
                book = (
                    snapshot.up_book if position.token_id == market.up_token else snapshot.down_book
                )
                price = max(D(state["floors"][position.token_id]), book.asks[0].price)
                price = (price / market.tick_size).to_integral_value(
                    rounding=ROUND_CEILING
                ) * market.tick_size
                if price >= 1:
                    continue
                try:
                    intent = self.ledger.reserve_exit(
                        position,
                        quantity,
                        price,
                        "SPLIT_MAKER_SALE",
                        self.session_id,
                        now_ms,
                        passive=True,
                    )
                except LedgerError as exc:
                    return EngineResult("HOLD", str(exc))
                result = await self._submit(intent, snapshot)
            return result
