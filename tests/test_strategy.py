import math
from dataclasses import replace
from decimal import Decimal

import pytest

from btc5m.config import Config
from btc5m.domain import Book, Level, Market, PricePoint, Side, Snapshot
from btc5m.strategy import evaluate, fee_for, terminal_probability_up

D = Decimal
START = 1_800_000_000
NOW = (START + 180) * 1000
SOURCE = "https://data.chain.link/streams/btc-usd-twap-60s-streams"


DEFAULT_MOVE = D("200")
DEFAULT_ASK = D(".70")


def make_snapshot(*, move=DEFAULT_MOVE, ask=DEFAULT_ASK, now_ms=NOW):
    price = D("80000") + move
    # Every five-second change is $5, so both windows have sigma=sqrt(5).
    history = tuple(
        PricePoint(
            "spot",
            now_ms - (360 - i) * 5000,
            now_ms - (360 - i) * 5000,
            price - D(5) if i % 2 else price,
        )
        for i in range(361)
    )
    market = Market(
        slug=f"btc-updown-5m-{START}",
        condition_id="condition",
        start_s=START,
        end_s=START + 300,
        up_token="up",
        down_token="down",
        reference_price=D("80000"),
        reference_source="eventMetadata.priceToBeat",
        settlement_source=SOURCE,
        tick_size=D(".01"),
        min_order_size=D("5"),
        fee_rate=D(".07"),
        fee_exponent=1,
        active=True,
        accepting_orders=True,
        reference_status="official",
        reference_timestamp_ms=START * 1000,
        metadata_received_ms=now_ms,
        metadata_provenance="gamma:get_event:include_chat=False",
    )
    return Snapshot(
        market,
        Book("up", now_ms, now_ms, (Level(ask - D(".02"), D("100")),), (Level(ask, D("100")),)),
        Book("down", now_ms, now_ms, (Level(D(".28"), D("100")),), (Level(D(".30"), D("100")),)),
        PricePoint("spot", now_ms, now_ms, price),
        PricePoint("twap60", now_ms, now_ms, price - D("20")),
        history,
        now_ms,
    )


def test_fee_independent_numerical_vector():
    assert fee_for(D("5"), D(".70"), D(".07")) == D(".07350")


@pytest.mark.parametrize(
    "shares,price,rate,exponent",
    [
        (D("NaN"), D(".7"), D(".07"), 1),
        (D("5"), D("Infinity"), D(".07"), 1),
        (D("5"), D(".7"), D("-1"), 1),
        (D("-5"), D(".7"), D(".07"), 1),
        (D("5"), D("1.1"), D(".07"), 1),
        (D("5"), D(".7"), D(".07"), 0),
    ],
)
def test_fee_rejects_invalid_inputs(shares, price, rate, exponent):
    with pytest.raises(ValueError):
        fee_for(shares, price, rate, exponent)


def test_terminal_probability_independent_numerical_vectors():
    p = terminal_probability_up(D("80090"), D("80000"), 50 / math.sqrt(60), 120)
    assert p == pytest.approx(0.9405, abs=0.0001)
    assert terminal_probability_up(D("80000"), D("80000"), 5, 120) == 0.5
    down = terminal_probability_up(D("79910"), D("80000"), 50 / math.sqrt(60), 120)
    assert p + down == pytest.approx(1)


@pytest.mark.parametrize("sigma,tau", [(float("nan"), 120), (0, 120), (1, 59)])
def test_terminal_probability_rejects_invalid_model(sigma, tau):
    with pytest.raises(ValueError):
        terminal_probability_up(D("80090"), D("80000"), sigma, tau)


def test_value_candidate_reserves_fixed_cash_and_records_cost_components():
    decision = evaluate(make_snapshot(), Config())
    assert decision.reason == "ENTRY"
    assert decision.side is Side.UP
    assert decision.buy_principal == D("4.67")
    assert decision.max_total_reserved == D("4.9969")
    assert decision.price_limit == D(".71")
    assert decision.minimum_receive_shares == D("6.5775")
    assert decision.expected_shares == D("4.67") / D(".70")
    assert decision.estimated_buy_fee == D(".09807")
    assert decision.terminal_surplus_proxy is not None
    assert decision.terminal_surplus_proxy > D(".02")
    assert D(decision.features["sell_fee_reserve_per_share"]) == D(".0175")
    assert decision.features["short_span_seconds"] == 300
    assert decision.features["long_sample_count"] == 361


