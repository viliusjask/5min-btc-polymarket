"""Prespecified flow hypotheses, kept out of funded strategy dispatch."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from btc5m.config import Config
from btc5m.domain import Side, Snapshot
from btc5m.lab_variants import Variant

D = Decimal


def order_flow_variants(base: Config) -> tuple[Variant, ...]:
    base = replace(
        base,
        risk=replace(
            base.risk,
            allocation_usd=D(100),
            daily_loss_usd=min(base.risk.daily_loss_usd, D(100)),
            session_loss_usd=min(base.risk.session_loss_usd, D(100)),
        ),
    )
    directional = replace(
        base,
        strategy=replace(
            base.strategy,
            mode="momentum",
            momentum_min_ask=D(".05"),
            momentum_min_seconds=60,
            momentum_max_seconds=180,
        ),
    )
    pairs = replace(
        base,
        strategy=replace(base.strategy, mode="inventory_pairs"),
        experiments=replace(base.experiments, pair_quote_seconds=15, pair_max_unhedged_seconds=60),
    )
    confirmation = replace(
        directional,
        strategy=replace(
            directional.strategy,
            entry_max_seconds=270,
            momentum_min_seconds=180,
            momentum_max_seconds=210,
        ),
    )
    result = [
        Variant(
            "control-value",
            "control",
            "Value control",
            replace(base, strategy=replace(base.strategy, mode="value")),
        ),
        Variant(
            "control-fast-value",
            "control",
            "Fast Value control",
            replace(base, strategy=replace(base.strategy, mode="fast_value")),
        ),
        Variant("control-inventory-pairs", "pairs", "Pair control · 15s quotes / 60s hedge", pairs),
    ]
    for signal in ("absorption", "flow_continuation"):
        for seconds in (10, 30):
            for threshold in (D(".3"), D(".6")):
                result.append(
                    Variant(
                        f"{signal}-{seconds}-{threshold}",
                        "flow",
                        f"{signal.replace('_', ' ').title()} · {seconds}s · {threshold}",
                        directional,
                        signal=signal,
                        threshold=threshold,
                        lookback_seconds=seconds,
                    )
                )
    for threshold in (D(".2"), D(".5")):
        result.append(
            Variant(
                f"pressure-pair-{threshold}",
                "pairs",
                f"Pressure first leg · {threshold}",
                pairs,
                signal="pressure_pair",
                threshold=threshold,
            )
        )
        result.append(
            Variant(
                f"pressure-confirm-{threshold}",
                "confirmation",
                f"Early pressure → later confirmation · {threshold}",
                confirmation,
                signal="pressure_confirm",
                threshold=threshold,
            )
        )
    result.append(
        Variant(
            "confirmation-control",
            "confirmation",
            "Later confirmation · no early pressure filter",
            confirmation,
            signal="confirmation_control",
        )
    )
    result.append(
        Variant(
            "split-sell",
            "split",
            "Split → passive sales → merge remainder",
            pairs,
            signal="split_sell",
        )
    )
    return tuple(result)


def _fresh(flow: dict[str, Any], now_ms: int) -> bool:
    return type(flow.get("received_ms")) is int and 0 <= now_ms - flow["received_ms"] <= 1500


def observe_flow(
    snapshot: Snapshot | None, variant: Variant, flow: dict[str, Any], state: dict[str, Any]
) -> None:
    """Called exactly once per recorded frame; state is committed with its orders."""
    if snapshot is None:
        state.clear()
        return
    now, slug = snapshot.now_ms, snapshot.market.slug
    if (
        state.get("slug") != slug
        or now - state.get("last_ms", now) > 5000
        or state.get("generation") != flow.get("generation")
    ):
        state.clear()
    state.update(slug=slug, last_ms=now, generation=flow.get("generation"))
    depth = flow.get("depth", {})
    valid_depth = (
        _fresh(flow, now)
        and depth.get("status") == "VALID"
        and 0 <= now - depth.get("received_ms", now + 1) <= 1500
    )
    imbalance = D(depth["imbalance"]) if valid_depth else D(0)
    direction = (
        "UP"
        if imbalance >= variant.threshold and imbalance > 0
        else "DOWN"
        if imbalance <= -variant.threshold and imbalance < 0
        else None
    )
    if direction != state.get("pressure_side"):
        state["pressure_since_ms"] = now
    state["pressure_side"] = direction
    if variant.signal not in ("pressure_confirm", "confirmation_control") or "arm" in state:
        return
    elapsed = now - snapshot.market.start_s * 1000
    if not 20000 <= elapsed <= 60000 or not snapshot.up_book.asks or not snapshot.down_book.asks:
        return
    prices = {
        Side.UP.value: str(snapshot.up_book.asks[0].price),
        Side.DOWN.value: str(snapshot.down_book.asks[0].price),
    }
    if not all(D(".4") <= D(p) <= D(".6") for p in prices.values()):
        return
    qualified = variant.signal == "confirmation_control" or (
        direction is not None and now - state.get("pressure_since_ms", now) >= 1000
    )
    state["arm"] = {
        "at_ms": now,
        "side": direction if variant.signal == "pressure_confirm" else None,
        "prices": prices,
        "qualified": qualified,
    }


def flow_side(
    snapshot: Snapshot, variant: Variant, flow: dict[str, Any], state: dict[str, Any]
) -> tuple[Side | None, str, dict[str, float | str]]:
    now = snapshot.now_ms
    features: dict[str, float | str] = {"lab_signal": variant.signal, "lab_variant": variant.ident}
    if variant.signal in ("pressure_confirm", "confirmation_control"):
        arm = state.get("arm")
        if arm and not arm.get("qualified", True):
            return None, "EARLY_PRESSURE_NOT_QUALIFIED", features
        if (
            not arm
            or not 90000 <= now - snapshot.market.start_s * 1000 <= 120000
            or now <= arm["at_ms"]
        ):
            return None, "EARLY_SIGNAL_NOT_ARMED" if not arm else "CONFIRMATION_WINDOW", features
        prices = {
            Side.UP: snapshot.up_book.asks[0].price,
            Side.DOWN: snapshot.down_book.asks[0].price,
        }
        choices = [Side(arm["side"])] if arm["side"] else list(Side)
        side = max(choices, key=lambda s: prices[s] - D(arm["prices"][s.value]))
        move = prices[side] - D(arm["prices"][side.value])
        features.update(
            early_signal_ms=str(arm["at_ms"]),
            early_ask=arm["prices"][side.value],
            confirmation_move=str(move),
        )
        return (
            (side, "VALID", features)
            if move >= variant.confirmation_move
            else (None, "PRICE_NOT_CONFIRMED", features)
        )
    if not _fresh(flow, now):
        return None, "FLOW_INPUT_MISSING_OR_STALE", features
    if variant.signal == "pressure_pair":
        depth = flow.get("depth", {})
        if (
            depth.get("status") != "VALID"
            or not 0 <= now - depth.get("received_ms", now + 1) <= 1500
        ):
            return None, "DEPTH_UNAVAILABLE", features
        side_name = state.get("pressure_side")
        if side_name is None or now - state.get("pressure_since_ms", now) < 1000:
            return None, "PRESSURE_NOT_PERSISTENT", features
        features.update(
            depth_imbalance=depth["imbalance"],
            depth_received_ms=str(depth["received_ms"]),
            depth_clock="receipt_only",
        )
        return Side(side_name), "VALID", features
    row = flow.get("windows", {}).get(str(variant.lookback_seconds), {})
    if row.get("status") != "VALID" or flow.get("status") != "VALID":
        return None, str(row.get("status", "FLOW_WINDOW_MISSING")), features
    stamp = row.get("source_ms")
    if type(stamp) is not int or not 0 <= now - stamp <= 1500:
        return None, "FLOW_TRADE_STALE", features
    imbalance, move = D(row["imbalance"]), D(row["return_bps"])
    features.update(
        flow_imbalance=str(imbalance), flow_move_bps=str(move), exchange_source_ms=str(stamp)
    )
    if abs(imbalance) < variant.threshold or imbalance == 0:
        return None, "FLOW_TOO_BALANCED", features
    sign = D(1) if imbalance > 0 else D(-1)
    if variant.signal == "absorption":
        if abs(move) > variant.absorption_max_bps:
            return None, "FLOW_NOT_ABSORBED", features
        up = imbalance < 0
    else:
        if move * sign <= variant.absorption_max_bps:
            return None, "FLOW_PRICE_NOT_FOLLOWING", features
        up = imbalance > 0
    return Side.UP if up else Side.DOWN, "VALID", features
