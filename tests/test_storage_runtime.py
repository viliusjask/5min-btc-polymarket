import json

import pytest

from btc5m.ledger import Ledger
from btc5m.storage import StorageError, compact_copy, register_event_reader
from btc5m.storage_runtime import maintain_runtime


def journal(path):
    ledger = Ledger(path, "0x" + "0" * 40, environment="paper")
    with ledger.db:
        ledger.db.executemany(
            "INSERT INTO events(kind,at_ms,data) VALUES ('test',1,?)",
            [(json.dumps({"value": "x" * 10000}),)] * 10,
        )
    ledger.close()


def runtime(tmp_path):
    (tmp_path / "paper.json").write_text(json.dumps({"version": 1, "environment": "paper"}))
    return tmp_path


def test_maintenance_preserves_history_reports_legacy_and_never_touches_capture(tmp_path):
    root = runtime(tmp_path)
    old = root / "source.sqlite"
    journal(old)
    compact_copy(old, root / "observations.sqlite", before_ms=0)
    original = root / "value/ledger.sqlite"
    journal(original)
    capture = root / "capture.sqlite"
    capture.write_bytes(b"untouched source tape")
    result = maintain_runtime(root, now_ms=8000000)
    assert not result["ok"]
    assert result["journals"]["value/ledger.sqlite"]["state"] == "migration_required"
    assert result["journals"]["observations.sqlite"]["status"]["hot_events"] == 0
    assert capture.read_bytes() == b"untouched source tape"
    assert json.loads((root / "storage-report.json").read_text())["completed_ms"]


def test_explicit_new_journal_enable_is_compatible_with_existing_connection(tmp_path):
    root = runtime(tmp_path)
    path = root / "lab/explore/a/ledger.sqlite"
    journal(path)
    ledger = Ledger(path, "0x" + "0" * 40, environment="paper")
    register_event_reader(ledger.db)
    before = ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall()
    result = maintain_runtime(root, now_ms=8000000, enable_new=True)
    assert result["ok"]
    assert ledger.db.execute("SELECT * FROM events ORDER BY id").fetchall() == before
    with ledger.db:
        ledger.db.execute("INSERT INTO events(kind,at_ms,data) VALUES ('new',8000000,'{}')")
    assert ledger.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == len(before) + 1
    ledger.close()


def test_runtime_rejects_nonpaper_manifest_and_symlink_escape(tmp_path):
    (tmp_path / "paper.json").write_text('{"environment":"live","version":1}')
    with pytest.raises(StorageError, match="PAPER_RUNTIME_REQUIRED"):
        maintain_runtime(tmp_path, now_ms=100)
    root = runtime(tmp_path)
    other = tmp_path.parent / (tmp_path.name + "-external.sqlite")
    journal(other)
    (root / "observations.sqlite").symlink_to(other)
    with pytest.raises(StorageError, match="STORAGE_PATH_OUTSIDE_RUNTIME"):
        maintain_runtime(root, now_ms=100, enable_new=True)


def test_broken_journal_does_not_starve_next_one_and_reports_failure(tmp_path):
    root = runtime(tmp_path)
    (root / "observations.sqlite").write_bytes(b"broken sqlite")
    journal(root / "value/ledger.sqlite")
    result = maintain_runtime(root, now_ms=8000000, enable_new=True)
    assert not result["ok"]
    assert result["journals"]["observations.sqlite"]["state"] == "error"
    assert result["journals"]["value/ledger.sqlite"]["status"]["format"] == "compact-events-v1"