@pytest.mark.parametrize("mode,ask", [("value", D(".92")), ("momentum", D(".93"))])
def test_optional_slippage_cannot_disqualify_an_affordable_current_ask(mode, ask):
    config = replace(Config(), strategy=replace(Config().strategy, mode=mode))
    decision = evaluate(make_snapshot(ask=ask), config)
    assert decision.reason == "ENTRY"
    assert decision.price_limit == ask
    assert decision.minimum_receive_shares >= 5
    assert decision.buy_principal == 5 * ask
    assert decision.max_total_reserved == 5 * ask * D("1.07")


def test_slippage_cap_does_not_authorize_an_unaffordable_current_ask():
    config = replace(Config(), strategy=replace(Config().strategy, mode="momentum"))
    assert evaluate(make_snapshot(ask=D(".94")), config).reason == "BELOW_MINIMUM_SIZE"


def test_improved_asks_increase_estimate_without_increasing_spending():
    before = evaluate(make_snapshot(ask=D(".70")), Config())
    after = evaluate(make_snapshot(ask=D(".65")), Config())
    assert after.side is Side.UP
    assert after.expected_shares > before.expected_shares
    assert after.buy_principal == before.buy_principal
    assert after.max_total_reserved == before.max_total_reserved


def test_cash_depth_consumption_and_tick_rounding():
    snap = make_snapshot()
    book = replace(
        snap.up_book,
        bids=(Level(D(".68"), D("100")),),
        asks=(Level(D(".705"), D("100")), Level(D(".70"), D("2"))),
    )
    decision = evaluate(replace(snap, up_book=book), Config())
    assert decision.side is Side.UP
    assert decision.buy_principal == D("4.67")
    assert decision.expected_shares == D("2") + D("3.27") / D(".705")
    assert decision.price_limit == D(".72")
    assert decision.minimum_receive_shares == D("6.4862")


def test_small_trade_cannot_round_up_to_exchange_minimum():
    snap = make_snapshot()
    decision = evaluate(
        replace(snap, market=replace(snap.market, min_order_size=D("10"))), Config()
    )
    assert decision.side is None
    assert decision.reason == "BELOW_MINIMUM_SIZE"
    assert decision.buy_principal == 0


def test_minimum_shares_checked_after_protected_integer_rounding():
    snap = make_snapshot()
    snap = replace(snap, market=replace(snap.market, min_order_size=D("6.672")))
    assert evaluate(snap, Config()).reason == "BELOW_MINIMUM_SIZE"


@pytest.mark.parametrize(
    "which,age", [("spot", 5001), ("twap60", 5001), ("up_book", 5001), ("down_book", 5001)]
)
def test_stale_source_rejected_even_with_fresh_receive(which, age):
    snap = make_snapshot()
    obj = replace(getattr(snap, which), timestamp_ms=NOW - age)
    decision = evaluate(replace(snap, **{which: obj}), Config())
    assert decision.side is None
    assert decision.reason == "STALE_DATA"


@pytest.mark.parametrize("which", ["spot", "twap60", "up_book", "down_book"])
def test_future_data_rejected(which):
    snap = make_snapshot()
    obj = replace(getattr(snap, which), timestamp_ms=NOW + 1001)
    assert evaluate(replace(snap, **{which: obj}), Config()).reason == "FUTURE_DATA"


