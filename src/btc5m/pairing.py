"""Sequential, post-only pair construction with explicit unmatched exposure."""

from decimal import ROUND_DOWN, Decimal

from btc5m.config import Config
from btc5m.domain import Decision, Side, Snapshot
from btc5m.execution_types import Position
from btc5m.strategy import _safety_reason, _skip, fair_value

D = Decimal


def pair_decision(snapshot: Snapshot, config: Config, positions: tuple[Position, ...]) -> Decision:
    market, policy = snapshot.market, config.experiments
    features: dict[str, float | str] = {
        "mode": config.strategy.mode,
        "config_hash": config.fingerprint,
        "order_type": "GTC",
        "post_only": "true",
        "quote_policy": "KEEP_VALID_V1",
    }
    safety = _safety_reason(snapshot, config)
    if safety:
        return _skip(snapshot, safety, features)
    held = [
        p
        for p in positions
        if p.status == "ACTIVE" and p.quantity > 0 and p.market.condition_id == market.condition_id
    ]
    if any(p.decision.features.get("mode") != config.strategy.mode for p in held):
        return _skip(snapshot, "PAIR_STRATEGY_MISMATCH", features)
    quantities = {
        side: sum((p.quantity for p in held if p.token_id == market.token(side)), D(0))
        for side in Side
    }
    imbalance = quantities[Side.UP] - quantities[Side.DOWN]
    features.update(
        unpaired_shares=str(abs(imbalance)), paired_shares=str(min(quantities.values()))
    )
    if held and imbalance == 0:
        return _skip(snapshot, "PAIR_COMPLETE", features)
    tau = (market.end_s * 1000 - snapshot.now_ms) / 1000
    if not config.execution.exit_seconds < tau <= config.strategy.entry_max_seconds or (
        not held and tau < config.strategy.entry_min_seconds
    ):
        return _skip(snapshot, "PAIR_WINDOW", features)
    value = fair_value(snapshot, config)
    # New directional risk requires a valid model. Completion below the fixed
    # all-in pair cap may proceed without one, using verified books and holdings.
    if not held and value.reason != "VALID":
        return _skip(snapshot, value.reason, {**features, **value.features})
    features.update(value.features)
    p_up = value.probability_up
    spendable = config.risk.trade_budget_usd - sum((p.cost_basis for p in held), D(0))
    choices = (Side.DOWN if imbalance > 0 else Side.UP,) if held else tuple(Side)
    candidates: list[Decision] = []
    for side in choices:
        book = snapshot.up_book if side is Side.UP else snapshot.down_book
        quantity = min(abs(imbalance), policy.pair_shares) if held else policy.pair_shares
        quantity = quantity.quantize(D(".01"), rounding=ROUND_DOWN)
        if quantity < market.min_order_size:
            continue
        price_cap = spendable / quantity / (1 + market.fee_rate)
        side_features = {
            **features,
            "pair_role": "HEDGE" if held else "OPEN",
            "evaluated_side": side.value,
        }
        if held:
            other = [p for p in held if p.token_id != market.token(side)]
            other_basis = sum((p.cost_basis for p in other), D(0)) / sum(
                (p.quantity for p in other), D(0)
            )
            price_cap = min(price_cap, (policy.pair_max_cost - other_basis) / (1 + market.fee_rate))
            side_features["opposite_cost_per_share"] = str(other_basis)
        else:
            price_cap = min(price_cap, D(str(value.floors[side])) - policy.pair_min_edge)
        adjustment = D(0)
        if held and config.strategy.mode == "inventory_pairs":
            # Binary terminal variance p(1-p), not a stock variance multiplied by
            # a clock that incorrectly forces the penalty to zero near expiry.
            probability = D(str(p_up)) if p_up is not None else D(".5")
            adjustment = (
                policy.inventory_adjustment
                * min(D(1), abs(imbalance) / policy.pair_shares)
                * 4
                * probability
                * (1 - probability)
            )
        price = min(
            book.bids[0].price + adjustment, book.asks[0].price - market.tick_size, price_cap
        )
        price = (price / market.tick_size).to_integral_value(rounding=ROUND_DOWN) * market.tick_size
        if price <= 0 or price >= book.asks[0].price:
            continue
        principal = quantity * price
        reserve = principal * (1 + market.fee_rate)
        surplus = (
            (
                policy.pair_max_cost
                - D(side_features["opposite_cost_per_share"])
                - reserve / quantity
            )
            if held
            else D(str(value.floors[side])) - price
        )
        side_features.update(
            best_bid=str(book.bids[0].price),
            best_ask=str(book.asks[0].price),
            quote_below_bid=str(max(D(0), book.bids[0].price - price)),
            inventory_adjustment=str(adjustment),
            pair_max_cost=str(policy.pair_max_cost),
            reserved_buy_fee=str(reserve - principal),
            estimated_maker_fee="0",
            model_status=value.reason,
        )
        candidates.append(
            Decision(
                market.slug,
                side,
                "ENTRY",
                price,
                principal,
                reserve,
                quantity,
                quantity,
                D(0),
                p_up,
                value.floors.get(side),
                surplus,
                side_features,
            )
        )
    if not candidates:
        return _skip(snapshot, "PAIR_NO_FEASIBLE_QUOTE", features, p_up)
    return max(candidates, key=lambda d: d.terminal_surplus_proxy or D(0))
