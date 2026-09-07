"""Registered, paper-only hypotheses; execution still uses the existing engine."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, is_dataclass, replace
from decimal import Decimal
from typing import Any, get_type_hints

from btc5m.config import Config
from btc5m.domain import Decision, Side, Snapshot
from btc5m.lab_tape import encode
from btc5m.strategy import FairValue, _quote, _safety_reason, _skip, evaluate, fair_value

D = Decimal


@dataclass(frozen=True)
class Variant:
    name: str
    family: str
    label: str
    config: Config
    signal: str = "core"
    threshold: Decimal = D(0)
    lookback_seconds: int = 30
    exit_policy: str = "baseline"
    scenario: str = "stress"

    def __post_init__(self) -> None:
        if self.config.strategy.mode not in ("momentum", "value", "fast_value", "model_exit"):
            raise ValueError("LAB_DIRECTIONAL_ONLY")
        if self.signal not in ("core", "normalized", "continuation", "reversal"):
            raise ValueError("INVALID_LAB_SIGNAL")
        if self.exit_policy not in ("baseline", "no_stop", "time_only", "settlement", "model"):
            raise ValueError("INVALID_LAB_EXIT")
        if self.scenario not in ("central", "stress"):
            raise ValueError("INVALID_LAB_SCENARIO")
        if (
            not self.threshold.is_finite()
            or self.threshold < 0
            or not 5 <= self.lookback_seconds <= 300
        ):
            raise ValueError("INVALID_LAB_THRESHOLD")

    @property
    def ident(self) -> str:
        return hashlib.sha256(encode(asdict(self)).encode()).hexdigest()[:20]

    def record(self) -> dict[str, Any]:
        return {**asdict(self), "ident": self.ident}


def config_from_record(raw: dict[str, Any]) -> Config:
    def restore(cls: type, values: dict[str, Any]) -> Any:
        hints = get_type_hints(cls)
        return cls(
            **{
                k: D(v) if hints[k] is D else restore(hints[k], v) if is_dataclass(hints[k]) else v
                for k, v in values.items()
            }
        )

    return restore(Config, raw)


def variant_from(raw: dict[str, Any]) -> Variant:
    fields = {k: v for k, v in raw.items() if k != "ident"}
    fields["config"] = config_from_record(fields["config"])
    fields["threshold"] = D(fields["threshold"])
    variant = Variant(**fields)
    if raw.get("ident") != variant.ident:
        raise ValueError("LAB_VARIANT_ID_MISMATCH")
    return variant


def default_variants(base: Config, *, dense: bool = False) -> tuple[Variant, ...]:
    # Independent $100 wallets, retaining the caller's fixed trade/loss budgets.
    risk = replace(
        base.risk,
        allocation_usd=D(100),
        daily_loss_usd=min(base.risk.daily_loss_usd, D(100)),
        session_loss_usd=min(base.risk.session_loss_usd, D(100)),
    )
    base = replace(base, risk=risk)
    result: list[Variant] = []

    def add(
        name: str,
        family: str,
        label: str,
        mode: str = "value",
        *,
        strategy: dict[str, Any] | None = None,
        execution: dict[str, Any] | None = None,
        experiments: dict[str, Any] | None = None,
        **kw: Any,
    ) -> None:
        config = replace(
            base,
            strategy=replace(base.strategy, mode=mode, **(strategy or {})),
            execution=replace(base.execution, **(execution or {})),
            experiments=replace(base.experiments, **(experiments or {})),
        )
        result.append(Variant(name, family, label, config, **kw))

    for mode in ("momentum", "value", "fast_value", "model_exit"):
        add(f"control-{mode}", "control", f"{mode.replace('_', ' ').title()} control", mode)
    windows = ((60, 120), (90, 150), (120, 180))
    for lead in range(1 if dense else 10, 101, 1 if dense else 10):
        for low, high in windows:
            add(
                f"momentum-{lead}-{low}-{high}",
                "momentum",
                f"${lead} lead · {low}–{high}s",
                "momentum",
                strategy={
                    "momentum_min_move_usd": D(lead),
                    "momentum_min_seconds": low,
                    "momentum_max_seconds": high,
                },
            )
    for surplus in ("0", ".01", ".02", ".04"):
        for low, high in windows:
            # Non-momentum timing still has to contain its unused momentum config.
            add(
                f"value-{surplus}-{low}-{high}",
                "value",
                f"{D(surplus) * 100:g}¢ surplus · {low}–{high}s",
                strategy={
                    "min_terminal_surplus": D(surplus),
                    "entry_min_seconds": low,
                    "entry_max_seconds": high,
                    "momentum_min_seconds": low,
                    "momentum_max_seconds": high,
                },
            )
    for adverse in (0, 5, 10):
        add(
            f"buffer-{adverse}",
            "buffer",
            f"Reference stress ${adverse}",
            strategy={"adverse_reference_usd": D(adverse)},
        )
    add("central-value", "buffer", "Central probability · no scenario floor", scenario="central")
    for mode in ("momentum", "value"):
        for stop in (".04", ".12", ".20"):
            add(
                f"{mode}-stop-{stop}",
                "exit",
                f"{mode.title()} · {D(stop) * 100:g}¢ stop",
                mode,
                execution={"stop_loss_per_share": D(stop)},
            )
        for policy in ("no_stop", "time_only", "settlement", "model"):
            add(
                f"{mode}-{policy}",
                "exit",
                f"{mode.title()} · {policy.replace('_', ' ')}",
                mode,
                exit_policy=policy,
            )
    for mode in ("value", "fast_value"):
        for latency in (750, 1500):
            add(
                f"{mode}-{latency}ms",
                "feed",
                f"{mode.replace('_', ' ').title()} · {latency}ms delay",
                mode,
                experiments={"paper_latency_ms": latency},
            )
    for z in (".5", "1", "1.5", "2"):
        add(
            f"normalized-{z}",
            "normalized",
            f"Opening lead ≥ {z} × expected volatility",
            "momentum",
            signal="normalized",
            threshold=D(z),
        )
    for signal in ("continuation", "reversal"):
        for seconds in (10, 30, 60):
            for z in (".5", "1"):
                add(
                    f"{signal}-{seconds}-{z}",
                    "recent",
                    f"{signal.title()} · {seconds}s · z≥{z}",
                    "momentum",
                    strategy={"momentum_min_ask": D(".05")},
                    signal=signal,
                    threshold=D(z),
                    lookback_seconds=seconds,
                )
    return tuple(result)


class Valuations:
    """One-frame cache: only model-changing parameters enter the key."""

    def __init__(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self.cache: dict[str, FairValue] = {}

    def get(self, variant: Variant) -> FairValue:
        cfg = variant.config
        key = encode(
            (
                cfg.strategy.volatility_short_seconds,
                cfg.strategy.volatility_long_seconds,
                cfg.strategy.volatility_stress_multiplier,
                cfg.strategy.adverse_reference_usd,
                asdict(cfg.data),
                cfg.strategy.mode == "fast_value",
                cfg.experiments.fast_max_age_ms,
                cfg.experiments.fast_alignment_ms,
                cfg.experiments.fast_max_move_bps,
                cfg.experiments.averaging_max_gap_ms,
            )
        )
        if key not in self.cache:
            self.cache[key] = fair_value(self.snapshot, cfg)
        value = self.cache[key]
        floors = value.floors
        if variant.scenario == "central" and value.probability_up is not None:
            floors = {Side.UP: value.probability_up, Side.DOWN: 1 - value.probability_up}
        return replace(
            value,
            floors=floors,
            features={
                **value.features,
                "mode": cfg.strategy.mode,
                "config_hash": cfg.fingerprint,
                "lab_variant": variant.ident,
                "lab_signal": variant.signal,
                "lab_scenario": variant.scenario,
            },
        )


def evaluate_variant(
    snapshot: Snapshot, variant: Variant, cache: Valuations | None = None
) -> Decision:
    cfg = variant.config
    value = (cache or Valuations(snapshot)).get(variant)
    if variant.signal == "core":
        return evaluate(snapshot, cfg, valuation=value)
    safety = _safety_reason(snapshot, cfg)
    if safety:
        return _skip(snapshot, safety, value.features)
    tau = (snapshot.market.end_s * 1000 - snapshot.now_ms) / 1000
    if not cfg.strategy.momentum_min_seconds <= tau <= cfg.strategy.momentum_max_seconds:
        return _skip(snapshot, "ENTRY_WINDOW", value.features)
    if value.reason != "VALID":
        return _skip(snapshot, value.reason, value.features)
    assert value.probability_up is not None
    sigma = float(value.features["short_sigma"])
    if variant.signal == "normalized":
        move = D(str(value.features["spot_reference_move_usd"]))
        denominator = sigma * math.sqrt(float(value.features["model_tau_seconds"]) - 40)
        reason = "NORMALIZED_LEAD"
    else:
        target = snapshot.spot.timestamp_ms - variant.lookback_seconds * 1000
        candidates = [
            p
            for p in snapshot.history
            if p.timestamp_ms <= target and p.received_ms <= snapshot.now_ms
        ]
        if not candidates or target - candidates[-1].timestamp_ms > cfg.data.sample_tolerance_ms:
            return _skip(snapshot, "RECENT_ENDPOINT_MISSING", value.features)
        move = snapshot.spot.price - candidates[-1].price
        denominator = sigma * math.sqrt(
            (snapshot.spot.timestamp_ms - candidates[-1].timestamp_ms) / 1000
        )
        reason = "RECENT_MOVE"
    z = float(abs(move)) / denominator
    features = {
        **value.features,
        "lab_signal_z": z,
        "lab_signal_threshold": str(variant.threshold),
        "lab_signal_move_usd": str(move),
    }
    if move == 0 or z < float(variant.threshold):
        return _skip(snapshot, reason, features, value.probability_up)
    up = move > 0
    if variant.signal == "reversal":
        up = not up
    side = Side.UP if up else Side.DOWN
    return _quote(
        snapshot,
        cfg,
        side,
        snapshot.up_book if up else snapshot.down_book,
        value.probability_up,
        value.floors[side],
        features,
    )
