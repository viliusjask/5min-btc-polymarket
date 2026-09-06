import math
from dataclasses import replace
from decimal import Decimal

import pytest
from test_strategy import make_snapshot

from btc5m.config import STRATEGIES, Config, strategy_for_round
from btc5m.domain import PricePoint
from btc5m.execution_types import Position
from btc5m.pairing import pair_decision
from btc5m.strategy import conditional_probability_up, evaluate, fair_value, fast_reference

D = Decimal


def mode(name):
    return replace(Config(), strategy=replace(Config().strategy, mode=name))


def test_comparison_assigns_each_variant_once_before_seeing_signals():
    config = mode("compare")
    assert [strategy_for_round(config, i * 300) for i in range(6)] == list(STRATEGIES)
    assert strategy_for_round(config, 1800) == STRATEGIES[0]


def test_fast_reference_uses_exchange_return_not_exchange_absolute_price():
    snap = make_snapshot()
    stamp = snap.spot.timestamp_ms
    snap = replace(
        snap,
        now_ms=stamp + 1000,
        exchange_history=(
            PricePoint("spot", stamp, stamp, D("100000")),
            PricePoint("spot", stamp + 1000, stamp + 1000, D("100010")),
        ),
    )
    point, features = fast_reference(snap, Config())
    assert point.price == snap.spot.price * D("1.0001")
    assert features["exchange_source_ms"] == str(stamp + 1000)
    assert snap.spot.price == D("80200")


@pytest.mark.parametrize("problem", ["missing", "stale", "unaligned", "future", "jump"])
def test_fast_value_never_silently_falls_back(problem):
    snap = make_snapshot()
    stamp = snap.now_ms
    points = (
        PricePoint("spot", stamp, stamp, D("80000")),
        PricePoint("spot", stamp + 1000, stamp + 1000, D("80001")),
    )
    if problem == "missing":
        points = ()
    elif problem == "stale":
        points = (replace(points[0], timestamp_ms=stamp - 6000, received_ms=stamp - 6000),)
    elif problem == "unaligned":
        points = points[1:]
    elif problem == "future":
        points = (*points, replace(points[-1], timestamp_ms=stamp + 10000))
    elif problem == "jump":
        points = (points[0], replace(points[1], price=D("90000")))
    result = evaluate(
        replace(snap, now_ms=stamp + 1000, exchange_history=points), mode("fast_value")
    )
    assert result.side is None
    assert result.reason.startswith("FAST_")


def test_final_average_probability_uses_realized_part_and_remaining_variance():
    # Half the average is already $100, current $102, anchor $100. Expected
    # average =101; std=2*sqrt(30**3/3)/60=sqrt(10).
    from statistics import NormalDist

    assert conditional_probability_up(D("102"), D("100"), 2, 30, D("3000")) == pytest.approx(
        NormalDist().cdf(1 / math.sqrt(10))
    )
    assert conditional_probability_up(D("100"), D("100"), 2, 60, D(0)) == 0.5


def test_final_minute_model_rejects_missing_realized_history():
    snap = make_snapshot(now_ms=(1_800_000_000 + 270) * 1000)
    value = fair_value(snap, mode("model_exit"))
    assert value.reason == "AVERAGING_HISTORY_GAP"


def test_baseline_and_model_exit_have_identical_entry_decisions():
    snap = make_snapshot()
    baseline, improved = evaluate(snap, mode("value")), evaluate(snap, mode("model_exit"))
    assert baseline.side == improved.side
    assert baseline.price_limit == improved.price_limit
    assert baseline.probability_up == improved.probability_up
    assert improved.features["mode"] == "model_exit"


def test_pairs_are_post_only_and_keep_full_round_under_budget():
    snap = make_snapshot()
    config = mode("passive_pairs")
    first = pair_decision(snap, config, ())
    assert first.side is not None
    assert first.features["order_type"] == "GTC"
    assert first.price_limit < snap.up_book.asks[0].price
    assert first.max_total_reserved <= config.risk.trade_budget_usd
    position = Position(
        "p",
        snap.market,
        snap.market.token(first.side),
        "wallet",
        first,
        D(5),
        first.buy_principal,
        first.price_limit,
        "ACTIVE",
    )
    hedge = pair_decision(snap, config, (position,))
    assert hedge.side != first.side
    assert hedge.max_total_reserved + position.cost_basis <= config.risk.trade_budget_usd
    assert (
        hedge.max_total_reserved / 5 + position.cost_basis / 5 <= config.experiments.pair_max_cost
    )


def test_inventory_policy_changes_hedge_quote_without_loosening_pair_cap():
    from btc5m.domain import Book, Level, Side

    snap = make_snapshot(move=D(0))
    snap = replace(
        snap,
        down_book=Book(
            "down", snap.now_ms, snap.now_ms, (Level(D(".40"), D(100)),), (Level(D(".50"), D(100)),)
        ),
    )
    configs = (mode("passive_pairs"), mode("inventory_pairs"))
    results = []
    for config in configs:
        source = replace(evaluate(make_snapshot(), config), side=Side.UP)
        held = Position(
            "p", snap.market, "up", "wallet", source, D(5), D("1.5"), D(".30"), "ACTIVE"
        )
        results.append(pair_decision(snap, config, (held,)))
    assert results[1].price_limit > results[0].price_limit
    assert results[1].features["pair_role"] == "HEDGE"


def test_pair_completion_never_counts_as_another_directional_entry():
    from btc5m.domain import Side

    snap, config = make_snapshot(), mode("passive_pairs")
    decision = evaluate(snap, config)
    held = tuple(
        Position(
            str(side),
            snap.market,
            snap.market.token(side),
            "wallet",
            decision,
            D(5),
            D(2),
            D(".4"),
            "ACTIVE",
        )
        for side in Side
    )
    assert pair_decision(snap, config, held).reason == "PAIR_COMPLETE"
