"""One complete, immutable configuration source."""

import hashlib
import json
import math
import tomllib
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, get_type_hints

from btc5m.domain import require_decimal, require_integer

STRATEGIES = ("momentum", "value", "fast_value", "model_exit", "passive_pairs", "inventory_pairs")
PAIR_STRATEGIES = ("passive_pairs", "inventory_pairs")


@dataclass(frozen=True)
class StrategyConfig:
    mode: str = "value"
    entry_min_seconds: int = 60
    entry_max_seconds: int = 180
    volatility_short_seconds: int = 300
    volatility_long_seconds: int = 1800
    volatility_stress_multiplier: Decimal = Decimal("1.25")
    adverse_reference_usd: Decimal = Decimal("10")
    value_min_ask: Decimal = Decimal("0")  # Zero disables the optional value price floor.
    value_max_ask: Decimal = Decimal(".92")
    min_terminal_surplus: Decimal = Decimal(".02")
    extra_price_allowance: Decimal = Decimal(".01")
    max_spread: Decimal = Decimal(".03")
    momentum_signal: str = "recent_continuation"
    momentum_lookback_seconds: int = 30
    momentum_min_signal_z: Decimal = Decimal(".5")
    momentum_min_move_usd: Decimal = Decimal("50")
    momentum_min_ask: Decimal = Decimal(".70")
    momentum_max_ask: Decimal = Decimal(".95")
    momentum_min_seconds: int = 90
    momentum_max_seconds: int = 150

    def __post_init__(self) -> None:
        _validate_types(self)
        if self.mode not in (*STRATEGIES, "compare"):
            raise ValueError("unsupported strategy.mode")
        if not 60 <= self.entry_min_seconds <= self.entry_max_seconds <= 300:
            raise ValueError("entry timing must be ordered and outside the ending average")
        if (
            not self.entry_min_seconds
            <= self.momentum_min_seconds
            <= self.momentum_max_seconds
            <= self.entry_max_seconds
        ):
            raise ValueError("momentum timing must fit the shared entry window")
        if not 60 <= self.volatility_short_seconds < self.volatility_long_seconds <= 86400:
            raise ValueError("volatility windows must be ordered and bounded")
        if not math.isfinite(float(self.volatility_stress_multiplier)):
            raise ValueError("volatility stress must have a finite float representation")
        if self.volatility_stress_multiplier < 1:
            raise ValueError("volatility stress cannot reduce sigma")
        if not 0 <= self.value_min_ask <= self.value_max_ask < 1 or self.value_max_ask == 0:
            raise ValueError("value ask band needs a positive ceiling below one")
        if not 0 < self.momentum_min_ask <= self.momentum_max_ask < 1:
            raise ValueError("momentum ask band must lie strictly inside zero and one")
        if any(
            value >= 1
            for value in (self.min_terminal_surplus, self.extra_price_allowance, self.max_spread)
        ):
            raise ValueError("per-share allowances must be less than one")
        if self.momentum_min_move_usd == 0:
            raise ValueError("momentum move must be positive")
        if self.momentum_signal not in ("opening_lead", "recent_continuation"):
            raise ValueError("unsupported momentum signal")
        if not 5 <= self.momentum_lookback_seconds <= self.volatility_short_seconds:
            raise ValueError("momentum lookback must fit the short history window")
        if not 0 < self.momentum_min_signal_z <= 100:
            raise ValueError("momentum normalized move must be positive and bounded")


@dataclass(frozen=True)
class RiskConfig:
    allocation_usd: Decimal = Decimal("100")
    trade_budget_usd: Decimal = Decimal("5")
    daily_loss_usd: Decimal = Decimal("10")
    session_loss_usd: Decimal = Decimal("10")
    max_entries_per_day: int = 0  # Zero disables the optional entry-count cap.

    def __post_init__(self) -> None:
        _validate_types(self)
        for name in ("allocation_usd", "trade_budget_usd", "daily_loss_usd", "session_loss_usd"):
            require_decimal(getattr(self, name), name, positive=True)
        require_integer(self.max_entries_per_day, "max_entries_per_day")
        if not self.trade_budget_usd <= min(
            self.allocation_usd, self.daily_loss_usd, self.session_loss_usd
        ):
            raise ValueError("trade budget exceeds allocation or loss allowance")
        if max(self.daily_loss_usd, self.session_loss_usd) > self.allocation_usd:
            raise ValueError("loss allowance exceeds experimental allocation")


@dataclass(frozen=True)
class DataConfig:
    max_price_age_ms: int = 5000
    max_book_age_ms: int = 5000
    future_tolerance_ms: int = 1000
    sample_seconds: int = 5
    sample_tolerance_ms: int = 2000
    max_sample_gap_ms: int = 12000  # Larger intervals consume the history's irregular-time budget.
    min_sample_coverage: Decimal = Decimal(".95")
    allow_captured_anchor: bool = True

    def __post_init__(self) -> None:
        _validate_types(self)
        if self.max_price_age_ms == 0 or self.max_book_age_ms == 0:
            raise ValueError("freshness budgets must be positive")
        if self.sample_seconds != 5 or not 0 <= self.sample_tolerance_ms <= 2000:
            raise ValueError(
                "supported source grid is five seconds with at most two seconds tolerance"
            )
        if not self.sample_seconds * 1000 <= self.max_sample_gap_ms <= 12000:
            raise ValueError("sample gap must be between five and twelve seconds")
        if not Decimal(".95") <= self.min_sample_coverage <= 1:
            raise ValueError("sample coverage must be between .95 and one")
        if self.future_tolerance_ms > min(self.max_price_age_ms, self.max_book_age_ms):
            raise ValueError("future tolerance exceeds freshness budget")


