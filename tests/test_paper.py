import asyncio
from dataclasses import replace
from decimal import Decimal

import pytest
from test_experiments import mode
from test_pair_execution import WALLET
from test_strategy import make_snapshot

from btc5m.domain import PricePoint
from btc5m.engine import Engine
from btc5m.ledger import Ledger
from btc5m.pairing import pair_decision
from btc5m.paper import PaperBroker
from btc5m.strategy import evaluate
from btc5m.streams import PublicStreams, PublicTrade

D = Decimal


def setup(tmp_path, strategy="value"):
    clock = [make_snapshot().now_ms]
    config = mode(strategy)
    ledger = Ledger(tmp_path / "paper.sqlite", WALLET, environment="paper")
    session = ledger.start_or_resume_session(config)
    streams = PublicStreams(config, clock=lambda: clock[0] / 1000)
    broker = PaperBroker(ledger, config, streams=streams, clock=lambda: clock[0] / 1000)
    broker.update(make_snapshot())
    ledger.observe_account(D(100), {}, (), now_ms=clock[0])
    return clock, config, ledger, session, streams, broker


async def submit(ledger, broker, decision, session, now):
    intent = ledger.reserve_entry(decision, broker.snapshot.market, session, now)
    prepared = await broker.prepare(intent, intent.market)
    ledger.prepare(intent.intent_id, prepared)
    ledger.mark_submitting(intent.intent_id)
    ledger.record_ack(intent.intent_id, await broker.post(prepared))
    return ledger.order(intent.intent_id)


def test_immediate_paper_order_waits_for_latency_and_later_book(tmp_path):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path)
        intent = await submit(ledger, broker, evaluate(broker.snapshot, config), session, clock[0])
        assert not (await broker.reconcile(intent)).fills
        clock[0] += 1000
        assert not (await broker.reconcile(intent)).fills  # original book is no proof of execution
        broker.update(make_snapshot(now_ms=clock[0]))
        evidence = await broker.reconcile(intent)
        assert evidence.terminal and evidence.fills
        assert evidence.fills[0].chain_id == 0
        assert sum(f.principal for f in evidence.fills) == intent.principal
        assert (
            sum(f.quantity for f in evidence.fills)
            == evaluate(make_snapshot(), config).expected_shares
        )
        ledger.apply_evidence(intent.intent_id, evidence)
        before = ledger.summary(clock[0]).cash
        ledger.apply_evidence(intent.intent_id, await broker.reconcile(intent))
        assert ledger.summary(clock[0]).cash == before
        ledger.close()

    asyncio.run(run())


def test_immediate_order_cannot_fill_from_a_fresh_book_after_a_long_outage(tmp_path):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path)
        intent = await submit(ledger, broker, evaluate(broker.snapshot, config), session, clock[0])
        clock[0] += 60000
        broker.update(make_snapshot(now_ms=clock[0]))
        evidence = await broker.reconcile(intent)
        assert evidence.terminal and not evidence.fills
        assert broker._load(intent.intent_id)["terminal_reason"] == "PAPER_EXECUTION_GAP"
        assert ledger.observations()[-1]["kind"] == "paper_uncertainty"
        ledger.close()

    asyncio.run(run())


def test_restart_before_passive_activation_does_not_start_a_new_queue(tmp_path):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, "passive_pairs")
        intent = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        clock[0] += 1000
        new_streams = PublicStreams(config, clock=lambda: clock[0] / 1000)
        restarted = PaperBroker(ledger, config, streams=new_streams, clock=lambda: clock[0] / 1000)
        restarted.update(make_snapshot(now_ms=clock[0]))
        evidence = await restarted.reconcile(intent)
        assert evidence.terminal and not evidence.fills
        assert restarted._load(intent.intent_id)["terminal_reason"] == "PAPER_QUEUE_GAP"
        ledger.close()

    asyncio.run(run())


