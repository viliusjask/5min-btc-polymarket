import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from test_paper import setup

from btc5m.paper import PaperBroker
from btc5m.service import atomic_json, notify


def test_lab_service_is_continuous_public_only_and_separate_from_collector(tmp_path):
    import runpy

    installer = Path(__file__).resolve().parents[1] / "scripts/install_paper_service.py"
    unit = runpy.run_path(str(installer))["unit"]
    content = unit(
        tmp_path,
        tmp_path / "paper",
        tmp_path / "config.toml",
        lab=True,
        env_file=tmp_path / "never-read.env",
    )
    assert '"lab" "run"' in content and '"--continuous"' in content
    assert "paper/capture.sqlite" in content and "paper/lab" in content
    assert "WatchdogSec=120" in content and "Type=notify" in content
    assert "--env-file" not in content and "--execute" not in content


def test_service_notification_and_atomic_file_preserve_previous_on_failed_write(
    tmp_path, monkeypatch
):
    address = str(tmp_path / "notify.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
        receiver.bind(address)
        receiver.settimeout(1)
        monkeypatch.setenv("NOTIFY_SOCKET", address)
        notify("READY=1\nWATCHDOG=1")
        assert receiver.recv(100) == b"READY=1\nWATCHDOG=1"
    output = tmp_path / "report.json"
    atomic_json(output, {"cash": "100"})
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError):
        atomic_json(output, {"cash": "99"})
    assert json.loads(output.read_text()) == {"cash": "100"}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("apply_before_kill", [False, True])
def test_sigkill_recovers_committed_fill_exactly_once_and_rolls_back_partial_write(
    tmp_path, apply_before_kill
):
    child = r"""
import asyncio, json, os, signal, sys
from pathlib import Path
from test_paper import setup, submit
from test_strategy import make_snapshot
from btc5m.strategy import evaluate
async def run():
    clock, config, ledger, session, streams, broker = setup(Path(sys.argv[1]))
    order = await submit(ledger, broker, evaluate(broker.snapshot, config), session, clock[0])
    clock[0] += 1000
    broker.update(make_snapshot(now_ms=clock[0]))
    evidence = await broker.reconcile(order)
    assert evidence.fills
    if sys.argv[2] == 'True': ledger.apply_evidence(order.intent_id, evidence)
    Path(sys.argv[1], 'receipt.json').write_text(json.dumps({'id':order.intent_id,'cash':str(100-sum(f.principal+f.fee for f in evidence.fills)),'now':clock[0]}))
    ledger.db.execute("INSERT INTO meta VALUES ('uncommitted_probe','must roll back')")
    os.kill(os.getpid(), signal.SIGKILL)
asyncio.run(run())
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent)}
    result = subprocess.run(
        [sys.executable, "-c", child, str(tmp_path), str(apply_before_kill)],
        env=env,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == -signal.SIGKILL, result.stderr.decode()
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    # Reopen with a new process/stream identity. Persisted completed fills remain authoritative.
    clock, config, ledger, session, streams, broker = setup(tmp_path)
    clock[0] = receipt["now"]
    broker = PaperBroker(ledger, config, streams=streams, clock=lambda: clock[0] / 1000)
    assert ledger.db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert (
        ledger.db.execute("SELECT value FROM meta WHERE key='uncommitted_probe'").fetchone() is None
    )
    for _ in range(2):
        evidence = asyncio.run(broker.reconcile(ledger.order(receipt["id"])))
        ledger.apply_evidence(receipt["id"], evidence)
    assert str(ledger.summary(clock[0]).cash) == receipt["cash"]
    assert ledger.db.execute("SELECT count(*) FROM fills").fetchone()[0] == len(evidence.fills)
    ledger.close()


def test_installer_verifies_units_without_touching_the_active_manager_runtime(
    tmp_path, monkeypatch
):
    import runpy
    import shutil

    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd unit verification requires systemd")
    installer = Path(__file__).resolve().parents[1] / "scripts/install_paper_service.py"
    main = runpy.run_path(str(installer))["main"]
    active = tmp_path / "active-runtime"
    private = active / "systemd/private"
    private.parent.mkdir(parents=True)
    private.write_text("existing control socket placeholder")
    runtime = tmp_path / "paper"
    runtime.mkdir()
    (runtime / "paper.json").write_text(json.dumps({"environment": "paper", "version": 1}))
    config = tmp_path / "paper.toml"
    config.touch()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(active))
    monkeypatch.setattr(
        sys, "argv", [str(installer), "--runtime", str(runtime), "--config", str(config)]
    )
    actual_run = subprocess.run
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "systemd-analyze":
            assert kwargs["env"]["XDG_RUNTIME_DIR"] != str(active)
            return actual_run(command, **kwargs)
        return subprocess.CompletedProcess(
            command, 0
        )  # Do not install real user services in tests.

    monkeypatch.setattr(subprocess, "run", run)
    main()
    assert private.read_text() == "existing control socket placeholder"
    assert calls[-1] == [
        "systemctl",
        "--user",
        "enable",
        "btc5m-paper.service",
        "btc5m-dashboard.service",
    ]
    content = (tmp_path / ".config/systemd/user/btc5m-paper.service").read_text()
    assert '"--continuous"' in content and "WatchdogSec=120" in content
    assert '"--execute"' not in content
