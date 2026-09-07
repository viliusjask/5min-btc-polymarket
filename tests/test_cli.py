"""Operator boundaries, durable reports and independent data publication."""

import asyncio
import subprocess
import sys
from dataclasses import replace

import pytest
from test_broker import CREDS, KEY, WALLET, Venue, broker_fixture
from test_engine import confirmation_snapshot, held
from test_ledger import NOW

from btc5m import cli
from btc5m.config import Config
from btc5m.ledger import Ledger


def test_help_and_missing_execute_never_load_credentials(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("credential read attempted")

    monkeypatch.setattr(cli, "load_credentials", forbidden)
    assert cli.main(["--help"]) == 0
    assert "observe" in capsys.readouterr().out
    assert cli.main(["run", "--duration", "1"]) == 2
    assert "--execute" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ["observe", "--execute"],
        ["run", "--execute", "--dur", "1"],
        ["observe", "--env-file", "nope"],
        ["doctor", "--env-file", "nope"],
        ["run", "--execute", "--duration", "nan"],
    ],
)
def test_unknown_abbreviated_or_inapplicable_flags_reject(args):
    assert cli.main(args) == 2


def test_config_path_does_not_follow_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.default_config().is_file()
    assert cli.default_config() != tmp_path / "config/btc5m.toml"


def test_env_file_is_data_never_shell(tmp_path):
    marker = tmp_path / "executed"
    file = tmp_path / "credentials"
    file.write_text(
        f'POLYMARKET_PRIVATE_KEY="$(touch {marker})"\nPOLYMARKET_FUNDER={WALLET}\nPOLYMARKET_API_KEY=k\nPOLYMARKET_API_SECRET=s\nPOLYMARKET_API_PASSPHRASE=p\n'
    )
    result = cli.load_credentials(file, None)
    assert result.private_key == f"$(touch {marker})"
    assert not marker.exists()
    assert result.wallet == WALLET.lower()
    assert "$(touch" not in repr(result)
    file.write_text("PATH=/tmp\n")
    with pytest.raises(cli.CLIError, match="ENV_FILE_UNSUPPORTED_KEY"):
        cli.load_credentials(file, None)
    file.write_text("export POLYMARKET_API_KEY=hello\n")
    with pytest.raises(cli.CLIError):
        cli.load_credentials(file, None)


@pytest.mark.parametrize("excursion", ["missing", "rejection", "reference", "stream", "conflict"])
def test_latest_cell_preserves_overwritten_invalidation(tmp_path, excursion):
    ledger = Ledger(tmp_path / "observe.sqlite", cli.ANONYMOUS_WALLET)
    now = [NOW]
    cell = cli.LatestInput(ledger, Config(), clock=lambda: now[0] / 1000, emit=lambda record: None)
    cell.publish(confirmation_snapshot(), cell.read().invalidation_generation)
    before = cell.read().invalidation_generation
    if excursion == "missing":
        cell.invalidate("NO_SNAPSHOT")
    elif excursion == "rejection":
        cell.publish(
            replace(
                confirmation_snapshot(),
                spot=replace(
                    confirmation_snapshot().spot,
                    price=confirmation_snapshot().market.reference_price,
                ),
            ),
            before,
        )
    elif excursion == "reference":
        snap = confirmation_snapshot()
        cell.publish(
            replace(
                snap, market=replace(snap.market, reference_price=snap.market.reference_price + 1)
            ),
            before,
        )
    else:
        cell.observe(
            {
                "kind": "stream_unavailable" if excursion == "stream" else "price_conflict",
                "stream": "spot",
                "received_ms": NOW,
                "code": "SYNTHETIC",
            }
        )
    now[0] += 1000
    cell.publish(confirmation_snapshot(now[0]), cell.read().invalidation_generation)
    assert cell.read().snapshot is not None
    assert cell.read().invalidation_generation > before
    ledger.close()


def test_cell_latches_inflight_gap_and_ignores_nonselected_rejection(tmp_path):
    ledger = Ledger(tmp_path / "observe.sqlite", cli.ANONYMOUS_WALLET)
    cell = cli.LatestInput(ledger, Config(), clock=lambda: NOW / 1000, emit=lambda record: None)
    # Value is eligible, momentum's .70 minimum rejects this .65 ask.
    snap = confirmation_snapshot(ask=".65")
    cell.publish(snap, 0)
    assert cell.read().invalidation_generation == 0
    cell.publish(snap, 0)
    assert cell.read().invalidation_generation == 0
    started = cell.read().invalidation_generation
    cell.observe(
        {"kind": "stream_unavailable", "stream": "twap60", "received_ms": NOW, "code": "GAP"}
    )
    cell.publish(snap, started)
    assert cell.read().snapshot is None
    assert len(ledger.decisions()) == 6  # paired recording remains independent of execution latch
    ledger.close()


