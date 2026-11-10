import asyncio
import json
from dataclasses import asdict, replace
from decimal import Decimal

import pytest
from test_strategy import make_snapshot

from btc5m.config import Config
from btc5m.lab_replay import Replay
from btc5m.lab_tape import Frame
from btc5m.lab_variants import Valuations, Variant

D = Decimal


@pytest.mark.parametrize("book_state", ["fresh", "stale", "pending"])
def test_directional_exit_uses_independent_book_when_oracle_snapshot_is_missing(
    tmp_path, book_state
):
    async def run():
        variant = Variant("value", "control", "Value", Config())
        snap = make_snapshot()
        path = tmp_path / "ledger.sqlite"
        runner = Replay(path, variant, "tape", 0)
        for ident in range(1, 4):
            current = make_snapshot(now_ms=snap.now_ms + (ident - 1) * 5000)
            await runner.apply(
                Frame(ident, current.now_ms, current, {}, "CAPTURED"), Valuations(current)
            )
        assert runner.ledger.active_positions()
        now = snap.now_ms + 15000
        independent = make_snapshot(ask=D(".50"), now_ms=now).up_book
        if book_state == "stale":
            independent = replace(independent, timestamp_ms=now - 6000, received_ms=now - 6000)
        raw = {
            "streams": {
                "session_id": "recorded-session",
                "generation": 1,
                "books": {independent.token_id: asdict(independent)},
                "pending_books": {independent.token_id: now} if book_state == "pending" else {},
                "trades": [],
            }
        }
        await runner.apply(Frame(4, now, None, {}, "STALE_ORACLE", research=raw), None)
        sells = [
            json.loads(row[0])
            for row in runner.ledger.db.execute(
                "SELECT data FROM intents WHERE json_extract(data,'$.side')='SELL'"
            )
        ]
        assert bool(sells) is (book_state == "fresh")
        if sells:
            assert sells[0]["reason"] == "STOP"
        # A usable sale book does not establish the missing forecasting path.
        row = json.loads(runner.ledger.db.execute("SELECT data FROM lab_rounds").fetchone()[0])
        assert row["uncertain"]
        runner.close()
        resumed = Replay(path, variant, "tape", 0)
        assert resumed.broker.streams is not None
        assert resumed.broker.streams.session_id == "recorded-session"
        assert resumed.broker.streams.books[independent.token_id] == independent
        if book_state == "fresh":
            next_book = replace(independent, timestamp_ms=now + 1000, received_ms=now + 1000)
            raw["streams"]["books"][independent.token_id] = asdict(next_book)
            await resumed.apply(Frame(5, now + 1000, None, {}, "STALE_ORACLE", research=raw), None)
            sold = resumed.ledger.db.execute(
                "SELECT COUNT(*) FROM fills f JOIN intents i ON f.intent_id=i.id "
                "WHERE json_extract(i.data,'$.side')='SELL'"
            ).fetchone()[0]
            assert sold > 0
        resumed.close()

    asyncio.run(run())


def test_replay_restart_keeps_confirmation_and_does_not_duplicate_fills(tmp_path):
    async def run():
        variant = Variant("value", "control", "Value", Config())
        snap = make_snapshot()
        path = tmp_path / "ledger.sqlite"
        runner = Replay(path, variant, "tape", 0)
        await runner.apply(Frame(1, snap.now_ms, snap, {}, "CAPTURED"), Valuations(snap))
        assert runner.engine.pending_candidate
        runner.close()
        runner = Replay(path, variant, "tape", 0)
        assert runner.engine.pending_candidate
        for i in (2, 3):
            current = make_snapshot(now_ms=snap.now_ms + (i - 1) * 5000)
            await runner.apply(
                Frame(i, current.now_ms, current, {}, "CAPTURED"), Valuations(current)
            )
        assert runner.ledger.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0] > 0
        cash = runner.ledger.summary().cash
        assert not await runner.apply(
            Frame(3, current.now_ms, current, {}, "CAPTURED"), Valuations(current)
        )
        assert runner.ledger.summary().cash == cash
        runner.close()
        runner = Replay(path, variant, "tape", 0)
        assert runner.cursor == 3
        assert runner.ledger.summary().cash == cash
        runner.close()

    asyncio.run(run())


