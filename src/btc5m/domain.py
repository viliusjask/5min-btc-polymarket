"""Immutable, Decimal-valued inputs and decisions for the trading core."""

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Literal


class Side(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


@dataclass(frozen=True)
class PricePoint:
    kind: Literal["spot", "twap60"]
    timestamp_ms: int
    received_ms: int
    price: Decimal

    def __post_init__(self) -> None:
        if self.kind not in ("spot", "twap60"):
            raise ValueError("unsupported price kind")
        require_integer(self.timestamp_ms, "timestamp_ms")
        require_integer(self.received_ms, "received_ms")
        require_decimal(self.price, "price", positive=True)


@dataclass(frozen=True)
class Level:
    price: Decimal
    size: Decimal

    def __post_init__(self) -> None:
        require_decimal(self.price, "price", positive=True)
        require_decimal(self.size, "size", positive=True)
        if self.price >= 1:
            raise ValueError("outcome price must be less than one")


@dataclass(frozen=True)
class Book:
    token_id: str
    timestamp_ms: int
    received_ms: int
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.token_id, str) or not self.token_id:
            raise ValueError("token_id is required")
        require_integer(self.timestamp_ms, "timestamp_ms")
        require_integer(self.received_ms, "received_ms")
        for side in (self.bids, self.asks):
            if not isinstance(side, tuple) or any(not isinstance(level, Level) for level in side):
                raise ValueError("book sides must be tuples of Levels")
        object.__setattr__(
            self, "bids", tuple(sorted(self.bids, key=lambda level: level.price, reverse=True))
        )
        object.__setattr__(self, "asks", tuple(sorted(self.asks, key=lambda level: level.price)))


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

    def __post_init__(self) -> None:
        for name in (
            "slug",
            "condition_id",
            "up_token",
            "down_token",
            "settlement_source",
            "metadata_provenance",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} is required")
        if self.up_token == self.down_token:
            raise ValueError("outcome tokens must be distinct")
        require_integer(self.start_s, "start_s")
        require_integer(self.end_s, "end_s")
        require_integer(self.metadata_received_ms, "metadata_received_ms")
        if self.end_s <= self.start_s:
            raise ValueError("market end must follow start")
        require_decimal(self.tick_size, "tick_size", positive=True)
        require_decimal(self.min_order_size, "min_order_size", positive=True)
        require_decimal(self.fee_rate, "fee_rate")
        require_integer(self.fee_exponent, "fee_exponent", positive=True)
        if self.tick_size >= 1 or self.fee_rate > 1:
            raise ValueError("invalid tick or fee rate")
        if type(self.active) is not bool or type(self.accepting_orders) is not bool:
            raise ValueError("explicit market booleans required")
        if self.reference_status not in ("official", "boundary", "missing", "conflict"):
            raise ValueError("unsupported reference status")
        if self.reference_price is not None:
            require_decimal(self.reference_price, "reference_price", positive=True)
        if self.reference_timestamp_ms is not None:
            require_integer(self.reference_timestamp_ms, "reference_timestamp_ms")

    def token(self, side: Side) -> str:
        if not isinstance(side, Side):
            raise ValueError("unsupported side")
        return self.up_token if side is Side.UP else self.down_token


@dataclass(frozen=True)
class Snapshot:
    market: Market
    up_book: Book
    down_book: Book
    spot: PricePoint
    twap60: PricePoint
    history: tuple[PricePoint, ...]
    now_ms: int
    exchange_history: tuple[PricePoint, ...] = ()

    def __post_init__(self) -> None:
        require_integer(self.now_ms, "now_ms")
        if self.spot.kind != "spot" or self.twap60.kind != "twap60":
            raise ValueError("snapshot requires distinct spot and twap60 feeds")
        if not isinstance(self.history, tuple) or any(
            not isinstance(p, PricePoint) for p in self.history
        ):
            raise ValueError("history must be a tuple of PricePoints")
        if not isinstance(self.exchange_history, tuple) or any(
            not isinstance(p, PricePoint) or p.kind != "spot" for p in self.exchange_history
        ):
            raise ValueError("exchange_history must contain spot PricePoints")


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

    def __post_init__(self) -> None:
        for name in (
            "buy_principal",
            "max_total_reserved",
            "expected_shares",
            "minimum_receive_shares",
            "estimated_buy_fee",
        ):
            require_decimal(getattr(self, name), name)
        if self.max_total_reserved < self.buy_principal:
            raise ValueError("reservation cannot be below signed principal")
        if self.price_limit is not None:
            require_decimal(self.price_limit, "price_limit", positive=True)
            if self.price_limit >= 1:
                raise ValueError("price limit must be less than one")
        if self.side is not None and not isinstance(self.side, Side):
            raise ValueError("unsupported decision side")
        for probability in (self.probability_up, self.scenario_floor):
            if probability is not None and (
                not math.isfinite(probability) or not 0 <= probability <= 1
            ):
                raise ValueError("probability must be finite and between zero and one")
        if self.terminal_surplus_proxy is not None and (
            not isinstance(self.terminal_surplus_proxy, Decimal)
            or not self.terminal_surplus_proxy.is_finite()
        ):
            raise ValueError("terminal surplus must be a finite Decimal")
        if any(
            not isinstance(value, str) and not math.isfinite(value)
            for value in self.features.values()
        ):
            raise ValueError("decision features must be finite")
        object.__setattr__(self, "features", dict(self.features))


def require_decimal(value: Decimal, name: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative Decimal")
    if positive and value == 0:
        raise ValueError(f"{name} must be positive")


def require_integer(value: int, name: str, *, positive: bool = False) -> None:
    if type(value) is not int or value < int(positive):
        raise ValueError(
            f"{name} must be a nonnegative integer"
            if not positive
            else f"{name} must be a positive integer"
        )
