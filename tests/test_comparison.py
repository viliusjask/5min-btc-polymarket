"""Public-only CLI lifecycle using real independent ledgers and execution engines."""

import asyncio
import json

import pytest

from btc5m import cli, comparison
from btc5m.config import STRATEGIES
from btc5m.ledger import Ledger
from btc5m.market_data import DataUnavailable
from btc5m.public_archive import PublicArchive


class AnonymousData:
    streams = None
    snapshot_status = {"code": "STREAM_WARMUP", "component": "spot"}

    def __init__(self, config, *, enhanced, observer, capture_flow=False, capture_archive=False):
        assert enhanced
        self.archive = PublicArchive() if capture_archive else None

    async def __aenter__(self):
        return self

    async def close(self):
        pass

    def restore_history(self, records):
        return 0

    def retain_markets(self, markets):
        pass

    def current_snapshot(self):
        return None

    def final_reference(self, market):
        return None

    def final_reference_conflicted(self, market):
        return False

    async def snapshot(self):
        raise DataUnavailable("STREAM_WARMUP")


def forbid_credentials(*args, **kwargs):
    pytest.fail("paper attempted account access")


def test_paper_cli_six_ledgers_no_credentials_resume_and_safe_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_credentials", forbid_credentials)
    monkeypatch.setattr(cli, "create_secure_client", forbid_credentials)
    monkeypatch.setattr(comparison, "MarketData", AnonymousData)
    args = ["paper", "--duration", ".01", "--shutdown-seconds", ".1", "--runtime", str(tmp_path)]
    assert cli.main(args) == 0
    assert cli.main(args) == 0
    report = comparison.paper_report(tmp_path, records=True)
    assert set(report["portfolios"]) == set(STRATEGIES)
    assert report["environment"] == "paper"
    assert report["manifest"]["allocation_per_portfolio"] == "16.66"
    assert report["manifest"]["unused_allocation"] == "0.04"
    assert report["raw_decisions"] == ()
    assert all(row["kind"] in ("paper_run", "paper_heartbeat") for row in report["observations"])
    assert report["observations"][-1]["status"] == "stopped"
    assert all(
        row["simulated_cash"] == 16.66 or str(row["simulated_cash"]) == "16.66"
        for row in report["portfolios"].values()
    )
    assert all(row["orders"] == 0 for row in report["portfolios"].values())
    capsys.readouterr()
    assert cli.main(["report", "--runtime", str(tmp_path), "--records"]) == 0
    assert "observations" in json.loads(capsys.readouterr().out)
    assert cli.main(["stop", "--runtime", str(tmp_path)]) == 0


def test_continuous_paper_has_no_duration_deadline_and_stops_explicitly(tmp_path, monkeypatch):
    monkeypatch.setattr(comparison, "MarketData", AnonymousData)
    monkeypatch.setattr(cli, "load_credentials", forbid_credentials)
    args = cli.parse_args(["paper", "--continuous", "--runtime", str(tmp_path)])
    args.duration = 0.001  # A finite default cannot terminate continuous mode.

    async def run():
        task = asyncio.create_task(
            comparison.run_paper(args, cli.load_config(args.config), lambda r: None)
        )
        await asyncio.sleep(0.4)
        assert not task.done()
        comparison.stop_paper(tmp_path)
        assert await asyncio.wait_for(task, 3) == 0

    asyncio.run(run())
    with pytest.raises(SystemExit):
        cli.parse_args(["paper", "--continuous", "--duration", "10"])
    with pytest.raises(SystemExit):
        cli.parse_args(["run", "--continuous", "--execute"])


def test_paper_cleanup_failure_releases_every_journal_owner(tmp_path, monkeypatch, capsys):
    class BrokenClose(AnonymousData):
        async def close(self):
            raise RuntimeError("PRIVATE_DIAGNOSTIC_NOT_FOR_LOG")

    monkeypatch.setattr(comparison, "MarketData", BrokenClose)
    assert cli.main(["paper", "--duration", ".01", "--runtime", str(tmp_path)]) == 2
    assert "PRIVATE_DIAGNOSTIC" not in capsys.readouterr().err
    master = Ledger(tmp_path / "observations.sqlite", comparison.MASTER_WALLET, environment="paper")
    master.close()
    for i, name in enumerate(STRATEGIES):
        ledger = Ledger(
            tmp_path / name / "ledger.sqlite", "0x" + str(i + 1).zfill(40), environment="paper"
        )
        ledger.close()


def test_exact_tape_keeps_recording_while_http_producer_waits(tmp_path, monkeypatch):
    import time

    from test_strategy import make_snapshot

    from btc5m.lab_tape import Tape

    class SlowHTTP(AnonymousData):
        async def snapshot(self):
            await asyncio.sleep(30)
            raise DataUnavailable("HTTP_UNAVAILABLE")

        def current_snapshot(self):
            return make_snapshot(now_ms=int(time.time() * 1000))

    monkeypatch.setattr(comparison, "MarketData", SlowHTTP)
    args = cli.parse_args(
        ["paper", "--duration", "1.8", "--shutdown-seconds", ".1", "--runtime", str(tmp_path)]
    )
    assert (
        asyncio.run(comparison.run_paper(args, cli.load_config(args.config), lambda r: None)) == 0
    )
    with Tape(tmp_path / "capture.sqlite", readonly=True) as tape:
        frames = list(tape.read_after(0))
        assert len(frames) >= 2
        assert all(f.snapshot is not None for f in frames)


@pytest.mark.parametrize("selection", ["value,value", "not-a-strategy", ""])
def test_paper_rejects_invalid_selection_before_account_or_storage(
    tmp_path, monkeypatch, selection
):
    monkeypatch.setattr(cli, "load_credentials", forbid_credentials)
    directory = tmp_path / "unused"
    assert cli.main(["paper", "--strategies", selection, "--runtime", str(directory)]) == 2
    assert not directory.exists()
