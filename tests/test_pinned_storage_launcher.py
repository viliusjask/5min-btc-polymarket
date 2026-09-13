"""An explicit decoder adapter must leave pinned application identity and SQLite behavior intact."""

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import venv
from pathlib import Path

import pytest

from btc5m.ledger import Ledger
from btc5m.storage import enable_compaction, rotate_events

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pinned_storage_launcher.py"
STORAGE = Path(__file__).resolve().parents[1] / "src" / "btc5m" / "storage.py"
WALLET = "0x" + "0" * 40


def adapter():
    assert SCRIPT.is_file(), "The explicit pinned storage launcher is not implemented"
    spec = importlib.util.spec_from_file_location("pinned_adapter_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_decoder_keeps_nested_factory_transactions_and_exact_rows(tmp_path):
    launcher = adapter()
    module = launcher.load_storage(STORAGE, hashlib.sha256(STORAGE.read_bytes()).hexdigest())
    journal = Ledger(tmp_path / "ledger.sqlite", WALLET, environment="paper")
    journal.db.execute("INSERT INTO events(kind,at_ms,data) VALUES ('DECISION',10,'{}')")
    journal.db.commit()
    enable_compaction(journal.db)
    rotate_events(journal.db, before_ms=20)
    journal.close()

    class Nested(sqlite3.Connection):
        pass

    original = sqlite3.connect
    with launcher.install_decoder(module.register_event_reader):
        with sqlite3.connect(tmp_path / "ledger.sqlite", factory=Nested) as db:
            assert isinstance(db, Nested)
            assert db.execute("SELECT data FROM events").fetchall() == [("{}",)]
            db.execute("SAVEPOINT frame")
            db.execute("INSERT INTO events(kind,at_ms,data) VALUES ('DECISION',11,'{\"a\":1}')")
            db.execute("ROLLBACK TO frame")
            db.execute("RELEASE frame")
            assert db.execute("SELECT COUNT(*) FROM events").fetchone() == (1,)
            db.execute("INSERT INTO events(kind,at_ms,data) VALUES ('DECISION',12,'{\"a\":2}')")
        db.close()
        with sqlite3.connect((tmp_path / "ledger.sqlite").as_uri() + "?mode=ro", uri=True) as db:
            assert db.execute("SELECT id,data FROM events ORDER BY id").fetchall() == [
                (1, "{}"),
                (2, '{"a":2}'),
            ]
        db.close()
    assert sqlite3.connect is original


def test_bad_decoder_hash_is_rejected_before_executing_module(tmp_path):
    launcher = adapter()
    module = tmp_path / "decoder.py"
    marker = tmp_path / "should-not-exist"
    module.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    with pytest.raises(launcher.LauncherError, match="STORAGE_HASH_MISMATCH"):
        launcher.load_storage(module, "0" * 64)
    assert not marker.exists()


@pytest.fixture
def pinned(tmp_path):
    checkout = tmp_path / "checkout"
    source = checkout / "src" / "btc5m"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("")
    (source / "config.py").write_text(
        "import hashlib\nfrom types import SimpleNamespace\n"
        "def load_config(path):\n"
        " return SimpleNamespace(fingerprint=hashlib.sha256(path.read_bytes()).hexdigest())\n"
    )
    (source / "lab_replay.py").write_text(
        "import sqlite3\nclass NestedConnection(sqlite3.Connection):\n pass\n"
    )
    (source / "lab.py").write_text(
        "from pathlib import Path\nimport hashlib\n"
        "SEMANTIC_FILES=('config.py','lab.py','lab_replay.py','cli.py')\n"
        "def implementation_id():\n"
        " p=Path(__file__).parent\n"
        " return hashlib.sha256(b''.join(n.encode()+b'\\0'+(p/n).read_bytes() "
        "for n in SEMANTIC_FILES)).hexdigest()\n"
    )
    (source / "cli.py").write_text(
        "import argparse,json,sqlite3\nfrom btc5m.lab import implementation_id\n"
        "from btc5m.lab_replay import NestedConnection\n"
        "def main():\n"
        " p=argparse.ArgumentParser();p.add_argument('lab');p.add_argument('action');"
        "p.add_argument('--runtime');p.add_argument('--source');p.add_argument('--config');"
        "p.add_argument('--continuous',action='store_true');a=p.parse_args()\n"
        " with sqlite3.connect(a.runtime+'/ledger.sqlite',factory=NestedConnection) as db:\n"
        "  before=db.execute('SELECT id,data FROM events ORDER BY id').fetchall()\n"
        "  db.execute(\"INSERT INTO events(kind,at_ms,data) VALUES ('DECISION',20,'{}')\")\n"
        " print(json.dumps(dict(implementation=implementation_id(),before=before,"
        "nested=isinstance(db,NestedConnection))))\n"
        " db.close();return 0\n"
    )
    (checkout / "pyproject.toml").write_text("[project]\nname='btc5m'\nversion='0.1.0'\n")
    (checkout / "uv.lock").write_text("version = 1\n")
    for command in (
        ["git", "init", "-q", str(checkout)],
        ["git", "-C", str(checkout), "add", "src", "pyproject.toml", "uv.lock"],
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "test: pinned source",
        ],
    ):
        subprocess.run(command, check=True, capture_output=True)
    commit = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    venv.EnvBuilder(with_pip=False).create(checkout / ".venv")
    site = next((checkout / ".venv" / "lib").glob("python*/site-packages"))
    (site / "pinned.pth").write_text(str(checkout / "src") + "\n")
    distribution = site / "fixture-1.0.dist-info"
    distribution.mkdir()
    (distribution / "METADATA").write_text("Metadata-Version: 2.1\nName: fixture\nVersion: 1.0\n")
    implementation = hashlib.sha256(
        b"".join(
            n.encode() + b"\0" + (source / n).read_bytes()
            for n in ("config.py", "lab.py", "lab_replay.py", "cli.py")
        )
    ).hexdigest()
    runtime = tmp_path / "study"
    runtime.mkdir()
    config = tmp_path / "policy.toml"
    config.write_text("# fixture\n")
    tape = tmp_path / "capture.sqlite"
    with sqlite3.connect(tape) as db:
        db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO meta VALUES ('identity','test-tape')")
    with sqlite3.connect(runtime / "study.sqlite") as db:
        db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO meta VALUES ('cursor','17')")
    manifest = dict(
        environment="paper-lab",
        implementation=implementation,
        source=str(tape),
        tape_identity="test-tape",
        base_config=hashlib.sha256(config.read_bytes()).hexdigest(),
    )
    (runtime / "study.json").write_text(json.dumps(manifest))
    ledger = Ledger(runtime / "ledger.sqlite", WALLET, environment="paper")
    ledger.db.execute("INSERT INTO events(kind,at_ms,data) VALUES ('DECISION',10,'{\"old\":1}')")
    ledger.db.commit()
    enable_compaction(ledger.db)
    rotate_events(ledger.db, before_ms=20)
    ledger.close()
    return dict(
        checkout=checkout,
        source=source,
        commit=commit,
        runtime=runtime,
        config=config,
        tape=tape,
        implementation=implementation,
    )


