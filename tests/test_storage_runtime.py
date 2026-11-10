import json
import sqlite3

import pytest

from btc5m.ledger import Ledger
from btc5m.storage import StorageError, compact_copy, register_event_reader
from btc5m.storage_runtime import maintain_runtime, paper_journals

VARIANT = "a" * 20


def journal(path):
    ledger = Ledger(path, "0x" + "0" * 40, environment="paper")
    with ledger.db:
        ledger.db.executemany(
            "INSERT INTO events(kind,at_ms,data) VALUES ('test',1,?)",
            [(json.dumps({"value": "x" * 10000}),)] * 10,
        )
    ledger.close()


def runtime(tmp_path):
    (tmp_path / "paper.json").write_text(
        json.dumps({"version": 1, "environment": "paper", "strategies": ["value"]})
    )
    return tmp_path


def study(root, *, phase="explore", variants=None):
    variants = [VARIANT] if variants is None else variants
    root.mkdir(parents=True, exist_ok=True)
    (root / "study.json").write_text(
        json.dumps(
            {
                "version": 1,
                "environment": "paper-lab",
                "variants": [{"ident": ident} for ident in variants],
            }
        )
    )
    with sqlite3.connect(root / "study.sqlite") as db:
        db.execute("CREATE TABLE phases(id TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute(
            "INSERT INTO phases VALUES (?,?)",
            (phase, json.dumps({"id": phase, "variant_ids": variants})),
        )


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
    study(root / "lab")
    path = root / f"lab/explore/{VARIANT}/ledger.sqlite"
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


def test_maintenance_ignores_backup_folders_and_unregistered_variants_and_phases(tmp_path):
    root = runtime(tmp_path)
    study(root / "lab")
    active = [
        root / "observations.sqlite",
        root / "value/ledger.sqlite",
        root / f"lab/explore/{VARIANT}/ledger.sqlite",
    ]
    backups = [
        root / "rollback-backup/ledger.sqlite",
        root / "momentum/ledger.sqlite",  # Supported strategy, but not selected by paper.json.
        root / f"lab/rollback-backup/{VARIANT}/ledger.sqlite",
        root / f"lab/explore/{'b' * 20}/ledger.sqlite",
        root / f"order-flow-lab-backup/explore/{VARIANT}/ledger.sqlite",
    ]
    for path in active + backups:
        journal(path)
    before = {path: path.read_bytes() for path in backups}
    result = maintain_runtime(root, now_ms=8000000, enable_new=True)
    assert result["known_journals"] == 3
    assert result["ok"]
    assert set(paper_journals(root)) == set(active)
    for path in backups:
        assert path.read_bytes() == before[path]
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT type FROM sqlite_master WHERE name='events'").fetchone() == (
                "table",
            )


@pytest.mark.parametrize(
    "strategies", [None, [], ["value", "value"], ["../rollback-backup"], ["invented"], [42]]
)
def test_invalid_strategy_registration_fails_before_any_mutation(tmp_path, strategies):
    root = runtime(tmp_path)
    (root / "paper.json").write_text(
        json.dumps({"version": 1, "environment": "paper", "strategies": strategies})
    )
    path = root / "observations.sqlite"
    journal(path)
    before = path.read_bytes()
    with pytest.raises(StorageError, match="PAPER_RUNTIME"):
        maintain_runtime(root, now_ms=8000000, enable_new=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "fault",
    [
        "phase_path",
        "variant_path",
        "unknown_variant",
        "phase_mismatch",
        "phase_json",
        "registry_json",
        "missing_catalog",
    ],
)
def test_invalid_study_registration_is_not_silently_skipped(tmp_path, fault):
    root = runtime(tmp_path)
    lab = root / "lab"
    study(lab)
    path = root / "observations.sqlite"
    journal(path)
    before = path.read_bytes()
    if fault in ("phase_path", "unknown_variant", "phase_mismatch", "phase_json"):
        data = {
            "id": "../rollback-backup"
            if fault == "phase_path"
            else "other"
            if fault == "phase_mismatch"
            else "explore",
            "variant_ids": ["b" * 20] if fault == "unknown_variant" else [VARIANT],
        }
        with sqlite3.connect(lab / "study.sqlite") as db:
            db.execute(
                "UPDATE phases SET data=?",
                ("{broken" if fault == "phase_json" else json.dumps(data),),
            )
    elif fault == "variant_path":
        (lab / "study.json").write_text(
            json.dumps(
                {"version": 1, "environment": "paper-lab", "variants": [{"ident": "../escape"}]}
            )
        )
    elif fault == "registry_json":
        (lab / "study.json").write_text("{broken")
    else:
        (lab / "study.sqlite").unlink()
    with pytest.raises(StorageError, match="STUDY"):
        maintain_runtime(root, now_ms=8000000, enable_new=True)
    assert path.read_bytes() == before


def test_registered_holdout_and_second_study_are_discovered_without_report_files(tmp_path):
    root = runtime(tmp_path)
    study(root / "lab")
    study(root / "order-flow-lab", variants=["b" * 20])
    with sqlite3.connect(root / "lab/study.sqlite") as db:
        db.execute(
            "INSERT INTO phases VALUES (?,?)",
            ("test-123", json.dumps({"id": "test-123", "variant_ids": [VARIANT]})),
        )
    expected = [
        root / f"lab/explore/{VARIANT}/ledger.sqlite",
        root / f"lab/test-123/{VARIANT}/ledger.sqlite",
        root / f"order-flow-lab/explore/{'b' * 20}/ledger.sqlite",
    ]
    for path in expected:
        journal(path)
    assert paper_journals(root) == sorted(expected)