def test_resting_quote_needs_trade_volume_after_queue_and_survives_restart(tmp_path):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, "passive_pairs")
        decision = pair_decision(broker.snapshot, config, ())
        intent = await submit(ledger, broker, decision, session, clock[0])
        clock[0] += 1000
        snap = make_snapshot(now_ms=clock[0])
        broker.update(snap)
        assert not (await broker.reconcile(intent)).fills
        # 100 shares were ahead at the quoted bid. A touch is not a trade.
        clock[0] += 1
        streams.trades.append(
            PublicTrade(
                "one",
                intent.token_id,
                intent.market.condition_id,
                "SELL",
                intent.price_limit,
                D(99),
                clock[0],
                clock[0],
                streams.generation,
            )
        )
        assert not (await broker.reconcile(intent)).fills
        ledger.close()
        ledger = Ledger(tmp_path / "paper.sqlite", WALLET, environment="paper")
        ledger.start_or_resume_session(config)
        broker = PaperBroker(ledger, config, streams=streams, clock=lambda: clock[0] / 1000)
        broker.update(snap)
        clock[0] += 1
        streams.trades.append(
            PublicTrade(
                "two",
                intent.token_id,
                intent.market.condition_id,
                "SELL",
                intent.price_limit,
                D(3),
                clock[0],
                clock[0],
                streams.generation,
            )
        )
        evidence = await broker.reconcile(ledger.order(intent.intent_id))
        assert sum((f.quantity for f in evidence.fills), D(0)) == 2
        ledger.apply_evidence(intent.intent_id, evidence)
        assert ledger.open_position().quantity == 2
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("complement", [False, True])
def test_cancel_race_can_fill_before_effective_cancellation(tmp_path, complement):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, "passive_pairs")
        decision = pair_decision(broker.snapshot, config, ())
        intent = await submit(ledger, broker, decision, session, clock[0])
        clock[0] += 1000
        broker.update(make_snapshot(now_ms=clock[0]))
        await broker.reconcile(intent)
        pending = ledger.request_cancel(intent.intent_id, clock[0])
        await broker.cancel(pending)
        clock[0] += 100
        token = (
            next(
                t
                for t in (intent.market.up_token, intent.market.down_token)
                if t != intent.token_id
            )
            if complement
            else intent.token_id
        )
        streams.trades.append(
            PublicTrade(
                "race",
                token,
                intent.market.condition_id,
                "BUY" if complement else "SELL",
                1 - intent.price_limit if complement else intent.price_limit,
                D(102),
                clock[0],
                clock[0],
                streams.generation,
                "0x" + "1" * 64,
            )
        )
        evidence = await broker.reconcile(ledger.order(intent.intent_id))
        assert sum((f.quantity for f in evidence.fills), D(0)) == 2
        assert not evidence.terminal
        clock[0] += 6000
        evidence = await broker.reconcile(ledger.order(intent.intent_id))
        assert evidence.terminal
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("strategy", ["passive_pairs", "inventory_pairs"])
def test_complementary_buy_matches_bid_without_double_counting_mirrored_volume(tmp_path, strategy):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, strategy)
        order = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        market = order.market
        streams.tokens = (market.up_token, market.down_token)
        streams.condition_id = market.condition_id
        opposite = next(token for token in streams.tokens if token != order.token_id)
        clock[0] += 1000
        broker.update(make_snapshot(now_ms=clock[0]))
        await broker.reconcile(order)  # 100 shares ahead at our bid.

        async def trade(token, side, price, quantity, tx):
            clock[0] += 1
            streams.ingest_market(
                {
                    "event_type": "last_trade_price",
                    "market": market.condition_id,
                    "asset_id": token,
                    "side": side,
                    "price": str(price),
                    "size": str(quantity),
                    "timestamp": str(clock[0]),
                    "transaction_hash": "0x" + str(tx) * 64 if tx is not None else None,
                }
            )
            return await broker.reconcile(order)

        # A purchase of the opposite outcome below the complementary price cannot match.
        assert not (await trade(opposite, "BUY", 1 - order.price_limit - D(".01"), 1000, 1)).fills
        assert not (await trade(opposite, "BUY", 1 - order.price_limit, 102, None)).fills
        assert any(row.get("code") == "PAPER_TRADE_ID_MISSING" for row in ledger.observations())
        first = await trade(opposite, "BUY", 1 - order.price_limit, 102, 2)
        assert sum(f.quantity for f in first.fills) == 2
        ledger.apply_evidence(order.intent_id, first)
        # The two outcome feeds may describe the same economic volume. A later mirror
        # of the same transaction must not consume the queue/fill the order twice.
        mirrored = await trade(order.token_id, "SELL", order.price_limit, 102, 2)
        assert sum(f.quantity for f in mirrored.fills) == 2
        later = await trade(opposite, "BUY", 1 - order.price_limit, 3, 3)
        assert later.terminal and sum(f.quantity for f in later.fills) == 5
        ledger.apply_evidence(order.intent_id, later)
        assert ledger.open_position().quantity == 5
        ledger.close()

    asyncio.run(run())