def test_cell_silent_aging_invalidates_at_consumption(tmp_path):
    ledger = Ledger(tmp_path / "observe.sqlite", cli.ANONYMOUS_WALLET)
    now = [NOW]
    cell = cli.LatestInput(ledger, Config(), clock=lambda: now[0] / 1000, emit=lambda record: None)
    cell.publish(confirmation_snapshot(), 0)
    now[0] += 6000
    assert cell.read().snapshot is None and cell.read().invalidation_generation == 1
    ledger.close()


def test_stop_status_report_work_with_owner_and_preserve_inventory(tmp_path, monkeypatch, capsys):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        held(ledger, session, venue)
        args = ["--runtime", str(ledger.path), "--wallet", WALLET]
        assert await cli.async_main(cli.parse_args(["stop", *args])) == 0
        assert ledger.stop_requested() and ledger.open_position().quantity == 5
        assert await cli.async_main(cli.parse_args(["report", *args])) == 0
        output = capsys.readouterr().out
        assert '"cash": "96.4265"' in output and '"quantity": "5"' in output
        assert "signed_payload" not in output
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_report_after_abrupt_termination(tmp_path, capsys):
    path = tmp_path / "ledger.sqlite"
    code = """import os,sys
from pathlib import Path
from btc5m.ledger import Ledger
from btc5m.config import Config
ledger=Ledger(Path(sys.argv[1]), sys.argv[2])
ledger.start_or_resume_session(Config())
ledger.record_observation({"kind":"cli_lifecycle","received_ms":1,"code":"STARTED"})
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", code, str(path), WALLET], check=True)
    assert cli.main(["report", "--runtime", str(path), "--wallet", WALLET]) == 0
    assert '"STARTED"' in capsys.readouterr().out


def test_mutating_reconcile_refuses_owner_before_account_setup(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite"
    owner = Ledger(path, WALLET)
    owner.start_or_resume_session(Config())
    monkeypatch.setattr(cli, "runtime_path", lambda *args: path)
    monkeypatch.setattr(cli, "load_credentials", lambda *args: cli.Credentials(KEY, WALLET, CREDS))

    async def forbidden(**kwargs):
        pytest.fail("account construction before exclusive lock")

    monkeypatch.setattr(cli, "create_secure_client", forbidden)
    assert cli.main(["reconcile"]) == 2
    owner.close()


def test_first_account_doctor_uses_temporary_state_without_session(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, fixture_ledger, _ = await broker_fixture(tmp_path / "fixture", monkeypatch, venue)
        live_path = tmp_path / "live" / "ledger.sqlite"
        monkeypatch.setattr(cli, "runtime_path", lambda *args: live_path)
        monkeypatch.setattr(
            cli, "load_credentials", lambda *args: cli.Credentials(KEY, WALLET, CREDS)
        )

        async def client(**kwargs):
            return broker.client

        monkeypatch.setattr(cli, "create_secure_client", client)
        real_broker = cli.Broker

        def construct(client, rpc, ledger, config):
            assert ledger.summary().session_id is None and ledger.summary().cash is None
            assert ledger.path != live_path
            return real_broker(
                client, broker.rpc, ledger, config, http=broker.http, clock=broker.clock
            )

        monkeypatch.setattr(cli, "Broker", construct)
        assert await cli.async_main(cli.parse_args(["doctor", "--account"])) == 0
        assert not live_path.exists() and not live_path.parent.exists()
        fixture_ledger.close()

    asyncio.run(run())


def test_stop_arriving_during_setup_survives_and_prevents_entry(tmp_path, monkeypatch):
    async def run():
        path = tmp_path / "live.sqlite"
        with_ledger = Ledger(path, WALLET)
        with_ledger.start_or_resume_session(Config())
        with_ledger.request_stop()
        with_ledger.close()
        monkeypatch.setattr(cli, "runtime_path", lambda *args: path)
        monkeypatch.setattr(
            cli, "load_credentials", lambda *args: cli.Credentials(KEY, WALLET, CREDS)
        )

        async def setup(**kwargs):
            reader = Ledger(path, WALLET, readonly=True)
            assert not reader.stop_requested()
            reader.close()
            Ledger.request_stop_at(path)
            await asyncio.sleep(0)
            raise cli.BrokerError("SYNTHETIC_SETUP_FAILURE")

        monkeypatch.setattr(cli, "create_secure_client", setup)
        args = cli.parse_args(["run", "--execute", "--duration", "1"])
        with pytest.raises(cli.BrokerError, match="SYNTHETIC_SETUP_FAILURE"):
            await cli.async_main(args)
        reader = Ledger(path, WALLET, readonly=True)
        assert reader.stop_requested()
        assert any(r.get("code") == "SYNTHETIC_SETUP_FAILURE" for r in reader.observations())
        reader.close()

    asyncio.run(run())


def test_observe_and_public_doctor_use_only_anonymous_adapter(tmp_path, monkeypatch):
    from test_market_data import Venue as PublicVenue

    from btc5m.market_data import MarketData

    async def run():
        venue = PublicVenue()

        async def forbidden(**kwargs):
            pytest.fail("secure client constructed")

        monkeypatch.setattr(cli, "create_secure_client", forbidden)
        monkeypatch.setattr(cli, "load_credentials", lambda *args: pytest.fail("credentials read"))

        def data(config, *, observer):
            return MarketData(
                config,
                client=venue.client,
                http_client=venue.http,
                clock=venue.clock.wall,
                monotonic=venue.clock.mono,
                observer=observer,
            )

        monkeypatch.setattr(cli, "MarketData", data)
        # Queue real attributed RTDS models before the streams start.
        await venue.emit()
        path = tmp_path / "anonymous.sqlite"
        args = cli.parse_args(["observe", "--duration", ".02", "--runtime", str(path)])
        assert await cli.async_main(args) == 0
        reader = Ledger(path, cli.ANONYMOUS_WALLET, readonly=True)
        assert reader.summary().session_id is None
        assert any(row["kind"] == "spot" for row in reader.observations())
        reader.close()

    asyncio.run(run())


def test_observe_rejects_live_namespace_before_opening(tmp_path, monkeypatch):
    path = tmp_path / ".runtime" / WALLET / "ledger.sqlite"
    monkeypatch.setattr(cli, "runtime_path", lambda *args: path)
    assert cli.main(["observe", "--duration", ".01", "--runtime", str(path)]) == 2
    assert not path.exists()


def test_run_startup_config_conflict_is_recorded_and_releases_owner(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        held(ledger, session, venue)
        path = ledger.path
        ledger.close()
        await broker.close()
        monkeypatch.setattr(cli, "runtime_path", lambda *args: path)
        monkeypatch.setattr(
            cli, "load_credentials", lambda *args: cli.Credentials(KEY, WALLET, CREDS)
        )
        config = replace(Config(), risk=replace(Config().risk, max_entries_per_day=10))
        with pytest.raises(cli.LedgerError):
            await cli.run_live(cli.parse_args(["run", "--execute", "--duration", "1"]), config)
        reopened = Ledger(path, WALLET)
        assert any(r["kind"] == "cli_lifecycle" for r in reopened.observations())
        assert reopened.stop_requested()
        reopened.close()

    asyncio.run(run())


def test_cleanup_does_not_leave_other_tasks_running_after_failure():
    async def run():
        async def failing():
            raise RuntimeError("synthetic")

        task = asyncio.create_task(failing())
        await asyncio.sleep(0)
        await cli._cancel(task)
        assert task.done()

    asyncio.run(run())


def test_second_process_run_refuses_same_owner(tmp_path):
    path = tmp_path / WALLET / "ledger.sqlite"
    owner = Ledger(path, WALLET)
    owner.start_or_resume_session(Config())
    code = """import sys
