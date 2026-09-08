import json
import logging
import sqlite3
import threading
import time
from contextlib import closing
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from test_dashboard import STAMP, observation, runtime

from btc5m import comparison
from btc5m.config import Config
from btc5m.dashboard import DashboardReader, make_server
from btc5m.ledger import Ledger


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("dashboard history did not advance without another request")


def append_history(root, count):
    ledger = Ledger(root / "observations.sqlite", comparison.MASTER_WALLET, environment="paper")
    with ledger.db:
        ledger.db.executemany(
            "INSERT INTO events(kind,at_ms,data) VALUES ('PUBLIC_OBSERVATION',?,?)",
            (
                (
                    STAMP + index,
                    json.dumps(
                        {
                            "kind": "spot",
                            "source_ms": STAMP - 1000 + index,
                            "received_ms": STAMP + index,
                            "price": str(80000 + index),
                        }
                    ),
                )
                for index in range(count)
            ),
        )
    maximum = ledger.db.execute("SELECT MAX(id) FROM events").fetchone()[0]
    ledger.close()
    return maximum


def test_one_http_request_catches_up_history_and_keeps_following_without_polling(
    tmp_path, monkeypatch
):
    root = runtime(tmp_path, monkeypatch)
    maximum = append_history(root, 210005)
    reader = DashboardReader(root, Config())
    server = make_server(reader, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/state"
    try:
        with urlopen(url) as response:
            first = json.load(response)
        assert first["observation_counts"]["spot"] == (
            first["collector"]["events_loaded"] - (maximum - 210005)
        )
        frozen = json.dumps(first, sort_keys=True)
        wait_until(lambda: reader.cursor == maximum)
        assert reader.observations["spot"] == 210005
        assert reader.feeds["spot"]["source_ms"] == STAMP + 209004
        assert json.dumps(first, sort_keys=True) == frozen
        observation(root, kind="paper_heartbeat", status="running", received_ms=STAMP + 300000)
        wait_until(lambda: reader.heartbeat.get("received_ms") == STAMP + 300000)
        current = reader.snapshot(now_ms=STAMP + 300001)
        assert current["collector"]["caught_up"] is True
        assert current["collector"]["status"] == "running"
        assert current["observation_counts"]["spot"] == 210005
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_server_close_stops_an_active_history_batch_and_cannot_restart_it(tmp_path, monkeypatch):
    root = runtime(tmp_path, monkeypatch)
    append_history(root, 10)
    reader = DashboardReader(root, Config())
    consumed = threading.Event()
    release = threading.Event()
    consume = reader._consume

    def slow_consume(*args):
        consumed.set()
        assert release.wait(3)
        consume(*args)

    monkeypatch.setattr(reader, "_consume", slow_consume)
    server = make_server(reader, port=0)
    try:
        assert consumed.wait(3), "server never started history catch-up"
        closer = threading.Thread(target=server.server_close)
        closer.start()
        release.set()
        closer.join(timeout=3)
        assert not closer.is_alive()
        assert reader._worker is not None and not reader._worker.is_alive()
        cursor = reader.cursor
        observation(root, kind="spot", source_ms=STAMP + 9000, price="90000")
        reader.start()
        assert reader.cursor == cursor
        assert not reader._worker.is_alive()
    finally:
        release.set()
        server.server_close()


def test_worker_reports_failure_and_recovers_without_duplicate_counts(
    tmp_path, monkeypatch, caplog
):
    root = runtime(tmp_path, monkeypatch)
    append_history(root, 4)
    reader = DashboardReader(root, Config())
    server = make_server(reader, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    caplog.set_level(logging.WARNING, logger="btc5m.dashboard")
    try:
        wait_until(lambda: reader.observations["spot"] == 4)
        # This invalid historical record fails after incrementing the anchor count.
        observation(root, kind="anchor")
        wait_until(lambda: "PAPER_HISTORY_UNAVAILABLE" in caplog.text)
        with pytest.raises(HTTPError) as exc:
            urlopen(f"http://127.0.0.1:{server.server_port}/api/state")
        assert exc.value.code == 503
        assert str(root) not in caplog.text
        ledger = Ledger(root / "observations.sqlite", comparison.MASTER_WALLET, environment="paper")
        with ledger.db:
            ledger.db.execute(
                "UPDATE events SET data=? WHERE id=(SELECT MAX(id) FROM events)",
                (json.dumps({"kind": "anchor", "slug": "repaired", "received_ms": STAMP}),),
            )
        ledger.close()
        wait_until(lambda: "repaired" in reader.anchors)
        result = reader.snapshot(now_ms=STAMP + 1000)
        assert result["collector"]["caught_up"] is True
        assert result["observation_counts"]["spot"] == 4
        assert result["observation_counts"]["anchor"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize("replace_file", [False, True])
def test_worker_resets_history_after_journal_replacement_or_truncation(
    tmp_path, monkeypatch, replace_file
):
    root = runtime(tmp_path, monkeypatch)
    append_history(root, 7)
    reader = DashboardReader(root, Config())
    server = make_server(reader, port=0)
    try:
        wait_until(lambda: reader.observations["spot"] == 7)
        target = root / "observations.sqlite"
        replacement = root / "replacement.sqlite" if replace_file else target
        if replace_file:
            with (
                closing(sqlite3.connect(target)) as source,
                closing(sqlite3.connect(replacement)) as destination,
            ):
                source.backup(destination)
        ledger = Ledger(replacement, comparison.MASTER_WALLET, environment="paper")
        with ledger.db:
            ledger.db.execute("DELETE FROM events")
        ledger.record_observation(
            {"kind": "spot", "source_ms": STAMP - 1000, "received_ms": STAMP, "price": "42"}
        )
        ledger.close()
        if replace_file:
            replacement.replace(target)
        wait_until(lambda: reader.feeds.get("spot", {}).get("price") == "42")
        assert reader.observations["spot"] == 1
        assert reader.feeds["spot"]["source_ms"] == STAMP - 1000
        assert reader.cursor == 1
    finally:
        server.server_close()
