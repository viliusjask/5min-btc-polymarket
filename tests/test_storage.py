"""Lossless event compaction keeps the ledger's existing SQL/cursor contract."""

import json
import sqlite3

import pytest

from btc5m.ledger import Ledger

WALLET = "0x" + "0" * 40


def populated(tmp_path, count=19):
    ledger = Ledger(tmp_path / "journal.sqlite", WALLET, environment="paper")
    with ledger.db:
        ledger.db.executemany(
            "INSERT INTO events(id,kind,at_ms,data) VALUES (?,?,?,?)",
            [
                (
                    index + 1,
                    "PUBLIC_OBSERVATION" if index % 2 else "DECISION",
                    1000 + index,
                    json.dumps({"kind": "book", "price": str(index), "bids": ["0.51"] * 100}),
                )
                for index in range(count)
            ],
        )
    return ledger


def test_compaction_preserves_sql_rows_ids_and_resume_across_chunk_boundaries(tmp_path):
    from btc5m.storage import enable_compaction, rotate_events, storage_status

    ledger = populated(tmp_path)
    expected = ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall()
    enable_compaction(ledger.db)
    first = rotate_events(ledger.db, before_ms=1013, chunk_rows=5, max_chunks=1)
    assert first["archived_events"] == 5
    assert ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall() == expected
    path = ledger.path
    ledger.close()
    ledger = Ledger(path, WALLET, environment="paper")
    try:
        second = rotate_events(ledger.db, before_ms=1013, chunk_rows=5, max_chunks=5)
        assert second["archived_events"] == 8
        assert ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall() == expected
        assert ledger.db.execute(
            "SELECT id,json_extract(data,'$.price') FROM events WHERE id>4 AND id<=7 ORDER BY id"
        ).fetchall() == [(5, "4"), (6, "5"), (7, "6")]
        with ledger.db:
            ledger.db.execute("INSERT INTO events(kind,at_ms,data) VALUES ('DECISION',2000,'{}')")
        assert ledger.db.execute("SELECT MAX(id) FROM events").fetchone()[0] == 20
        status = storage_status(path)
        assert status["archived_events"] == 13
        assert status["hot_events"] == 7
        assert status["chunks"] == 3
    finally:
        ledger.close()


def test_legacy_readers_remain_unchanged_but_compact_payload_requires_registered_decoder(tmp_path):
    from btc5m.storage import enable_compaction, rotate_events

    ledger = populated(tmp_path)
    path = ledger.path
    schema = ledger.db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    reader = Ledger(path, WALLET, readonly=True)
    assert reader.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 19
    reader.close()
    assert (
        ledger.db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall() == schema
    )
    enable_compaction(ledger.db)
    rotate_events(ledger.db, before_ms=2000)
    ledger.close()
    with sqlite3.connect(path) as external:
        with pytest.raises(sqlite3.OperationalError, match="no such function"):
            external.execute("SELECT data FROM events LIMIT 1").fetchone()
    reader = Ledger(path, WALLET, readonly=True)
    try:
        assert len(reader.decisions()) == 10
        assert len(reader.observations()) == 9
    finally:
        reader.close()