def test_resting_queue_does_not_reuse_trade_volume_already_in_activation_book(tmp_path):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, "passive_pairs")
        intent = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        clock[0] += 1000
        broker.update(make_snapshot(now_ms=clock[0]))
        # This trade and the updated book share a timestamp. Its volume may
        # already have been removed from the visible queue; ordering is unknown.
        aggressive_sell(streams, intent, clock, "activation-trade", D(1000))
        assert not (await broker.reconcile(intent)).fills
        clock[0] += 1
        aggressive_sell(streams, intent, clock, "later-trade", D(101))
        evidence = await broker.reconcile(intent)
        assert sum(f.quantity for f in evidence.fills) == 1
        ledger.close()

    asyncio.run(run())


def test_all_six_modes_use_same_engine_with_paper_broker(tmp_path):
    async def run():
        from btc5m.config import STRATEGIES

        for name in STRATEGIES:
            clock, config, ledger, session, streams, broker = setup(tmp_path / name, name)
            engine = Engine(broker, ledger, config, session)
            result = await engine.step(broker.snapshot, None, clock[0])
            assert result.reason == (
                "FAST_MISSING" if name == "fast_value" else "ENTRY_CONFIRMATION_WAITING"
            )
            ledger.close()

    asyncio.run(run())


def publish(broker, clock, **kwargs):
    snap = make_snapshot(now_ms=clock[0] // 5000 * 5000, **kwargs)
    snap = replace(
        snap,
        now_ms=clock[0],
        market=replace(snap.market, metadata_received_ms=clock[0]),
        spot=replace(snap.spot, timestamp_ms=clock[0], received_ms=clock[0]),
        twap60=replace(snap.twap60, timestamp_ms=clock[0], received_ms=clock[0]),
        up_book=replace(snap.up_book, timestamp_ms=clock[0], received_ms=clock[0]),
        down_book=replace(snap.down_book, timestamp_ms=clock[0], received_ms=clock[0]),
    )
    if broker.config.strategy.mode == "fast_value":
        prior = snap.history[0]
        snap = replace(
            snap,
            history=(
                replace(
                    prior,
                    timestamp_ms=prior.timestamp_ms - 5000,
                    received_ms=prior.received_ms - 5000,
                    price=prior.price - D(5),
                ),
                *snap.history,
            ),
            spot=replace(snap.spot, timestamp_ms=clock[0] - 500),
            exchange_history=(
                PricePoint("spot", clock[0] - 500, clock[0] - 500, D(80000)),
                PricePoint("spot", clock[0], clock[0], D(80001)),
            ),
        )
    broker.update(snap)
    return snap


def aggressive_sell(streams, intent, clock, identity, quantity=None):
    quantity = D(106) if quantity is None else quantity
    streams.trades.append(
        PublicTrade(
            identity,
            intent.token_id,
            intent.market.condition_id,
            "SELL",
            intent.price_limit,
            quantity,
            clock[0],
            clock[0],
            streams.generation,
        )
    )


@pytest.mark.parametrize(
    "name", ["momentum", "value", "fast_value", "model_exit", "passive_pairs", "inventory_pairs"]
)
def test_every_strategy_confirms_submits_and_receives_simulated_fill(tmp_path, name):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, name)
        engine = Engine(broker, ledger, config, session, read_exit_book=broker.book)
        first = await engine.step(publish(broker, clock), None, clock[0])
        assert first.reason == "ENTRY_CONFIRMATION_WAITING"
        clock[0] += 1000
        result = await engine.step(publish(broker, clock), None, clock[0])
        assert result.action == "SUBMITTED", result
        intent = ledger.unresolved_orders()[0]
        assert bool(intent.passive) == name.endswith("pairs")
        clock[0] += 1000
        publish(broker, clock)
        evidence = await broker.reconcile(intent)
        if intent.passive:
            assert not evidence.fills
            clock[0] += 1
            aggressive_sell(streams, intent, clock, "first")
            evidence = await broker.reconcile(intent)
        assert evidence.terminal and evidence.fills
        ledger.apply_evidence(intent.intent_id, evidence)
        assert ledger.open_position().quantity >= intent.quantity
        assert ledger.portfolio_results()[name]["fills"] >= 1
        ledger.close()

    asyncio.run(run())


