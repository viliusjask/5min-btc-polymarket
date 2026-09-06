"""Real core, SQLite and broker, with only external HTTP/RPC responses substituted."""

import asyncio
from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_broker import TOKEN, TOKEN2, WALLET, Venue, broker_fixture, market
from test_ledger import HASH, NOW, decision
from test_strategy import make_snapshot

from btc5m.config import Config
from btc5m.domain import Book, Level
from btc5m.engine import Engine
from btc5m.execution_types import ConfirmedFill, OrderEvidence, PreparedOrder


def snapshot(now=NOW):
    snap = make_snapshot(now_ms=now)
    return replace(
        snap,
        market=replace(market(), metadata_received_ms=now),
        up_book=replace(snap.up_book, token_id=TOKEN),
        down_book=replace(snap.down_book, token_id=TOKEN2),
    )


def held(ledger, session, venue, *, quantity="5", principal="3.50", minimum="5", entry_tick=".01"):
    venue.book_min = minimum
    m = replace(market(), min_order_size=D(minimum), tick_size=D(entry_tick))
    buy = ledger.reserve_entry(
        replace(decision(), minimum_receive_shares=D(quantity), expected_shares=D(quantity)),
        m,
        session,
        NOW,
    )
    ledger.prepare(buy.intent_id, PreparedOrder(buy.intent_id, HASH, "{}", D("3.75"), D(quantity)))
    ledger.mark_submitting(buy.intent_id)
    f = ConfirmedFill(
        137,
        "0x" + "12" * 32,
        0,
        HASH,
        TOKEN,
        WALLET,
        "BUY",
        D(quantity),
        D(principal),
        D(".0735"),
        NOW,
    )
    ledger.apply_evidence(buy.intent_id, OrderEvidence((f,), (), True, None, {}))
    venue.balance = int((D(100) - D(principal) - D(".0735")) * 1000000)
    venue.inventory = {TOKEN: int(D(quantity) * 1000000)}
    return ledger.open_position()


def bid_book(now, *, price=".68", size="100"):
    return Book(TOKEN, now, now, (Level(D(price), D(size)),), ())