@pytest.mark.parametrize("book_name", ["up_book", "down_book"])
@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"asks": ()}, "MISSING_BOOK_SIDE"),
        ({"bids": ()}, "MISSING_BOOK_SIDE"),
        ({"bids": (Level(D(".99"), D("10")),)}, "CROSSED_BOOK"),
        ({"token_id": "wrong"}, "BOOK_TOKEN_MISMATCH"),
    ],
)
def test_invalid_either_outcome_book_rejected(book_name, changes, reason):
    snap = make_snapshot()
    book = replace(getattr(snap, book_name), **changes)
    assert evaluate(replace(snap, **{book_name: book}), Config()).reason == reason


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"reference_price": None, "reference_status": "missing"}, "MISSING_REFERENCE"),
        ({"reference_status": "conflict"}, "REFERENCE_CONFLICT"),
        ({"settlement_source": "binance"}, "UNSUPPORTED_RULE"),
        ({"slug": f"btc-updown-5m-{START - 300}"}, "WRONG_ROUND"),
        ({"end_s": START + 600}, "WRONG_ROUND"),
        ({"active": False}, "MARKET_INACTIVE"),
        ({"accepting_orders": False}, "MARKET_NOT_ACCEPTING"),
    ],
)
def test_invalid_contract_rejected(changes, reason):
    snap = make_snapshot()
    assert (
        evaluate(replace(snap, market=replace(snap.market, **changes)), Config()).reason == reason
    )


def test_boundary_reference_requires_enabled_policy_and_exact_source_time():
    config = Config()
    snap = make_snapshot()
    snap = replace(snap, market=replace(snap.market, reference_status="boundary"))
    assert evaluate(snap, config).side is Side.UP
    disabled = replace(config, data=replace(config.data, allow_captured_anchor=False))
    assert evaluate(snap, disabled).reason == "BOUNDARY_REFERENCE_DISABLED"
    wrong = replace(snap, market=replace(snap.market, reference_timestamp_ms=START * 1000 + 1))
    assert evaluate(wrong, config).reason == "INVALID_REFERENCE_TIME"


def test_unknown_reference_status_cannot_construct_valid_market():
    snap = make_snapshot()
    with pytest.raises(ValueError):
        replace(snap.market, reference_status="unknown")


@pytest.mark.parametrize(
    "history_change", ["short", "long_gap", "consecutive_gap", "future", "repeated", "twap"]
)
def test_incomplete_or_invalid_spot_history_cannot_pass_warmup(history_change):
    snap = make_snapshot()
    history = snap.history
    if history_change == "short":
        history = history[-60:]
    elif history_change == "long_gap":
        history = tuple(p for p in history if not NOW - 100_000 < p.timestamp_ms < NOW - 39_000)
    elif history_change == "consecutive_gap":
        history = history[:330] + history[333:]
    elif history_change == "future":
        history = history[:-1] + (replace(history[-1], timestamp_ms=NOW + 61_000),)
    elif history_change == "repeated":
        history = history[:-2] + (history[-1], history[-1])
    else:
        history = tuple(replace(p, kind="twap60") for p in history)
    assert evaluate(replace(snap, history=history), Config()).reason in {
        "INSUFFICIENT_HISTORY",
        "FUTURE_DATA",
        "INVALID_HISTORY",
    }


def test_variance_uses_actual_source_elapsed_not_grid_count():
    snap = make_snapshot()
    # First sample is 2 seconds before its grid; accepted span is therefore 1802 seconds.
    first = replace(snap.history[0], timestamp_ms=snap.history[0].timestamp_ms - 2000)
    decision = evaluate(replace(snap, history=(first,) + snap.history[1:]), Config())
    assert decision.side is Side.UP
    assert decision.features["long_span_seconds"] == 1802
    assert decision.features["long_sigma"] == pytest.approx(math.sqrt(9000 / 1802))


def test_model_horizon_uses_spot_source_time_not_receive_time():
    snap = make_snapshot(move=D("30"))
    fresh = evaluate(snap, Config())
    stale_spot = replace(snap.spot, timestamp_ms=NOW - 5000)
    earlier = replace(
        snap.history[0],
        timestamp_ms=NOW - 1_805_000,
        received_ms=NOW - 1_805_000,
        price=snap.history[0].price - D("5"),
    )
    old = evaluate(replace(snap, spot=stale_spot, history=(earlier,) + snap.history), Config())
    assert old.features["model_tau_seconds"] == 125
    assert old.probability_up is not None and fresh.probability_up is not None
    assert old.probability_up < fresh.probability_up


def test_zero_variance_rejects_unjustified_certainty():
    snap = make_snapshot()
    history = tuple(replace(p, price=snap.spot.price) for p in snap.history)
    assert evaluate(replace(snap, history=history), Config()).reason == "ZERO_VARIANCE"