from pathlib import Path
from btc5m import cli
from polymarket.models.clob import ApiKeyCreds
cli.runtime_path=lambda *args: Path(sys.argv[1])
cli.load_credentials=lambda *args: cli.Credentials("0x"+"01"*32, sys.argv[2], ApiKeyCreds(key="fixture",secret="fixture",passphrase="fixture"))
raise SystemExit(cli.main(["run","--execute","--duration","1"]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(path), WALLET], capture_output=True, text=True
    )
    assert result.returncode == 2 and result.stderr.strip() == "WALLET_LOCKED"
    assert not owner.stop_requested()
    owner.close()


def test_account_doctor_can_read_owned_runtime_without_adopting_cash(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, _ = await broker_fixture(tmp_path, monkeypatch, venue)
        ledger.request_stop()
        before = ledger.summary()
        monkeypatch.setattr(cli, "runtime_path", lambda *args: ledger.path)
        monkeypatch.setattr(
            cli, "load_credentials", lambda *args: cli.Credentials(KEY, WALLET, CREDS)
        )

        async def client(**kwargs):
            return broker.client

        monkeypatch.setattr(cli, "create_secure_client", client)
        real_broker = cli.Broker
        monkeypatch.setattr(
            cli,
            "Broker",
            lambda client, rpc, journal, config: real_broker(
                client, broker.rpc, journal, config, http=broker.http, clock=broker.clock
            ),
        )
        assert await cli.async_main(cli.parse_args(["doctor", "--account"])) == 0
        assert ledger.summary() == before
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_bounded_run_shutdown_retains_unknown_order_and_releases_owner(
    tmp_path, monkeypatch, cancel
):
    import httpx
    from test_market_data import Venue as PublicVenue

    from btc5m.engine import Engine
    from btc5m.market_data import MarketData

    async def run():
        venue = Venue()
        venue.post_loss = True
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        engine = Engine(broker, ledger, Config(), session)
        await engine.step(confirmation_snapshot(), None, NOW)
        venue.now += 1000
        await engine.step(confirmation_snapshot(venue.now), None, venue.now)
        path = ledger.path
        ledger.close()
        await broker.close()
        monkeypatch.setattr(cli, "runtime_path", lambda *args: path)
        monkeypatch.setattr(
            cli, "load_credentials", lambda *args: cli.Credentials(KEY, WALLET, CREDS)
        )
        public = PublicVenue()
        monkeypatch.setattr(
            cli,
            "MarketData",
            lambda config, observer: MarketData(
                config,
                client=public.client,
                http_client=public.http,
                clock=public.clock.wall,
                observer=observer,
            ),
        )
        real_broker = cli.Broker
        monkeypatch.setattr(
            cli,
            "Broker",
            lambda client, rpc, journal, config: real_broker(
                client, rpc, journal, config, clock=lambda: venue.now / 1000
            ),
        )
        reading = asyncio.Event()

        async def send(client, request, **kwargs):
            if cancel and request.url.path.startswith("/data/order/"):
                reading.set()
                await asyncio.Event().wait()
            return await venue.send(client, request, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "send", send)
        task = asyncio.create_task(
            cli.async_main(
                cli.parse_args(
                    [
                        "run",
                        "--execute",
                        "--duration",
                        "30" if cancel else ".01",
                        "--shutdown-seconds",
                        ".01",
                    ]
                )
            )
        )
        try:
            if cancel:
                await asyncio.wait_for(reading.wait(), 2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 0.5)
            else:
                assert await task == 2
        finally:
            await cli._cancel(task)
        reopened = Ledger(path, WALLET)
        assert reopened.stop_requested()
        assert reopened.unresolved_orders()[0].state == "UNKNOWN"
        assert reopened.summary().risk_reserve == D("4.5582")
        assert venue.posts == 1
        reopened.close()

    from decimal import Decimal as D

    asyncio.run(run())


def test_anonymous_discovery_records_config_without_account_session(tmp_path, monkeypatch):
    from test_market_data import Venue as PublicVenue

    from btc5m.market_data import MarketData

    async def run():
        venue = PublicVenue()
        monkeypatch.setattr(
            cli,
            "MarketData",
            lambda config, observer: MarketData(
                config,
                client=venue.client,
                http_client=venue.http,
                clock=venue.clock.wall,
                observer=observer,
            ),
        )
        path = tmp_path / "anonymous.sqlite"
        assert (
            await cli.async_main(
                cli.parse_args(["observe", "--duration", ".02", "--runtime", str(path)])
            )
            == 0
        )
        reader = Ledger(path, cli.ANONYMOUS_WALLET, readonly=True)
        assert reader.measurements()[0]["config_fingerprint"] == Config().fingerprint
        assert reader.summary().session_id is None and reader.summary().cash is None
        assert reader.decisions() == ()
        reader.close()

    asyncio.run(run())


def test_reconcile_releases_journal_even_if_transport_close_fails(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, _ = await broker_fixture(tmp_path, monkeypatch, venue)
        path = ledger.path
        ledger.close()
        monkeypatch.setattr(cli, "runtime_path", lambda *args: path)
        monkeypatch.setattr(
            cli, "load_credentials", lambda *args: cli.Credentials(KEY, WALLET, CREDS)
        )

        async def client(**kwargs):
            return broker.client

        monkeypatch.setattr(cli, "create_secure_client", client)

        def construct(client, rpc, journal, config):
            broker.ledger = journal
            return broker

        monkeypatch.setattr(cli, "Broker", construct)
        original = broker.close

        async def close():
            await original()
            raise cli.BrokerError("SYNTHETIC_CLOSE_FAILURE")

        monkeypatch.setattr(broker, "close", close)
        with pytest.raises(cli.BrokerError, match="SYNTHETIC_CLOSE_FAILURE"):
            await cli.async_main(cli.parse_args(["reconcile"]))
        reopened = Ledger(path, WALLET)
        reopened.close()

    asyncio.run(run())


def test_actual_cli_sells_with_fresh_book_while_discovery_is_blocked(tmp_path, monkeypatch):
    import httpx
    from polymarket.models.clob.order_book import OrderBook
    from test_market_data import Venue as PublicVenue

    from btc5m.market_data import MarketData

    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        held(ledger, session, venue)
        venue.now = NOW + 100000
        venue.post_loss = True
        path = ledger.path
        ledger.close()
        await broker.close()
        discovered, discovery_release, posted = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def send(client, request, **kwargs):
            if request.url.host == "gamma-api.polymarket.com":
                discovered.set()
                await discovery_release.wait()
                raise AssertionError("discovery must remain blocked until shutdown cancellation")
            try:
                return await venue.send(client, request, **kwargs)
            finally:
                if request.url.path == "/order":
                    posted.set()

        monkeypatch.setattr(httpx.AsyncClient, "send", send)
        public = PublicVenue()

        async def book(*, token_id):
            response = await venue.send(
                None,
                httpx.Request(
                    "GET", "https://clob.polymarket.com/book", params={"token_id": token_id}
                ),
            )
            return OrderBook.model_validate(response.json())

        monkeypatch.setattr(public.client, "get_order_book", book)
        monkeypatch.setattr(
            cli,
            "MarketData",
            lambda config, observer: MarketData(
                config,
                client=public.client,
                http_client=public.http,
                clock=lambda: venue.now / 1000,
                observer=observer,
            ),
        )
        monkeypatch.setattr(cli, "runtime_path", lambda *args: path)
        monkeypatch.setattr(
            cli, "load_credentials", lambda *args: cli.Credentials(KEY, WALLET, CREDS)
        )
        real_broker = cli.Broker

        def construct(client, rpc, journal, config):
            instance = real_broker(client, rpc, journal, config, clock=lambda: venue.now / 1000)
            original = instance.preflight

            async def account():
                await discovered.wait()
                result = await original()
                venue.now += 6000
                return result

            monkeypatch.setattr(instance, "preflight", account)
            return instance

        monkeypatch.setattr(cli, "Broker", construct)
        task = asyncio.create_task(
            cli.async_main(
                cli.parse_args(
                    ["run", "--execute", "--duration", "30", "--shutdown-seconds", ".01"]
                )
            )
        )
        try:
            await asyncio.wait_for(posted.wait(), 2)
            assert not discovery_release.is_set()
            reader = Ledger(path, WALLET, readonly=True)
            assert reader.unresolved_orders()[0].side == "SELL"
            assert reader.unresolved_orders()[0].reason == "TIME"
            reader.close()
            Ledger.request_stop_at(path)
            assert await asyncio.wait_for(task, 2) == 2
            assert venue.posts == 1
        finally:
            await cli._cancel(task)

    asyncio.run(run())


def test_public_pair_and_calibration_record_before_blocked_account_finishes(tmp_path, monkeypatch):
    import copy

    from polymarket.models.rtds_events import (
        CryptoPricesChainlinkEvent,
        CryptoPricesChainlinkTwapEvent,
    )
    from test_market_data import START, fixture, settle
    from test_market_data import Venue as PublicVenue

    from btc5m.engine import Engine
    from btc5m.market_data import MarketData

    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        public = PublicVenue()

        async def public_send(request, **kwargs):
            return public.request(request)

        monkeypatch.setattr(public.http, "send", public_send)
        recorded, account_started, account_release = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        original = broker.preflight

        async def account():
            account_started.set()
            await account_release.wait()
            return await original()

        monkeypatch.setattr(broker, "preflight", account)
        cell = cli.LatestInput(
            ledger,
            Config(),
            clock=public.clock.wall,
            emit=lambda row: recorded.set() if row.get("kind") == "raw_screens" else None,
        )
        engine = Engine(broker, ledger, Config(), session, read_snapshot=cell.read)
        data = MarketData(
            Config(),
            client=public.client,
            http_client=public.http,
            clock=public.clock.wall,
            monotonic=public.clock.mono,
            observer=cell.observe,
        )
        async with data:
            await public.emit()
            public.clock.ms = START * 1000 + 180000
            for raw in public.books.values():
                raw["timestamp"] = str(public.clock.ms)
            for kind in ("spot", "twap60"):
                raw = copy.deepcopy(
                    next(
                        row["event"]
                        for row in fixture("boundary-events")
                        if row["event"]["topic"].endswith(".twap") == (kind == "twap60")
                    )
                )
                raw["payload"]["timestamp"] = public.clock.ms
                model = (
                    CryptoPricesChainlinkTwapEvent
                    if kind == "twap60"
                    else CryptoPricesChainlinkEvent
                )
                (public.client.twap if kind == "twap60" else public.client.spot).queue.put_nowait(
                    model.model_validate(raw)
                )
            await settle()
            account_task = asyncio.create_task(engine.step(None, None, NOW))
            await account_started.wait()
            polling = asyncio.create_task(cli.poll_snapshots(data, cell))
            try:
                await asyncio.wait_for(recorded.wait(), 2)
                assert not account_task.done()
                assert len(ledger.decisions()) == 2
                sample = next(row for row in ledger.measurements() if row["kind"] == "calibration")
                assert sample["status"] == "observed" and sample["now_ms"] == START * 1000 + 180000
            finally:
                await cli._cancel(polling)
                account_release.set()
                await account_task
        await broker.close()
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("conflict", ["anchor", "rule"])
@pytest.mark.parametrize("phase", ["account", "prepare"])
@pytest.mark.parametrize("overwrite", [False, True])
@pytest.mark.parametrize("historical", [False, True])
def test_official_conflict_invalidates_current_entry_during_io(
    tmp_path, monkeypatch, conflict, phase, overwrite, historical
):
    from datetime import UTC, datetime

    from test_market_data import Venue as PublicVenue

    from btc5m.engine import Engine
    from btc5m.market_data import MarketData, _Round

    async def run():
        venue = Venue()
        venue.post_loss = True
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        public = PublicVenue()
        cell = cli.LatestInput(
            ledger, Config(), clock=lambda: venue.now / 1000, emit=lambda row: None
        )
        snap = confirmation_snapshot()
        cell.publish(snap, 0)
        engine = Engine(broker, ledger, Config(), session, read_snapshot=cell.read)
        assert (await engine.step(None, None, venue.now)).reason == "ENTRY_CONFIRMATION_WAITING"
        venue.now += 1000
        snap = confirmation_snapshot(venue.now)
        cell.publish(snap, 0)
        start = snap.market.start_s - (300 if historical else 0)
        state = _Round(
            f"btc-updown-5m-{start}",
            start,
            snap.market.condition_id,
            official=snap.market.reference_price,
        )
        event = public.event
        event.update(
            slug=state.slug,
            startTime=datetime.fromtimestamp(start, UTC).isoformat(),
            endDate=datetime.fromtimestamp(start + 300, UTC).isoformat(),
            eventMetadata={"priceToBeat": str(state.official + 1)},
        )
        event["markets"][0]["conditionId"] = state.condition_id
        if conflict == "rule":
            event["description"] = "Conflicting official rule"
        public.events[state.slug] = event
        data = MarketData(
            Config(),
            client=public.client,
            http_client=public.http,
            clock=lambda: venue.now / 1000,
            monotonic=public.clock.mono,
            observer=cell.observe,
        )
        data._rounds[state.slug] = state
        blocked, release = asyncio.Event(), asyncio.Event()
        original = getattr(broker, "preflight" if phase == "account" else "prepare")

        async def delayed(*args):
            result = await original(*args)
            blocked.set()
            await release.wait()
            return result

        monkeypatch.setattr(broker, "preflight" if phase == "account" else "prepare", delayed)
        task = asyncio.create_task(engine.step(None, None, venue.now))
        try:
            await asyncio.wait_for(blocked.wait(), 2)
            await data._poll_due()  # Actual SDK model -> producer -> cache observation.
            assert state.conflict
            invalidated = cell.read()
            if overwrite:
                cell.publish(snap, invalidated.invalidation_generation)
            release.set()
            result = await task
            if historical:
                assert invalidated.invalidation_generation == 0
                assert result.action == "SUBMITTED" and venue.posts == 1
            else:
                assert invalidated.snapshot is None
                assert invalidated.invalidation_generation == 1
                assert venue.posts == 0 and not ledger.unresolved_orders()
                if phase == "prepare":
                    assert result.reason == "INPUT_INVALIDATED_BEFORE_POST"
                    assert ledger.order(result.intent_id).state == "REJECTED"
                else:
                    rows = ledger.observations()
                    assert any(
                        r.get("status") == "cancelled" and r.get("code") == "INPUT_INVALIDATED"
                        for r in rows
                    )
        finally:
            release.set()
            await cli._cancel(task)
            await data.close()
            await broker.close()
            ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize(
    "sequence,expected",
    [
        (["80000", "80001", "80000"], "conflict"),
        (["80000", "80000", "80000.000000005"], "official"),
    ],
)
def test_report_reduces_produced_final_reference_conflicts_retrospectively(
    tmp_path, sequence, expected, restart
):
    from test_market_data import Venue as PublicVenue

    from btc5m.market_data import MarketData, _Round

    async def run():
        ledger = Ledger(tmp_path / "labels.sqlite", cli.ANONYMOUS_WALLET)
        public = PublicVenue()
        data = MarketData(
            Config(),
            client=public.client,
            http_client=public.http,
            clock=lambda: 1788712200,
            observer=ledger.record_observation,
        )
        state = _Round("btc-updown-5m-1788711600", 1788711600, public.market["condition_id"])
        for index, price in enumerate(sequence):
            if restart:
                state = _Round(state.slug, state.start_s, state.condition_id)
            data._metadata(state, {"finalPrice": price}, f"synthetic official metadata {index}")
        # Reopening the historical journal exercises retrospective report reduction.
        path = ledger.path
        ledger.close()
        reader = Ledger(path, cli.ANONYMOUS_WALLET, readonly=True)
        try:
            final = cli.report(reader)["official_final_references_by_round"][state.slug]
            assert final["status"] == expected and final["price"] == "80000"
        finally:
            reader.close()
            await data.close()

    asyncio.run(run())


@pytest.mark.parametrize("first_conflict", [False, True])
def test_report_final_reference_conflict_cannot_heal_across_producer_restart(
    tmp_path, first_conflict
):
    from test_market_data import Venue as PublicVenue

    from btc5m.market_data import MarketData, _Round

    async def run():
        ledger = Ledger(tmp_path / "labels.sqlite", cli.ANONYMOUS_WALLET)
        public = PublicVenue()
        data = MarketData(
            Config(),
            client=public.client,
            http_client=public.http,
            clock=lambda: 1788712200,
            observer=ledger.record_observation,
        )
        state = _Round("btc-updown-5m-1788711600", 1788711600, public.market["condition_id"])
        if first_conflict:
            from decimal import Decimal

            state.final = Decimal("80000")
        else:
            data._metadata(state, {"finalPrice": "80000"}, "synthetic initial metadata")
        data._metadata(state, {"finalPrice": "80001"}, "synthetic conflict metadata")
        # A restarted producer has no in-memory conflict, but the journal retains it.
        restarted = _Round(state.slug, state.start_s, state.condition_id)
        data._metadata(restarted, {"finalPrice": "80000"}, "synthetic later metadata")
        try:
            result = cli.report(ledger)["official_final_references_by_round"][state.slug]
            assert result["status"] == "conflict"
        finally:
            await data.close()
            ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("resource", ["public", "secure", "rpc", "stream"])
def test_flat_run_bounds_delayed_transport_teardown(tmp_path, monkeypatch, resource):
    from test_market_data import Venue as PublicVenue

    from btc5m.ledger import LedgerError
    from btc5m.market_data import MarketData

    async def run():
        venue = Venue()
        broker, ledger, _ = await broker_fixture(tmp_path, monkeypatch, venue)
        path = ledger.path
        ledger.close()
        public = PublicVenue()
        data = MarketData(
            Config(), client=public.client, http_client=public.http, clock=public.clock.wall
        )
        monkeypatch.setattr(cli, "runtime_path", lambda *args: path)
        monkeypatch.setattr(
            cli, "load_credentials", lambda *args: cli.Credentials(KEY, WALLET, CREDS)
        )
        monkeypatch.setattr(cli, "MarketData", lambda config, observer: data)

        async def client(**kwargs):
            return broker.client

        def construct(client, rpc, journal, config):
            broker.ledger = journal
            return broker

        monkeypatch.setattr(cli, "create_secure_client", client)
        monkeypatch.setattr(cli, "Broker", construct)
        closing, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        target = {
            "public": public.client,
            "secure": broker.client,
            "rpc": broker.rpc,
            "stream": public.client.spot,
        }[resource]
        original_close = target.close

        async def delayed_close():
            closing.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            finally:
                await original_close()

        monkeypatch.setattr(target, "close", delayed_close)
        emitted = []
        monkeypatch.setattr(cli, "emit", emitted.append)
        task = asyncio.create_task(
            cli.run_live(
                cli.parse_args(
                    ["run", "--execute", "--duration", ".02", "--shutdown-seconds", ".35"]
                ),
                Config(),
            )
        )
        try:
            await asyncio.wait_for(closing.wait(), 2)
            with pytest.raises(LedgerError, match="WALLET_LOCKED"):
                Ledger(path, WALLET)
            done, _ = await asyncio.wait({task}, timeout=0.5)
            assert task in done, "transport teardown exceeded the shared shutdown budget"
            assert await task == 2 and cancelled.is_set()
            assert any(row["kind"] == "run_completed" for row in emitted)
            reopened = Ledger(path, WALLET)
            assert reopened.stop_requested() and not reopened.unresolved_orders()
            assert any(row.get("code") == "SHUTDOWN_DEADLINE" for row in reopened.observations())
            reopened.close()
            assert all(stream.done() for stream in data._tasks)
            assert broker.http.is_closed and broker.rpc.http.is_closed and public.http.is_closed
            assert venue.posts == 0
        finally:
            release.set()
            await cli._cancel(task)

    asyncio.run(run())


def test_cancelled_run_drains_inflight_post_before_releasing_owner(tmp_path, monkeypatch):
    import httpx
    from polymarket.models.clob.order_book import OrderBook
    from test_market_data import Venue as PublicVenue

    from btc5m.ledger import LedgerError
    from btc5m.market_data import MarketData

    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        held(ledger, session, venue)
        venue.now = NOW + 100000
        path = ledger.path
        ledger.close()
        public = PublicVenue()
        posting, cancellation, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def send(client, request, **kwargs):
            if request.method == "POST" and request.url.path == "/order":
                venue.posts += 1
                posting.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancellation.set()
                    await release.wait()  # Deliberately hold cancellation acknowledgement.
                    raise
            return await venue.send(client, request, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "send", send)

        async def book(*, token_id):
            response = await venue.send(
                None,
                httpx.Request(
                    "GET", "https://clob.polymarket.com/book", params={"token_id": token_id}
                ),
            )
            return OrderBook.model_validate(response.json())

        monkeypatch.setattr(public.client, "get_order_book", book)
        data = MarketData(
            Config(), client=public.client, http_client=public.http, clock=lambda: venue.now / 1000
        )
        monkeypatch.setattr(cli, "MarketData", lambda config, observer: data)
        monkeypatch.setattr(cli, "runtime_path", lambda *args: path)
        monkeypatch.setattr(
            cli, "load_credentials", lambda *args: cli.Credentials(KEY, WALLET, CREDS)
        )

        async def client(**kwargs):
            return broker.client

        def construct(client, rpc, journal, config):
            broker.ledger = journal
            return broker

        monkeypatch.setattr(cli, "create_secure_client", client)
        monkeypatch.setattr(cli, "Broker", construct)
        emitted = []
        monkeypatch.setattr(cli, "emit", emitted.append)
        task = asyncio.create_task(
            cli.run_live(
                cli.parse_args(
                    ["run", "--execute", "--duration", "30", "--shutdown-seconds", ".2"]
                ),
                Config(),
            )
        )
        try:
            await asyncio.wait_for(posting.wait(), 2)
            task.cancel()
            await asyncio.wait_for(cancellation.wait(), 2)
            with pytest.raises(LedgerError, match="WALLET_LOCKED"):
                Ledger(path, WALLET)
            reader = Ledger(path, WALLET, readonly=True)
            assert reader.stop_requested()
            reader.close()
            task.cancel()  # A second caller cancellation cannot release the owner early.
            await asyncio.sleep(0)
            with pytest.raises(LedgerError, match="WALLET_LOCKED"):
                Ledger(path, WALLET)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.5)
            reopened = Ledger(path, WALLET)
            order = reopened.unresolved_orders()[0]
            assert order.state == "UNKNOWN" and order.outstanding_quantity == 5
            assert reopened.stop_requested() and reopened.open_position().quantity == 5
            assert any(row["kind"] == "run_completed" for row in emitted)
            assert venue.posts == 1
            reopened.close()
        finally:
            release.set()
            await cli._cancel(task)

    asyncio.run(run())
