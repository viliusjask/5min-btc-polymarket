import asyncio
import json
import signal
import threading
from dataclasses import replace
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_comparison import AnonymousData

from btc5m import cli, comparison
from btc5m.config import STRATEGIES, Config
from btc5m.dashboard import DashboardReader, make_server
from btc5m.ledger import Ledger, LedgerError

D = Decimal
STAMP = 1_800_000_000_000


def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(comparison, "MarketData", AnonymousData)
    args = cli.parse_args(["paper", "--duration", ".01", "--runtime", str(tmp_path)])
    asyncio.run(comparison.run_paper(args, Config(), lambda row: None))
    return tmp_path


def test_dashboard_stops_on_first_signal_and_restores_handler(tmp_path, monkeypatch):
    from btc5m import dashboard

    root = runtime(tmp_path, monkeypatch)
    closed = []
    previous = signal.getsignal(signal.SIGTERM)

    class Server:
        server_port = 8765

        def serve_forever(self, **kwargs):
            signal.raise_signal(signal.SIGTERM)

        def server_close(self):
            closed.append(True)

    monkeypatch.setattr(dashboard, "make_server", lambda *a, **kw: Server())
    dashboard.serve_dashboard(root, Config(), 8765)
    assert closed == [True]
    assert signal.getsignal(signal.SIGTERM) is previous


def observation(root, **fields):
    master = Ledger(root / "observations.sqlite", comparison.MASTER_WALLET, environment="paper")
    master.record_observation({"received_ms": STAMP, **fields})
    master.close()


def test_all_portfolios_and_missing_history_are_explained_without_fake_performance(
    tmp_path, monkeypatch
):
    root = runtime(tmp_path, monkeypatch)
    master = Ledger(root / "observations.sqlite", comparison.MASTER_WALLET, environment="paper")
    record = {
        "mode": "value",
        "slug": "btc-updown-5m-1800000000",
        "now_ms": STAMP,
        "decision": {
            "reason": "INSUFFICIENT_HISTORY",
            "features": {
                "long_sampling_status": "EXCESSIVE_GAP",
                "long_max_sample_gap_ms": 25000,
                "long_sample_count": 352,
                "long_requested_sample_count": 361,
                "short_sampling_status": "VALID",
            },
        },
    }
    with master.db:
        master._event("DECISION", STAMP, record)
    master.close()
    before = (root / "observations.sqlite").read_bytes()
    reader = DashboardReader(root, Config())
    data = reader.snapshot(now_ms=STAMP + 60000)
    assert set(data["portfolios"]) == set(STRATEGIES)
    assert data["portfolios"]["value"]["fills"] == 0
    assert data["portfolios"]["value"]["win_rate"] is None
    assert data["decisions"]["value"]["latest"]["category"] == "data"
    assert "gap" in data["decisions"]["value"]["latest"]["explanation"].lower()
    assert data["decisions"]["value"]["history_reasons"]["EXCESSIVE_GAP"] == 1
    assert (root / "observations.sqlite").read_bytes() == before


def test_refresh_only_counts_new_events_and_preserves_capture_time(tmp_path, monkeypatch):
    root = runtime(tmp_path, monkeypatch)
    reader = DashboardReader(root, Config())
    observation(root, kind="spot", source_ms=STAMP - 1000, price="80000")
    first = reader.snapshot(now_ms=STAMP + 100000)
    again = reader.snapshot(now_ms=STAMP + 110000)
    assert again["observation_counts"] == first["observation_counts"]
    assert again["feeds"]["spot"]["source_ms"] == STAMP - 1000
    observation(root, kind="spot", source_ms=STAMP + 1000, price="80001", received_ms=STAMP + 2000)
    last = reader.snapshot(now_ms=STAMP + 120000)
    assert last["observation_counts"]["spot"] == 2
    assert last["feeds"]["spot"]["price"] == "80001"
    assert last["collector"]["status"] != "running"


def test_paper_dashboard_rejects_live_journal_before_exposing_records(tmp_path):
    root = tmp_path
    (root / "paper.json").write_text(
        json.dumps(
            {
                "environment": "paper",
                "version": 1,
                "strategies": ["value"],
                "allocation_per_portfolio": "100",
            }
        )
    )
    ledger = Ledger(root / "observations.sqlite", comparison.MASTER_WALLET)
    ledger.close()
    with pytest.raises(LedgerError, match="EXECUTION_ENVIRONMENT_MISMATCH"):
        DashboardReader(root, Config()).snapshot()


