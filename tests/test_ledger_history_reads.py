"""Order checks retain exact results without scanning closed archival orders."""

import json
import sqlite3
from dataclasses import asdict, replace
from decimal import Decimal as D

import pytest
from test_ledger import NOW, WALLET, opened, reserve

from btc5m.ledger import Ledger

DAY = NOW // 86400000 * 86400000
INDEXES = """
CREATE INDEX IF NOT EXISTS unresolved_intents ON intents(state)
    WHERE state NOT IN ('SETTLED','REJECTED');
CREATE INDEX IF NOT EXISTS daily_buy_intents ON intents(json_extract(data,'$.created_ms'))
    WHERE json_extract(data,'$.side')='BUY';
"""


def insert(db, intent):
    db.execute(
        "INSERT INTO intents VALUES (?,NULL,?,?,NULL)",
        (intent.intent_id, intent.state, json.dumps(asdict(intent), default=str)),
    )


def legacy_history(tmp_path, *, prior_indexes=False):
    ledger, session = opened(tmp_path)
    template = reserve(ledger, session)
    with ledger.db:
        ledger.db.execute("DELETE FROM intents")
        for i in range(2048):
            insert(
                ledger.db,
                replace(
                    template,
                    intent_id=f"archive-{i}",
                    state="SETTLED" if i % 2 else "REJECTED",
                    confirmed_quantity=D(5),
                    remaining_reserve=D(0),
                    created_ms=DAY - 1 if i % 2 else DAY + 86400000,
                ),
            )
        ledger.db.execute("DROP INDEX IF EXISTS unresolved_intents")
        ledger.db.execute("DROP INDEX IF EXISTS daily_buy_intents")
    if prior_indexes:
        # No ANALYZE: SQLite prefers the full table scan for ORDER BY rowid unless
        # the reader makes the sparse access path explicit.
        ledger.db.executescript(INDEXES)
    path = ledger.path
    ledger.close()
    return path, template


@pytest.mark.parametrize("prior_indexes", [False, True])
def test_unresolved_order_work_is_bounded_and_keeps_insertion_order(tmp_path, prior_indexes):
    path, template = legacy_history(tmp_path, prior_indexes=prior_indexes)
    expected = []
    with sqlite3.connect(path) as db:
        for ident, state in zip(
            ["z", "a", "middle", "b", "last"],
            ["UNKNOWN", "RESERVED", "ACK", "SUBMITTING", "PREPARED"],
            strict=True,
        ):
            order = replace(template, intent_id=ident, state=state, created_ms=DAY - 1000)
            insert(db, order)
            expected.append(order)
    ledger = Ledger(path, WALLET)
    try:
        ledger.db.set_progress_handler(lambda: 1, 1000)
        try:
            assert ledger.unresolved_orders() == tuple(expected)
        finally:
            ledger.db.set_progress_handler(None, 0)
    finally:
        ledger.close()


@pytest.mark.parametrize("prior_indexes", [False, True])
def test_daily_entry_work_ignores_archive_and_keeps_boundaries_and_all_sessions(
    tmp_path, prior_indexes
):
    path, template = legacy_history(tmp_path, prior_indexes=prior_indexes)
    with sqlite3.connect(path) as db:
        for ident, slug, created, state, filled, side, session in [
            ("at-start", "first", DAY, "SETTLED", "5", "BUY", "older-session"),
            ("same-round", "first", DAY + 1, "ACK", "0", "BUY", "current-session"),
            ("at-end", "second", DAY + 86399999, "SETTLED", "1E-30", "BUY", "older-session"),
            ("rejected-filled", "third", DAY + 1, "REJECTED", "1", "BUY", "older-session"),
            ("cancelled", "cancelled", DAY + 1, "SETTLED", "0", "BUY", "current-session"),
            ("sell", "sell", DAY + 1, "ACK", "1", "SELL", "current-session"),
        ]:
            insert(
                db,
                replace(
                    template,
                    intent_id=ident,
                    session_id=session,
                    market=replace(template.market, slug=slug),
                    state=state,
                    confirmed_quantity=D(filled),
                    side=side,
                    created_ms=created,
                ),
            )
    ledger = Ledger(path, WALLET)
    try:
        ledger.db.set_progress_handler(lambda: 1, 1000)
        try:
            summary = ledger.summary(NOW)
        finally:
            ledger.db.set_progress_handler(None, 0)
        assert summary.daily_entries == 3
        assert [o.intent_id for o in summary.unresolved_orders] == ["same-round", "sell"]
    finally:
        ledger.close()


def test_legacy_readonly_journal_is_unchanged_and_writer_migration_preserves_results(tmp_path):
    path, template = legacy_history(tmp_path)
    with sqlite3.connect(path) as db:
        insert(db, replace(template, intent_id="pending", state="UNKNOWN", created_ms=NOW))
        before = db.execute("SELECT id,state,data FROM intents ORDER BY rowid").fetchall()
        schema = db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    old_reader = Ledger(path, WALLET, readonly=True)
    try:
        expected = old_reader.summary(NOW)
        assert expected.daily_entries == 1
        assert [o.intent_id for o in expected.unresolved_orders] == ["pending"]
        assert (
            old_reader.db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
            == schema
        )
        writer = Ledger(path, WALLET)
        try:
            assert writer.summary(NOW) == expected
            assert (
                writer.db.execute("SELECT id,state,data FROM intents ORDER BY rowid").fetchall()
                == before
            )
            # A reader opened before migration can continue using its original path.
            assert old_reader.summary(NOW) == expected
        finally:
            writer.close()
    finally:
        old_reader.close()
    migrated_reader = Ledger(path, WALLET, readonly=True)
    try:
        migrated_reader.db.set_progress_handler(lambda: 1, 1000)
        try:
            assert migrated_reader.summary(NOW) == expected
        finally:
            migrated_reader.db.set_progress_handler(None, 0)
    finally:
        migrated_reader.close()


def test_order_state_and_day_index_changes_rollback_and_survive_restart(tmp_path):
    ledger, session = opened(tmp_path)
    order = reserve(ledger, session)
    assert ledger.summary(NOW).daily_entries == 1
    ledger.db.execute("BEGIN")
    ledger._save(replace(order, state="SETTLED"))
    assert not ledger.unresolved_orders()
    assert ledger.summary(NOW).daily_entries == 0
    ledger.db.rollback()
    assert ledger.unresolved_orders() == (order,)
    ledger.db.execute("BEGIN")
    ledger._save(replace(order, state="SETTLED", confirmed_quantity=D(5), created_ms=DAY - 1))
    assert ledger.summary(NOW).daily_entries == 0
    ledger.db.rollback()
    assert ledger.summary(NOW).daily_entries == 1
    with ledger.db:
        ledger._save(replace(order, state="SETTLED", confirmed_quantity=D(5)))
    ledger.close()
    resumed = Ledger(tmp_path / "ledger.sqlite", WALLET)
    try:
        assert not resumed.unresolved_orders()
        assert resumed.summary(NOW).daily_entries == 1
    finally:
        resumed.close()
