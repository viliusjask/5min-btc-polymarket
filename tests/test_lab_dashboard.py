import json
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from btc5m import cli
from btc5m.dashboard import lab_profit_context, make_server
from btc5m.lab_tape import Tape


def test_excluded_profit_is_exact_complement_and_not_unfinished_inventory_value():
    row = {
        "realized_pnl": "208.3285917257819272843576865",
        "clean_completed_pnl": "-2.52379200",
        "completed_rounds": 26,
        "clean_completed_rounds": 4,
        "unresolved_rounds": 1,
        "open_basis": "4.93",
    }
    lab_profit_context({"phases": [{"variants": [row]}]})
    assert row["excluded_realized_pnl"] == "210.8523837257819272843576865"
    assert row["flagged_completed_rounds"] == 22
    assert row["unresolved_rounds"] == 1 and row["open_basis"] == "4.93"


def test_lab_endpoint_is_readonly_and_never_opens_real_account(tmp_path):
    class NoAccount:
        def snapshot(self):
            pytest.fail("experiment page accessed real account")

    server = make_server(SimpleNamespace(path=tmp_path), port=0, live=NoAccount())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/lab") as response:
            assert json.load(response)["status"] == "not_started"
        folder = tmp_path / "lab"
        folder.mkdir()
        (folder / "report.json").write_text(
            json.dumps({"environment": "paper-lab", "status": "running", "phases": []})
        )
        with urlopen(base + "/api/lab") as response:
            report = json.load(response)
            assert report["status"] == "running"
            assert report["capture_quality"]["status"] == "not_instrumented"
        with Tape(tmp_path / "capture.sqlite") as tape:
            tape.append(
                1000, None, diagnostic={"code": "STALE_DATA", "component": "spot"}, max_gap_ms=5000
            )
        with urlopen(base + "/api/lab") as response:
            quality = json.load(response)["capture_quality"]
            assert quality["frames"] == 1 and quality["causes"] == {"spot:STALE_DATA": 1}
        assert "capture_quality" not in json.loads((folder / "report.json").read_text())
        other = tmp_path / "order-flow-lab"
        other.mkdir()
        (other / "report.json").write_text(
            json.dumps({"environment": "paper-lab", "suite": "order-flow", "status": "running"})
        )
        with urlopen(base + "/api/lab?suite=order-flow") as response:
            assert json.load(response)["suite"] == "order-flow"
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/lab?suite=../../secrets")
        assert error.value.code == 400
        with urlopen(base + "/lab.js") as response:
            assert response.headers["Content-Type"].startswith("text/javascript")
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/api/lab", data=b"{}", method="POST"))
        assert error.value.code == 405
        (folder / "report.json").write_text("[]")
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/lab")
        assert error.value.code == 503
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_lab_cli_requires_explicit_tape_and_refuses_funded_flags():
    with pytest.raises(SystemExit):
        cli.parse_args(["lab", "run", "--runtime", "lab"])
    with pytest.raises(SystemExit):
        cli.parse_args(
            ["lab", "run", "--runtime", "lab", "--source", "capture.sqlite", "--execute"]
        )
    with pytest.raises(SystemExit):
        cli.parse_args(["lab", "freeze", "--runtime", "lab"])
    args = cli.parse_args(
        ["lab", "run", "--runtime", "lab", "--source", "capture.sqlite", "--continuous"]
    )
    assert args.source == Path("capture.sqlite") and args.continuous