def test_wide_unselected_spread_does_not_reject_selected_side():
    snap = make_snapshot()
    down = replace(snap.down_book, bids=(Level(D(".01"), D("100")),))
    assert evaluate(replace(snap, down_book=down), Config()).side is Side.UP


def test_selected_side_spread_limit_consumed():
    snap = make_snapshot()
    up = replace(snap.up_book, bids=(Level(D(".60"), D("100")),))
    assert evaluate(replace(snap, up_book=up), Config()).reason == "SPREAD_TOO_WIDE"


def test_insufficient_full_cash_depth_rejects_entry():
    snap = make_snapshot()
    up = replace(snap.up_book, asks=(Level(D(".70"), D("1")),))
    assert evaluate(replace(snap, up_book=up), Config()).reason == "INSUFFICIENT_DEPTH"


def test_rounded_limit_must_stay_in_value_ask_band():
    snap = make_snapshot(ask=D(".92"))
    assert evaluate(snap, Config()).price_limit == D(".92")
    assert evaluate(make_snapshot(ask=D(".93")), Config()).reason == "PRICE_BAND"


def test_value_scenario_floor_can_reject_central_probability_candidate():
    snap = make_snapshot(move=D("15"))
    decision = evaluate(snap, Config())
    assert decision.side is None
    assert decision.reason == "INSUFFICIENT_TERMINAL_SURPLUS"
    assert decision.probability_up is not None
    assert decision.probability_up > 0.7
    assert decision.scenario_floor is not None
    assert decision.scenario_floor < 0.7


@pytest.mark.parametrize("seconds,eligible", [(59, False), (60, True), (180, True), (181, False)])
def test_entry_window_inclusive_and_excludes_ending_average(seconds, eligible):
    snap = make_snapshot(now_ms=(START + 300 - seconds) * 1000)
    decision = evaluate(snap, Config())
    assert (decision.side is not None) is eligible
    if not eligible:
        assert decision.reason == "ENTRY_WINDOW"


def test_down_value_uses_actual_down_book():
    snap = make_snapshot(move=D("-200"))
    down = replace(
        snap.down_book, bids=(Level(D(".68"), D("100")),), asks=(Level(D(".70"), D("100")),)
    )
    decision = evaluate(replace(snap, down_book=down), Config())
    assert decision.side is Side.DOWN
    assert decision.probability_up is not None
    assert decision.probability_up < 0.001
    assert decision.scenario_floor is not None
    assert decision.scenario_floor > 0.99


def test_momentum_uses_explicit_move_ask_and_timing_settings_with_shared_safety():
    config = Config()
    config = replace(config, strategy=replace(config.strategy, mode="momentum"))
    assert evaluate(make_snapshot(move=D("70")), config).side is Side.UP
    assert evaluate(make_snapshot(move=D("69.99")), config).reason == "MOMENTUM_MOVE"
    assert evaluate(make_snapshot(ask=D(".69")), config).reason == "PRICE_BAND"
    assert evaluate(make_snapshot(now_ms=(START + 220) * 1000), config).reason == "ENTRY_WINDOW"
    snap = make_snapshot()
    assert evaluate(replace(snap, history=()), config).reason == "INSUFFICIENT_HISTORY"


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: PricePoint("spot", NOW, NOW, D("NaN")),
        lambda: PricePoint("bogus", NOW, NOW, D("1")),  # type: ignore[arg-type]
        lambda: Level(D(".7"), D("Infinity")),
        lambda: Level(D("-.1"), D("1")),
    ],
)
def test_domain_rejects_nonfinite_and_invalid_values(constructor):
    with pytest.raises(ValueError):
        constructor()


def test_pinned_sdk_protected_buy_minimum_vector():
    config = Config()
    config = replace(config, risk=replace(config.risk, trade_budget_usd=D("5.25")))
    decision = evaluate(make_snapshot(ask=D(".91")), config)
    assert decision.side is Side.UP
    assert decision.buy_principal == D("4.90")
    assert decision.price_limit == D(".92")
    assert decision.minimum_receive_shares == D("5.3261")


