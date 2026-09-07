import asyncio
from dataclasses import asdict, replace
from decimal import Decimal

from test_strategy import make_snapshot

from btc5m.config import Config
from btc5m.domain import Book, Level
from btc5m.flow_signals import order_flow_variants
from btc5m.lab_replay import Replay
from btc5m.lab_report import replay_report
from btc5m.lab_tape import Frame
from btc5m.lab_variants import Valuations
from btc5m.streams import PublicTrade

D = Decimal


def frame(ident, stamp, trades=()):
    snap = make_snapshot(now_ms=stamp)
    snap = replace(
        snap,
        up_book=Book("up", stamp, stamp, (Level(D(".49"), D(20)),), (Level(D(".51"), D(2)),)),
        down_book=Book("down", stamp, stamp, (Level(D(".49"), D(20)),), (Level(D(".51"), D(2)),)),
    )
    research = {
        "streams": {
            "session_id": "public-session",
            "generation": 0,
            "pending_books": {},
            "books": {b.token_id: asdict(b) for b in (snap.up_book, snap.down_book)},
            "trades": [asdict(t) for t in trades],
        }
    }
    return Frame(ident, stamp, snap, {}, "CAPTURED", research)


def test_split_delays_conversion_posts_both_sales_and_restores_exact_queue_after_restart(tmp_path):
    async def run():
        variant = next(v for v in order_flow_variants(Config()) if v.signal == "split_sell")
        stamp = make_snapshot().now_ms
        path = tmp_path / "ledger.sqlite"
        replay = Replay(path, variant, "tape", 0)
        first = frame(1, stamp)
        await replay.apply(first, Valuations(first.snapshot))
        assert replay.ledger.summary(stamp).cash == 100
        assert not replay.ledger.positions()
        replay.close()
        replay = Replay(path, variant, "tape", 0)
        for ident, delta in ((2, 1000), (3, 1500), (4, 2000)):
            current = frame(ident, stamp + delta)
            await replay.apply(current, Valuations(current.snapshot))
        assert replay.ledger.summary(stamp + 2000).cash == 95
        orders = replay.ledger.unresolved_orders()
        assert len(orders) == 2
        assert all(o.side == "SELL" and o.passive for o in orders)
        replay.close()
        replay = Replay(path, variant, "tape", 0)
        events = tuple(
            PublicTrade(
                "trade-" + token,
                token,
                "condition",
                "BUY",
                D(".51"),
                D(7),
                stamp + 2500,
                stamp + 2500,
                0,
            )
            for token in ("up", "down")
        )
        current = frame(5, stamp + 2500, events)
        await replay.apply(current, Valuations(current.snapshot))
        assert replay.ledger.summary(current.now_ms).cash == D("100.10")
        assert replay.ledger.summary(current.now_ms).realized_net_pnl == D(".10")
        assert replay.ledger.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 2
        assert not replay.ledger.active_positions()
        report = replay_report(replay)
        assert report["conversions"]["splits"] == 1
        assert report["funnel"]["opening_orders"] == 0
        assert report["funnel"]["filled_maker_sales"] == 2
        assert report["fill_rate"] == 1
        assert report["fill_rate_basis"] == "maker_sales"
        replay.close()

    asyncio.run(run())


def test_no_sale_round_cancels_then_merges_without_inventing_fills(tmp_path):
    async def run():
        variant = next(v for v in order_flow_variants(Config()) if v.signal == "split_sell")
        stamp = make_snapshot().now_ms
        path = tmp_path / "ledger.sqlite"
        replay = Replay(path, variant, "tape", 0)
        # Every frame stays below the capture-gap limit. Cancellation and merge
        # must finish using the simulated clock, without a closing trade.
        for ident, delta in enumerate(range(0, 116001, 500), 1):
            current = frame(ident, stamp + delta)
            await replay.apply(current, Valuations(current.snapshot))
            if delta == 105000:
                replay.close()
                replay = Replay(path, variant, "tape", 0)
        report = replay_report(replay)
        assert replay.ledger.summary().cash == 100
        assert replay.ledger.summary().realized_net_pnl == 0
        assert not replay.ledger.active_positions()
        assert not replay.ledger.unresolved_orders()
        assert report["conversions"]["splits"] == 1
        assert report["conversions"]["merges"] == 1
        assert report["completed_rounds"] == 1
        assert replay.ledger.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 0
        replay.close()

    asyncio.run(run())


def test_queue_uncertainty_reaches_round_quality_even_without_a_capture_gap(tmp_path):
    import json

    async def run():
        variant = next(v for v in order_flow_variants(Config()) if v.signal == "split_sell")
        stamp = make_snapshot().now_ms
        replay = Replay(tmp_path / "ledger.sqlite", variant, "tape", 0)
        for ident, delta in ((1, 0), (2, 1000), (3, 1500), (4, 2000)):
            current = frame(ident, stamp + delta)
            if ident == 4:
                current.research["streams"]["generation"] = 1
            await replay.apply(current, Valuations(current.snapshot))
        rows = [json.loads(r[0]) for r in replay.ledger.db.execute("SELECT data FROM lab_rounds")]
        assert rows[0]["uncertain"]
        replay.close()

    asyncio.run(run())
