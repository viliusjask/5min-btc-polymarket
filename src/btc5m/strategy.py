"""Pure terminal-probability screening, not expected return under the exit policy."""

import math
from bisect import bisect_right
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from statistics import NormalDist

from btc5m.config import PAIR_STRATEGIES, Config, strategy_for_round
from btc5m.domain import (
    Book,
    Decision,
    PricePoint,
    Side,
    Snapshot,
    require_decimal,
    require_integer,
)

SETTLEMENT_SOURCE = "https://data.chain.link/streams/btc-usd-twap-60s-streams"
# Pinned SDK 0.9.0 context._ROUNDING_BY_TICK: protected BUY requested-amount precision.
_AMOUNT_DECIMALS = {
    Decimal(".1"): 3,
    Decimal(".01"): 4,
    Decimal(".005"): 5,
    Decimal(".0025"): 6,
    Decimal(".001"): 5,
    Decimal(".0001"): 6,
}
_ZERO = Decimal(0)
SAMPLING_POLICY = "BOUNDED_INTERVALS_V1"


def fee_for(shares: Decimal, price: Decimal, rate: Decimal, exponent: int = 1) -> Decimal:
    """Cash fee at an executed price, before any venue-specific receipt rounding."""
    for value, name in ((shares, "shares"), (price, "price"), (rate, "rate")):
        require_decimal(value, name)
    require_integer(exponent, "exponent", positive=True)
    if price > 1 or rate > 1:
        raise ValueError("price and fee rate must not exceed one")
    return shares * rate * (price * (1 - price)) ** exponent


def terminal_probability_up(spot: Decimal, reference: Decimal, sigma: float, tau: float) -> float:
    """Zero-drift normal probability for a future sixty-second arithmetic average.

    sigma is raw dollars/sqrt(second); tau is seconds from spot source time to expiry.
    This approximation is supported only before the entire ending average starts.
    """
    require_decimal(spot, "spot", positive=True)
    require_decimal(reference, "reference", positive=True)
    if not math.isfinite(sigma) or sigma <= 0 or not math.isfinite(tau) or tau < 60:
        raise ValueError("invalid volatility or model horizon")
    delta = float(spot - reference)
    denominator = sigma * math.sqrt(tau - 40)
    if not math.isfinite(delta) or not math.isfinite(denominator):
        raise ValueError("nonfinite probability inputs")
    return NormalDist().cdf(delta / denominator)


def _skip(
    snapshot: Snapshot,
    reason: str,
    features: dict[str, float | str],
    probability_up: float | None = None,
    floor: float | None = None,
    surplus: Decimal | None = None,
) -> Decision:
    return Decision(
        snapshot.market.slug,
        None,
        reason,
        None,
        _ZERO,
        _ZERO,
        _ZERO,
        _ZERO,
        _ZERO,
        probability_up,
        floor,
        surplus,
        dict(features),
    )