def test_model_exit_sells_when_holding_value_collapses_before_hard_stop(tmp_path):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, "model_exit")
        intent = await submit(ledger, broker, evaluate(broker.snapshot, config), session, clock[0])
        clock[0] += 1000
        publish(broker, clock)
        ledger.apply_evidence(intent.intent_id, await broker.reconcile(intent))
        engine = Engine(broker, ledger, config, session, read_exit_book=broker.book)
        clock[0] += 1000
        result = await engine.step(publish(broker, clock, move=D(-50)), None, clock[0])
        assert result.action == "SUBMITTED", result
        exit_order = ledger.unresolved_orders()[0]
        assert exit_order.side == "SELL" and exit_order.reason == "MODEL"
        assert (
            ledger.open_position().gross_entry_price - D(".68")
            < config.execution.stop_loss_per_share
        )
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("name", ["passive_pairs", "inventory_pairs"])
def test_pair_engine_completes_two_legs_and_settles_one_net_round(tmp_path, name):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, name)
        engine = Engine(broker, ledger, config, session, read_exit_book=broker.book)
        first = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        clock[0] += 1000
        publish(broker, clock)
        await broker.reconcile(first)
        clock[0] += 1
        aggressive_sell(streams, first, clock, "first")
        result = await engine.step(publish(broker, clock), None, clock[0])
        assert result.action == "SUBMITTED", result
        second = ledger.unresolved_orders()[0]
        assert second.token_id != first.token_id and second.quantity == 5
        clock[0] += 1000
        publish(broker, clock)
        await broker.reconcile(second)
        clock[0] += 1
        aggressive_sell(streams, second, clock, "second")
        result = await engine.step(publish(broker, clock), None, clock[0])
        assert result.reason == "PAIR_COMPLETE_AWAITING_RESOLUTION", result
        assert ledger.summary(clock[0]).daily_entries == 1
        cost = sum(p.cost_basis for p in ledger.active_positions())
        broker.final_reference = lambda market: (D(80000), D(80001))
        clock[0] = first.market.end_s * 1000 + 1
        await engine.step(None, None, clock[0])
        await engine.reconcile()  # explicit simulated payout after verified public labels
        report = ledger.portfolio_results()[name]
        assert report["realized_net_pnl"] == 5 - cost
        assert report["completed_rounds"] == 1
        assert ledger.summary(clock[0]).cash == 100 + 5 - cost
        ledger.close()

    asyncio.run(run())


def test_new_stream_session_cannot_inherit_prior_queue_position(tmp_path):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, "passive_pairs")
        first = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        clock[0] += 1000
        snap = publish(broker, clock)
        await broker.reconcile(first)
        restarted = PublicStreams(config, clock=lambda: clock[0] / 1000)
        assert restarted.generation == streams.generation
        broker = PaperBroker(ledger, config, streams=restarted, clock=lambda: clock[0] / 1000)
        broker.update(snap)
        clock[0] += 1
        aggressive_sell(restarted, first, clock, "after-restart", D(1000))
        evidence = await broker.reconcile(first)
        assert evidence.terminal and not evidence.fills
        assert any(r.get("code") == "PAPER_QUEUE_GAP" for r in ledger.observations())
        ledger.close()

    asyncio.run(run())


def test_unpaired_timeout_submits_a_protected_sale(tmp_path):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, "passive_pairs")
        first = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        clock[0] += 1000
        publish(broker, clock)
        await broker.reconcile(first)
        clock[0] += 1
        aggressive_sell(streams, first, clock, "first")
        ledger.apply_evidence(first.intent_id, await broker.reconcile(first))
        clock[0] += 31000
        engine = Engine(broker, ledger, config, session, read_exit_book=broker.book)
        result = await engine.step(publish(broker, clock), None, clock[0])
        assert result.action == "SUBMITTED", result
        sell = ledger.unresolved_orders()[0]
        assert sell.side == "SELL" and sell.quantity == 5 and sell.reason == "UNPAIRED_TIMEOUT"
        assert sell.price_limit >= D(".67")
        ledger.close()

    asyncio.run(run())