def launch(pinned, *extra):
    assert SCRIPT.is_file(), "The explicit pinned storage launcher is not implemented"
    args = [
        str(pinned["checkout"] / ".venv/bin/python"),
        "-I",
        str(SCRIPT),
        "--checkout",
        str(pinned["checkout"]),
        "--commit",
        pinned["commit"],
        "--storage-module",
        str(STORAGE),
        "--storage-sha256",
        hashlib.sha256(STORAGE.read_bytes()).hexdigest(),
        "--runtime",
        str(pinned["runtime"]),
        "--source",
        str(pinned["tape"]),
        "--config",
        str(pinned["config"]),
        *extra,
    ]
    return subprocess.run(args, text=True, capture_output=True, timeout=20)


def test_pinned_cli_resumes_compact_journal_and_records_separate_provenance(pinned):
    adapter()
    manifest = (pinned["runtime"] / "study.json").read_bytes()
    first = launch(pinned)
    assert first.returncode == 0, first.stderr
    output = json.loads(first.stdout.splitlines()[-1])
    assert output == {
        "implementation": pinned["implementation"],
        "before": [[1, '{"old":1}']],
        "nested": True,
    }
    registrations = list((pinned["runtime"] / "storage-adapters").glob("*.json"))
    assert len(registrations) == 1
    initial = registrations[0].read_bytes()
    second = launch(pinned)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout.splitlines()[-1])["before"] == [[1, '{"old":1}'], [2, "{}"]]
    assert registrations[0].read_bytes() == initial
    assert (pinned["runtime"] / "study.json").read_bytes() == manifest
    identity = json.loads(initial)["identity"]
    assert identity["original_implementation"] == pinned["implementation"]
    assert identity["distributions"] == [["fixture", "1.0"]]
    assert identity["storage_sha256"] == hashlib.sha256(STORAGE.read_bytes()).hexdigest()
    runs = [
        json.loads(x)
        for x in (pinned["runtime"] / "storage-adapter-runs.jsonl").read_text().splitlines()
    ]
    assert [x["event"] for x in runs] == ["started", "finished", "started", "finished"]


@pytest.mark.parametrize("tamper", ["tracked", "untracked", "manifest", "tape", "config"])
def test_identity_mismatch_cannot_launch_or_register(pinned, tamper):
    adapter()
    if tamper == "tracked":
        (pinned["source"] / "cli.py").write_text("raise RuntimeError('must not execute')\n")
    elif tamper == "untracked":
        (pinned["source"] / "surprise.py").write_text("# unexpected importable source\n")
    elif tamper == "manifest":
        path = pinned["runtime"] / "study.json"
        data = json.loads(path.read_text())
        data["implementation"] = "0" * 64
        path.write_text(json.dumps(data))
    elif tamper == "tape":
        with sqlite3.connect(pinned["tape"]) as db:
            db.execute("UPDATE meta SET value='different' WHERE key='identity'")
    else:
        pinned["config"].write_text("# changed policy\n")
    result = launch(pinned)
    assert result.returncode != 0
    assert not (pinned["runtime"] / "storage-adapters").exists()


def test_verify_only_creates_no_provenance_and_corruption_fails_visibly(pinned):
    adapter()
    dry = launch(pinned, "--verify-only")
    assert dry.returncode == 0, dry.stderr
    assert not (pinned["runtime"] / "storage-adapters").exists()
    with sqlite3.connect(pinned["runtime"] / "ledger.sqlite") as db:
        db.execute("UPDATE event_chunks SET payload=x'00'")
    broken = launch(pinned)
    assert broken.returncode != 0
    assert json.loads(broken.stderr)["error"] == "OperationalError"
    runs = [
        json.loads(x)
        for x in (pinned["runtime"] / "storage-adapter-runs.jsonl").read_text().splitlines()
    ]
    assert runs[-1]["event"] == "failed"