def test_failed_rotation_rolls_back_payload_replacement_and_can_retry(tmp_path):
    from btc5m.storage import enable_compaction, rotate_events

    ledger = populated(tmp_path)
    expected = ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall()
    enable_compaction(ledger.db)
    ledger.db.execute("""CREATE TRIGGER deny_archive BEFORE UPDATE ON event_records
        WHEN NEW.chunk_id IS NOT NULL BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        rotate_events(ledger.db, before_ms=2000)
    assert ledger.db.execute("SELECT COUNT(*) FROM event_chunks").fetchone()[0] == 0
    assert ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall() == expected
    ledger.db.execute("DROP TRIGGER deny_archive")
    assert rotate_events(ledger.db, before_ms=2000)["archived_events"] == 19
    assert ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall() == expected
    ledger.close()


@pytest.mark.parametrize("damage", ["payload", "delete", "identity"])
def test_corruption_is_visible_instead_of_skipped_or_returned_as_empty(tmp_path, damage):
    from btc5m.storage import enable_compaction, rotate_events, verify_storage

    ledger = populated(tmp_path)
    enable_compaction(ledger.db)
    rotate_events(ledger.db, before_ms=2000)
    path = ledger.path
    ledger.close()
    with sqlite3.connect(path) as db:
        if damage == "payload":
            db.execute("UPDATE event_chunks SET payload=x'00' WHERE id=1")
        elif damage == "delete":
            db.execute("DELETE FROM event_chunks WHERE id=1")
        else:
            db.execute("UPDATE event_records SET at_ms=0 WHERE id=1")
    reader = Ledger(path, WALLET, readonly=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="user-defined function"):
            reader.db.execute("SELECT data FROM events WHERE id=1").fetchone()
    finally:
        reader.close()
    with pytest.raises(Exception, match="ARCHIVE"):
        verify_storage(path)


def test_cursor_and_max_queries_do_not_decode_or_scan_archive(tmp_path):
    from btc5m.storage import enable_compaction, rotate_events

    ledger = populated(tmp_path, count=10000)
    enable_compaction(ledger.db)
    rotate_events(ledger.db, before_ms=20000, max_chunks=100)
    ledger.db.set_progress_handler(lambda: 1, 1000)
    try:
        assert ledger.db.execute("SELECT MAX(id) FROM events").fetchone()[0] == 10000
        assert ledger.db.execute(
            "SELECT id FROM events WHERE id>9997 ORDER BY id LIMIT 10"
        ).fetchall() == [(9998,), (9999,), (10000,)]
    finally:
        ledger.db.set_progress_handler(None, 0)
        ledger.close()


def test_byte_budget_rotates_recent_events_but_retains_original_json(tmp_path):
    from btc5m.storage import enable_compaction, rotate_events, storage_status

    ledger = populated(tmp_path)
    expected = ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall()
    enable_compaction(ledger.db)
    rotate_events(ledger.db, before_ms=0, max_hot_bytes=1800, chunk_rows=3, max_chunks=20)
    assert storage_status(ledger.path)["hot_payload_bytes"] <= 1800
    assert ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall() == expected
    ledger.close()


def test_copy_reclaims_storage_keeps_source_and_syncs_append_and_measurement_update(tmp_path):
    from btc5m.storage import compact_copy, sync_compact_copy, verify_storage

    ledger = populated(tmp_path, count=3000)
    with ledger.db:
        ledger.db.execute("INSERT INTO measurements VALUES ('price','{\"value\":\"1\"}')")
    source = ledger.path
    before = ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall()
    target = tmp_path / "compact.sqlite"
    report = compact_copy(source, target, before_ms=100000)
    assert report["verified"] is True
    source_bytes = source.stat().st_size + source.with_name(source.name + "-wal").stat().st_size
    assert target.stat().st_size < source_bytes / 2
    assert ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall() == before
    with ledger.db:
        ledger.db.execute("INSERT INTO events(kind,at_ms,data) VALUES ('DECISION',100000,'{}')")
        ledger.db.execute('UPDATE measurements SET data=\'{"value":"2"}\'')
    with pytest.raises(Exception, match="LOCKED"):
        sync_compact_copy(source, target)
    ledger.close()
    assert sync_compact_copy(source, target)["appended_events"] == 1
    reader = Ledger(target, WALLET, readonly=True)
    try:
        assert reader.db.execute("SELECT * FROM events ORDER BY id").fetchall() == before + [
            (3001, "DECISION", 100000, "{}")
        ]
        assert reader.db.execute("SELECT data FROM measurements").fetchall() == [('{"value":"2"}',)]
    finally:
        reader.close()
    assert verify_storage(target)["events"] == 3001


def test_sync_rejects_rewritten_source_prefix_and_destination_reuse(tmp_path):
    from btc5m.storage import compact_copy, sync_compact_copy

    ledger = populated(tmp_path)
    source, target = ledger.path, tmp_path / "compact.sqlite"
    compact_copy(source, target, before_ms=2000)
    with pytest.raises(Exception, match="EXISTS"):
        compact_copy(source, target, before_ms=2000)
    with ledger.db:
        ledger.db.execute("UPDATE events SET data='{}' WHERE id=1")
    ledger.close()
    with pytest.raises(Exception, match="PREFIX"):
        sync_compact_copy(source, target)


def test_live_wallet_cannot_be_migrated(tmp_path):
    from btc5m.storage import enable_compaction

    ledger = Ledger(tmp_path / "funded.sqlite", WALLET, environment="live")
    try:
        with pytest.raises(Exception, match="REQUIRES_PAPER"):
            enable_compaction(ledger.db)
    finally:
        ledger.close()


def test_paper_financial_state_survives_compact_copy_and_post_copy_fill(tmp_path):
    import asyncio

    from test_paper import setup, submit
    from test_strategy import make_snapshot

    from btc5m.storage import compact_copy, sync_compact_copy
    from btc5m.strategy import evaluate

    clock, config, ledger, session, streams, broker = setup(tmp_path)
    order = asyncio.run(
        submit(ledger, broker, evaluate(broker.snapshot, config), session, clock[0])
    )
    target = tmp_path / "compact.sqlite"
    compact_copy(ledger.path, target, before_ms=clock[0] + 10000)
    clock[0] += 1000
    broker.update(make_snapshot(now_ms=clock[0]))
    ledger.apply_evidence(order.intent_id, asyncio.run(broker.reconcile(order)))
    expected = ledger.summary(clock[0])
    expected_position = ledger.open_position()
    assert expected_position is not None
    financial_tables = ("sessions", "intents", "positions", "fills", "accounting", "meta")
    expected_rows = {
        name: ledger.db.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall()
        for name in financial_tables
    }
    source, wallet = ledger.path, ledger.wallet
    ledger.close()
    sync_compact_copy(source, target)
    reader = Ledger(target, wallet, readonly=True)
    try:
        assert reader.summary(clock[0]) == expected
        assert reader.open_position() == expected_position
        for name in financial_tables:
            assert (
                reader.db.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall()
                == expected_rows[name]
            )
    finally:
        reader.close()


def test_committed_rotation_survives_abrupt_process_exit(tmp_path):
    import subprocess
    import sys

    from btc5m.storage import storage_status

    ledger = populated(tmp_path)
    expected = ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall()
    path = ledger.path
    ledger.close()
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            """import os,sys
from pathlib import Path
from btc5m.ledger import Ledger
from btc5m.storage import enable_compaction,rotate_events
ledger=Ledger(Path(sys.argv[1]),sys.argv[2],environment='paper')
enable_compaction(ledger.db)
rotate_events(ledger.db,before_ms=2000,chunk_rows=5,max_chunks=2)
os._exit(17)
""",
            str(path),
            WALLET,
        ],
        check=False,
    )
    assert process.returncode == 17
    assert storage_status(path)["archived_events"] == 10
    ledger = Ledger(path, WALLET, environment="paper")
    try:
        assert ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall() == expected
    finally:
        ledger.close()


def test_dashboard_and_restart_price_query_match_after_compaction(tmp_path, monkeypatch):
    from test_dashboard import STAMP, observation, runtime

    from btc5m.config import Config
    from btc5m.dashboard import DashboardReader
    from btc5m.storage import enable_compaction, rotate_events

    root = runtime(tmp_path, monkeypatch)
    observation(root, kind="spot", price="80000.000000001", source_ms=STAMP - 1000)
    observation(root, kind="twap60", price="79999.123456789", source_ms=STAMP - 1000)
    observation(root, kind="price_conflict", source_ms=STAMP - 2000)
    before = DashboardReader(root, Config()).snapshot(now_ms=STAMP + 1000)
    ledger = Ledger(root / "observations.sqlite", WALLET, environment="paper")
    query = """SELECT data FROM events WHERE kind='PUBLIC_OBSERVATION' AND at_ms>=?
        AND json_extract(data,'$.kind') IN ('spot','twap60','price_conflict') ORDER BY id"""
    history = ledger.db.execute(query, (STAMP - 3000,)).fetchall()
    enable_compaction(ledger.db)
    rotate_events(ledger.db, before_ms=STAMP + 100000)
    assert ledger.db.execute(query, (STAMP - 3000,)).fetchall() == history
    ledger.close()
    after = DashboardReader(root, Config()).snapshot(now_ms=STAMP + 1000)
    for name in ("observation_counts", "feeds", "decisions", "portfolios"):
        assert after[name] == before[name]


def test_independent_reader_observes_atomic_before_then_after_rotation(tmp_path):
    from btc5m.storage import enable_compaction, maintain_storage

    ledger = populated(tmp_path)
    enable_compaction(ledger.db)
    expected = ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall()
    reader = Ledger(ledger.path, WALLET, readonly=True)
    try:
        reader.db.execute("BEGIN")
        assert reader.db.execute("SELECT data FROM events WHERE id=1").fetchone() == (
            expected[0][3],
        )
        maintain_storage(ledger.path, now_ms=2000, hot_ms=0)
        assert reader.db.execute("SELECT * FROM events ORDER BY id").fetchall() == expected
        reader.db.rollback()
        assert reader.db.execute("SELECT * FROM events ORDER BY id").fetchall() == expected
        # Collection remains appendable while the independent maintenance pass runs.
        with ledger.db:
            ledger.db.execute("INSERT INTO events(kind,at_ms,data) VALUES ('DECISION',2001,'{}')")
        assert reader.db.execute("SELECT MAX(id) FROM events").fetchone()[0] == 20
    finally:
        reader.close()
        ledger.close()


def test_unknown_compact_version_open_failure_releases_connection_and_writer_lock(tmp_path):
    import fcntl
    import os
    from pathlib import Path

    from btc5m.storage import StorageError, enable_compaction

    ledger = populated(tmp_path)
    enable_compaction(ledger.db)
    path = ledger.path
    ledger.db.execute("UPDATE event_storage SET version=999")
    ledger.db.commit()
    ledger.close()
    before = len(list(Path("/proc/self/fd").iterdir()))
    for readonly in (True, False, True, False):
        with pytest.raises(StorageError, match="VERSION"):
            Ledger(path, WALLET, readonly=readonly, environment="paper")
    assert len(list(Path("/proc/self/fd").iterdir())) == before
    fd = os.open(str(path) + ".lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)
