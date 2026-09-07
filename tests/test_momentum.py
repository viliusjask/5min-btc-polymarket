"""Momentum follows a causal recent move, independently of terminal valuation."""

from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_strategy import make_snapshot

from btc5m.config import Config
from btc5m.domain import Side
from btc5m.lab_variants import default_variants, evaluate_variant
from btc5m.strategy import evaluate, fair_value


def recent_snapshot(direction=1):
    snapshot = make_snapshot()
    history = tuple(
        replace(p, price=p.price - D(direction * 2 * (60 - i)))
        for i, p in enumerate(snapshot.history[-61:])
    )
    # Both executable books meet the unchanged Momentum band for either signal.
    return replace(
        snapshot,
        history=history,
        down_book=replace(snapshot.up_book, token_id="down"),
    )


def momentum_config(**settings):
    base = Config()
    return replace(base, strategy=replace(base.strategy, mode="momentum", **settings))


@pytest.mark.parametrize("direction,side", [(1, Side.UP), (-1, Side.DOWN)])
def test_recent_direction_with_only_five_minutes_and_no_terminal_model(direction, side):
    snapshot, config = recent_snapshot(direction), momentum_config()
    # Opening reference remains below spot in BOTH cases. The falling case must buy Down.
    assert snapshot.spot.price > snapshot.market.reference_price
    unavailable = fair_value(snapshot, config)
    assert unavailable.reason == "INSUFFICIENT_HISTORY"
    decision = evaluate(snapshot, config, valuation=unavailable)
    assert decision.reason == "ENTRY" and decision.side is side
    assert decision.probability_up is None
    assert decision.scenario_floor is None and decision.terminal_surplus_proxy is None
    assert decision.features["momentum_recent_move_usd"] == str(D(direction * 12))
    assert decision.features["model_status"] == "NOT_REQUIRED"
    assert decision.max_total_reserved <= config.risk.trade_budget_usd


def test_large_opening_lead_with_flat_recent_price_is_not_momentum():
    decision = evaluate(make_snapshot(), momentum_config())
    assert decision.reason == "MOMENTUM_RECENT_MOVE"
    assert decision.side is None


def test_missing_recent_endpoint_is_not_interpolated():
    snapshot = recent_snapshot()
    target = snapshot.spot.timestamp_ms - 30_000
    snapshot = replace(
        snapshot, history=tuple(p for p in snapshot.history if p.timestamp_ms != target)
    )
    assert evaluate(snapshot, momentum_config()).reason == "RECENT_ENDPOINT_MISSING"


@pytest.mark.parametrize(
    "fault,reason",
    [("future", "FUTURE_DATA"), ("duplicate", "INVALID_HISTORY"), ("gap", "INSUFFICIENT_HISTORY")],
)
def test_recent_signal_rejects_invalid_or_incomplete_history(fault, reason):
    snapshot = recent_snapshot()
    history = snapshot.history
    if fault == "future":
        history = (*history[:-1], replace(history[-1], received_ms=snapshot.now_ms + 1))
    elif fault == "duplicate":
        history = (*history, history[-1])
    else:
        history = history[10:]
    assert evaluate(replace(snapshot, history=history), momentum_config()).reason == reason


def test_recent_signal_retains_price_band_and_market_safety():
    snapshot = recent_snapshot()
    snapshot = replace(
        snapshot,
        up_book=replace(
            snapshot.up_book, asks=(replace(snapshot.up_book.asks[0], price=D(".69")),)
        ),
    )
    assert evaluate(snapshot, momentum_config()).reason == "PRICE_BAND"
    stale = replace(recent_snapshot(), now_ms=snapshot.now_ms + 6000)
    assert evaluate(stale, momentum_config()).side is None


def test_lab_core_uses_recent_signal_but_dollar_lead_grid_stays_legacy():
    variants = default_variants(Config())
    core = next(v for v in variants if v.name == "control-momentum")
    grid = next(v for v in variants if v.name == "momentum-50-90-150")
    assert grid.config.strategy.momentum_signal == "opening_lead"
    decision = evaluate_variant(recent_snapshot(-1), core)
    assert decision.side is Side.DOWN
    assert decision.features["lab_variant"] == core.ident


@pytest.mark.parametrize(
    "settings",
    [
        {"momentum_signal": "unknown"},
        {"momentum_lookback_seconds": 0},
        {"momentum_lookback_seconds": 301},
        {"momentum_min_signal_z": D(0)},
        {"momentum_min_signal_z": D("Infinity")},
    ],
)
def test_recent_signal_configuration_is_validated(settings):
    with pytest.raises(ValueError):
        momentum_config(**settings)
