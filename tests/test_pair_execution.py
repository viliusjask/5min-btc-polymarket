from decimal import Decimal

import pytest
from test_experiments import mode
from test_strategy import make_snapshot

from btc5m.execution_types import ConfirmedFill, OrderAck, OrderEvidence, PreparedOrder
from btc5m.ledger import Ledger, LedgerError
from btc5m.pairing import pair_decision

D = Decimal
WALLET = "0x" + "11" * 20


def setup(tmp_path, strategy="passive_pairs", environment="live"):
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET, environment=environment)
    config = mode(strategy)
    session = ledger.start_or_resume_session(config)
    ledger.observe_account(D(100), {}, (), now_ms=make_snapshot().now_ms)
    return ledger, config, session


def fill(ledger, intent, quantity=None, price=None, terminal=True):
    quantity = intent.quantity if quantity is None else quantity
    price = intent.price_limit if price is None else price
    order_hash = "0x" + intent.intent_id.ljust(64, "0")
    ledger.prepare(
        intent.intent_id,
        PreparedOrder(intent.intent_id, order_hash, "{}", intent.reserved_cash, intent.quantity),
    )
    ledger.mark_submitting(intent.intent_id)
    ledger.record_ack(intent.intent_id, OrderAck("accepted", order_hash))
    evidence = ConfirmedFill(
        137,
        order_hash,
        0,
        order_hash,
        intent.token_id,
        WALLET,
        intent.side,
        quantity,
        quantity * price,
        D(0),
        intent.created_ms,
    )
    ledger.apply_evidence(intent.intent_id, OrderEvidence((evidence,), (), terminal, None, {}))
    return ledger.order(intent.intent_id)


def test_pair_two_legs_have_separate_holdings_one_round_and_shared_budget(tmp_path):
    ledger, config, session = setup(tmp_path)
    snap = make_snapshot()
    first = ledger.reserve_entry(pair_decision(snap, config, ()), snap.market, session, snap.now_ms)
    fill(ledger, first)
    second = ledger.reserve_entry(
        pair_decision(snap, config, ledger.active_positions()),
        snap.market,
        session,
        snap.now_ms + 1,
    )
    fill(ledger, second)
    assert len(ledger.active_positions()) == 2
    assert ledger.open_position() is not None
    assert ledger.summary(snap.now_ms).daily_entries == 1
    assert ledger.summary(snap.now_ms).position_risk <= config.risk.trade_budget_usd
    assert pair_decision(snap, config, ledger.active_positions()).reason == "PAIR_COMPLETE"
    ledger.close()


def test_partial_maker_fill_and_cancel_request_keep_remaining_reserve(tmp_path):
    ledger, config, session = setup(tmp_path)
    snap = make_snapshot()
    first = ledger.reserve_entry(pair_decision(snap, config, ()), snap.market, session, snap.now_ms)
    order = fill(ledger, first, quantity=D(2), terminal=False)
    reserve = order.remaining_reserve
    assert reserve > 0
    ledger.request_cancel(order.intent_id, snap.now_ms + 100)
    assert ledger.order(order.intent_id).remaining_reserve == reserve
    ledger.close()
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET)
    ledger.start_or_resume_session(config)
    assert ledger.order(order.intent_id).cancel_requested_ms == snap.now_ms + 100
    assert ledger.order(order.intent_id).remaining_reserve == reserve
    ledger.close()


def test_cannot_reopen_pair_after_an_exit_was_requested(tmp_path):
    ledger, config, session = setup(tmp_path)
    snap = make_snapshot()
    first = ledger.reserve_entry(pair_decision(snap, config, ()), snap.market, session, snap.now_ms)
    fill(ledger, first)
    ledger.note_exit(first.position_id, "UNPAIRED_TIMEOUT", None, snap.now_ms)
    with pytest.raises(LedgerError, match="PAIR_EXIT_LATCHED"):
        ledger.reserve_entry(
            pair_decision(snap, config, ledger.active_positions()),
            snap.market,
            session,
            snap.now_ms,
        )
    ledger.close()


def test_paper_journal_cannot_be_reopened_for_live_execution(tmp_path):
    ledger, _, _ = setup(tmp_path, environment="paper")
    ledger.close()
    with pytest.raises(LedgerError, match="EXECUTION_ENVIRONMENT_MISMATCH"):
        Ledger(tmp_path / "ledger.sqlite", WALLET)


def test_cancelled_unfilled_round_is_an_attempt_not_a_completed_trade(tmp_path):
    ledger, config, session = setup(tmp_path)
    snap = make_snapshot()
    first = ledger.reserve_entry(pair_decision(snap, config, ()), snap.market, session, snap.now_ms)
    ledger.abandon(first.intent_id, "NO_FILL")
    result = ledger.portfolio_results()["passive_pairs"]
    assert result["attempted_rounds"] == 1
    assert result["filled_rounds"] == result["completed_rounds"] == 0
    ledger.close()
