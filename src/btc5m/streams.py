"""Credential-free exchange ticks and Polymarket books/trades with visible gaps."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from websockets.asyncio.client import connect

from btc5m.config import Config
from btc5m.domain import Book, Level, PricePoint
from btc5m.order_flow import OrderFlow


class StreamError(ValueError):
    pass


@dataclass(frozen=True)
class PublicTrade:
    identity: str
    token_id: str
    condition_id: str
    side: str
    price: Decimal
    quantity: Decimal
    timestamp_ms: int
    received_ms: int
    generation: int
    transaction_hash: str | None = None


def _decimal(value: Any, *, zero: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise StreamError("INVALID_NUMBER")
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or (not zero and result == 0):
        raise StreamError("INVALID_NUMBER")
    return result


def _stamp(value: Any) -> int:
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if type(value) is not int or not 1_000_000_000_000 <= value < 100_000_000_000_000:
        raise StreamError("INVALID_TIMESTAMP")
    return value


class PublicStreams:
    def __init__(
        self,
        config: Config,
        *,
        clock: Callable[[], float] = time.time,
        observer: Callable[[dict[str, object]], None] | None = None,
        capture_flow: bool = False,
    ) -> None:
        self.config, self.clock, self.observer = config, clock, observer
        self.tokens: tuple[str, ...] = ()
        self.condition_id = ""
        self.books: dict[str, Book] = {}
        self._working_books: dict[str, Book] = {}
        self.pending_books: dict[str, int] = {}
        self.generation = 0
        self.session_id = uuid.uuid4().hex
        self.trades: deque[PublicTrade] = deque()
        self._trade_keys: set[str] = set()
        self._exchange: dict[int, PricePoint] = {}
        self._exchange_task: asyncio.Task[None] | None = None
        self._market_task: asyncio.Task[None] | None = None
        self._closed = False
        self._last_exchange_logged = -1
        self.flow = OrderFlow() if capture_flow else None
        self._depth_task: asyncio.Task[None] | None = None
        self._research_trades: list[PublicTrade] = []

    @property
    def exchange_history(self) -> tuple[PricePoint, ...]:
        return tuple(self._exchange[k] for k in sorted(self._exchange))

    def _emit(self, kind: str, **fields: object) -> None:
        if self.observer is not None:
            self.observer({"kind": kind, "received_ms": int(self.clock() * 1000), **fields})

    async def start(self) -> None:
        if self._closed or self._exchange_task is not None:
            raise StreamError("INVALID_LIFECYCLE")
        self._exchange_task = asyncio.create_task(self._consume_exchange())
        if self.flow is not None:
            self._depth_task = asyncio.create_task(self._consume_depth())

    async def select_market(self, tokens: tuple[str, str], condition_id: str) -> None:
        if self.tokens == tokens and self.condition_id == condition_id:
            return
        if self._market_task:
            self._market_task.cancel()
            await asyncio.gather(self._market_task, return_exceptions=True)
        self.tokens, self.condition_id = tokens, condition_id
        self.invalidate_market("MARKET_CHANGED")
        self._market_task = asyncio.create_task(self._consume_market())

    async def close(self) -> None:
        self._closed = True
        tasks = [
            t for t in (self._exchange_task, self._market_task, self._depth_task) if t is not None
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def invalidate_market(self, code: str) -> None:
        self.books.clear()
        self._working_books.clear()
        self.pending_books.clear()
        self.generation += 1
        self._emit("stream_unavailable", stream="books", code=code, generation=self.generation)

    def ingest_exchange(self, event: dict[str, Any]) -> None:
        if event.get("e") != "aggTrade" or event.get("s") != "BTCUSDT":
            raise StreamError("EXCHANGE_IDENTITY")
        stamp, now = _stamp(event.get("T")), int(self.clock() * 1000)
        if stamp > now + self.config.data.future_tolerance_ms:
            raise StreamError("EXCHANGE_FUTURE")
        if now - stamp > self.config.data.max_price_age_ms:
            raise StreamError("EXCHANGE_STALE")
        point = PricePoint("spot", stamp, now, _decimal(event.get("p")))
        if self.flow is not None:
            self.flow.trade(event, now)
        bucket = stamp // 100
        previous = self._exchange.get(bucket)
        if previous is None or previous.timestamp_ms <= stamp:
            self._exchange[bucket] = point
        for old in list(self._exchange):
            if old < now // 100 - 1200:
                del self._exchange[old]
        if bucket > self._last_exchange_logged:
            self._emit(
                "exchange_spot",
                source="binance:BTCUSDT:aggTrade",
                source_ms=stamp,
                price=str(point.price),
            )
            self._last_exchange_logged = bucket

    def ingest_market(self, event: dict[str, Any]) -> None:
        kind = event.get("event_type")
        if kind not in ("book", "price_change", "last_trade_price", "tick_size_change"):
            return
        if event.get("market") != self.condition_id:
            raise StreamError("MARKET_IDENTITY")
        stamp, now = _stamp(event.get("timestamp")), int(self.clock() * 1000)
        if stamp > now + self.config.data.future_tolerance_ms:
            raise StreamError("BOOK_FUTURE")
        if kind == "tick_size_change":
            self.invalidate_market("TICK_SIZE_CHANGED")
            raise StreamError("TICK_SIZE_CHANGED")
        if kind == "last_trade_price":
            token, side = event.get("asset_id"), event.get("side")
            if token not in self.tokens or side not in ("BUY", "SELL"):
                raise StreamError("TRADE_IDENTITY")
            if event.get("size") is None:
                self._emit("trade_unavailable", token_id=token, code="TRADE_SIZE_MISSING")
                return
            price, quantity = _decimal(event.get("price")), _decimal(event["size"])
            if price >= 1:
                raise StreamError("INVALID_TRADE_PRICE")
            transaction_hash = event.get("transaction_hash")
            if transaction_hash is not None:
                if not isinstance(transaction_hash, str) or not re.fullmatch(
                    r"0x[0-9a-fA-F]{64}", transaction_hash
                ):
                    raise StreamError("TRADE_TRANSACTION_IDENTITY")
                transaction_hash = transaction_hash.lower()
            identity = hashlib.sha256(
                json.dumps(
                    [
                        self.condition_id,
                        token,
                        stamp,
                        side,
                        str(price),
                        str(quantity),
                        transaction_hash,
                    ],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            if identity in self._trade_keys:
                return
            trade = PublicTrade(
                identity,
                token,
                self.condition_id,
                side,
                price,
                quantity,
                stamp,
                now,
                self.generation,
                transaction_hash,
            )
            self.trades.append(trade)
            if self.flow is not None:
                if len(self._research_trades) >= 100000:
                    raise StreamError("RESEARCH_TRADE_BUFFER_LIMIT")
                self._research_trades.append(trade)
            self._trade_keys.add(identity)
            while self.trades and (
                len(self.trades) > 20000 or self.trades[0].received_ms < now - 300000
            ):
                self._trade_keys.discard(self.trades.popleft().identity)
            self._emit("public_trade", **asdict(trade))
            return
        updates: dict[str, Book] = {}
        expected: dict[str, dict[str, Decimal]] = {}
        if kind == "book":
            token = event.get("asset_id")
            if token not in self.tokens:
                raise StreamError("BOOK_TOKEN")

            def parse_levels(key: str) -> tuple[Level, ...]:
                return tuple(
                    Level(_decimal(x["price"]), size)
                    for x in event[key]
                    if (size := _decimal(x["size"], zero=True)) > 0
                )

            updates[token] = Book(token, stamp, now, parse_levels("bids"), parse_levels("asks"))
        else:
            for change in event["price_changes"]:
                token = change.get("asset_id")
                if token not in self.tokens:
                    raise StreamError("BOOK_TOKEN")
                prior = updates.get(token, self._working_books.get(token))
                if prior is None:
                    raise StreamError("BOOK_SNAPSHOT_REQUIRED")
                side = change.get("side")
                if side not in ("BUY", "SELL"):
                    raise StreamError("BOOK_SIDE")
                price, size = _decimal(change["price"]), _decimal(change["size"], zero=True)
                levels_by_price = {
                    x.price: x.size for x in (prior.bids if side == "BUY" else prior.asks)
                }
                if size:
                    levels_by_price[price] = size
                else:
                    levels_by_price.pop(price, None)
                levels = tuple(Level(p, q) for p, q in levels_by_price.items())
                current = Book(
                    token,
                    stamp,
                    now,
                    levels if side == "BUY" else prior.bids,
                    levels if side == "SELL" else prior.asks,
                )
                for label in ("best_bid", "best_ask"):
                    if change.get(label) is not None:
                        expected.setdefault(token, {})[label] = _decimal(change[label], zero=True)
                updates[token] = current
        for token, current in updates.items():
            prior = self._working_books.get(token)
            if prior and current.timestamp_ms < prior.timestamp_ms:
                if kind == "book":
                    # The stream can deliver a cached full snapshot behind newer
                    # deltas. Do not roll the current state backwards to it.
                    continue
                raise StreamError("BOOK_OUT_OF_ORDER")
            crossed = bool(
                current.bids and current.asks and current.bids[0].price >= current.asks[0].price
            )
            mismatch = any(
                expected[token][label]
                != (entries[0].price if entries else Decimal(0 if label == "best_bid" else 1))
                for label, entries in (("best_bid", current.bids), ("best_ask", current.asks))
                if label in expected.get(token, {})
            )
            if kind == "book" and crossed:
                raise StreamError("CROSSED_BOOK")
            self._working_books[token] = current
            if crossed or mismatch:
                # Matching can send the new level and the consumed level's zero
                # removal as two messages with the same source timestamp. Keep
                # the incomplete state private until both messages/full book arrive.
                self.books.pop(token, None)
                self.pending_books.setdefault(token, now)
            else:
                self.pending_books.pop(token, None)
                self.books[token] = current
        self.check_pending()

    def check_pending(self) -> None:
        if any(int(self.clock() * 1000) - start > 1000 for start in self.pending_books.values()):
            raise StreamError("BOOK_SEQUENCE_MISMATCH")

    async def _consume_exchange(self) -> None:
        while not self._closed:
            try:
                async with connect(
                    "wss://data-stream.binance.vision/ws/btcusdt@aggTrade",
                    open_timeout=10,
                    close_timeout=2,
                    max_size=65536,
                ) as ws:
                    while not self._closed:
                        async with asyncio.timeout(5):
                            event = json.loads(await ws.recv(), parse_float=Decimal)
                        self.ingest_exchange(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._exchange.clear()
                if self.flow is not None:
                    self.flow.reset_trades("EXCHANGE_DISCONNECTED", int(self.clock() * 1000))
                self._emit(
                    "stream_unavailable",
                    stream="exchange",
                    code=str(exc) if isinstance(exc, StreamError) else "EXCHANGE_DISCONNECTED",
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(1)

    def research_frame(self, now_ms: int) -> dict[str, Any] | None:
        if self.flow is None:
            return None
        trades, self._research_trades = self._research_trades, []
        return {
            "version": 1,
            "flow": self.flow.view(now_ms),
            "exchange": self.flow.drain(),
            "streams": {
                "session_id": self.session_id,
                "generation": self.generation,
                "books": {k: asdict(v) for k, v in self.books.items()},
                "pending_books": self.pending_books.copy(),
                "trades": [asdict(t) for t in trades],
            },
        }

    async def _consume_depth(self) -> None:
        assert self.flow is not None
        while not self._closed:
            try:
                async with connect(
                    "wss://data-stream.binance.vision/ws/btcusdt@depth20@100ms",
                    open_timeout=10,
                    close_timeout=2,
                    max_size=65536,
                ) as ws:
                    while not self._closed:
                        async with asyncio.timeout(5):
                            event = json.loads(await ws.recv(), parse_float=Decimal)
                        self.flow.depth(event, int(self.clock() * 1000))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.flow.reset_depth("DEPTH_DISCONNECTED", int(self.clock() * 1000))
                self._emit(
                    "stream_unavailable",
                    stream="exchange_depth",
                    code="DEPTH_DISCONNECTED",
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(1)

    async def _consume_market(self) -> None:
        while not self._closed:
            try:
                async with connect(
                    "wss://ws-subscriptions-clob.polymarket.com/ws/market",
                    open_timeout=10,
                    close_timeout=2,
                    max_size=2**22,
                ) as ws:
                    await ws.send(
                        json.dumps(
                            {
                                "assets_ids": self.tokens,
                                "type": "market",
                                "custom_feature_enabled": True,
                            }
                        )
                    )
                    last_ping = time.monotonic()
                    while not self._closed:
                        self.check_pending()
                        if time.monotonic() - last_ping >= 5:
                            await ws.send("PING")
                            last_ping = time.monotonic()
                        try:
                            async with asyncio.timeout(1):
                                raw = await ws.recv()
                        except TimeoutError:
                            continue
                        if raw == "PONG":
                            continue
                        payload = json.loads(raw, parse_float=Decimal)
                        for event in payload if isinstance(payload, list) else (payload,):
                            self.ingest_market(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.invalidate_market(
                    str(exc) if isinstance(exc, StreamError) else "BOOK_STREAM_DISCONNECTED"
                )
                await asyncio.sleep(1)