def _safety_reason(snapshot: Snapshot, config: Config) -> str | None:
    market, data = snapshot.market, config.data
    if market.settlement_source != SETTLEMENT_SOURCE:
        return "UNSUPPORTED_RULE"
    current_start = (snapshot.now_ms // 1000 // 300) * 300
    if (
        market.slug != f"btc-updown-5m-{market.start_s}"
        or market.start_s != current_start
        or market.end_s - market.start_s != 300
    ):
        return "WRONG_ROUND"
    if not market.active:
        return "MARKET_INACTIVE"
    if not market.accepting_orders:
        return "MARKET_NOT_ACCEPTING"
    if market.reference_status == "conflict":
        return "REFERENCE_CONFLICT"
    if (
        market.reference_status == "missing"
        or market.reference_price is None
        or not market.reference_source
    ):
        return "MISSING_REFERENCE"
    if market.reference_status == "boundary" and not data.allow_captured_anchor:
        return "BOUNDARY_REFERENCE_DISABLED"
    if (
        market.reference_timestamp_ms is not None
        and market.reference_timestamp_ms != market.start_s * 1000
    ) or (market.reference_status == "boundary" and market.reference_timestamp_ms is None):
        return "INVALID_REFERENCE_TIME"
    if market.tick_size not in _AMOUNT_DECIMALS:
        return "UNSUPPORTED_TICK"
    if market.metadata_received_ms > snapshot.now_ms + data.future_tolerance_ms:
        return "FUTURE_DATA"
    for observation, age_limit in (
        (snapshot.spot, data.max_price_age_ms),
        (snapshot.twap60, data.max_price_age_ms),
        (snapshot.up_book, data.max_book_age_ms),
        (snapshot.down_book, data.max_book_age_ms),
    ):
        if (
            max(observation.timestamp_ms, observation.received_ms)
            > snapshot.now_ms + data.future_tolerance_ms
        ):
            return "FUTURE_DATA"
        if min(observation.timestamp_ms, observation.received_ms) < snapshot.now_ms - age_limit:
            return "STALE_DATA"
    for side, book in ((Side.UP, snapshot.up_book), (Side.DOWN, snapshot.down_book)):
        if book.token_id != market.token(side):
            return "BOOK_TOKEN_MISMATCH"
        if not book.bids or not book.asks:
            return "MISSING_BOOK_SIDE"
        if book.bids[0].price >= book.asks[0].price:
            return "CROSSED_BOOK"
    return None


@dataclass(frozen=True)
class _SampleWindow:
    sigma: float | None
    span_seconds: float
    sample_count: int
    requested_count: int
    coverage: float
    max_gap_ms: int
    rejection: str | None
    regular_time_coverage: float = 0.0
    irregular_seconds: float = 0.0
    effective_increments: float = 0.0


def _sample_window(
    history: tuple[PricePoint, ...], source_end_ms: int, window_seconds: int, config: Config
) -> _SampleWindow:
    """Measure available distinct UTC-grid samples; never fill a missing observation."""
    data = config.data
    step_ms = data.sample_seconds * 1000
    end_grid = source_end_ms // step_ms * step_ms
    start_grid = end_grid - window_seconds * 1000
    times = [point.timestamp_ms for point in history]
    samples: list[PricePoint] = []
    for grid in range(start_grid, end_grid + 1, step_ms):
        index = bisect_right(times, grid) - 1
        if index < 0:
            continue
        point = history[index]
        if grid - point.timestamp_ms > data.sample_tolerance_ms:
            continue
        if samples and point.timestamp_ms == samples[-1].timestamp_ms:
            continue
        samples.append(point)
    count = len(samples)
    requested = window_seconds // data.sample_seconds + 1
    elapsed = (samples[-1].timestamp_ms - samples[0].timestamp_ms) / 1000 if count >= 2 else 0.0
    gaps = [
        right.timestamp_ms - left.timestamp_ms
        for left, right in zip(samples, samples[1:], strict=False)
    ]
    total_ms = sum(gaps)
    irregular_ms = sum(gap for gap in gaps if gap > data.max_sample_gap_ms)
    result = _SampleWindow(
        None,
        elapsed,
        count,
        requested,
        count / requested,
        max(gaps, default=0),
        None,
        (total_ms - irregular_ms) / total_ms if total_ms else 0.0,
        irregular_ms / 1000,
        total_ms**2 / sum(gap**2 for gap in gaps) if total_ms else 0.0,
    )
    if count < 2:
        return replace(result, rejection="INSUFFICIENT_SAMPLES")
    if samples[0].timestamp_ms > start_grid:
        return replace(result, rejection="MISSING_START")
    if samples[-1].timestamp_ms < end_grid - data.sample_tolerance_ms:
        return replace(result, rejection="MISSING_END")
    if elapsed < window_seconds - data.sample_tolerance_ms / 1000:
        return replace(result, rejection="INSUFFICIENT_SPAN")
    if Decimal(count) < data.min_sample_coverage * requested:
        return replace(result, rejection="INSUFFICIENT_COVERAGE")
    # A single delayed interval must not veto an otherwise usable half-hour.
    # Bound the total time in intervals above the normal-gap threshold using
    # the same completeness requirement as point coverage. Keep ALL observed
    # endpoint changes below: dropping gap returns would discard observed jumps.
    if Decimal(irregular_ms) > (1 - data.min_sample_coverage) * total_ms:
        return replace(result, rejection="INSUFFICIENT_INTERVAL_COVERAGE")
    # A gap contributes the actual endpoint change over its actual elapsed time.
    # Decimal subtraction retains source precision; only variance math uses float.
    try:
        changes = [
            float(right.price - left.price)
            for left, right in zip(samples, samples[1:], strict=False)
        ]
        variance_rate = math.fsum(change * change for change in changes) / elapsed
        if not math.isfinite(variance_rate):
            return replace(result, rejection="INVALID_VARIANCE")
    except (ValueError, OverflowError):
        return replace(result, rejection="INVALID_VARIANCE")
    return replace(result, sigma=math.sqrt(variance_rate))


def _quote(
    snapshot: Snapshot,
    config: Config,
    side: Side,
    book: Book,
    probability_up: float,
    floor: float,
    features: dict[str, float | str],
) -> Decision:
    market, strategy = snapshot.market, config.strategy
    features = dict(features)
    features["evaluated_side"] = side.value
    features["scenario_floor"] = floor
    if book.asks[0].price - book.bids[0].price > strategy.max_spread:
        return _skip(snapshot, "SPREAD_TOO_WIDE", features, probability_up, floor)
    minimum_ask, maximum_ask = (
        (strategy.value_min_ask, strategy.value_max_ask)
        if strategy.mode != "momentum"
        else (strategy.momentum_min_ask, strategy.momentum_max_ask)
    )
    if not minimum_ask <= book.asks[0].price <= maximum_ask:
        return _skip(snapshot, "PRICE_BAND", features, probability_up, floor)

    # For exponent>=1, fee/cash = rate*p**(e-1)*(1-p)**e <= rate.
    # This reserve stays safe if lower asks deliver extra shares, and does not spend expected VWAP.
    principal = (config.risk.trade_budget_usd / (1 + market.fee_rate)).quantize(
        Decimal(".01"), rounding=ROUND_DOWN
    )
    reserved_fee = principal * market.fee_rate
    reserved = principal + reserved_fee
    if principal <= 0:
        return _skip(snapshot, "BELOW_MINIMUM_SIZE", features, probability_up, floor)
    remaining = principal
    shares, buy_fee, last_price = _ZERO, _ZERO, _ZERO
    for level in book.asks:
        cash = min(remaining, level.price * level.size)
        quantity = cash / level.price
        shares += quantity
        buy_fee += fee_for(quantity, level.price, market.fee_rate, market.fee_exponent)
        remaining -= cash
        last_price = level.price
        if remaining == 0:
            break
    if remaining > 0:
        return _skip(snapshot, "INSUFFICIENT_DEPTH", features, probability_up, floor)
    limit = ((last_price + config.execution.buy_slippage) / market.tick_size).to_integral_value(
        rounding=ROUND_CEILING
    ) * market.tick_size
    if limit > maximum_ask or limit > 1 - market.tick_size:
        return _skip(snapshot, "PRICE_BAND", features, probability_up, floor)
    # Protected SDK BUY ceilings the requested shares, never worsening the signed cash/share cap.
    quantum = Decimal(10) ** -_AMOUNT_DECIMALS[market.tick_size]
    minimum_receive = (principal / limit).quantize(quantum, rounding=ROUND_CEILING)
    if minimum_receive < market.min_order_size or shares < minimum_receive:
        return _skip(snapshot, "BELOW_MINIMUM_SIZE", features, probability_up, floor)
    average_ask = principal / shares
    buy_fee_per_share = buy_fee / shares
    sell_fee_reserve = market.fee_rate * Decimal(".25") ** market.fee_exponent
    surplus = (
        Decimal(str(floor))
        - average_ask
        - buy_fee_per_share
        - sell_fee_reserve
        - strategy.extra_price_allowance
    )
    features.update(
        {
            "expected_ask_per_share": str(average_ask),
            "estimated_buy_fee_per_share": str(buy_fee_per_share),
            "sell_fee_reserve_per_share": str(sell_fee_reserve),
            "extra_price_allowance_per_share": str(strategy.extra_price_allowance),
            "reserved_buy_fee": str(reserved_fee),
            "selected_spread": str(book.asks[0].price - book.bids[0].price),
            "terminal_surplus_proxy_units": "USD/share; uncalibrated terminal screen, not stopped-policy return",
        }
    )
    if strategy.mode != "momentum" and surplus <= strategy.min_terminal_surplus:
        return _skip(
            snapshot, "INSUFFICIENT_TERMINAL_SURPLUS", features, probability_up, floor, surplus
        )
    return Decision(
        snapshot.market.slug,
        side,
        "ENTRY",
        limit,
        principal,
        reserved,
        shares,
        minimum_receive,
        buy_fee,
        probability_up,
        floor,
        surplus,
        features,
    )


class FastReferenceError(ValueError):
    pass


def fast_reference(snapshot: Snapshot, config: Config) -> tuple[PricePoint, dict[str, float | str]]:
    """Bridge the observed Chainlink value using a timestamp-aligned exchange return."""
    points = snapshot.exchange_history
    if not points:
        raise FastReferenceError("FAST_MISSING")
    now, limits = snapshot.now_ms, config.experiments
    if any(
        max(p.timestamp_ms, p.received_ms) > now + config.data.future_tolerance_ms for p in points
    ):
        raise FastReferenceError("FAST_FUTURE")
    points = tuple(sorted(points, key=lambda p: p.timestamp_ms))
    latest = points[-1]
    if any(
        now - stamp > limits.fast_max_age_ms for stamp in (latest.timestamp_ms, latest.received_ms)
    ):
        raise FastReferenceError("FAST_STALE")
    aligned = [p for p in points if p.timestamp_ms <= snapshot.spot.timestamp_ms]
    if (
        not aligned
        or snapshot.spot.timestamp_ms - aligned[-1].timestamp_ms > limits.fast_alignment_ms
    ):
        raise FastReferenceError("FAST_UNALIGNED")
    if latest.timestamp_ms <= snapshot.spot.timestamp_ms:
        raise FastReferenceError("FAST_NOT_AHEAD")
    base = aligned[-1]
    change = latest.price / base.price - 1
    if abs(change) * 10000 > limits.fast_max_move_bps:
        raise FastReferenceError("FAST_MOVE_GUARD")
    return PricePoint(
        "spot",
        latest.timestamp_ms,
        max(latest.received_ms, snapshot.spot.received_ms),
        snapshot.spot.price * (1 + change),
    ), {
        "exchange_source": "binance:BTCUSDT:aggTrade",
        "exchange_source_ms": str(latest.timestamp_ms),
        "exchange_received_ms": str(latest.received_ms),
        "exchange_anchor_ms": str(base.timestamp_ms),
        "exchange_return": str(change),
        "chainlink_source_ms": str(snapshot.spot.timestamp_ms),
        "fast_reference_price": str(snapshot.spot.price * (1 + change)),
    }


def conditional_probability_up(
    spot: Decimal, reference: Decimal, sigma: float, tau: float, realized_integral: Decimal = _ZERO
) -> float:
    """Conditional final-60s average under the same arithmetic Brownian approximation.

    The realized integral has USD-second units. Inside the average, only the future
    part is random: variance = sigma**2 * tau**3 / (3 * 60**2).
    """
    if tau >= 60:
        return terminal_probability_up(spot, reference, sigma, tau)
    require_decimal(spot, "spot", positive=True)
    require_decimal(reference, "reference", positive=True)
    require_decimal(realized_integral, "realized_integral")
    if not math.isfinite(tau) or tau <= 0 or not math.isfinite(sigma) or sigma <= 0:
        raise ValueError("invalid conditional horizon or volatility")
    mean = (realized_integral + spot * Decimal(str(tau))) / 60
    deviation = sigma * math.sqrt(tau**3 / 3) / 60
    return NormalDist().cdf(float(mean - reference) / deviation)


def _realized_integral(snapshot: Snapshot, end_ms: int, config: Config) -> Decimal:
    start = (snapshot.market.end_s - 60) * 1000
    if end_ms <= start:
        return _ZERO
    # This numerical integration is a model approximation, never a settlement price.
    points = sorted(
        (p for p in snapshot.history if p.timestamp_ms <= end_ms), key=lambda p: p.timestamp_ms
    )
    previous = next((p for p in reversed(points) if p.timestamp_ms <= start), None)
    gap = config.experiments.averaging_max_gap_ms
    if previous is None or start - previous.timestamp_ms > gap:
        raise ValueError("AVERAGING_HISTORY_GAP")
    total, cursor = _ZERO, start
    for point in points:
        if point.timestamp_ms <= start:
            continue
        if point.timestamp_ms - previous.timestamp_ms > gap:
            raise ValueError("AVERAGING_HISTORY_GAP")
        total += previous.price * Decimal(point.timestamp_ms - cursor) / 1000
        cursor, previous = point.timestamp_ms, point
    if end_ms - previous.timestamp_ms > gap:
        raise ValueError("AVERAGING_HISTORY_GAP")
    return total + previous.price * Decimal(end_ms - cursor) / 1000


@dataclass(frozen=True)
class FairValue:
    reason: str
    probability_up: float | None
    floors: dict[Side, float]
    features: dict[str, float | str]
    ceilings: dict[Side, float]


def fair_value(snapshot: Snapshot, config: Config) -> FairValue:
    """Shared probability and sensitivity scenarios, usable during the ending average."""
    strategy, data, market = config.strategy, config.data, snapshot.market
    point = snapshot.spot
    features: dict[str, float | str] = {
        "mode": strategy.mode,
        "sampling_policy": SAMPLING_POLICY,
        "required_history_coverage": str(data.min_sample_coverage),
        "config_hash": config.fingerprint,
        "entry_tau_seconds": (market.end_s * 1000 - snapshot.now_ms) / 1000,
        "model_tau_seconds": (market.end_s * 1000 - point.timestamp_ms) / 1000,
        "reference_status": market.reference_status,
        "reference_source": market.reference_source or "missing",
        "spot_source_ms": str(point.timestamp_ms),
        "spot_received_ms": str(point.received_ms),
    }

    def fail(reason: str) -> FairValue:
        return FairValue(reason, None, {}, dict(features), {})

    safety = _safety_reason(snapshot, config)
    if safety:
        return fail(safety)
    if strategy.mode == "fast_value":
        try:
            point, extra = fast_reference(snapshot, config)
            features.update(extra)
        except FastReferenceError as exc:
            return fail(str(exc))
    tau = (market.end_s * 1000 - point.timestamp_ms) / 1000
    features["model_tau_seconds"] = tau
    if tau <= 0:
        return fail("MODEL_HORIZON")
    if any(
        max(p.timestamp_ms, p.received_ms) > snapshot.now_ms + data.future_tolerance_ms
        for p in snapshot.history
    ):
        return fail("FUTURE_DATA")
    history = tuple(sorted(snapshot.history, key=lambda p: p.timestamp_ms))
    if any(p.kind != "spot" for p in history) or len({p.timestamp_ms for p in history}) != len(
        history
    ):
        return fail("INVALID_HISTORY")
    try:
        windows = [
            _sample_window(
                history, min(snapshot.spot.timestamp_ms, snapshot.now_ms), seconds, config
            )
            for seconds in (strategy.volatility_short_seconds, strategy.volatility_long_seconds)
        ]
        for label, window in zip(("short", "long"), windows, strict=True):
            features.update(
                {
                    f"{label}_span_seconds": window.span_seconds,
                    f"{label}_sample_count": window.sample_count,
                    f"{label}_requested_sample_count": window.requested_count,
                    f"{label}_sample_coverage": window.coverage,
                    f"{label}_max_sample_gap_ms": window.max_gap_ms,
                    f"{label}_regular_time_coverage": window.regular_time_coverage,
                    f"{label}_irregular_seconds": window.irregular_seconds,
                    f"{label}_effective_increments": window.effective_increments,
                    f"{label}_sampling_status": window.rejection or "VALID",
                }
            )
            if window.sigma is not None:
                features[f"{label}_sigma"] = window.sigma
        if any(w.rejection for w in windows):
            return fail(
                "INVALID_MODEL"
                if any(w.rejection == "INVALID_VARIANCE" for w in windows)
                else "INSUFFICIENT_HISTORY"
            )
        short, long = windows[0].sigma, windows[1].sigma
        assert short is not None and long is not None
        if short == 0 or long == 0:
            return fail("ZERO_VARIANCE")
        stress = max(short, long) * float(strategy.volatility_stress_multiplier)
        if not math.isfinite(stress):
            return fail("INVALID_MODEL")
        reference = market.reference_price
        assert reference is not None
        integral = _realized_integral(snapshot, point.timestamp_ms, config) if tau < 60 else _ZERO
        p = conditional_probability_up(point.price, reference, short, tau, integral)
        features.update(
            central_probability_down=1 - p,
            stress_sigma=stress,
            adverse_reference_usd=str(strategy.adverse_reference_usd),
            spot_reference_move_usd=str(point.price - reference),
        )
        if tau < 60:
            features.update(
                realized_integral_usd_seconds=str(integral),
                averaging_method="left-step integration of observed Chainlink points; not settlement evidence",
            )
        scenarios = [
            conditional_probability_up(point.price, reference + offset, sigma, tau, integral)
            for sigma in (short, long, stress)
            for offset in (-strategy.adverse_reference_usd, _ZERO, strategy.adverse_reference_usd)
        ]
        return FairValue(
            "VALID",
            p,
            {Side.UP: min(scenarios), Side.DOWN: 1 - max(scenarios)},
            dict(features),
            {Side.UP: max(scenarios), Side.DOWN: 1 - min(scenarios)},
        )
    except (ValueError, OverflowError) as exc:
        return fail(
            "AVERAGING_HISTORY_GAP" if str(exc) == "AVERAGING_HISTORY_GAP" else "INVALID_MODEL"
        )


def evaluate(snapshot: Snapshot, config: Config) -> Decision:
    """Return a real executable policy candidate or a visible rejection."""
    selected = strategy_for_round(config, snapshot.market.start_s)
    if selected != config.strategy.mode:
        config = replace(config, strategy=replace(config.strategy, mode=selected))
    if selected in PAIR_STRATEGIES:
        from btc5m.pairing import pair_decision

        return pair_decision(snapshot, config, ())
    strategy, market = config.strategy, snapshot.market
    # Preserve baseline rejection ordering and entry windows.
    features: dict[str, float | str] = {
        "mode": selected,
        "config_hash": config.fingerprint,
        "entry_tau_seconds": (market.end_s * 1000 - snapshot.now_ms) / 1000,
        "model_tau_seconds": (market.end_s * 1000 - snapshot.spot.timestamp_ms) / 1000,
        "reference_status": market.reference_status,
        "reference_source": market.reference_source or "missing",
        "spot_source_ms": str(snapshot.spot.timestamp_ms),
        "spot_received_ms": str(snapshot.spot.received_ms),
    }
    safety = _safety_reason(snapshot, config)
    if safety:
        return _skip(snapshot, safety, features)
    low, high = (
        (strategy.momentum_min_seconds, strategy.momentum_max_seconds)
        if selected == "momentum"
        else (strategy.entry_min_seconds, strategy.entry_max_seconds)
    )
    if not low <= float(features["entry_tau_seconds"]) <= high:
        return _skip(snapshot, "ENTRY_WINDOW", features)
    if float(features["model_tau_seconds"]) < 60:
        return _skip(snapshot, "MODEL_HORIZON", features)
    value = fair_value(snapshot, config)
    if value.reason != "VALID":
        return _skip(snapshot, value.reason, value.features)
    assert value.probability_up is not None and market.reference_price is not None
    move = Decimal(str(value.features["spot_reference_move_usd"]))
    preferred = Side.UP if move >= 0 else Side.DOWN
    if selected == "momentum" and abs(move) < strategy.momentum_min_move_usd:
        return _skip(snapshot, "MOMENTUM_MOVE", value.features, value.probability_up)
    sides = (
        (preferred,)
        if selected == "momentum"
        else (preferred, Side.DOWN if preferred is Side.UP else Side.UP)
    )
    decisions = [
        _quote(
            snapshot,
            config,
            side,
            snapshot.up_book if side is Side.UP else snapshot.down_book,
            value.probability_up,
            value.floors[side],
            value.features,
        )
        for side in sides
    ]
    eligible = [d for d in decisions if d.side is not None]
    if eligible:
        return max(
            eligible,
            key=lambda d: d.terminal_surplus_proxy
            if d.terminal_surplus_proxy is not None
            else Decimal("-Infinity"),
        )
    first = decisions[0]
    return (
        replace(first, features={**first.features, "other_side_reason": decisions[1].reason})
        if len(decisions) > 1
        else first
    )
