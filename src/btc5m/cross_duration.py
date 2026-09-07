"""Anonymous 5m/15m quote scanner. It never submits or simulates filled arbitrage."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from decimal import ROUND_CEILING, Decimal
from typing import Any

from btc5m.config import Config
from btc5m.domain import Book, Market, Snapshot
from btc5m.market_data import (
    CLOB,
    GAMMA,
    SOURCE,
    DataUnavailable,
    MarketData,
    _array,
    _condition,
    _Round,
    _token_map,
)
from btc5m.strategy import fee_for

D = Decimal


def scan_pair(
    short: Snapshot, long: Market, long_up: Book, long_down: Book, config: Config, now_ms: int
) -> dict[str, Any]:
    first = short.market
    result: dict[str, Any] = {
        "received_ms": now_ms,
        "short_market": first.slug,
        "long_market": long.slug,
        "execution": "not_attempted",
        "status": "INCOMPATIBLE_SETTLEMENT",
    }
    if (
        first.end_s != long.end_s
        or first.settlement_source != SOURCE
        or long.settlement_source != SOURCE
        or first.end_s - first.start_s != 300
        or long.end_s - long.start_s != 900
    ):
        return result
    if any(
        m.reference_status not in ("official", "boundary") or m.reference_price is None
        for m in (first, long)
    ):
        return {**result, "status": "ANCHOR_UNAVAILABLE"}
    if not first.start_s * 1000 <= now_ms < first.end_s * 1000 or not all(
        m.active and m.accepting_orders for m in (first, long)
    ):
        return {**result, "status": "MARKET_NOT_OPEN"}
    assert first.reference_price is not None and long.reference_price is not None
    if first.reference_price <= long.reference_price:
        markets, books = (first, long), (short.up_book, long_down)
    else:
        markets, books = (long, first), (long_up, short.down_book)
    if books[0].token_id != markets[0].up_token or books[1].token_id != markets[1].down_token:
        return {**result, "status": "TOKEN_MISMATCH"}
    if any(
        not b.bids
        or not b.asks
        or b.bids[0].price >= b.asks[0].price
        or any(
            not 0 <= now_ms - stamp <= config.data.max_book_age_ms
            for stamp in (b.timestamp_ms, b.received_ms)
        )
        for b in books
    ):
        return {**result, "status": "BOOK_UNAVAILABLE"}
    quantity = config.experiments.pair_shares
    if quantity < max(m.min_order_size for m in markets):
        return {**result, "status": "BELOW_VENUE_MINIMUM"}
    cost, fees, protected = D(0), D(0), D(0)
    for market, book in zip(markets, books, strict=True):
        remaining, last = quantity, D(0)
        for level in book.asks:
            q = min(remaining, level.size)
            cost += q * level.price
            fees += fee_for(q, level.price, market.fee_rate, market.fee_exponent)
            remaining -= q
            last = level.price
            if remaining == 0:
                break
        if remaining:
            return {**result, "status": "INSUFFICIENT_DEPTH"}
        limit = ((last + config.execution.buy_slippage) / market.tick_size).to_integral_value(
            rounding=ROUND_CEILING
        ) * market.tick_size
        if limit >= 1:
            return {**result, "status": "UNSIGNABLE_PRICE"}
        protected += quantity * limit * (1 + market.fee_rate)
    result.update(
        up_market=markets[0].slug,
        down_market=markets[1].slug,
        lower_threshold=str(markets[0].reference_price),
        upper_threshold=str(markets[1].reference_price),
        shares=str(quantity),
        ask_cost=str(cost),
        estimated_fees=str(fees),
        protected_cost=str(protected),
        minimum_payout=str(quantity),
        protected_surplus=str(quantity - protected),
        max_receipt_separation_ms=max(b.received_ms for b in books)
        - min(b.received_ms for b in books),
        inputs={"short": asdict(first), "long": asdict(long), "books": [asdict(b) for b in books]},
    )
    result["status"] = (
        "QUOTE_CANDIDATE"
        if protected < quantity and protected <= config.risk.trade_budget_usd
        else "PAIR_BUDGET_LIMIT"
        if protected > config.risk.trade_budget_usd
        else "NO_PROTECTED_SURPLUS"
    )
    return result


class CrossDuration:
    def __init__(self, source: MarketData, config: Config) -> None:
        self.source, self.config = source, config
        self.reader = MarketData(
            config
        )  # public HTTP/SDK only; no account or extra RTDS connection
        self.latest: dict[str, Any] = {
            "status": "SCANNER_STARTING",
            "received_ms": int(time.time() * 1000),
        }
        self.states: dict[str, _Round] = {}

    async def sample(self) -> dict[str, Any]:
        now = int(time.time() * 1000)
        short = self.source.current_snapshot()
        if short is None:
            return {"status": "SCANNER_SNAPSHOT_MISSING", "received_ms": now}
        start = short.market.start_s // 900 * 900
        if short.market.end_s != start + 900:
            return {
                "status": "WAITING_SHARED_EXPIRY",
                "received_ms": now,
                "short_market": short.market.slug,
            }
        slug = f"btc-updown-15m-{start}"
        event = await self.reader._raw(
            f"{GAMMA}/events/slug/{slug}", params={"include_chat": "false"}
        )
        raw = self.reader._parse_event(event, slug, start, duration_seconds=900)
        condition = _condition(raw.get("conditionId"))
        tokens = _token_map(_array(raw.get("outcomes")), _array(raw.get("clobTokenIds")))
        point = self.source._points["twap60"].get(start * 1000)
        state = self.states.setdefault(
            slug, _Round(slug, start, condition, captured=point.price if point else None)
        )
        if (
            state.condition_id != condition
            or start * 1000 in self.source._conflicting_points["twap60"]
        ):
            state.conflict = True
        self.reader._metadata(state, event.get("eventMetadata"), f"{GAMMA}/events/slug/{slug}")
        flags, fees, up, down = await asyncio.gather(
            self.reader._raw(f"{CLOB}/markets/{condition}"),
            self.reader._raw(f"{CLOB}/clob-markets/{condition}"),
            self.reader._read_book(tokens["Up"]),
            self.reader._read_book(tokens["Down"]),
        )
        tick, minimum, rate, exponent = self.reader._trading_metadata(
            flags, fees, slug, condition, tokens
        )
        if any(
            b.condition_id != condition or b.tick != tick or b.minimum != minimum
            for b in (up, down)
        ):
            raise DataUnavailable("TRADING_METADATA_CHANGED")
        value, status = self.reader._reference(state)
        market = Market(
            slug,
            condition,
            start,
            start + 900,
            tokens["Up"],
            tokens["Down"],
            value,
            "eventMetadata.priceToBeat"
            if state.official is not None
            else "chainlink_twap60_exact_boundary"
            if value is not None
            else None,
            SOURCE,
            tick,
            minimum,
            rate,
            exponent,
            True,
            True,
            status,
            start * 1000 if value is not None else None,
            state.received_ms,
            state.provenance,
        )
        self.states = {slug: state}
        current = self.source.current_snapshot()
        if current is None or current.market.slug != short.market.slug:
            raise DataUnavailable("SCANNER_ROUND_CHANGED")
        return scan_pair(current, market, up.book, down.book, self.config, int(time.time() * 1000))

    async def run(self) -> None:
        try:
            while True:
                try:
                    self.latest = await self.sample()
                except DataUnavailable as exc:
                    self.latest = {"status": exc.code, "received_ms": int(time.time() * 1000)}
                except (ValueError, TypeError, KeyError):
                    self.latest = {
                        "status": "SCANNER_INVALID_INPUT",
                        "received_ms": int(time.time() * 1000),
                    }
                await asyncio.sleep(1)
        finally:
            await self.reader.close()
