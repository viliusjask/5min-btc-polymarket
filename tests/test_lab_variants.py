from dataclasses import replace
from decimal import Decimal

from test_strategy import make_snapshot

from btc5m.config import Config
from btc5m.domain import Side
from btc5m.lab_variants import Variant, default_variants, evaluate_variant
from btc5m.strategy import evaluate

D = Decimal


def test_registry_is_unique_reproducible_and_budget_comparable():
    variants = default_variants(Config())
    assert variants == default_variants(Config())
    assert len({v.ident for v in variants}) == len(variants)
    assert {v.config.risk.allocation_usd for v in variants} == {D(100)}
    assert {v.config.risk.trade_budget_usd for v in variants} == {D(5)}
    assert {v.family for v in variants} >= {
        "momentum",
        "value",
        "exit",
        "feed",
        "normalized",
        "recent",
    }
    dense = default_variants(Config(), dense=True)
    assert {v.config.strategy.momentum_min_move_usd for v in dense if v.family == "momentum"} == {
        D(i) for i in range(1, 101)
    }


def test_control_decision_preserves_the_original_strategy():
    snap, config = make_snapshot(), Config()
    variant = Variant("control", "control", "Value control", config)
    decision = evaluate_variant(snap, variant)
    original = evaluate(snap, config)
    assert decision.side == original.side
    assert decision.reason == original.reason
    assert decision.buy_principal == original.buy_principal
    assert decision.price_limit == original.price_limit


def test_normalized_lead_responds_to_volatility_and_still_checks_depth():
    snap = make_snapshot(move=D(100))
    cfg = replace(Config(), strategy=replace(Config().strategy, mode="momentum"))
    variant = Variant("z", "normalized", "Normalized", cfg, signal="normalized", threshold=D(1))
    assert evaluate_variant(snap, variant).reason == "ENTRY"
    volatile = replace(
        snap,
        history=tuple(
            replace(p, price=snap.spot.price - D(1000) if i % 2 else snap.spot.price)
            for i, p in enumerate(snap.history)
        ),
    )
    assert evaluate_variant(volatile, variant).reason == "NORMALIZED_LEAD"
    assert (
        evaluate_variant(replace(snap, up_book=replace(snap.up_book, asks=())), variant).reason
        != "ENTRY"
    )


def test_recent_continuation_and_reversal_use_lagged_prices_with_opposite_sides():
    snap = make_snapshot(move=D(100))
    history = tuple(
        replace(p, price=p.price - D(100)) if p.timestamp_ms < snap.spot.timestamp_ms - 5000 else p
        for p in snap.history
    )
    snap = replace(snap, history=history)
    cfg = replace(
        Config(), strategy=replace(Config().strategy, mode="momentum", momentum_min_ask=D(".01"))
    )
    continuation = Variant(
        "cont",
        "recent",
        "Continue",
        cfg,
        signal="continuation",
        threshold=D(".1"),
        lookback_seconds=30,
    )
    reversal = replace(continuation, name="rev", signal="reversal")
    assert evaluate_variant(snap, continuation).side is Side.UP
    assert evaluate_variant(snap, reversal).side is Side.DOWN
    missing = replace(
        snap,
        history=tuple(
            p for p in history if abs(p.timestamp_ms - (snap.spot.timestamp_ms - 30000)) > 5000
        ),
    )
    assert evaluate_variant(missing, continuation).reason != "ENTRY"