def test_http_serves_dashboard_but_no_paths_secrets_or_mutations(tmp_path, monkeypatch):
    root = runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "load_credentials", lambda *a: pytest.fail("read credentials"))
    server = make_server(DashboardReader(root, Config()), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(url) as response:
            assert b"Paper observatory" in response.read()
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        with urlopen(url + "/api/state") as response:
            state = json.load(response)
            assert state["environment"] == "paper"
        with urlopen(url + "/api/live") as response:
            assert json.load(response)["status"] == "not_configured"
        for path in ("/../.env", "/.env", "/api/stop"):
            with pytest.raises(HTTPError) as exc:
                urlopen(url + path)
            assert exc.value.code == 404
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(url + "/api/state", headers={"Host": "attacker.example"}))
        assert exc.value.code == 403
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(url + "/api/state", data=b"{}", method="POST"))
        assert exc.value.code == 405
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(url + "/api/live", data=b"{}", method="POST"))
        assert exc.value.code == 405
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_recorder_heartbeat_becomes_stale_and_explicit_stop_is_preserved(tmp_path, monkeypatch):
    root = runtime(tmp_path, monkeypatch)
    reader = DashboardReader(root, Config())
    observation(root, kind="paper_run", status="started")
    observation(root, kind="paper_heartbeat", status="running", received_ms=STAMP + 1000)
    assert reader.snapshot(now_ms=STAMP + 2000)["collector"]["status"] == "running"
    assert reader.snapshot(now_ms=STAMP + 20000)["collector"]["status"] == "heartbeat_stale"
    observation(root, kind="paper_run", status="stopped", received_ms=STAMP + 25000)
    assert reader.snapshot(now_ms=STAMP + 26000)["collector"]["status"] == "stopped"


def test_delayed_old_tick_cannot_replace_latest_source_price(tmp_path, monkeypatch):
    root = runtime(tmp_path, monkeypatch)
    observation(root, kind="spot", source_ms=STAMP, price="80000")
    observation(root, kind="spot", source_ms=STAMP - 1000, price="79990", received_ms=STAMP + 1000)
    data = DashboardReader(root, Config()).snapshot(now_ms=STAMP + 2000)
    assert data["feeds"]["spot"]["source_ms"] == STAMP
    assert data["feeds"]["spot"]["price"] == "80000"


def test_dashboard_accounts_for_pair_fills_resolution_and_payout_without_leaking_payloads(
    tmp_path, monkeypatch
):
    from test_paper import aggressive_sell, submit
    from test_strategy import make_snapshot

    from btc5m.pairing import pair_decision
    from btc5m.paper import PaperBroker
    from btc5m.streams import PublicStreams

    async def run(root):
        name = "passive_pairs"
        config = replace(
            Config(),
            strategy=replace(Config().strategy, mode=name),
            risk=replace(Config().risk, allocation_usd=D("16.66")),
        )
        wallet = "0x" + str(STRATEGIES.index(name) + 1).zfill(40)
        ledger = Ledger(root / name / "ledger.sqlite", wallet, environment="paper")
        session = ledger.start_or_resume_session(config)
        ledger.clear_stop_request()
        clock = [make_snapshot().now_ms]
        streams = PublicStreams(config, clock=lambda: clock[0] / 1000)
        broker = PaperBroker(ledger, config, streams=streams, clock=lambda: clock[0] / 1000)
        broker.update(make_snapshot())
        reader = DashboardReader(root, Config())
        for leg in range(2):
            order = await submit(
                ledger,
                broker,
                pair_decision(broker.snapshot, config, ledger.active_positions()),
                session,
                clock[0],
            )
            clock[0] += 1000
            broker.update(make_snapshot(now_ms=clock[0]))
            await broker.reconcile(order)
            clock[0] += 1
            aggressive_sell(streams, order, clock, f"leg-{leg}")
            ledger.apply_evidence(order.intent_id, await broker.reconcile(order))
        with ledger.db:
            ledger.db.execute("UPDATE intents SET signed_payload=?", ("PRIVATE_SIGNED_VALUE",))
        before = reader.snapshot(now_ms=clock[0])["portfolios"][name]
        assert before["fills"] == before["orders"] == 2
        assert all(row["execution_status"] == "FILLED" for row in before["recent_orders"])
        assert D(before["realized_net_pnl"]) == 0
        assert D(before["cash"]) < D("16.66")
        assert all(D(point["pnl"]) == 0 for point in before["pnl_curve"])
        cost = D(before["open_cost_basis"])
        broker.final_reference = lambda market: (D(80000), D(80001))
        clock[0] = order.market.end_s * 1000 + 1
        evidence = await broker.resolve(order.market)
        ledger.apply_resolution(order.market, evidence, clock[0])
        ledger.settle_paper_claims(clock[0] + 1)
        after = reader.snapshot(now_ms=clock[0] + 1)
        report = after["portfolios"][name]
        assert D(report["realized_net_pnl"]) == D(5) - cost
        assert D(report["pnl_curve"][-1]["pnl"]) == D(report["realized_net_pnl"])
        assert report["untimed_accounting"] == 0
        assert report["completed_rounds"] == 1 and report["win_rate"] == 1
        assert "PRIVATE_SIGNED_VALUE" not in json.dumps(after)
        ledger.close()

    asyncio.run(run(runtime(tmp_path, monkeypatch)))


