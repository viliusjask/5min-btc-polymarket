"""Pure terminal-probability screening, not expected return under the exit policy."""

import math
from bisect import bisect_right
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from statistics import NormalDist

from btc5m.config import Config
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
    result = _SampleWindow(
        None, elapsed, count, requested, count / requested, max(gaps, default=0), None
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
    if result.max_gap_ms > data.max_sample_gap_ms:
        return replace(result, rejection="EXCESSIVE_GAP")
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
        if strategy.mode == "value"
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
    if strategy.mode == "value" and surplus <= strategy.min_terminal_surplus:
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


def evaluate(snapshot: Snapshot, config: Config) -> Decision:
    """Return one deterministic candidate or a visible non-entry reason; perform no I/O."""
    strategy, data, market = config.strategy, config.data, snapshot.market
    entry_tau = (market.end_s * 1000 - snapshot.now_ms) / 1000
    model_tau = (market.end_s * 1000 - snapshot.spot.timestamp_ms) / 1000
    features: dict[str, float | str] = {
        "mode": strategy.mode,
        "config_hash": config.fingerprint,
        "entry_tau_seconds": entry_tau,
        "model_tau_seconds": model_tau,
        "reference_status": market.reference_status,
        "reference_source": market.reference_source or "missing",
        "spot_source_ms": str(snapshot.spot.timestamp_ms),
        "spot_received_ms": str(snapshot.spot.received_ms),
    }
    safety = _safety_reason(snapshot, config)
    if safety:
        return _skip(snapshot, safety, features)
    entry_min, entry_max = (
        (strategy.entry_min_seconds, strategy.entry_max_seconds)
        if strategy.mode == "value"
        else (strategy.momentum_min_seconds, strategy.momentum_max_seconds)
    )
    if not entry_min <= entry_tau <= entry_max:
        return _skip(snapshot, "ENTRY_WINDOW", features)
    if model_tau < 60:
        return _skip(snapshot, "MODEL_HORIZON", features)
    if any(
        max(p.timestamp_ms, p.received_ms) > snapshot.now_ms + data.future_tolerance_ms
        for p in snapshot.history
    ):
        return _skip(snapshot, "FUTURE_DATA", features)
    history = tuple(sorted(snapshot.history, key=lambda point: point.timestamp_ms))
    if any(p.kind != "spot" for p in history) or len({p.timestamp_ms for p in history}) != len(
        history
    ):
        return _skip(snapshot, "INVALID_HISTORY", features)
    try:
        short = _sample_window(
            history,
            min(snapshot.spot.timestamp_ms, snapshot.now_ms),
            strategy.volatility_short_seconds,
            config,
        )
        long = _sample_window(
            history,
            min(snapshot.spot.timestamp_ms, snapshot.now_ms),
            strategy.volatility_long_seconds,
            config,
        )
        for label, window in (("short", short), ("long", long)):
            features.update(
                {
                    f"{label}_span_seconds": window.span_seconds,
                    f"{label}_sample_count": window.sample_count,
                    f"{label}_requested_sample_count": window.requested_count,
                    f"{label}_sample_coverage": window.coverage,
                    f"{label}_max_sample_gap_ms": window.max_gap_ms,
                    f"{label}_sampling_status": window.rejection or "VALID",
                }
            )
            if window.sigma is not None:
                features[f"{label}_sigma"] = window.sigma
        if short.rejection or long.rejection:
            reason = (
                "INVALID_MODEL"
                if "INVALID_VARIANCE" in (short.rejection, long.rejection)
                else "INSUFFICIENT_HISTORY"
            )
            return _skip(snapshot, reason, features)
        assert short.sigma is not None and long.sigma is not None
        if short.sigma == 0 or long.sigma == 0:
            return _skip(snapshot, "ZERO_VARIANCE", features)
        stress = max(short.sigma, long.sigma) * float(strategy.volatility_stress_multiplier)
        if not math.isfinite(stress):
            raise ValueError("nonfinite stressed volatility")
        sigmas = (short.sigma, long.sigma, stress)
        reference = market.reference_price
        assert reference is not None  # The common safety gate already rejects missing references.
        probability_up = terminal_probability_up(
            snapshot.spot.price, reference, short.sigma, model_tau
        )
        features["central_probability_down"] = 1 - probability_up
        features["stress_sigma"] = stress
        features["adverse_reference_usd"] = str(strategy.adverse_reference_usd)
        floors: dict[Side, float] = {}
        for side in Side:
            adverse_reference = reference + strategy.adverse_reference_usd * (
                1 if side is Side.UP else -1
            )
            scenarios = [
                terminal_probability_up(snapshot.spot.price, anchor, sigma, model_tau)
                for sigma in sigmas
                for anchor in (reference, adverse_reference)
            ]
            floors[side] = min(scenarios if side is Side.UP else [1 - p for p in scenarios])
    except (ValueError, OverflowError):
        return _skip(snapshot, "INVALID_MODEL", features)
    move = snapshot.spot.price - reference
    features["spot_reference_move_usd"] = str(move)
    preferred = Side.UP if move >= 0 else Side.DOWN
    if strategy.mode == "momentum" and abs(move) < strategy.momentum_min_move_usd:
        return _skip(snapshot, "MOMENTUM_MOVE", features, probability_up)
    sides = (
        (preferred,)
        if strategy.mode == "momentum"
        else (preferred, Side.DOWN if preferred is Side.UP else Side.UP)
    )
    decisions = [
        _quote(
            snapshot,
            config,
            side,
            snapshot.up_book if side is Side.UP else snapshot.down_book,
            probability_up,
            floors[side],
            features,
        )
        for side in sides
    ]
    eligible = [decision for decision in decisions if decision.side is not None]
    if eligible:
        return max(
            eligible,
            key=lambda decision: decision.terminal_surplus_proxy
            if decision.terminal_surplus_proxy is not None
            else Decimal("-Infinity"),
        )
    first = decisions[0]
    if len(decisions) > 1:
        first = replace(
            first, features={**first.features, "other_side_reason": decisions[1].reason}
        )
    return first