def test_frame_failure_rolls_back_order_and_cursor_together(tmp_path, monkeypatch):
    async def run():
        variant = Variant("value", "control", "Value", Config())
        snap = make_snapshot()
        runner = Replay(tmp_path / "ledger.sqlite", variant, "tape", 0)
        await runner.apply(Frame(1, snap.now_ms, snap, {}, "CAPTURED"), Valuations(snap))

        def fail(*args):
            raise RuntimeError("fault between execution and cursor")

        monkeypatch.setattr(runner, "checkpoint", fail)
        current = make_snapshot(now_ms=snap.now_ms + 5000)
        with pytest.raises(RuntimeError):
            await runner.apply(
                Frame(2, current.now_ms, current, {}, "CAPTURED"), Valuations(current)
            )
        assert runner.ledger.db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0
        assert runner.ledger._meta("lab_cursor") == "1"
        runner.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "policy,expects_exit",
    [("baseline", True), ("no_stop", False), ("time_only", False), ("settlement", False)],
)
def test_exit_controls_use_actual_engine_and_official_delayed_payout(
    tmp_path, policy, expects_exit
):
    async def run():
        variant = Variant("exit", "exit", "Exit", Config(), exit_policy=policy)
        snap = make_snapshot()
        runner = Replay(tmp_path / "ledger.sqlite", variant, "tape", 0)
        for i in range(1, 4):
            current = make_snapshot(now_ms=snap.now_ms + (i - 1) * 5000)
            await runner.apply(
                Frame(i, current.now_ms, current, {}, "CAPTURED"), Valuations(current)
            )
        current = make_snapshot(ask=D(".50"), now_ms=snap.now_ms + 15000)
        await runner.apply(Frame(4, current.now_ms, current, {}, "CAPTURED"), Valuations(current))
        sells = runner.ledger.db.execute(
            "SELECT COUNT(*) FROM intents WHERE json_extract(data,'$.side')='SELL'"
        ).fetchone()[0]
        assert bool(sells) is expects_exit
        if policy == "settlement":
            end = snap.market.end_s * 1000
            await runner.apply(Frame(5, end + 1, None, {}, "NO_SNAPSHOT"), None)
            assert runner.ledger.open_position() is not None
            label = {
                snap.market.slug: {
                    "condition_id": snap.market.condition_id,
                    "opening": str(snap.market.reference_price),
                    "final": "80500",
                }
            }
            await runner.apply(Frame(6, end + 2000, None, label, "NO_SNAPSHOT"), None)
            await runner.apply(Frame(7, end + 2500, None, {}, "NO_SNAPSHOT"), None)
            assert runner.ledger.open_position() is None
            assert runner.ledger.summary(end + 2500).cash > D(100)
            row = json.loads(runner.ledger.db.execute("SELECT data FROM lab_rounds").fetchone()[0])
            assert not row["uncertain"]  # This policy needs no intermediate sale quote.
        runner.close()

    asyncio.run(run())


def test_gap_cancels_pending_and_future_study_does_not_trade_early(tmp_path):
    async def run():
        snap = make_snapshot()
        variant = Variant("v", "control", "Value", Config())
        runner = Replay(tmp_path / "ledger.sqlite", variant, "tape", snap.now_ms + 1000)
        await runner.apply(Frame(1, snap.now_ms, snap, {}, "CAPTURED"), Valuations(snap))
        assert runner.engine.pending_candidate is None
        runner.close()
        runner = Replay(tmp_path / "second.sqlite", variant, "tape", 0)
        current = make_snapshot(now_ms=snap.now_ms + 5000)
        await runner.apply(Frame(1, current.now_ms, current, {}, "CAPTURED"), Valuations(current))
        assert runner.engine.pending_candidate
        await runner.apply(Frame(2, current.now_ms + 500, None, {}, "MISSING_BOOK"), None)
        assert runner.engine.pending_candidate is None
        row = json.loads(runner.ledger.db.execute("SELECT data FROM lab_rounds").fetchone()[0])
        assert row["uncertain"]
        runner.close()

    asyncio.run(run())


def test_sigkill_mid_frame_replays_order_and_fill_exactly_once(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    from pathlib import Path

    child = r"""
import asyncio, os, signal, sys
from pathlib import Path
from test_strategy import make_snapshot
from btc5m.config import Config
from btc5m.lab_replay import Replay
from btc5m.lab_tape import Frame
from btc5m.lab_variants import Variant, Valuations
async def run():
    runner = Replay(Path(sys.argv[1]), Variant('v','control','Value',Config()), 'tape', 0)
    snap = make_snapshot()
    await runner.apply(Frame(1,snap.now_ms,snap,{},'CAPTURED'), Valuations(snap))
    def die(frame):
        assert runner.ledger.db.execute('SELECT COUNT(*) FROM intents').fetchone()[0] == 1
        os.kill(os.getpid(), signal.SIGKILL)
    runner.checkpoint = die
    snap = make_snapshot(now_ms=snap.now_ms+5000)
    await runner.apply(Frame(2,snap.now_ms,snap,{},'CAPTURED'), Valuations(snap))
asyncio.run(run())
"""
    path = tmp_path / "crashed.sqlite"
    result = subprocess.run(
        [sys.executable, "-c", child, str(path)],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parent)},
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == -signal.SIGKILL, result.stderr.decode()

    async def recover():
        variant = Variant("v", "control", "Value", Config())
        recovered = Replay(path, variant, "tape", 0)
        reference = Replay(tmp_path / "reference.sqlite", variant, "tape", 0)
        assert recovered.cursor == 1 and recovered.engine.pending_candidate
        assert recovered.ledger.db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0
        assert recovered.ledger.db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        for i in range(1, 4):
            snap = make_snapshot(now_ms=make_snapshot().now_ms + (i - 1) * 5000)
            frame = Frame(i, snap.now_ms, snap, {}, "CAPTURED")
            for runner in (recovered, reference):
                await runner.apply(frame, Valuations(snap))
        assert recovered.ledger.summary().cash == reference.ledger.summary().cash < D(100)
        for runner in (recovered, reference):
            assert runner.cursor == 3
            assert runner.ledger.db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 1
            assert runner.ledger.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1
            runner.close()

    asyncio.run(recover())
