"""Explicit simulated execution using subsequent public books and trade volume.

No keys, signatures, account transport or onchain submissions exist in this adapter.
Paper orders share the strategy/ledger engine but never claim venue confirmation.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict
from decimal import ROUND_CEILING, Decimal
from typing import Any

from btc5m.broker import BrokerError
from btc5m.config import Config
from btc5m.domain import Book, Market, Snapshot
from btc5m.execution_types import (
    ConfirmedFill,
    Intent,
    OrderAck,
    OrderEvidence,
    PreflightEvidence,
    PreparedOrder,
    ResolutionEvidence,
    SigningDomain,
)
from btc5m.ledger import Ledger
from btc5m.market_data import ANCHOR_TOLERANCE
from btc5m.strategy import fee_for
from btc5m.streams import PublicStreams

D = Decimal
PAPER_DOMAIN = SigningDomain("BTC5m PAPER", "1", 0, "0x" + "00" * 20)


class PaperBroker:
    def __init__(
        self,
        ledger: Ledger,
        config: Config,
        *,
        streams: PublicStreams | None = None,
        clock: Callable[[], float] = time.time,
        final_reference: Callable[[Market], tuple[Decimal, Decimal] | None] | None = None,
    ) -> None:
        if ledger.environment != "paper":
            raise BrokerError("PAPER_BROKER_REQUIRES_PAPER_JOURNAL")
        self.ledger, self.config, self.clock, self.streams = ledger, config, clock, streams
        self.final_reference = final_reference
        self.snapshot: Snapshot | None = None
        self.books: dict[str, Book] = {}

    def update(self, snapshot: Snapshot | None) -> None:
        self.snapshot = snapshot
        if snapshot:
            self.books.update({b.token_id: b for b in (snapshot.up_book, snapshot.down_book)})

    async def close(self) -> None:
        pass

    def _load(self, ident: str) -> dict[str, Any] | None:
        row = self.ledger.db.execute(
            "SELECT data FROM measurements WHERE key=?", ("paper_order:" + ident,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def _save(self, ident: str, state: dict[str, Any]) -> None:
        with self.ledger.db:
            self.ledger.db.execute(
                "INSERT OR REPLACE INTO measurements VALUES (?,?)",
                ("paper_order:" + ident, json.dumps(state, default=str, separators=(",", ":"))),
            )

    def _book(self, token: str, now_ms: int) -> Book | None:
        if self.streams and token in self.streams.pending_books:
            return None
        book = self.streams.books.get(token) if self.streams else None
        book = book or self.books.get(token)
        if book is None or any(
            not -self.config.data.future_tolerance_ms
            <= now_ms - stamp
            <= self.config.data.max_book_age_ms
            for stamp in (book.timestamp_ms, book.received_ms)
        ):
            return None
        if book.bids and book.asks and book.bids[0].price >= book.asks[0].price:
            return None
        return book

    async def book(self, token: str) -> Book | None:
        return self._book(token, int(self.clock() * 1000))

    async def preflight(self) -> PreflightEvidence:
        now = int(self.clock() * 1000)
        self.ledger.settle_paper_claims(now)
        summary = self.ledger.summary(now)
        cash = summary.cash if summary.cash is not None else self.config.risk.allocation_usd
        return PreflightEvidence(
            self.ledger.wallet,
            self.ledger.wallet,
            "PAPER",
            137,
            cash,
            self.config.risk.allocation_usd,
            self.ledger.known_inventory(),
            True,
            (),
            (),
            (),
            True,
            (
                "SIMULATED_EXECUTION_NOT_VENUE_FILLS",
                "PUBLIC_QUEUE_MODEL_NOT_VERIFIED_QUEUE_POSITION",
                "ZERO_COST_AUTOMATIC_SIMULATED_REDEMPTION",
                "NO_MAKER_REBATES_INCLUDED",
            ),
        )

    async def prepare(self, intent: Intent, market: Market) -> PreparedOrder:
        if (
            intent.market != market
            or intent.wallet != self.ledger.wallet
            or intent.state != "RESERVED"
        ):
            raise BrokerError("INTENT_IDENTITY_INVALID")
        now = int(self.clock() * 1000)
        book = self._book(intent.token_id, now)
        if book is None:
            raise BrokerError("STALE_BOOK")
        if intent.quantity < market.min_order_size:
            raise BrokerError("BELOW_VENUE_MINIMUM")
        if intent.passive and (not book.asks or intent.price_limit >= book.asks[0].price):
            raise BrokerError("PASSIVE_QUOTE_WOULD_CROSS")
        payload = json.dumps(
            {
                "simulation": True,
                "intent_id": intent.intent_id,
                "quantity": str(intent.quantity),
                "price": str(intent.price_limit),
            },
            sort_keys=True,
        )
        order_hash = "paper:" + hashlib.sha256(payload.encode()).hexdigest()
        return PreparedOrder(
            intent.intent_id,
            order_hash,
            payload,
            intent.reserved_cash,
            intent.quantity,
            signing_domain=PAPER_DOMAIN,
        )

    async def post(self, prepared: PreparedOrder) -> OrderAck:
        order = self.ledger.order(prepared.intent_id)
        if (
            order.state != "SUBMITTING"
            or order.order_hash != prepared.order_hash
            or self._load(order.intent_id) is not None
        ):
            raise BrokerError("POST_NOT_AUTHORIZED_OR_ALREADY_ATTEMPTED")
        now = int(self.clock() * 1000)
        self._save(
            order.intent_id,
            {
                "kind": "paper_order",
                "intent_id": order.intent_id,
                "activation_ms": now + self.config.experiments.paper_latency_ms,
                "queue_ahead": None,
                "queue_start_ms": None,
                "generation": None,
                "seen": [],
                "fills": [],
                "terminal": False,
            },
        )
        return OrderAck("accepted", prepared.order_hash, reason="PAPER_ACCEPTED_NOT_VENUE_ORDER")

    async def cancel(self, order: Intent) -> bool:
        stored = self.ledger.order(order.intent_id)
        if (
            not stored.passive
            or stored.cancel_requested_ms is None
            or stored.order_hash != order.order_hash
        ):
            raise BrokerError("CANCEL_NOT_AUTHORIZED")
        return True  # local request only; reconcile enforces latency and late-trade grace

    def _fill(
        self,
        order: Intent,
        state: dict[str, Any],
        quantity: Decimal,
        price: Decimal,
        stamp: int,
        principal: Decimal | None = None,
    ) -> None:
        principal = quantity * price if principal is None else principal
        if order.side == "BUY":
            spent = sum((D(f["principal"]) for f in state["fills"]), D(0))
            if spent + principal > order.principal:
                raise BrokerError("PAPER_PRINCIPAL_LIMIT")
        fee = (
            D(0)
            if order.passive
            else fee_for(
                quantity, price, order.market.fee_rate, order.market.fee_exponent
            ).quantize(D(".000001"), rounding=ROUND_CEILING)
        )
        assert order.order_hash is not None
        fill = ConfirmedFill(
            0,
            "paper:" + order.intent_id,
            len(state["fills"]),
            order.order_hash,
            order.token_id,
            order.wallet,
            order.side,
            quantity,
            principal,
            fee,
            stamp,
        )
        state["fills"].append(json.loads(json.dumps(asdict(fill), default=str)))

    def _immediate(self, order: Intent, state: dict[str, Any], book: Book | None, now: int) -> None:
        if book is None or min(book.timestamp_ms, book.received_ms) < state["activation_ms"]:
            if now - state["activation_ms"] > self.config.data.max_book_age_ms:
                state.update(terminal=True, terminal_reason="PAPER_NO_SUBSEQUENT_BOOK")
            return
        remaining = order.principal if order.side == "BUY" else order.quantity
        fills: list[tuple[Decimal, Decimal, Decimal]] = []
        for level in book.asks if order.side == "BUY" else book.bids:
            if (order.side == "BUY" and level.price > order.price_limit) or (
                order.side == "SELL" and level.price < order.price_limit
            ):
                break
            principal = (
                min(remaining, level.size * level.price)
                if order.side == "BUY"
                else min(remaining, level.size) * level.price
            )
            quantity = (
                principal / level.price if order.side == "BUY" else min(remaining, level.size)
            )
            if quantity:
                fills.append((quantity, level.price, principal))
                remaining -= principal if order.side == "BUY" else quantity
            if not remaining:
                break
        if order.side == "BUY" and (
            remaining or sum((q for q, _, _ in fills), D(0)) < order.quantity
        ):
            fills = []  # FOK is all-or-none at the protected price
        for quantity, price, principal in fills:
            self._fill(order, state, quantity, price, now, principal)
        state.update(
            terminal=True,
            terminal_reason="PAPER_IMMEDIATE_EXECUTED" if fills else "PAPER_NO_PROTECTED_DEPTH",
        )

    def _passive(self, order: Intent, state: dict[str, Any], book: Book | None, now: int) -> None:
        streams = self.streams
        if streams is None:
            state.update(terminal=True, terminal_reason="PAPER_TRADE_STREAM_REQUIRED")
            return
        cancel_at = (
            order.cancel_requested_ms + self.config.experiments.paper_latency_ms
            if order.cancel_requested_ms is not None
            else None
        )
        if state["generation"] is not None and (
            state["generation"] != streams.generation
            or state.get("stream_session") != streams.session_id
        ):
            state.update(terminal=True, terminal_reason="PAPER_QUEUE_GAP")
            self.ledger.record_observation(
                {
                    "kind": "paper_uncertainty",
                    "received_ms": now,
                    "slug": order.market.slug,
                    "code": "PAPER_QUEUE_GAP",
                    "mode": order.decision.features.get("mode") if order.decision else "unknown",
                }
            )
            return
        if state["queue_ahead"] is None:
            if (
                book is not None
                and min(book.timestamp_ms, book.received_ms) >= state["activation_ms"]
            ):
                if book.asks and order.price_limit >= book.asks[0].price:
                    state.update(terminal=True, terminal_reason="PAPER_POST_ONLY_REJECTED")
                    return
                state.update(
                    queue_ahead=str(
                        # Trades at/below our limit already imply price priority
                        # reached this level. Only same-price size is queue ahead;
                        # counting better bids here would charge that priority twice.
                        sum((x.size for x in book.bids if x.price == order.price_limit), D(0))
                    ),
                    queue_start_ms=max(book.timestamp_ms, book.received_ms),
                    generation=streams.generation,
                    stream_session=streams.session_id,
                )
        if state["queue_ahead"] is not None:
            ahead, seen = D(state["queue_ahead"]), set(state["seen"])
            filled = sum((D(f["quantity"]) for f in state["fills"]), D(0))
            for trade in streams.trades:
                if (
                    trade.identity in seen
                    or trade.generation != state["generation"]
                    or trade.token_id != order.token_id
                    or trade.condition_id != order.market.condition_id
                    or trade.side != "SELL"
                    or trade.price > order.price_limit
                    # Same-timestamp trades may already be reflected in the
                    # activation book. Require demonstrably subsequent volume.
                    or min(trade.timestamp_ms, trade.received_ms) <= state["queue_start_ms"]
                    or max(trade.timestamp_ms, trade.received_ms) > now
                    or (cancel_at is not None and trade.timestamp_ms >= cancel_at)
                ):
                    continue
                seen.add(trade.identity)
                consumed = min(ahead, trade.quantity)
                ahead -= consumed
                quantity = min(order.quantity - filled, trade.quantity - consumed)
                if quantity > 0:
                    self._fill(order, state, quantity, order.price_limit, trade.received_ms)
                    filled += quantity
                if filled >= order.quantity:
                    state.update(terminal=True, terminal_reason="PAPER_PASSIVE_FILLED")
                    break
            state.update(queue_ahead=str(ahead), seen=sorted(seen))
        if cancel_at is not None and now >= cancel_at + self.config.data.max_book_age_ms:
            state.update(terminal=True, terminal_reason="PAPER_CANCELLED_AFTER_TRADE_GRACE")

    async def reconcile(self, order: Intent) -> OrderEvidence:
        state = self._load(order.intent_id)
        if state is None:
            # Simulated submission and its state write are one local operation.
            # Absence can be proven here; a live timeout never takes this path.
            return OrderEvidence((), (), True, None, {})
        now = int(self.clock() * 1000)
        if not state["terminal"] and now >= state["activation_ms"]:
            book = self._book(order.token_id, now)
            if order.passive:
                self._passive(order, state, book, now)
            else:
                self._immediate(order, state, book, now)
            self._save(order.intent_id, state)
        fills = []
        for raw in state["fills"]:
            row = dict(raw)
            for key in ("quantity", "principal", "fee"):
                row[key] = D(row[key])
            fills.append(ConfirmedFill(**row))
        return OrderEvidence(tuple(fills), (), state["terminal"], None, {})

    async def resolve(self, market: Market) -> ResolutionEvidence | None:
        reference = self.final_reference(market) if self.final_reference else None
        if reference is None:
            return None
        opening, final = reference
        if (
            not opening.is_finite()
            or not final.is_finite()
            or market.reference_price is None
            or abs(market.reference_price - opening) > ANCHOR_TOLERANCE
            or opening <= 0
            or final <= 0
        ):
            return None
        up = D(int(final >= opening))
        return ResolutionEvidence(
            market.condition_id,
            0,
            0,
            "paper:official-final",
            1,
            (int(up), int(1 - up)),
            ((market.up_token, up), (market.down_token, 1 - up)),
            "PAPER_OFFICIAL_FINAL",
            int(self.clock() * 1000),
        )