@dataclass(frozen=True)
class ExecutionConfig:
    stop_loss_per_share: Decimal = Decimal(".08")
    take_profit_bid: Decimal = Decimal(".98")
    exit_seconds: int = 20
    buy_slippage: Decimal = Decimal(".01")
    sell_slippage: Decimal = Decimal(".01")

    def __post_init__(self) -> None:
        _validate_types(self)
        if not 0 < self.stop_loss_per_share < 1 or not 0 < self.take_profit_bid < 1:
            raise ValueError("exit prices must lie strictly inside zero and one")
        if self.exit_seconds == 0 or self.buy_slippage >= 1 or self.sell_slippage >= 1:
            raise ValueError("invalid exit timing or slippage")


@dataclass(frozen=True)
class ExperimentConfig:
    fast_max_age_ms: int = 1500
    fast_alignment_ms: int = 1000
    fast_max_move_bps: Decimal = Decimal("50")
    model_exit_surplus: Decimal = Decimal(".01")
    averaging_max_gap_ms: int = 2500
    pair_shares: Decimal = Decimal("5")
    pair_max_cost: Decimal = Decimal(".97")
    pair_min_edge: Decimal = Decimal(".02")
    pair_quote_seconds: int = 5
    pair_max_unhedged_seconds: int = 30
    pair_max_orders_per_round: int = 24
    inventory_adjustment: Decimal = Decimal(".04")
    paper_latency_ms: int = 250

    def __post_init__(self) -> None:
        _validate_types(self)
        for name in (
            "fast_max_age_ms",
            "fast_alignment_ms",
            "averaging_max_gap_ms",
            "paper_latency_ms",
        ):
            if not 1 <= getattr(self, name) <= 5000:
                raise ValueError(f"{name} must be between one and 5000 milliseconds")
        if not 0 < self.fast_max_move_bps <= 100:
            raise ValueError("fast move guard must be between zero and 100 basis points")
        if not 0 < self.pair_max_cost < 1 or self.pair_shares <= 0:
            raise ValueError("invalid pair size or all-in cost")
        if any(
            not 0 < x < 1
            for x in (self.pair_min_edge, self.model_exit_surplus, self.inventory_adjustment)
        ):
            raise ValueError("invalid experiment price allowances")
        if not 1 <= self.pair_quote_seconds <= 30:
            raise ValueError("pair quote lifetime must be one to 30 seconds")
        if not self.pair_quote_seconds <= self.pair_max_unhedged_seconds <= 120:
            raise ValueError("invalid unmatched inventory lifetime")
        if not 2 <= self.pair_max_orders_per_round <= 100:
            raise ValueError("pair order cap must be two to 100")


@dataclass(frozen=True)
class Config:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    data: DataConfig = field(default_factory=DataConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    experiments: ExperimentConfig = field(default_factory=ExperimentConfig)

    def __post_init__(self) -> None:
        _validate_types(self)
        if self.execution.exit_seconds >= self.strategy.entry_min_seconds:
            raise ValueError("exit timing must precede the shared new-entry cutoff")
        for window in (
            self.strategy.volatility_short_seconds,
            self.strategy.volatility_long_seconds,
        ):
            if window % self.data.sample_seconds:
                raise ValueError("variance windows must fit the source grid")

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: format(value.normalize(), "f"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_types(instance: Any) -> None:
    for name, expected in get_type_hints(type(instance)).items():
        value = getattr(instance, name)
        if expected is Decimal:
            require_decimal(value, name)
        elif expected is int:
            require_integer(value, name)
        elif type(value) is not expected:
            raise ValueError(f"{name} has an invalid type")


def _section[T](cls: type[T], values: object, label: str) -> T:
    if not isinstance(values, dict):
        raise ValueError(f"{label} must be a TOML table")
    assert is_dataclass(cls)
    known = {item.name for item in fields(cls)}
    if values.keys() - known:
        raise ValueError(f"{label} has unknown configuration keys")
    if known - values.keys():
        raise ValueError(f"{label} has missing configuration keys")
    prepared: dict[str, Any] = {}
    for name, expected in get_type_hints(cls).items():
        value = values[name]
        if expected is Decimal:
            if type(value) not in (int, Decimal):
                raise ValueError(f"{label}.{name} must be numeric")
            prepared[name] = Decimal(value)
        elif isinstance(expected, type) and is_dataclass(expected):
            prepared[name] = _section(expected, value, f"{label}.{name}")
        else:
            prepared[name] = value
    return cls(**prepared)


def load_config(path: Path) -> Config:
    with path.open("rb") as handle:
        raw = tomllib.load(handle, parse_float=Decimal)
    return _section(Config, raw, "config")


def strategy_for_round(config: Config, start_s: int) -> str:
    """Preassigned UTC rounds prevent selecting a live variant after seeing its signal."""
    return (
        STRATEGIES[(start_s // 300) % len(STRATEGIES)]
        if config.strategy.mode == "compare"
        else config.strategy.mode
    )