def test_lower_hedge_quote_waits_for_its_price_without_double_counting_better_bids(tmp_path):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, "passive_pairs")
        first = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        clock[0] += 1000
        publish(broker, clock)
        await broker.reconcile(first)
        clock[0] += 1
        aggressive_sell(streams, first, clock, "first")
        ledger.apply_evidence(first.intent_id, await broker.reconcile(first))
        hedge = await submit(
            ledger,
            broker,
            pair_decision(broker.snapshot, config, ledger.active_positions()),
            session,
            clock[0],
        )
        assert hedge.price_limit < broker.snapshot.down_book.bids[0].price
        clock[0] += 1000
        publish(broker, clock)
        await broker.reconcile(hedge)
        clock[0] += 1
        aggressive_sell(streams, hedge, clock, "one-share-at-our-price", D(1))
        evidence = await broker.reconcile(hedge)
        assert sum(f.quantity for f in evidence.fills) == 1
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("name", ["passive_pairs", "inventory_pairs"])
def test_resting_quote_keeps_priority_when_market_bid_improves_and_then_fills(tmp_path, name):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, name)
        engine = Engine(broker, ledger, config, session, read_exit_book=broker.book)
        order = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        created = clock[0]
        clock[0] += 500
        snap = publish(broker, clock, ask=D(".71"))
        assert pair_decision(snap, config, ()).price_limit > order.price_limit
        await engine.step(snap, None, clock[0])
        assert ledger.order(order.intent_id).cancel_requested_ms is None
        # Public executions later reach our original price while it is still valuable.
        clock[0] = created + 1200
        aggressive_sell(streams, order, clock, "after-favorable-update")
        await engine.step(publish(broker, clock, ask=D(".71")), None, clock[0])
        assert ledger.order(order.intent_id).confirmed_quantity == order.quantity
        assert len(ledger.round_orders(order.market.slug)) == 2  # opening fill, then actual hedge
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("trigger", ["expiry", "edge", "missing", "stop"])
def test_resting_quote_cancels_with_specific_durable_reason(tmp_path, trigger):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, "passive_pairs")
        engine = Engine(broker, ledger, config, session)
        order = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        clock[0] += 5000 if trigger == "expiry" else 1000
        snap = publish(broker, clock, move=D(-200) if trigger == "edge" else D(200))
        if trigger == "stop":
            ledger.request_stop()
        await engine.step(None if trigger == "missing" else snap, None, clock[0])
        requested = ledger.order(order.intent_id).cancel_requested_ms
        assert requested == clock[0]
        expected = dict(
            expiry="QUOTE_EXPIRED",
            edge="QUOTE_EDGE_LOST",
            missing="NO_SNAPSHOT",
            stop="STOP_REQUESTED",
        )[trigger]
        events = [r for r in ledger.observations() if r.get("kind") == "quote_cancel"]
        assert len(events) == 1
        assert events[0]["code"] == expected
        assert events[0]["identity"] == order.intent_id
        # Cancellation reconciliation is still in progress; preserve its original cause.
        clock[0] += 300
        await engine.step(publish(broker, clock), None, clock[0])
        assert ledger.order(order.intent_id).cancel_requested_ms == requested
        assert len([r for r in ledger.observations() if r.get("kind") == "quote_cancel"]) == 1
        ledger.close()

    asyncio.run(run())


def test_new_side_preference_does_not_cancel_a_still_valuable_owned_quote(tmp_path):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, "passive_pairs")
        broker.update(make_snapshot(move=D(2)))
        order = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        engine = Engine(broker, ledger, config, session)
        clock[0] += 500
        snap = publish(broker, clock, move=D(3))
        assert pair_decision(snap, config, ()).side != order.decision.side
        await engine.step(snap, None, clock[0])
        assert ledger.order(order.intent_id).cancel_requested_ms is None
        ledger.close()

    asyncio.run(run())


def test_partial_opening_quote_cancels_remaining_risk_when_its_edge_disappears(tmp_path):
    async def run():
        clock, config, ledger, session, streams, broker = setup(tmp_path, "passive_pairs")
        engine = Engine(broker, ledger, config, session)
        order = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        clock[0] += 500
        await engine.step(publish(broker, clock), None, clock[0])
        clock[0] += 250
        aggressive_sell(streams, order, clock, "partial", D(102))
        await engine.step(publish(broker, clock), None, clock[0])
        partial = ledger.order(order.intent_id)
        assert partial.confirmed_quantity == 2 and partial.cancel_requested_ms is None
        clock[0] += 250
        await engine.step(publish(broker, clock, move=D(-200)), None, clock[0])
        cancelled = ledger.order(order.intent_id)
        assert cancelled.cancel_requested_ms == clock[0]
        assert cancelled.confirmed_quantity == 2
        assert cancelled.remaining_reserve == partial.remaining_reserve > 0
        assert ledger.open_position().quantity == 2
        assert (
            next(r for r in ledger.observations() if r.get("kind") == "quote_cancel")["code"]
            == "QUOTE_EDGE_LOST"
        )
        ledger.close()

    asyncio.run(run())
