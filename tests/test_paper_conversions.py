from dataclasses import replace
from decimal import Decimal

import pytest
from test_strategy import make_snapshot

from btc5m.config import Config
from btc5m.ledger import Ledger, LedgerError
from btc5m.paper_conversions import merge_pair, split_pair

D = Decimal
WALLET = "0x" + "7" * 40


def setup(tmp_path):
    config = Config()
    config = replace(config, strategy=replace(config.strategy, mode="inventory_pairs"))
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET, environment="paper")
    session = ledger.start_or_resume_session(config)
    ledger.observe_account(D(100), {}, (), now_ms=make_snapshot().now_ms)
    return ledger, session


def test_split_and_partial_merge_conserve_cash_basis_and_inventory_across_restart(tmp_path):
    ledger, session = setup(tmp_path)
    snap = make_snapshot()
    split_pair(ledger, snap.market, D(5), session, snap.now_ms)
    assert ledger.summary(snap.now_ms).cash == 95
    assert ledger.summary(snap.now_ms).position_risk == 5
    assert len(ledger.positions()) == 2
    assert not ledger.unresolved_orders()
    assert ledger.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 0
    config = ledger.config
    ledger.close()
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET, environment="paper")
    ledger.start_or_resume_session(config)
    merge_pair(ledger, snap.market, D(2), session, snap.now_ms + 1000, "merge-1")
    assert ledger.summary(snap.now_ms).cash == 97
    assert ledger.summary(snap.now_ms).position_risk == 3
    assert ledger.summary(snap.now_ms).realized_net_pnl == 0
    merge_pair(ledger, snap.market, D(2), session, snap.now_ms + 1000, "merge-1")
    assert ledger.summary(snap.now_ms).cash == 97
    assert ledger.portfolio_results()["inventory_pairs"]["fills"] == 0
    ledger.close()


def test_split_respects_existing_cash_and_loss_limits_and_is_idempotent(tmp_path):
    ledger, session = setup(tmp_path)
    snap = make_snapshot()
    with pytest.raises(LedgerError, match="ALLOCATION_LIMIT"):
        split_pair(ledger, snap.market, D(6), session, snap.now_ms)
    split_pair(ledger, snap.market, D(5), session, snap.now_ms)
    split_pair(ledger, snap.market, D(5), session, snap.now_ms)
    assert ledger.summary(snap.now_ms).cash == 95
    with pytest.raises(LedgerError):
        merge_pair(ledger, snap.market, D(6), session, snap.now_ms, "too-many")
    ledger.close()


def test_merging_cannot_consume_shares_reserved_for_a_resting_sale(tmp_path):
    ledger, session = setup(tmp_path)
    snap = make_snapshot()
    split_pair(ledger, snap.market, D(5), session, snap.now_ms)
    position = ledger.positions()[0]
    ledger.reserve_exit(position, D(5), D(".55"), "SPLIT_SELL", session, snap.now_ms, passive=True)
    with pytest.raises(LedgerError, match="UNRESOLVED"):
        merge_pair(ledger, snap.market, D(5), session, snap.now_ms, "unsafe")
    ledger.close()


def test_conversion_rollback_and_official_payout_need_no_fake_opening_order(tmp_path, monkeypatch):
    import asyncio

    from btc5m.paper import PaperBroker

    ledger, session = setup(tmp_path)
    snap = make_snapshot()
    actual_event = ledger._event
    monkeypatch.setattr(
        ledger, "_event", lambda *args: (_ for _ in ()).throw(RuntimeError("disk failure"))
    )
    with pytest.raises(RuntimeError):
        split_pair(ledger, snap.market, D(5), session, snap.now_ms)
    assert not ledger.positions()
    assert ledger.summary(snap.now_ms).cash == 100
    monkeypatch.setattr(ledger, "_event", actual_event)
    split_pair(ledger, snap.market, D(5), session, snap.now_ms)
    broker = PaperBroker(
        ledger, ledger.config, final_reference=lambda m: (m.reference_price, m.reference_price + 1)
    )
    final = asyncio.run(broker.resolve(snap.market))
    ledger.apply_resolution(snap.market, final, snap.market.end_s * 1000 + 1)
    ledger.settle_paper_claims(snap.market.end_s * 1000 + 2)
    assert ledger.summary(snap.now_ms).cash == 100
    assert ledger.summary(snap.now_ms).realized_net_pnl == 0
    assert ledger.portfolio_results()["inventory_pairs"]["cash_movement"] == 0
    assert ledger.db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0
    ledger.close()


def test_passive_sales_require_subsequent_aggressive_buys_and_consume_ask_queue(tmp_path):
    import asyncio

    from btc5m.domain import Book, Level
    from btc5m.paper import PaperBroker
    from btc5m.streams import PublicStreams, PublicTrade

    async def run():
        ledger, session = setup(tmp_path)
        snap, clock = make_snapshot(), [make_snapshot().now_ms]
        split_pair(ledger, snap.market, D(5), session, clock[0])
        position = ledger.positions()[0]
        streams = PublicStreams(ledger.config, clock=lambda: clock[0] / 1000)

        def book():
            return Book(
                position.token_id,
                clock[0],
                clock[0],
                (Level(D(".59"), D(10)),),
                (Level(D(".60"), D(2)),),
            )

        streams.books[position.token_id] = book()
        broker = PaperBroker(ledger, ledger.config, streams=streams, clock=lambda: clock[0] / 1000)
        intent = ledger.reserve_exit(
            position, D(5), D(".60"), "SPLIT_SELL", session, clock[0], passive=True
        )
        prepared = await broker.prepare(intent, snap.market)
        ledger.prepare(intent.intent_id, prepared)
        ledger.mark_submitting(intent.intent_id)
        ledger.record_ack(intent.intent_id, await broker.post(prepared))
        clock[0] += 500
        streams.books[position.token_id] = book()
        ledger.apply_evidence(
            intent.intent_id, await broker.reconcile(ledger.order(intent.intent_id))
        )
        assert ledger.order(intent.intent_id).confirmed_quantity == 0
        clock[0] += 100
        streams.trades.append(
            PublicTrade(
                "wrong-side",
                position.token_id,
                snap.market.condition_id,
                "SELL",
                D(".60"),
                D(100),
                clock[0],
                clock[0],
                0,
            )
        )
        ledger.apply_evidence(
            intent.intent_id, await broker.reconcile(ledger.order(intent.intent_id))
        )
        assert ledger.order(intent.intent_id).confirmed_quantity == 0
        clock[0] += 100
        streams.trades.append(
            PublicTrade(
                "right-side",
                position.token_id,
                snap.market.condition_id,
                "BUY",
                D(".60"),
                D(4),
                clock[0],
                clock[0],
                0,
            )
        )
        ledger.apply_evidence(
            intent.intent_id, await broker.reconcile(ledger.order(intent.intent_id))
        )
        assert ledger.order(intent.intent_id).confirmed_quantity == 2
        assert ledger.summary(clock[0]).cash == D("96.2")
        assert ledger.summary(clock[0]).realized_net_pnl == D(".2")
        ledger.apply_evidence(
            intent.intent_id, await broker.reconcile(ledger.order(intent.intent_id))
        )
        assert ledger.order(intent.intent_id).confirmed_quantity == 2
        ledger.close()

    asyncio.run(run())