def test_nondecimal_tick_rounds_to_actual_multiple():
    snap = make_snapshot(ask=D(".701"))
    snap = replace(snap, market=replace(snap.market, tick_size=D(".0025")))
    decision = evaluate(snap, Config())
    assert decision.side is Side.UP
    assert decision.price_limit == D(".7125")
    assert decision.minimum_receive_shares == D("6.554386")


def test_depth_fee_uses_each_consumed_price():
    snap = make_snapshot()
    book = replace(snap.up_book, asks=(Level(D(".70"), D("2")), Level(D(".705"), D("100"))))
    decision = evaluate(replace(snap, up_book=book), Config())
    assert decision.side is Side.UP
    assert decision.estimated_buy_fee == D(".0969255")


def test_both_variance_windows_and_larger_sigma_stress_are_used():
    snap = make_snapshot(move=D("20"))
    history = tuple(
        replace(
            p,
            price=snap.spot.price - (D("10") if i < 300 else D("5")) if i % 2 else snap.spot.price,
        )
        for i, p in enumerate(snap.history)
    )
    decision = evaluate(replace(snap, history=history), Config())
    assert decision.features["short_sigma"] == pytest.approx(math.sqrt(5))
    assert decision.features["long_sigma"] == pytest.approx(math.sqrt(17.5))
    assert decision.features["stress_sigma"] == pytest.approx(math.sqrt(17.5) * 1.25)
    assert decision.scenario_floor == pytest.approx(0.5847, abs=0.0001)


def test_future_observation_within_clock_tolerance_does_not_fill_missing_grid():
    snap = make_snapshot()
    history = snap.history[:-1] + (replace(snap.history[-1], timestamp_ms=NOW + 1000),)
    assert evaluate(replace(snap, history=history), Config()).reason == "INSUFFICIENT_HISTORY"


def test_grid_discards_overage_observation_and_honors_tighter_gap_limit():
    snap = make_snapshot()
    too_old = replace(snap.history[330], timestamp_ms=snap.history[330].timestamp_ms - 2001)
    history = snap.history[:330] + (too_old,) + snap.history[331:]
    decision = evaluate(replace(snap, history=history), Config())
    assert decision.side is Side.UP
    assert decision.features["short_sample_count"] == 60
    smaller_gap = replace(Config(), data=replace(Config().data, max_sample_gap_ms=6000))
    delayed = replace(snap.history[330], timestamp_ms=snap.history[330].timestamp_ms - 2000)
    history = snap.history[:330] + (delayed,) + snap.history[331:]
    relaxed = evaluate(replace(snap, history=history), smaller_gap)
    assert relaxed.features["short_irregular_seconds"] == 7
    strict = replace(smaller_gap, data=replace(smaller_gap.data, min_sample_coverage=D(1)))
    assert evaluate(replace(snap, history=history), strict).reason == "INSUFFICIENT_HISTORY"


def test_stale_received_time_rejects_even_when_source_is_fresh():
    snap = make_snapshot()
    assert (
        evaluate(
            replace(snap, up_book=replace(snap.up_book, received_ms=NOW - 5001)), Config()
        ).reason
        == "STALE_DATA"
    )


def test_incomplete_official_anchor_and_nonboolean_market_flags_fail_closed():
    snap = make_snapshot()
    assert (
        evaluate(replace(snap, market=replace(snap.market, reference_source=None)), Config()).reason
        == "MISSING_REFERENCE"
    )
    with pytest.raises(ValueError):
        replace(snap.market, active=None)


def test_decision_rejects_nonfinite_or_underreserved_cash():
    decision = evaluate(make_snapshot(), Config())
    with pytest.raises(ValueError):
        replace(decision, buy_principal=D("NaN"))
    with pytest.raises(ValueError):
        replace(decision, max_total_reserved=D("1"))
    with pytest.raises(ValueError):
        replace(decision, probability_up=float("nan"))


