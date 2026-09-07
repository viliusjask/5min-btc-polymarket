import json
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from btc5m import cli
from btc5m.dashboard import make_server


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
            assert json.load(response)["status"] == "running"
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