def test_current_decision_time_rejects_old_completed_snapshot(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        engine = Engine(broker, ledger, Config(), session)
        result = await engine.step(snapshot(), None, NOW + 6000)
        assert result.action == "SKIP" and result.reason == "STALE_DATA"
        assert not ledger.unresolved_orders() and venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_real_core_entry_persists_before_one_unknown_post(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        venue.post_loss = True
        engine = Engine(broker, ledger, Config(), session)
        assert (await engine.step(snapshot(), None, NOW)).reason == "ENTRY_CONFIRMATION_WAITING"
        venue.now = NOW + 1000
        result = await engine.step(confirmation_snapshot(venue.now), None, venue.now)
        assert result.action == "SUBMITTED" and venue.posts == 1, result
        order = ledger.unresolved_orders()[0]
        assert order.state == "UNKNOWN" and order.remaining_reserve == D("4.9969")
        assert order.decision.buy_principal == D("4.67")
        second = await engine.step(snapshot(), None, NOW)
        assert second.reason == "ORDER_UNRESOLVED" and venue.posts == 1
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_time_exit_without_snapshot_uses_stored_round_and_partial_depth(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        pos = held(ledger, session, venue, minimum=".01")
        venue.now = NOW + 100000
        engine = Engine(broker, ledger, Config(), session)
        venue.post_loss = True
        result = await engine.step(None, bid_book(venue.now, size="2"), venue.now)
        assert result.action == "SUBMITTED" and venue.posts == 1, result
        sell = ledger.unresolved_orders()[0]
        assert sell.side == "SELL" and sell.quantity == 2 and sell.market.slug == pos.market.slug
        assert sell.reason == "TIME" and sell.price_limit == D(".67")
        assert ledger.open_position().quantity == 5
        assert ledger.summary(venue.now).realized_net_pnl == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_stop_trigger_uses_gross_entry_price_and_whole_quantity_depth(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        held(ledger, session, venue)
        engine = Engine(broker, ledger, Config(), session)
        result = await engine.step(None, bid_book(NOW, price=".63"), NOW)
        assert (
            result.action == "HOLD" and venue.posts == 0
        )  # .70-.08=.62; fee basis .7147 must not trigger
        result = await engine.step(None, bid_book(NOW, price=".60", size="1"), NOW)
        assert result.reason == "INSUFFICIENT_FULL_EXIT_DEPTH" and venue.posts == 0
        venue.post_loss = True
        result = await engine.step(None, bid_book(NOW, price=".62"), NOW)
        assert result.action == "SUBMITTED" and ledger.unresolved_orders()[0].reason == "STOP"
        await broker.close()
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "quantity,minimum,expected",
    [(".007891", ".01", "BELOW_SELL_PRECISION"), ("4.99", "5", "BELOW_VENUE_MINIMUM")],
)
def test_unexitable_dust_records_reason_without_endless_sell_intents(
    tmp_path, monkeypatch, quantity, minimum, expected
):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        held(ledger, session, venue, quantity=quantity, minimum=minimum)
        venue.now = NOW + 100000
        engine = Engine(broker, ledger, Config(), session)
        for _ in range(2):
            result = await engine.step(None, bid_book(venue.now), venue.now)
            assert result.reason == expected
        assert venue.posts == 0 and not ledger.unresolved_orders()
        assert ledger.open_position().exit_problem == expected
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_shutdown_without_bids_preserves_exposure_and_stop_request(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        held(ledger, session, venue)
        engine = Engine(broker, ledger, Config(), session)
        result = await engine.shutdown(None, NOW)
        assert result.reason == "NO_EXIT_BOOK"
        assert ledger.stop_requested() and ledger.open_position().quantity == 5
        assert ledger.open_position().exit_reason == "SHUTDOWN" and venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_first_candidates_and_fixed_calibration_missing_are_durable(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        ledger.record_snapshot(snapshot(NOW - 10000), Config())
        ledger.record_snapshot(snapshot(NOW + 3000), Config())
        ledger.record_snapshot(snapshot(NOW + 4000), Config())
        ledger.record_observation(
            {
                "kind": "final_reference",
                "slug": market().slug,
                "received_ms": NOW + 200000,
                "price": "80001",
                "status": "official",
                "source_ms": market().end_s * 1000,
                "provenance": "synthetic",
            }
        )
        rows = ledger.measurements()
        assert len([r for r in rows if r["kind"] == "candidate"]) == 2
        calibration = next(r for r in rows if r["kind"] == "calibration")
        assert calibration["status"] == "missing"
        assert len([r for r in ledger.observations() if r["kind"] == "final_reference"]) == 1
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_calibration_first_valid_window_does_not_shift_to_later_better_snapshot(
    tmp_path, monkeypatch
):
    async def run():
        venue = Venue()
        broker, ledger, _ = await broker_fixture(tmp_path, monkeypatch, venue)
        ledger.record_snapshot(snapshot(NOW + 1000), Config())
        ledger.record_snapshot(snapshot(NOW + 2000), Config())
        calibration = next(r for r in ledger.measurements() if r["kind"] == "calibration")
        assert calibration["status"] == "observed" and calibration["now_ms"] == NOW + 1000
        assert calibration["spot"]["price"] == "80200"
        await broker.close()
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["stop", "stale", "window"])
def test_entry_is_abandoned_if_control_or_time_changes_during_preparation(
    tmp_path, monkeypatch, change
):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        original = broker.prepare

        async def prepare(intent, market):
            result = await original(intent, market)
            if change == "stop":
                Ledger.request_stop_at(ledger.path)
            elif change == "stale":
                venue.now += 6000
            else:
                venue.now += 61000
            return result

        monkeypatch.setattr(broker, "prepare", prepare)
        engine = Engine(broker, ledger, Config(), session)
        assert (await engine.step(snapshot(), None, NOW)).reason == "ENTRY_CONFIRMATION_WAITING"
        venue.now = NOW + 1000
        result = await engine.step(confirmation_snapshot(venue.now), None, venue.now)
        assert venue.posts == 0 and not ledger.unresolved_orders()
        assert result.reason in ("STOP_REQUESTED_BEFORE_POST", "STALE_DATA", "ENTRY_WINDOW")
        row = ledger.order(result.intent_id)
        assert row.state == "REJECTED" and row.reason == result.reason
        await broker.close()
        ledger.close()

    from btc5m.ledger import Ledger

    asyncio.run(run())


def test_actual_partial_sell_settles_then_retries_only_remaining_inventory(tmp_path, monkeypatch):
    async def run():
        from test_broker import open_order, trade
        from test_rpc import receipt

        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        held(ledger, session, venue, minimum=".01")
        venue.now = NOW + 100000
        venue.post_loss = True
        venue.bid = ".8"
        engine = Engine(broker, ledger, Config(), session)
        await engine.step(None, bid_book(venue.now, price=".8"), venue.now)
        first = ledger.unresolved_orders()[0]
        venue.order = open_order(first.order_hash, matched="2", trades=("sell",)) | {
            "side": "SELL",
            "order_type": "FAK",
        }
        venue.trades = [[trade(first.order_hash, ident="sell", size="2") | {"side": "SELL"}]]
        venue.rpc.receipt = receipt(side=1, maker=2000000, taker=1600000, fee=22400)
        venue.rpc.receipt["logs"][0]["topics"][1] = first.order_hash
        venue.rpc.receipt["logs"][0]["topics"][2] = "0x" + "00" * 12 + WALLET[2:]
        venue.rpc.receipt["logs"][0]["logIndex"] = "0x1"
        venue.balance = 98004100
        venue.inventory = {TOKEN: 3000000}
        result = await engine.step(None, bid_book(venue.now, price=".8"), venue.now)
        assert result.action == "SUBMITTED"
        assert ledger.order(first.intent_id).state == "SETTLED"
        assert ledger.open_position().quantity == 3
        assert ledger.open_position().cost_basis == D("2.1441")
        assert ledger.summary(venue.now).realized_net_pnl == D(".1482")
        assert ledger.unresolved_orders()[0].quantity == 3 and venue.posts == 2
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_missing_actual_holdings_read_blocks_exit_without_fabricating_quantity(
    tmp_path, monkeypatch
):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        held(ledger, session, venue)
        venue.inventory = {TOKEN: 1000000}
        venue.now = NOW + 100000
        engine = Engine(broker, ledger, Config(), session)
        result = await engine.step(None, bid_book(venue.now), venue.now)
        assert result.reason == "ACCOUNT_EXPOSURE_UNRECONCILED" and venue.posts == 0
        assert ledger.open_position().quantity == 5
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_sell_floor_uses_current_tick_after_historical_grid_changes(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        held(ledger, session, venue, entry_tick=".1")
        venue.book_tick = ".001"
        venue.current_tick = ".001"
        venue.bid = ".995"
        venue.post_loss = True
        engine = Engine(broker, ledger, Config(), session)
        result = await engine.step(None, bid_book(NOW, price=".995"), NOW)
        assert result.action == "SUBMITTED" and venue.posts == 1
        assert ledger.unresolved_orders()[0].price_limit == D(".985")
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_discovered_round_with_no_complete_snapshot_records_missing_calibration(
    tmp_path, monkeypatch
):
    async def run():
        venue = Venue()
        broker, ledger, _ = await broker_fixture(tmp_path, monkeypatch, venue)
        ledger.record_observation(
            {
                "kind": "discovery",
                "slug": market().slug,
                "source_ms": market().start_s * 1000,
                "received_ms": NOW - 10000,
                "stage": "received",
            }
        )
        ledger.record_clock(NOW + 3000)
        rows = ledger.measurements()
        assert (
            len(rows) == 1 and rows[0]["kind"] == "calibration" and rows[0]["status"] == "missing"
        )
        await broker.close()
        ledger.close()

    asyncio.run(run())


def confirmation_snapshot(now=NOW, *, source=None, book_source=None, price="80200", ask=".70"):
    from btc5m.domain import PricePoint

    source = now if source is None else source
    base = snapshot(now)
    history = tuple(
        PricePoint("spot", stamp, stamp, D("80200") if (stamp // 5000) % 2 == 0 else D("80195"))
        for stamp in range(NOW - 1820000, source + 1, 5000)
    )
    spot = PricePoint("spot", source, now, D(price))
    history = tuple(p for p in history if p.timestamp_ms != source) + (spot,)
    book_source = now if book_source is None else book_source
    return replace(
        base,
        spot=spot,
        history=history,
        up_book=Book(
            TOKEN, book_source, now, (Level(D(ask) - D(".02"), D(100)),), (Level(D(ask), D(100)),)
        ),
    )


@pytest.mark.parametrize("mode", ["value", "momentum"])
def test_entry_waits_for_newer_same_side_confirmation_without_reserving_cash(
    tmp_path, monkeypatch, mode
):
    async def run():
        config = replace(Config(), strategy=replace(Config().strategy, mode=mode))
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue, config=config)
        engine = Engine(broker, ledger, config, session)
        initial = confirmation_snapshot()
        first = await engine.step(initial, None, NOW)
        assert first.reason == "ENTRY_CONFIRMATION_WAITING"
        assert engine.pending_candidate is not None
        assert not ledger.unresolved_orders() and ledger.summary(NOW).daily_entries == 0
        repeat = await engine.step(initial, None, NOW)
        assert repeat.reason == "ENTRY_CONFIRMATION_WAITING" and venue.posts == 0
        venue.now = NOW + 1000
        venue.post_loss = True
        result = await engine.step(confirmation_snapshot(venue.now), None, venue.now)
        assert result.action == "SUBMITTED" and ledger.summary(venue.now).daily_entries == 1
        assert engine.pending_candidate is None and venue.posts == 1
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_delayed_eighteen_dollar_shock_invalidates_raw_value_candidate(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        engine = Engine(broker, ledger, Config(), session)
        # Public-event-shaped synthetic case: .61 ask, lagged favorable spot,
        # then a newly delivered18USD drop. This asserts eligibility, never PnL.
        first = confirmation_snapshot(
            source=NOW - 3000, book_source=NOW - 1000, price="80024", ask=".61"
        )
        # Use a complete low-volatility pre-candidate history, independent of the delayed shock.
        first = replace(
            first,
            history=tuple(
                replace(p, price=D("80024") if i % 2 else D("80019"))
                for i, p in enumerate(first.history)
            ),
        )
        assert (await engine.step(first, None, NOW)).reason == "ENTRY_CONFIRMATION_WAITING"
        venue.now = NOW + 1000
        shock = replace(
            confirmation_snapshot(venue.now, price="80006", ask=".61"),
            history=first.history
            + (
                replace(
                    first.spot, timestamp_ms=NOW + 1000, received_ms=NOW + 1000, price=D("80006")
                ),
            ),
        )
        result = await engine.step(shock, None, venue.now)
        assert result.action == "SKIP" and engine.pending_candidate is None
        assert not ledger.unresolved_orders() and venue.posts == 0
        assert any(
            r.get("status") == "cancelled"
            for r in ledger.observations()
            if r["kind"] == "execution_confirmation"
        )
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_confirmation_uses_new_price_and_immutable_original_book_watermark(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        engine = Engine(broker, ledger, Config(), session)
        await engine.step(
            confirmation_snapshot(source=NOW - 3000, book_source=NOW - 1000), None, NOW
        )
        assert engine.pending_candidate is not None
        original = engine.pending_candidate.original_book_source_ms
        venue.now = NOW + 1000
        await engine.step(confirmation_snapshot(venue.now, source=NOW - 2000), None, venue.now)
        assert engine.pending_candidate is not None
        assert engine.pending_candidate.original_book_source_ms == original
        assert not ledger.unresolved_orders()
        venue.now = NOW + 2000
        venue.ask = ".65"
        venue.post_loss = True
        result = await engine.step(
            confirmation_snapshot(venue.now, source=NOW - 1000, ask=".65"), None, venue.now
        )
        assert result.action == "SUBMITTED"
        order = ledger.unresolved_orders()[0]
        assert order.decision.price_limit == D(".66") and order.price_limit == D(".66")
        confirmed = next(
            r
            for r in ledger.observations()
            if r["kind"] == "execution_confirmation" and r["status"] == "confirmed"
        )
        assert confirmed["book_minus_spot_ms"] == 3000
        assert confirmed["original_book_source_ms"] == NOW - 1000
        await broker.close()
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "change", ["missing", "stale", "window", "stop", "config", "restart", "account"]
)
def test_pending_confirmation_is_discarded_on_invalidity_or_restart(tmp_path, monkeypatch, change):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        engine = Engine(broker, ledger, Config(), session)
        first = confirmation_snapshot()
        await engine.step(first, None, NOW)
        assert engine.pending_candidate is not None
        if change == "restart":
            engine = Engine(broker, ledger, Config(), session)
            assert engine.pending_candidate is None
        else:
            current = first
            if change == "missing":
                current = None
            elif change == "stale":
                venue.now = NOW + 6000
            elif change == "window":
                venue.now = NOW + 61000
                current = confirmation_snapshot(venue.now)
            elif change == "stop":
                ledger.request_stop()
            elif change == "config":
                engine.config = replace(
                    Config(), risk=replace(Config().risk, max_entries_per_day=10)
                )
            elif change == "account":
                venue.invalid_auth = True
            await engine.step(current, None, venue.now)
            assert engine.pending_candidate is None
        assert not ledger.unresolved_orders() and venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "change", ["side", "round", "condition", "reference", "token", "provenance"]
)
def test_confirmation_identity_changes_rearm_without_confirming_same_call(
    tmp_path, monkeypatch, change
):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        engine = Engine(broker, ledger, Config(), session)
        await engine.step(confirmation_snapshot(), None, NOW)
        venue.now = NOW + 1000
        venue.post_loss = True
        newer = confirmation_snapshot(venue.now)
        if change == "condition":
            newer = replace(newer, market=replace(newer.market, condition_id="0x" + "34" * 32))
        elif change == "reference":
            newer = replace(newer, market=replace(newer.market, reference_price=D("80001")))
        elif change == "token":
            newer = replace(
                newer,
                market=replace(newer.market, up_token="42"),
                up_book=replace(newer.up_book, token_id="42"),
            )
        elif change == "round":
            venue.now = NOW + 300000
            newer = confirmation_snapshot(venue.now)
            next_market = replace(
                newer.market,
                slug=f"btc-updown-5m-{newer.market.start_s + 300}",
                start_s=newer.market.start_s + 300,
                end_s=newer.market.end_s + 300,
                reference_timestamp_ms=(newer.market.start_s + 300) * 1000,
            )
            newer = replace(newer, market=next_market)
        elif change == "side":
            newer = replace(
                newer,
                spot=replace(newer.spot, price=D("79800")),
                up_book=Book(
                    TOKEN,
                    venue.now,
                    venue.now,
                    (Level(D(".28"), D(100)),),
                    (Level(D(".30"), D(100)),),
                ),
                down_book=Book(
                    TOKEN2,
                    venue.now,
                    venue.now,
                    (Level(D(".68"), D(100)),),
                    (Level(D(".70"), D(100)),),
                ),
            )
        else:
            newer = replace(
                newer,
                market=replace(
                    newer.market,
                    reference_source="same-value-official-upgrade",
                    metadata_provenance="same-price-confirmation",
                ),
            )
        result = await engine.step(newer, None, venue.now)
        if change == "provenance":
            assert result.action == "SUBMITTED" and venue.posts == 1
        else:
            assert result.reason == "ENTRY_CONFIRMATION_WAITING", result
            assert engine.pending_candidate is not None
            assert engine.pending_candidate.original_decision_ms == venue.now
            assert not ledger.unresolved_orders() and venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_confirmation_watermark_uses_exact_milliseconds_without_future_tolerance(
    tmp_path, monkeypatch
):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        engine = Engine(broker, ledger, Config(), session)
        await engine.step(confirmation_snapshot(book_source=NOW + 999), None, NOW)
        venue.now = NOW + 1000
        result = await engine.step(
            confirmation_snapshot(venue.now, source=NOW + 998), None, venue.now
        )
        assert result.reason == "ENTRY_CONFIRMATION_WAITING" and not ledger.unresolved_orders()
        venue.now = NOW + 1001
        venue.post_loss = True
        result = await engine.step(
            confirmation_snapshot(venue.now, source=NOW + 999), None, venue.now
        )
        assert result.action == "SUBMITTED" and venue.posts == 1
        await broker.close()
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("size,covered,full", [("100", "5", True), ("2", "2", False)])
def test_exit_quote_reports_depth_and_estimated_net_separately_from_actual_cash(
    tmp_path, monkeypatch, size, covered, full
):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        held(ledger, session, venue)
        engine = Engine(broker, ledger, Config(), session)
        await engine.step(None, bid_book(NOW, price=".80", size=size), NOW)
        quotes = [row for row in ledger.observations() if row["kind"] == "exit_quote"]
        assert len(quotes) == 1
        quote = quotes[0]
        assert D(quote["held_quantity"]) == 5
        assert D(quote["covered_quantity"]) == D(covered)
        assert quote["full_depth"] is full
        assert D(quote["gross_price"]) == D(".80")
        assert D(quote["estimated_sell_fee"]) == D(covered) * D(".0112")
        assert D(quote["estimated_net_proceeds"]) == D(covered) * D(".7888")
        assert quote["source"] == "stored_market_fee_estimate"
        assert ledger.summary(NOW).realized_net_pnl == 0
        assert ledger.summary(NOW).fees == D(".0735")
        assert venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())