@pytest.mark.parametrize("failure", ["stress_overflow", "horizon_overflow", "variance_overflow"])
def test_model_overflow_returns_finite_nonentry_decision(failure):
    snap = make_snapshot()
    config = Config()
    if failure == "stress_overflow":
        # Both factors are finite, but sqrt(5) * 1e308 is not.
        config = replace(
            config, strategy=replace(config.strategy, volatility_stress_multiplier=D("1e308"))
        )
    elif failure == "horizon_overflow":
        # Stressed sigma stays finite, but sigma * sqrt(model_tau-40) overflows.
        config = replace(
            config, strategy=replace(config.strategy, volatility_stress_multiplier=D("1e307"))
        )
    else:
        # Finite source prices overflow squared-dollar float variance.
        snap = replace(
            snap,
            history=tuple(
                replace(point, price=D("1e155") if i % 2 else D("1"))
                for i, point in enumerate(snap.history)
            ),
        )
    decision = evaluate(snap, config)
    assert decision.reason == "INVALID_MODEL"
    assert decision.side is None
    assert decision.buy_principal == 0
    assert decision.max_total_reserved == 0
    assert decision.probability_up is None
    assert decision.scenario_floor is None
    assert all(
        isinstance(value, str) or math.isfinite(value) for value in decision.features.values()
    )


def test_isolated_missing_grid_uses_actual_change_and_elapsed_with_coverage():
    snap = make_snapshot()
    history = snap.history[:330] + snap.history[331:]
    decision = evaluate(replace(snap, history=history), Config())
    assert decision.side is Side.UP
    # The omitted alternating point removes two $5 changes, replacing them with a zero change.
    assert decision.features["short_sigma"] == pytest.approx(math.sqrt(1450 / 300))
    assert decision.features["long_sigma"] == pytest.approx(math.sqrt(8950 / 1800))
    assert decision.features["short_span_seconds"] == 300
    assert decision.features["long_span_seconds"] == 1800
    assert decision.features["short_sample_count"] == 60
    assert decision.features["long_sample_count"] == 360
    assert decision.features["short_sample_coverage"] == pytest.approx(60 / 61)
    assert decision.features["long_sample_coverage"] == pytest.approx(360 / 361)


def test_complete_grid_keeps_original_math_and_reports_full_coverage():
    decision = evaluate(make_snapshot(), Config())
    assert decision.side is Side.UP
    assert decision.features["short_sigma"] == pytest.approx(math.sqrt(5))
    assert decision.features["long_sigma"] == pytest.approx(math.sqrt(5))
    assert decision.features["short_sample_coverage"] == 1
    assert decision.features["long_sample_coverage"] == 1


@pytest.mark.parametrize("window", ["short", "long"])
def test_missing_grid_coverage_rejects_even_with_bounded_individual_gaps(window):
    snap = make_snapshot()
    # Every missing point is isolated, so each accepted-sample gap stays at 10 seconds.
    missing = {310, 320, 330, 340} if window == "short" else set(range(10, 191, 10))
    history = tuple(point for i, point in enumerate(snap.history) if i not in missing)
    assert evaluate(replace(snap, history=history), Config()).reason == "INSUFFICIENT_HISTORY"


def test_coverage_setting_is_consumed_and_can_require_stricter_windows():
    snap = make_snapshot()
    history = snap.history[:330] + snap.history[331:]
    snap = replace(snap, history=history)
    config = Config()
    assert evaluate(snap, config).side is Side.UP
    stricter = replace(config, data=replace(config.data, min_sample_coverage=D(".99")))
    assert evaluate(snap, stricter).reason == "INSUFFICIENT_HISTORY"


@pytest.mark.parametrize("endpoint", ["first", "last"])
def test_missing_endpoint_rejects_despite_enough_coverage(endpoint):
    snap = make_snapshot()
    history = snap.history[1:] if endpoint == "first" else snap.history[:-1]
    assert evaluate(replace(snap, history=history), Config()).reason == "INSUFFICIENT_HISTORY"


def test_endpoint_with_two_second_shortfall_is_accepted():
    snap = make_snapshot()
    final = replace(snap.history[-1], timestamp_ms=NOW - 2000)
    decision = evaluate(replace(snap, history=snap.history[:-1] + (final,)), Config())
    assert decision.side is Side.UP
    assert decision.features["short_span_seconds"] == 298
    assert decision.features["long_span_seconds"] == 1798