@pytest.mark.parametrize("cause", [None, "QUOTE_EXPIRED"])
def test_cancelled_order_shows_execution_outcome_and_old_model_warning(
    tmp_path, monkeypatch, cause
):
    from test_paper import submit
    from test_strategy import make_snapshot

    from btc5m.pairing import pair_decision
    from btc5m.paper import PaperBroker
    from btc5m.streams import PublicStreams

    root = runtime(tmp_path, monkeypatch)

    async def run():
        name = "passive_pairs"
        base = Config()
        config = replace(
            base,
            strategy=replace(base.strategy, mode=name),
            risk=replace(base.risk, allocation_usd=D("16.66")),
        )
        ledger = Ledger(root / name / "ledger.sqlite", "0x" + str(5).zfill(40), environment="paper")
        session = ledger.start_or_resume_session(config)
        ledger.clear_stop_request()
        clock = [make_snapshot().now_ms]
        streams = PublicStreams(config, clock=lambda: clock[0] / 1000)
        broker = PaperBroker(ledger, config, streams=streams, clock=lambda: clock[0] / 1000)
        broker.update(make_snapshot())
        order = await submit(
            ledger, broker, pair_decision(broker.snapshot, config, ()), session, clock[0]
        )
        clock[0] += 1000
        broker.update(make_snapshot(now_ms=clock[0]))
        await broker.reconcile(order)
        reader = DashboardReader(root, base)
        row = reader.snapshot(now_ms=clock[0])["portfolios"][name]["recent_orders"][0]
        assert row["execution_status"] == "RESTING"
        if cause:
            ledger.record_observation(
                {
                    "kind": "quote_cancel",
                    "received_ms": clock[0],
                    "identity": order.intent_id,
                    "code": cause,
                }
            )
        ledger.request_cancel(order.intent_id, clock[0])
        row = reader.snapshot(now_ms=clock[0])["portfolios"][name]["recent_orders"][0]
        assert row["execution_status"] == "CANCELLING"
        if cause:
            assert row["execution_reason"] == cause
        clock[0] += 6000
        ledger.apply_evidence(
            order.intent_id, await broker.reconcile(ledger.order(order.intent_id))
        )
        state = broker._load(order.intent_id)
        state.pop("matching_model")  # Persisted pre-fix execution, retained without rewriting P/L.
        broker._save(order.intent_id, state)
        data = DashboardReader(root, base).snapshot(now_ms=clock[0])["portfolios"][name]
        row = data["recent_orders"][0]
        assert row["state"] == "SETTLED"  # Internal reconciliation state remains available.
        assert row["execution_status"] == "CANCELLED_UNFILLED"
        assert row["execution_reason"] == (cause or "PAPER_CANCELLED_AFTER_TRADE_GRACE")
        assert data["legacy_matching_orders"] == 1
        assert data["orders"] == 1 and data["fills"] == 0
        ledger.close()

    asyncio.run(run())
