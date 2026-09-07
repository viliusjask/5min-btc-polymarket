from dataclasses import replace
from decimal import Decimal

from test_strategy import make_snapshot

from btc5m.config import Config
from btc5m.domain import Side
from btc5m.flow_signals import flow_side, observe_flow, order_flow_variants

D = Decimal


def sample(now, imbalance="-.7", move="-.2", depth=".6"):
    window = {"status": "VALID", "imbalance": imbalance, "return_bps": move, "source_ms": now}
    return {
        "received_ms": now,
        "source_ms": now,
        "generation": 0,
        "status": "VALID",
        "windows": {"10": window, "30": window},
        "depth": {"status": "VALID", "imbalance": depth, "received_ms": now, "update_id": now},
    }


def chosen(signal):
    return next(v for v in order_flow_variants(Config()) if v.signal == signal)


def test_absorption_opposes_unproductive_flow_and_continuation_requires_price_confirmation():
    snap = make_snapshot()
    assert flow_side(snap, chosen("absorption"), sample(snap.now_ms), {})[0] is Side.UP
    assert flow_side(snap, chosen("flow_continuation"), sample(snap.now_ms), {})[0] is None
    fast_fall = sample(snap.now_ms, move="-5")
    assert flow_side(snap, chosen("absorption"), fast_fall, {})[0] is None
    assert flow_side(snap, chosen("flow_continuation"), fast_fall, {})[0] is Side.DOWN


def test_absorption_is_symmetric_and_rejects_missing_stale_or_future_inputs():
    snap, variant = make_snapshot(), chosen("absorption")
    assert (
        flow_side(snap, variant, sample(snap.now_ms, imbalance=".7", move=".2"), {})[0] is Side.DOWN
    )
    for data in ({}, sample(snap.now_ms - 3000), sample(snap.now_ms + 1)):
        assert flow_side(snap, variant, data, {})[0] is None


def test_pressure_requires_persistence_and_restarts_after_side_flip():
    snap, variant, state = make_snapshot(), chosen("pressure_pair"), {}
    observe_flow(snap, variant, sample(snap.now_ms), state)
    assert flow_side(snap, variant, sample(snap.now_ms), state)[0] is None
    later = replace(snap, now_ms=snap.now_ms + 1000)
    observe_flow(later, variant, sample(later.now_ms), state)
    assert flow_side(later, variant, sample(later.now_ms), state)[0] is Side.UP
    observe_flow(later, variant, sample(later.now_ms, depth="-.7"), state)
    assert flow_side(later, variant, sample(later.now_ms, depth="-.7"), state)[0] is None


def test_confirmation_cannot_arm_after_the_early_window_or_use_future_confirmation():
    snap, variant, state = make_snapshot(), chosen("pressure_confirm"), {}
    observe_flow(snap, variant, sample(snap.now_ms), state)
    assert "arm" not in state
    assert flow_side(snap, variant, sample(snap.now_ms), state)[0] is None


def test_confirmation_preserves_early_observation_and_later_requires_higher_executable_price():
    from btc5m.domain import Book, Level

    original = make_snapshot()
    start = original.market.start_s * 1000
    variant, state = chosen("pressure_confirm"), {}
    control, control_state = chosen("confirmation_control"), {}
    for elapsed in range(19, 92):
        now = start + elapsed * 1000
        snap = make_snapshot(now_ms=now)
        ask = D(".55") if elapsed >= 90 else D(".50")
        snap = replace(
            snap,
            up_book=Book("up", now, now, (Level(ask - D(".01"), D(100)),), (Level(ask, D(100)),)),
            down_book=Book(
                "down", now, now, (Level(D(".49"), D(100)),), (Level(D(".50"), D(100)),)
            ),
        )
        observe_flow(snap, variant, sample(now), state)
        observe_flow(snap, control, sample(now), control_state)
        if elapsed == 89:
            assert flow_side(snap, variant, sample(now), state)[0] is None
    assert state["arm"]["at_ms"] == control_state["arm"]["at_ms"] == start + 20000
    assert state["arm"]["prices"] == control_state["arm"]["prices"]
    assert flow_side(snap, variant, sample(now), state)[0] is Side.UP
    assert flow_side(snap, control, sample(now), control_state)[0] is Side.UP


def test_failed_early_pressure_is_not_replaced_by_a_later_favorable_observation():
    from btc5m.domain import Book, Level

    snap = make_snapshot()
    start = snap.market.start_s * 1000
    variant, state = chosen("pressure_confirm"), {}
    for elapsed in range(20, 32):
        now = start + elapsed * 1000
        current = make_snapshot(now_ms=now, ask=D(".50"))
        current = replace(
            current,
            down_book=Book(
                "down", now, now, (Level(D(".49"), D(100)),), (Level(D(".50"), D(100)),)
            ),
        )
        observe_flow(current, variant, sample(now, depth="0" if elapsed == 20 else ".8"), state)
    assert state["arm"]["at_ms"] == start + 20000
    assert not state["arm"]["qualified"]


def test_pressure_pair_selects_its_preferred_first_leg_and_keeps_original_hedge_policy(tmp_path):
    from btc5m.domain import Book, Level
    from btc5m.lab_replay import Replay

    snap = make_snapshot(move=D(0), ask=D(".42"))
    now = snap.now_ms
    snap = replace(
        snap,
        down_book=Book("down", now, now, (Level(D(".38"), D(100)),), (Level(D(".40"), D(100)),)),
    )
    variant = chosen("pressure_pair")
    replay = Replay(tmp_path / "ledger.sqlite", variant, "tape", 0)
    replay.engine.flow = sample(now)
    replay.engine.signal_state = {"pressure_side": "UP", "pressure_since_ms": now - 1000}
    decision = replay.engine._evaluate(snap, variant.config)
    assert decision.reason == "ENTRY" and decision.side is Side.UP
    assert decision.features["pair_role"] == "OPEN"
    replay.close()
