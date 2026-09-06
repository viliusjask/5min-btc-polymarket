"""Explicit native operator commands; no implicit authentication or shell evaluation."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import os
import re
import signal
import tempfile
import time
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from polymarket.models.clob import ApiKeyCreds

from btc5m.broker import Broker, BrokerError, create_secure_client
from btc5m.config import Config, load_config
from btc5m.domain import Snapshot
from btc5m.engine import Engine
from btc5m.execution_types import SnapshotInput
from btc5m.ledger import Ledger, LedgerError, normalize_wallet, runtime_path
from btc5m.market_data import DataUnavailable, MarketData
from btc5m.rpc import ReadOnlyRPC, RPCError
from btc5m.strategy import evaluate

ANONYMOUS_WALLET = "0x" + "00" * 20
ENV_KEYS = frozenset(
    {
        "POLYMARKET_PRIVATE_KEY",
        "POLYMARKET_FUNDER",
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_API_PASSPHRASE",
    }
)


class CLIError(Exception):
    """A safe operator reason, with no credential or request text."""


@dataclass(frozen=True)
class Credentials:
    private_key: str = field(repr=False)
    wallet: str
    api: ApiKeyCreds = field(repr=False)


def repository() -> Path:
    return Path(__file__).resolve().parents[2]


def default_config() -> Path:
    return repository() / "config" / "btc5m.toml"


def load_credentials(env_file: Path | None, wallet: str | None) -> Credentials:
    values = {key: os.environ[key] for key in ENV_KEYS if key in os.environ}
    if env_file is not None:
        if env_file.stat().st_size > 16384:
            raise CLIError("ENV_FILE_TOO_LARGE")
        seen = set()
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not separator or key not in ENV_KEYS:
                raise CLIError("ENV_FILE_UNSUPPORTED_KEY")
            if key in seen:
                raise CLIError("ENV_FILE_DUPLICATE_KEY")
            seen.add(key)
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise CLIError("ENV_FILE_INVALID_QUOTE")
                value = value[1:-1]
            values[key] = value
    if wallet is not None:
        values["POLYMARKET_FUNDER"] = wallet
    if any(not values.get(key) for key in ENV_KEYS):
        raise CLIError("EXPLICIT_EXISTING_CREDENTIALS_REQUIRED")
    return Credentials(
        values["POLYMARKET_PRIVATE_KEY"],
        normalize_wallet(values["POLYMARKET_FUNDER"]),
        ApiKeyCreds(
            key=values["POLYMARKET_API_KEY"],
            secret=values["POLYMARKET_API_SECRET"],
            passphrase=values["POLYMARKET_API_PASSPHRASE"],
        ),
    )


def safe_reason(exc: BaseException) -> str:
    if isinstance(exc, CLIError | BrokerError | LedgerError | RPCError | DataUnavailable):
        code = str(exc)
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", code):
            return code
    return "OPERATION_FAILED_" + type(exc).__name__.upper()


def emit(record: dict[str, Any]) -> None:
    print(json.dumps(record, default=str, sort_keys=True), flush=True)


def _seconds(value: str) -> float:
    try:
        result = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("seconds must be a positive finite number") from None
    if not math.isfinite(result) or not 0 < result <= 86400:
        raise argparse.ArgumentTypeError("seconds must be between zero and 86400")
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="btc5m",
        allow_abbrev=False,
        description="Development-verified BTC5m experiment; funded execution remains unverified.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("observe", "doctor", "run", "stop", "status", "report", "reconcile"):
        command = commands.add_parser(name, allow_abbrev=False)
        if name in ("observe", "doctor", "run", "reconcile"):
            command.add_argument("--config", type=Path, default=default_config())
        if name in ("observe", "doctor", "run"):
            command.add_argument(
                "--duration",
                type=_seconds,
                default=2100 if name == "observe" else 15 if name == "doctor" else None,
                required=name == "run",
                help="finite seconds; entry history needs 1800 seconds by default",
            )
        if name in ("doctor", "run", "reconcile", "stop", "status", "report"):
            command.add_argument("--wallet", help="public account/funder address")
        if name in ("doctor", "run", "reconcile"):
            command.add_argument(
                "--env-file", type=Path, help="explicit existing credentials; parsed as data"
            )
        if name in ("observe", "stop", "status", "report"):
            command.add_argument(
                "--runtime",
                type=Path,
                required=name != "observe",
                help="SQLite ledger file; no credential loading",
            )
        if name == "doctor":
            command.add_argument(
                "--account", action="store_true", help="explicit read-only authenticated checks"
            )
        if name == "run":
            command.add_argument(
                "--execute",
                action="store_true",
                required=True,
                help="explicitly authorize funded order submission",
            )
            command.add_argument(
                "--shutdown-seconds",
                type=_seconds,
                default=60,
                help="maximum additional seconds for reconciliation and protected close",
            )
        if name == "report":
            command.add_argument(
                "--records",
                action="store_true",
                help="include all safe public observations and raw paired decisions",
            )
    args = parser.parse_args(argv)
    if (
        args.command == "doctor"
        and not args.account
        and (args.env_file is not None or args.wallet is not None)
    ):
        parser.error("--env-file and --wallet require doctor --account")
    return args


class LatestInput:
    """One immutable latest snapshot plus durable-in-process invalidation history."""

    def __init__(
        self,
        ledger: Ledger,
        config: Config,
        *,
        clock: Callable[[], float] = time.time,
        emit: Callable[[dict[str, Any]], None] = emit,
    ) -> None:
        self.ledger, self.config, self.clock, self.emit = ledger, config, clock, emit
        self._value = SnapshotInput(None, 0)
        self._identity: tuple[object, ...] | None = None
        self._last_screen: tuple[object, ...] | None = None
        self._last_public_event: dict[tuple[object, object], dict[str, object]] = {}

    def invalidate(self, code: str) -> None:
        self._value = SnapshotInput(None, self._value.invalidation_generation + 1)
        self.ledger.record_observation(
            {"kind": "execution_input", "received_ms": int(self.clock() * 1000), "code": code}
        )

    def observe(self, record: dict[str, object]) -> None:
        self.ledger.record_observation(record)
        if record.get("kind") in ("stream_unavailable", "price_conflict") and record.get(
            "stream"
        ) in ("spot", "twap60"):
            self.invalidate(str(record.get("code", record["kind"])))
        if record.get("kind") in (
            "stream_unavailable",
            "price_conflict",
            "metadata_rejected",
            "anchor",
            "final_reference",
        ):
            # The ledger selects safe fields; never echo arbitrary transport payloads.
            public = {
                key: record[key]
                for key in (
                    "kind",
                    "slug",
                    "stream",
                    "code",
                    "price",
                    "status",
                    "compared_field",
                    "expected",
                    "actual",
                    "token_id",
                    "endpoint",
                )
                if key in record
            }
            key = (record.get("kind"), record.get("stream"))
            if self._last_public_event.get(key) != public:
                self.emit({**public, "received_ms": record.get("received_ms")})
                self._last_public_event[key] = public

    def read(self) -> SnapshotInput:
        snap = self._value.snapshot
        if snap is not None:
            reason = evaluate(replace(snap, now_ms=int(self.clock() * 1000)), self.config).reason
            if reason != "ENTRY":
                self.invalidate(reason)
        return self._value

    def publish(self, snapshot: Snapshot, started_generation: int) -> None:
        current = replace(snapshot, now_ms=int(self.clock() * 1000))
        decisions = self.ledger.record_snapshot(current, self.config)
        selected = decisions[0 if self.config.strategy.mode == "value" else 1]
        screen = (current.market.slug, decisions[0].reason, decisions[1].reason)
        if screen != self._last_screen:
            self.emit(
                {
                    "kind": "raw_screens",
                    "received_ms": current.now_ms,
                    "slug": current.market.slug,
                    "value": decisions[0].reason,
                    "momentum": decisions[1].reason,
                }
            )
            self._last_screen = screen
        identity = (
            None
            if selected.side is None
            else (
                self.config.fingerprint,
                selected.side,
                *Engine.candidate_identity(current.market, selected.side),
            )
        )
        if selected.reason != "ENTRY":
            self.invalidate(selected.reason)
        elif started_generation != self._value.invalidation_generation:
            # A poll from before a source failure cannot silently restore readiness.
            return
        else:
            if self._identity is not None and identity != self._identity:
                self.invalidate("CANDIDATE_IDENTITY_CHANGED")
            self._value = SnapshotInput(current, self._value.invalidation_generation)
        self._identity = identity


async def poll_snapshots(data: MarketData, cell: LatestInput) -> None:
    last_error = None
    while True:
        generation = cell.read().invalidation_generation
        try:
            snap = await data.snapshot()
            cell.publish(snap, generation)
            last_error = None
        except DataUnavailable as exc:
            cell.invalidate(exc.code)
            if exc.code != last_error:
                cell.emit(
                    {
                        "kind": "snapshot_skip",
                        "received_ms": int(cell.clock() * 1000),
                        "code": exc.code,
                    }
                )
                last_error = exc.code
        await asyncio.sleep(0.5)


def _record(ledger: Ledger, code: str) -> None:
    ledger.record_observation(
        {"kind": "cli_lifecycle", "received_ms": int(time.time() * 1000), "code": code}
    )


def _wallet_for_path(path: Path, wallet: str | None) -> str:
    if wallet is not None:
        return normalize_wallet(wallet)
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", path.resolve().parent.name):
        return normalize_wallet(path.resolve().parent.name)
    return ANONYMOUS_WALLET


def report(ledger: Ledger, *, records: bool = False) -> dict[str, Any]:
    summary = asdict(ledger.summary())
    observations, measurements, decisions = (
        ledger.observations(),
        ledger.measurements(),
        ledger.decisions(),
    )
    final: dict[str, dict[str, Any]] = {}
    for row in observations:
        if row.get("kind") == "final_reference":
            slug = str(row.get("slug"))
            if slug in final and final[slug].get("price") != row.get("price"):
                final[slug] = {"slug": slug, "status": "conflict"}
            elif slug not in final:
                final[slug] = row
    result = {
        "summary": summary,
        "screen_unit": "raw core screen; repeated snapshots are not independent trades",
        "raw_screen_counts": dict(
            Counter(f"{r['mode']}:{r['decision']['reason']}" for r in decisions)
        ),
        "first_eligible_screens": [r for r in measurements if r["kind"] == "candidate"],
        "calibration": [r for r in measurements if r["kind"] == "calibration"],
        "official_final_references_by_round": final,
        "confirmation_counts": dict(
            Counter(
                str(r.get("status")) for r in observations if r["kind"] == "execution_confirmation"
            )
        ),
        "observation_counts": dict(Counter(str(r["kind"]) for r in observations)),
        "recent_events": [
            r
            for r in observations
            if r["kind"] not in ("spot", "twap60", "book", "discovery", "snapshot")
        ][-30:],
    }
    if records:
        result.update(observations=observations, raw_decisions=decisions)
    return result


async def _cancel(task: asyncio.Task[Any]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


async def observe(args: argparse.Namespace, config: Config, *, doctor: bool = False) -> int:
    # Anonymous storage never shares the live wallet namespace or identity.
    common = runtime_path(repository(), ANONYMOUS_WALLET).parents[1]
    path = (
        getattr(args, "runtime", None)
        or common.parent / ".observations" / uuid.uuid4().hex / "ledger.sqlite"
    )
    path = path.resolve()
    if path.is_relative_to(common):
        raise CLIError("OBSERVATION_RUNTIME_MUST_BE_SEPARATE")
    ledger = Ledger(path, ANONYMOUS_WALLET)
    ledger.config = config  # Public observation identity, without account/session initialization.
    cell = LatestInput(ledger, config)
    data = MarketData(config, observer=cell.observe)
    polling: asyncio.Task[None] | None = None
    interrupted = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, interrupted.set)
    try:
        _record(ledger, "PUBLIC_DOCTOR_STARTED" if doctor else "OBSERVE_STARTED")
        emit(
            {
                "kind": "runtime",
                "path": str(path),
                "config_fingerprint": config.fingerprint,
                "duration_seconds": args.duration,
            }
        )
        async with data:
            polling = asyncio.create_task(poll_snapshots(data, cell))
            deadline = time.monotonic() + args.duration
            while time.monotonic() < deadline and not interrupted.is_set():
                if polling.done():
                    await polling
                ledger.record_clock(int(time.time() * 1000))
                await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
            await _cancel(polling)
            polling = None
        _record(ledger, "OBSERVE_COMPLETED")
        result = report(ledger)
        emit(
            {
                "kind": "observation_completed",
                "summary": result["summary"],
                "observation_counts": result["observation_counts"],
                "raw_screen_counts": result["raw_screen_counts"],
            }
        )
        if doctor:
            counts = result["observation_counts"]
            return 0 if all(counts.get(kind, 0) for kind in ("spot", "twap60", "discovery")) else 2
        return 0
    finally:
        async with contextlib.AsyncExitStack() as cleanup:
            for sig in (signal.SIGINT, signal.SIGTERM):
                cleanup.callback(loop.remove_signal_handler, sig)
            cleanup.callback(ledger.close)
            cleanup.push_async_callback(data.close)
            if polling is not None:
                cleanup.push_async_callback(_cancel, polling)


async def account(args: argparse.Namespace, config: Config) -> int:
    credentials = load_credentials(args.env_file, args.wallet)
    path = runtime_path(repository(), credentials.wallet)
    with tempfile.TemporaryDirectory(prefix="btc5m-doctor-") as temporary:
        doctor = args.command == "doctor"
        if not doctor and not path.is_file():
            raise CLIError("LIVE_RUNTIME_MISSING")
        ledger = Ledger(
            path if path.is_file() else Path(temporary) / "ledger.sqlite",
            credentials.wallet,
            readonly=doctor and path.is_file(),
        )
        broker = None
        rpc = ReadOnlyRPC()
        try:
            client = await create_secure_client(
                private_key=credentials.private_key,
                wallet=credentials.wallet,
                credentials=credentials.api,
            )
            broker = Broker(client, rpc, ledger, config)
            if doctor:
                evidence = await broker.preflight()
                emit(
                    {
                        "kind": "account_doctor",
                        "entry_ready": evidence.entry_ready,
                        **asdict(evidence),
                    }
                )
                return 0 if evidence.entry_ready else 2
            # Reconciliation writes only local evidence and never changes session or stop.
            session_id = ledger.summary().session_id
            if session_id is None:
                raise CLIError("LIVE_SESSION_MISSING")
            engine = Engine(broker, ledger, config, session_id)
            await engine.reconcile()
            emit(report(ledger))
            return 2 if ledger.unresolved_orders() or ledger.summary().halts else 0
        finally:
            async with contextlib.AsyncExitStack() as cleanup:
                cleanup.callback(ledger.close)
                cleanup.push_async_callback(rpc.close)
                if broker is not None:
                    cleanup.push_async_callback(broker.close)


async def run_live(args: argparse.Namespace, config: Config) -> int:
    if not args.execute:
        raise CLIError("EXPLICIT_EXECUTE_REQUIRED")
    credentials = load_credentials(args.env_file, args.wallet)
    path = runtime_path(repository(), credentials.wallet)
    ledger = Ledger(path, credentials.wallet)
    # Only this explicit owner start acknowledges an old stop, before awaited setup.
    try:
        ledger.clear_stop_request()
        session = ledger.start_or_resume_session(config)
    except Exception as exc:
        ledger.request_stop()
        _record(ledger, safe_reason(exc))
        ledger.close()
        raise
    cell = LatestInput(ledger, config)
    data = MarketData(config, observer=cell.observe)
    broker: Broker | None = None
    rpc = ReadOnlyRPC()
    signal_stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_stop.set)
    deadline = time.monotonic() + args.duration

    async def control() -> None:
        shutdown_deadline = None
        while True:
            ledger.record_clock(int(time.time() * 1000))
            cell.read()  # catches silent aging even while account I/O is in progress
            if shutdown_deadline is None and (
                signal_stop.is_set() or ledger.stop_requested() or time.monotonic() >= deadline
            ):
                ledger.request_stop()
                cell.invalidate("STOP_REQUESTED")
                _record(ledger, "SHUTDOWN_REQUESTED")
                shutdown_deadline = time.monotonic() + args.shutdown_seconds
            if shutdown_deadline is not None and time.monotonic() >= shutdown_deadline:
                _record(ledger, "SHUTDOWN_DEADLINE")
                return
            await asyncio.sleep(0.25)

    async def execute() -> int:
        nonlocal broker
        client = await create_secure_client(
            private_key=credentials.private_key,
            wallet=credentials.wallet,
            credentials=credentials.api,
        )
        broker = Broker(client, rpc, ledger, config)

        async def held_book(token: str):
            try:
                return await data.book(token)
            except DataUnavailable as exc:
                ledger.record_observation(
                    {
                        "kind": "exit_book_unavailable",
                        "received_ms": int(time.time() * 1000),
                        "token_id": token,
                        "code": exc.code,
                    }
                )
                return None

        engine = Engine(
            broker, ledger, config, session, read_exit_book=held_book, read_snapshot=cell.read
        )
        prior = None
        while True:
            now = int(time.time() * 1000)
            result = (
                await engine.shutdown(None, now)
                if ledger.stop_requested()
                else await engine.step(None, None, now)
            )
            if result != prior:
                emit({"kind": "execution", **asdict(result)})
                ledger.record_observation(
                    {
                        "kind": "execution_result",
                        "received_ms": int(time.time() * 1000),
                        "status": result.action,
                        "code": result.reason,
                    }
                )
                prior = result
            if (
                ledger.stop_requested()
                and not ledger.unresolved_orders()
                and ledger.open_position() is None
            ):
                return 0
            await asyncio.sleep(0.25)

    tasks: list[asyncio.Task[Any]] = []
    try:
        _record(ledger, "RUN_STARTED")
        emit(
            {
                "kind": "runtime",
                "path": str(path),
                "config_fingerprint": config.fingerprint,
                "duration_seconds": args.duration,
                "max_entries_per_day": config.risk.max_entries_per_day,
            }
        )
        async with data:
            polling = asyncio.create_task(poll_snapshots(data, cell))
            controller = asyncio.create_task(control())
            worker = asyncio.create_task(execute())
            tasks = [polling, controller, worker]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if polling in done:
                await polling
                raise CLIError("OBSERVATION_WORKER_STOPPED")
            if worker in done:
                code = await worker
            else:
                code = 2
            for task in tasks:
                await _cancel(task)
            tasks = []
        _record(ledger, "RUN_COMPLETED" if code == 0 else "RUN_UNRESOLVED")
        emit({"kind": "run_completed", "summary": asdict(ledger.summary())})
        return code
    except Exception as exc:
        ledger.request_stop()
        _record(ledger, safe_reason(exc))
        raise
    finally:
        async with contextlib.AsyncExitStack() as cleanup:
            for sig in (signal.SIGINT, signal.SIGTERM):
                cleanup.callback(loop.remove_signal_handler, sig)
            cleanup.callback(ledger.close)
            cleanup.push_async_callback(rpc.close)
            if broker is not None:
                cleanup.push_async_callback(broker.close)
            cleanup.push_async_callback(data.close)
            for task in tasks:
                cleanup.push_async_callback(_cancel, task)


async def async_main(args: argparse.Namespace) -> int:
    if args.command in ("stop", "status", "report"):
        if not args.runtime.is_file():
            raise CLIError("RUNTIME_MISSING")
        wallet = _wallet_for_path(args.runtime, args.wallet)
        ledger = Ledger(args.runtime, wallet, readonly=True)
        try:
            if args.command == "stop":
                Ledger.request_stop_at(args.runtime)
                emit(
                    {
                        "kind": "stop_requested",
                        "runtime": str(args.runtime.resolve()),
                        "inventory_preserved": True,
                    }
                )
            elif args.command == "status":
                emit({"summary": asdict(ledger.summary())})
            else:
                emit(report(ledger, records=args.records))
            return 0
        finally:
            ledger.close()
    config = load_config(args.config)
    if args.command == "observe":
        return await observe(args, config)
    if args.command == "doctor" and not args.account:
        return await observe(args, config, doctor=True)
    if args.command in ("doctor", "reconcile"):
        return await account(args, config)
    return await run_live(args, config)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        return asyncio.run(async_main(args))
    except SystemExit as exc:
        return int(exc.code or 0)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        import sys

        print(safe_reason(exc), file=sys.stderr)
        return 2
