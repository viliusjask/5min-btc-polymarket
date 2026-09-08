"""Calibration expiry stays bounded as the public observation journal grows."""

import json
import sqlite3
from pathlib import Path

import pytest
from test_ledger import WALLET
from test_strategy import NOW, make_snapshot

from btc5m.config import Config
from btc5m.ledger import Ledger


def legacy_measurements(path: Path) -> dict[str, str]:
    # Existing collectors have this table and its primary key, but no expiry index.
    rows = {
        f"historical:{i}": json.dumps(
            {
                "kind": "candidate" if i % 2 else "calibration",
                "status": "observed" if i % 3 else "missing",
                "target_ms": NOW - 10000,
                "public_depth": [{"price": ".5", "size": "100"}] * 30,
            }
        )
        for i in range(2048)
    }
    rows.update(
        {
            f"future:{i}": json.dumps(
                {"kind": "calibration", "status": "pending", "target_ms": NOW + 300000 + i}
            )
            for i in range(2048)
        }
    )
    rows["due"] = json.dumps({"kind": "calibration", "status": "pending", "target_ms": NOW - 2001})
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE measurements(key TEXT PRIMARY KEY, data TEXT NOT NULL)")
        db.executemany("INSERT INTO measurements VALUES (?,?)", rows.items())
    return rows


def test_public_tick_expiry_work_stays_bounded_after_existing_journal_reopens(tmp_path):
    path = tmp_path / "ledger.sqlite"
    original = legacy_measurements(path)
    ledger = Ledger(path, WALLET, environment="paper")
    try:
        # Count SQLite VM work, not wall time: a scan of old or future records must
        # fail even on a fast machine. The one due update needs far fewer steps.
        ledger.db.set_progress_handler(lambda: 1, 1000)
        try:
            ledger.record_observation({"kind": "spot", "received_ms": NOW, "price": "80000"})
        finally:
            ledger.db.set_progress_handler(None, 0)
        current = dict(ledger.db.execute("SELECT key,data FROM measurements"))
        due = json.loads(current.pop("due"))
        original.pop("due")
        assert current == original
        assert due == {
            "kind": "calibration",
            "status": "missing",
            "target_ms": NOW - 2001,
            "missing_recorded_ms": NOW,
        }
        assert ledger.observations() == ({"kind": "spot", "received_ms": NOW, "price": "80000"},)
    finally:
        ledger.close()


def test_expiry_keeps_exact_window_and_first_missing_time_across_restart(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = Ledger(path, WALLET, environment="paper")
    snapshot = make_snapshot(now_ms=NOW - 1000)
    try:
        ledger.record_observation(
            {
                "kind": "discovery",
                "slug": snapshot.market.slug,
                "source_ms": snapshot.market.start_s * 1000,
                "received_ms": NOW - 1000,
            }
        )
        ledger.record_clock(NOW + 2000)
        assert ledger.measurements()[0]["status"] == "pending"
    finally:
        ledger.close()
    resumed = Ledger(path, WALLET, environment="paper")
    try:
        resumed.record_clock(NOW + 2001)
        resumed.record_clock(NOW + 9000)
        row = resumed.measurements()[0]
        assert row["status"] == "missing" and row["missing_recorded_ms"] == NOW + 2001
    finally:
        resumed.close()


def test_observed_calibration_leaves_expiry_work_and_cannot_be_marked_missing(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET, environment="paper")
    try:
        ledger.record_snapshot(make_snapshot(now_ms=NOW - 1000), Config(), modes=())
        assert ledger.measurements()[0]["status"] == "pending"
        ledger.record_snapshot(make_snapshot(now_ms=NOW + 2000), Config(), modes=())
        observed = ledger.measurements()[0]
        assert observed["status"] == "observed" and observed["now_ms"] == NOW + 2000
        ledger.record_clock(NOW + 2001)
        assert ledger.measurements()[0] == observed
    finally:
        ledger.close()


def test_failed_expiry_transaction_keeps_pending_work_for_restart(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = Ledger(path, WALLET, environment="paper")
    original = json.dumps({"kind": "calibration", "status": "pending", "target_ms": NOW - 3000})
    try:
        with ledger.db:
            ledger.db.executemany(
                "INSERT INTO measurements VALUES (?,?)", [("first", original), ("second", original)]
            )
            ledger.db.execute(
                "CREATE TRIGGER reject_expiry BEFORE UPDATE ON measurements "
                "WHEN OLD.key='second' BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END"
            )
        with pytest.raises(sqlite3.IntegrityError, match="synthetic write failure"):
            ledger.record_clock(NOW)
        assert list(ledger.db.execute("SELECT data FROM measurements")) == [
            (original,),
            (original,),
        ]
        ledger.db.execute("DROP TRIGGER reject_expiry")
    finally:
        ledger.close()
    resumed = Ledger(path, WALLET, environment="paper")
    try:
        resumed.record_clock(NOW + 1)
        assert [r["status"] for r in resumed.measurements()] == ["missing", "missing"]
        assert [r["missing_recorded_ms"] for r in resumed.measurements()] == [NOW + 1, NOW + 1]
    finally:
        resumed.close()
