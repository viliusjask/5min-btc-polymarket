"""Actual core, SDK signing, receipt adapter and SQLite; only venue I/O is synthetic."""

import asyncio
from dataclasses import replace
from decimal import Decimal as D

from test_broker import TOKEN, WALLET, Venue, broker_fixture, open_order, trade
from test_engine import bid_book, confirmation_snapshot
from test_ledger import NOW
from test_rpc import receipt

from btc5m.cli import LatestInput, report
from btc5m.config import Config
from btc5m.engine import Engine
from btc5m.ledger import Ledger


def settle_venue(venue, order, *, side, shares, principal, fee, log, balance, remaining):
    """Supply a matching account trade and canonical receipt, never inject ledger money."""
    venue.order = open_order(order.order_hash, matched=shares, trades=(f"fill-{log}",)) | {
        "side": side,
        "order_type": "FOK" if side == "BUY" else "FAK",
    }
    venue.trades = [[trade(order.order_hash, ident=f"fill-{log}", size=shares) | {"side": side}]]
    venue.rpc.receipt = receipt(
        side=0 if side == "BUY" else 1,
        maker=int(D(principal if side == "BUY" else shares) * 1000000),
        taker=int(D(shares if side == "BUY" else principal) * 1000000),
        fee=int(D(fee) * 1000000),
    )
    venue.rpc.receipt["logs"][0]["topics"][1] = order.order_hash
    venue.rpc.receipt["logs"][0]["topics"][2] = "0x" + "00" * 12 + WALLET[2:]
    venue.rpc.receipt["logs"][0]["logIndex"] = hex(log)
    venue.balance = int(D(balance) * 1000000)
    venue.inventory = {TOKEN: int(D(remaining) * 1000000)}


def test_entry_partial_exits_confirmed_fees_flat_report(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        venue.book_min = ".01"
        venue.post_loss = True
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        cell = LatestInput(ledger, Config(), clock=lambda: venue.now / 1000, emit=lambda row: None)
        engine = Engine(broker, ledger, Config(), session, read_snapshot=cell.read)

        def publish():
            snap = confirmation_snapshot(venue.now)
            snap = replace(snap, market=replace(snap.market, min_order_size=D(".01")))
            cell.publish(snap, cell.read().invalidation_generation)

        publish()
        assert (await engine.step(None, None, venue.now)).reason == "ENTRY_CONFIRMATION_WAITING"
        assert ledger.summary(venue.now).risk_reserve == 0
        venue.now += 1000
        publish()
        assert (await engine.step(None, None, venue.now)).action == "SUBMITTED"
        buy = ledger.unresolved_orders()[0]
        assert buy.state == "UNKNOWN" and venue.posts == 1
        assert ledger.summary(venue.now).cash_movement == 0
        settle_venue(
            venue,
            buy,
            side="BUY",
            shares="5",
            principal="3.50",
            fee=".0735",
            log=0,
            balance="96.4265",
            remaining="5",
        )
        venue.now = NOW + 100000
        venue.bid = ".80"
        result = await engine.step(None, bid_book(venue.now, price=".8", size="2"), venue.now)
        assert result.action == "SUBMITTED"
        sell = ledger.unresolved_orders()[0]
        assert sell.quantity == 2 and ledger.open_position().quantity == 5
        settle_venue(
            venue,
            sell,
            side="SELL",
            shares="2",
            principal="1.60",
            fee=".0224",
            log=1,
            balance="98.0041",
            remaining="3",
        )
        result = await engine.step(None, bid_book(venue.now, price=".8", size="3"), venue.now)
        assert result.action == "SUBMITTED"
        assert ledger.open_position().quantity == 3
        assert ledger.summary(venue.now).realized_net_pnl == D(".1482")
        last = ledger.unresolved_orders()[0]
        settle_venue(
            venue,
            last,
            side="SELL",
            shares="3",
            principal="2.40",
            fee=".0336",
            log=2,
            balance="100.3705",
            remaining="0",
        )
        ledger.request_stop()
        assert (await engine.shutdown(None, venue.now)).reason == "FLAT"
        output = report(ledger, records=True)
        assert output["summary"]["cash"] == D("100.3705")
        assert output["summary"]["realized_net_pnl"] == D(".3705")
        assert output["summary"]["fees"] == D(".1295")
        assert all(
            row["quantity"] == 0 and row["cost_basis"] == 0
            for row in output["summary"]["inventory"]
        )
        assert output["summary"]["risk_reserve"] == 0
        assert output["summary"]["claimable_value"] == 0
        assert output["summary"]["unresolved_orders"] == ()
        # The synthetic flat recent path qualifies Value only, despite its large opening lead.
        assert len(output["first_eligible_screens"]) == 1
        assert output["confirmation_counts"]["confirmed"] == 1
        assert venue.posts == 3
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_unknown_restart_retains_reserve_until_receipt_and_stop_never_replays_buy(
    tmp_path, monkeypatch
):
    async def run():
        venue = Venue()
        venue.post_loss = True
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        engine = Engine(broker, ledger, Config(), session)
        await engine.step(confirmation_snapshot(), None, NOW)
        venue.now += 1000
        await engine.step(confirmation_snapshot(venue.now), None, venue.now)
        order = ledger.unresolved_orders()[0]
        path = ledger.path
        ledger.close()
        ledger = Ledger(path, WALLET)
        assert ledger.start_or_resume_session(Config()) == session
        broker.ledger = ledger
        engine = Engine(broker, ledger, Config(), session)
        assert engine.pending_candidate is None
        assert (await engine.step(None, None, venue.now)).reason == "ORDER_UNRESOLVED"
        assert venue.posts == 1
        stopped = await engine.shutdown(None, venue.now)
        assert stopped.reason == "ORDER_UNRESOLVED"
        before = report(ledger)["summary"]
        assert before["risk_reserve"] == D("4.5582") and before["cash_movement"] == 0
        settle_venue(
            venue,
            order,
            side="BUY",
            shares="5",
            principal="3.50",
            fee=".0735",
            log=0,
            balance="96.4265",
            remaining="5",
        )
        assert (await engine.shutdown(None, venue.now)).reason == "NO_EXIT_BOOK"
        after = report(ledger)["summary"]
        assert after["cash"] == D("96.4265") and after["inventory"][0]["quantity"] == 5
        assert after["risk_reserve"] == 0 and after["position_risk"] == D("3.5735")
        assert venue.posts == 1
        await broker.close()
        ledger.close()

    asyncio.run(run())