def test_one_missing_grid_permits_exact_twelve_second_source_gap():
    snap = make_snapshot()
    previous = replace(snap.history[329], timestamp_ms=snap.history[329].timestamp_ms - 2000)
    history = snap.history[:329] + (previous,) + snap.history[331:]
    assert evaluate(replace(snap, history=history), Config()).side is Side.UP


def test_two_missing_grids_fit_a_bounded_irregular_interval():
    snap = make_snapshot()
    following = replace(snap.history[332], timestamp_ms=snap.history[332].timestamp_ms - 2000)
    history = snap.history[:330] + (following,) + snap.history[333:]
    result = evaluate(replace(snap, history=history), Config())
    assert result.side is Side.UP
    assert result.features["short_irregular_seconds"] == 13
    assert result.features["short_regular_time_coverage"] == pytest.approx(287 / 300)


@pytest.mark.parametrize(
    "missing,window,reason,count,span,max_gap",
    [
        (set(range(361)), "long", "INSUFFICIENT_SAMPLES", 0, 0, 0),
        ({0}, "long", "MISSING_START", 360, 1795, 5000),
        ({360}, "long", "MISSING_END", 360, 1795, 5000),
        ({330, 331, 332}, "short", "INSUFFICIENT_INTERVAL_COVERAGE", 58, 300, 20000),
        ({310, 320, 330, 340}, "short", "INSUFFICIENT_COVERAGE", 57, 300, 10000),
    ],
)
def test_rejected_sampling_retains_finite_measured_diagnostics(
    missing, window, reason, count, span, max_gap
):
    snap = make_snapshot()
    history = tuple(point for i, point in enumerate(snap.history) if i not in missing)
    decision = evaluate(replace(snap, history=history), Config())
    assert decision.reason == "INSUFFICIENT_HISTORY"
    assert decision.features[f"{window}_sampling_status"] == reason
    assert decision.features[f"{window}_sample_count"] == count
    assert decision.features[f"{window}_span_seconds"] == span
    assert decision.features[f"{window}_max_sample_gap_ms"] == max_gap
    assert decision.features[f"{window}_sample_coverage"] == pytest.approx(
        count / (61 if window == "short" else 361)
    )
    assert all(
        isinstance(value, str) or math.isfinite(value) for value in decision.features.values()
    )


@pytest.mark.parametrize("old_gap", [False, True])
def test_fifteen_second_gap_keeps_observed_jump_and_usable_history(old_gap):
    snap = make_snapshot()
    begin = 100 if old_gap else 330
    history = tuple(
        replace(point, price=point.price + (D(100) if i > begin + 1 else D(0)))
        for i, point in enumerate(snap.history)
        if i not in (begin, begin + 1)
    )
    result = evaluate(replace(snap, history=history), Config())
    assert result.reason != "INSUFFICIENT_HISTORY"
    for window in ("short", "long"):
        assert result.features[f"{window}_sampling_status"] == "VALID"
    selected = [p for p in history if p.timestamp_ms >= NOW - 1800000]
    expected = math.sqrt(
        sum(float(b.price - a.price) ** 2 for a, b in zip(selected, selected[1:], strict=False))
        / 1800
    )
    assert result.features["long_sigma"] == expected
    assert result.features["long_irregular_seconds"] == 15
    assert result.features["long_regular_time_coverage"] == pytest.approx(1785 / 1800)
    if not old_gap:
        assert result.features["short_regular_time_coverage"] == 0.95
        assert result.features["short_effective_increments"] == pytest.approx(54.54545454545)


def test_large_old_outage_exceeds_long_interval_budget_despite_sample_count():
    snap = make_snapshot()
    history = tuple(p for i, p in enumerate(snap.history) if i not in range(100, 118))
    result = evaluate(replace(snap, history=history), Config())
    assert result.reason == "INSUFFICIENT_HISTORY"
    assert result.features["short_sampling_status"] == "VALID"
    assert result.features["long_sample_coverage"] > 0.95
    assert result.features["long_sampling_status"] == "INSUFFICIENT_INTERVAL_COVERAGE"
    assert result.features["long_irregular_seconds"] == 95
