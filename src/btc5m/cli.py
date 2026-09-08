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
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from polymarket.models.clob import ApiKeyCreds

from btc5m.broker import Broker, BrokerError, create_secure_client
from btc5m.config import STRATEGIES, Config, load_config
from btc5m.credentials import CredentialError
from btc5m.domain import Snapshot
from btc5m.engine import Engine
from btc5m.execution_types import SnapshotInput
from btc5m.ledger import Ledger, LedgerError, normalize_wallet, runtime_path
from btc5m.market_data import ANCHOR_TOLERANCE, DataUnavailable, MarketData
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


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in ENV_KEYS:
            raise CLIError("ENV_FILE_UNSUPPORTED_KEY")
        if key in values:
            raise CLIError("ENV_FILE_DUPLICATE_KEY")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise CLIError("ENV_FILE_INVALID_QUOTE")
            value = value[1:-1]
        values[key] = value
    return values


def read_env(env_file: Path) -> str:
    if env_file.stat().st_size > 16384:
        raise CLIError("ENV_FILE_TOO_LARGE")
    return env_file.read_text()


def load_credentials(env_file: Path | None, wallet: str | None) -> Credentials:
    values = {key: os.environ[key] for key in ENV_KEYS if key in os.environ}
    if env_file is not None:
        values.update(parse_env(read_env(env_file)))
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


async def configure_credentials(args: argparse.Namespace) -> int:
    from btc5m.credentials import trading_credentials

    path = args.env_file.resolve(strict=True)
    original = read_env(path)
    values = parse_env(original)
    if not values.get("POLYMARKET_PRIVATE_KEY") or not values.get("POLYMARKET_FUNDER"):
        raise CLIError("PRIVATE_KEY_AND_FUNDER_REQUIRED_IN_ENV_FILE")
    normalize_wallet(values["POLYMARKET_FUNDER"])
    credentials = await trading_credentials(values["POLYMARKET_PRIVATE_KEY"], create=args.create)
    updates = {
        "POLYMARKET_API_KEY": credentials.key,
        "POLYMARKET_API_SECRET": credentials.secret,
        "POLYMARKET_API_PASSPHRASE": credentials.passphrase,
    }
    lines = []
    for line in original.splitlines():
        key = line.partition("=")[0].strip()
        if key in updates:
            lines.append(f"{key}={updates.pop(key)}")
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in updates.items())
    if read_env(path) != original:
        raise CLIError("ENV_CHANGED_DURING_AUTH_DERIVE_AGAIN")
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=".btc5m-credentials-", suffix=".tmp", dir=path.parent
        )
        with os.fdopen(fd, "w") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write("\n".join(lines) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
        emit({"kind": "trading_credentials_saved", "env_file": str(path), "trades_placed": False})
        return 0
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def safe_reason(exc: BaseException) -> str:
    if isinstance(
        exc, CLIError | CredentialError | BrokerError | LedgerError | RPCError | DataUnavailable
    ):
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


def _historical_time(value: str) -> int:
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("timezone required")
        delta = stamp.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
        if delta.microseconds % 1000:
            raise ValueError("millisecond precision required")
        return delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "use timezone-aware ISO8601, e.g. 2026-09-08T06:00:00Z"
        ) from exc


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="btc5m",
        allow_abbrev=False,
        description="Development-verified BTC5m experiment; funded execution remains unverified.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    archive = commands.add_parser(
        "archive", allow_abbrev=False, help="read-only bounded saved-history status"
    )
    archive.add_argument("archive_action", choices=("status",))
    archive.add_argument("--source", type=Path, required=True, help="existing capture.sqlite")
    lab = commands.add_parser(
        "lab", allow_abbrev=False, help="paper-only parameter studies on a common recorded tape"
    )
    lab.add_argument("lab_action", choices=("run", "freeze", "report", "variants"))
    lab.add_argument(
        "--runtime",
        type=Path,
        help="separate experiment directory, usually PAPER_RUNTIME/lab",
    )
    lab.add_argument(
        "--source", type=Path, help="existing paper runtime's capture.sqlite; required for run"
    )
    lab.add_argument("--config", type=Path, default=default_config())
    lab.add_argument("--continuous", action="store_true", help="keep consuming new recorded frames")
    lab.add_argument(
        "--suite",
        choices=("directional", "order-flow", "original-six"),
        help="registered experiment suite; order-flow requires --capture-flow on the paper collector",
    )
    lab.add_argument(
        "--dense",
        action="store_true",
        default=None,
        help="new study only: all integer Momentum leads 1–100",
    )
    lab.add_argument(
        "--explore-rounds",
        type=int,
        help="full rounds before automatic shortlist selection (new study default: 288)",
    )
    lab.add_argument(
        "--variants", help="comma-separated registered IDs to run, or freeze for a future test"
    )
    lab.add_argument(
        "--start",
        type=_historical_time,
        help="historical entry start, inclusive, timezone-aware ISO8601",
    )
    lab.add_argument(
        "--end",
        type=_historical_time,
        help="historical entry end, exclusive, timezone-aware ISO8601",
    )
    lab.add_argument("--test-rounds", type=int, default=288)
    credentials = commands.add_parser(
        "credentials",
        allow_abbrev=False,
        help="derive CLOB trading credentials and replace the three API fields in an explicit env file",
    )
    credentials.add_argument("--env-file", type=Path, required=True)
    credentials.add_argument(
        "--create",
        action="store_true",
        help="explicitly create trading credentials if needed; no wallet or order actions",
    )
    for name in (
        "observe",
        "doctor",
        "run",
        "paper",
        "dashboard",
        "stop",
        "status",
        "report",
        "reconcile",
    ):
        command = commands.add_parser(name, allow_abbrev=False)
        if name in ("observe", "doctor", "run", "paper", "dashboard", "reconcile"):
            command.add_argument("--config", type=Path, default=default_config())
        if name in ("observe", "doctor", "run", "reconcile"):
            command.add_argument(
                "--strategy",
                choices=(*STRATEGIES, "compare"),
                help="override the recorded strategy mode; compare preassigns one live policy per UTC round",
            )
        if name in ("observe", "doctor", "run", "paper"):
            timing = command.add_mutually_exclusive_group() if name == "paper" else command
            if name == "paper":
                command.add_argument(
                    "--capture-flow",
                    action="store_true",
                    help="record public executed volume, exchange depth and trades for new research studies",
                )
                timing.add_argument(
                    "--continuous",
                    action="store_true",
                    help="paper only: run until explicitly stopped; preserve this runtime on restart",
                )
            timing.add_argument(
                "--duration",
                type=_seconds,
                default=2100
                if name == "observe"
                else 15
                if name == "doctor"
                else 3600
                if name == "paper"
                else None,
                required=name == "run",
                help="finite seconds; entry history needs 1800 seconds by default",
            )
        if name in ("doctor", "run", "reconcile", "stop", "status", "report"):
            command.add_argument("--wallet", help="public account/funder address")
        if name in ("doctor", "run", "reconcile", "dashboard"):
            command.add_argument(
                "--env-file", type=Path, help="explicit existing credentials; parsed as data"
            )
        if name in ("observe", "stop", "status", "report", "paper", "dashboard"):
            command.add_argument(
                "--runtime",
                type=Path,
                required=name not in ("observe", "paper"),
                default=repository() / "work" / "paper" if name == "paper" else None,
                help="SQLite journal, or paper runtime directory for paper/dashboard/status/report/stop",
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
        if name in ("run", "paper"):
            command.add_argument(
                "--shutdown-seconds",
                type=_seconds,
                default=60,
                help=(
                    "seconds to monitor open exposure during shutdown; transport cleanup follows"
                    if name == "paper"
                    else "shared shutdown budget for reconciliation, cancellation and transport close"
                ),
            )
        if name == "paper":
            command.add_argument(
                "--strategies",
                default="all",
                help="all or comma-separated strategy names; total allocation is split equally",
            )
        if name == "dashboard":
            command.add_argument(
                "--account",
                action="store_true",
                help="enable read-only Real account monitoring; never enables trading",
            )
            command.add_argument(
                "--port",
                type=int,
                default=8765,
                help="local read-only monitoring port; binds to 127.0.0.1 only",
            )
        if name == "report":
            command.add_argument(
                "--records",
                action="store_true",
                help="include all safe public observations and raw paired decisions",
            )
    args = parser.parse_args(argv)
    if args.command == "lab":
        if args.lab_action != "variants" and args.runtime is None:
            parser.error("lab run/freeze/report requires --runtime")
        if args.lab_action == "run" and args.source is None:
            parser.error("lab run requires --source capture.sqlite")
        if args.lab_action == "freeze" and not args.variants:
            parser.error("lab freeze requires --variants")
        if (args.start is None) != (args.end is None):
            parser.error("historical lab run requires both --start and --end")
        if args.start is not None:
            if args.lab_action != "run" or args.continuous or args.explore_rounds is not None:
                parser.error(
                    "historical bounds require finite lab run without --continuous or --explore-rounds"
                )
            if args.start < 0 or args.start >= args.end or args.start % 300000 or args.end % 300000:
                parser.error("historical bounds must be ordered five-minute boundaries")
    if (
        args.command == "doctor"
        and not args.account
        and (args.env_file is not None or args.wallet is not None)
    ):
        parser.error("--env-file and --wallet require doctor --account")
    if args.command == "dashboard" and args.env_file is not None and not args.account:
        parser.error("dashboard --env-file requires --account")
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
        snapshot = self._value.snapshot
        if (
            snapshot is not None
            and record.get("slug") == snapshot.market.slug
            and (
                (record.get("kind") == "anchor" and record.get("status") == "conflict")
                or (
                    record.get("kind") == "metadata_unavailable"
                    and record.get("code") == "UNSUPPORTED_RULE"
                )
            )
        ):
            # Official conflicts arrive before the producer's next awaited snapshot.
            self.invalidate(str(record.get("code", "ANCHOR_CONFLICT")))
        if record.get("kind") in ("stream_unavailable", "price_conflict") and record.get(
            "stream"
        ) in ("spot", "twap60", "books"):
            # Book failures can arrive while discovery or order preparation awaits.
            # Keep their generation change even if an older poll later completes.
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
        modes = (
            ("value", "momentum")
            if self.config.strategy.mode in ("value", "momentum")
            else STRATEGIES
        )
        decisions = self.ledger.record_snapshot(current, self.config, modes=modes)
        selected = evaluate(current, self.config)
        screen = (current.market.slug, *(d.reason for d in decisions))
        if screen != self._last_screen:
            self.emit(
                {
                    "kind": "raw_screens",
                    "received_ms": current.now_ms,
                    "slug": current.market.slug,
                    **{
                        mode: decision.reason
                        for mode, decision in zip(modes, decisions, strict=True)
                    },
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
    ledger.db.execute("SAVEPOINT report_read")
    try:
        return _report_snapshot(ledger, records=records)
    finally:
        ledger.db.execute("RELEASE SAVEPOINT report_read")


def _report_snapshot(ledger: Ledger, *, records: bool = False) -> dict[str, Any]:
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
            prior = final.get(slug)
            if prior is None:
                final[slug] = row
            elif prior.get("status") != "conflict":
                try:
                    first, current = (
                        Decimal(str(prior.get("price"))),
                        Decimal(str(row.get("price"))),
                    )
                    changed = (
                        not first.is_finite()
                        or not current.is_finite()
                        or abs(first - current) > ANCHOR_TOLERANCE
                    )
                except InvalidOperation:
                    changed = True
                if row.get("status") == "conflict" or changed:
                    # The producer retains its original numeric value on conflict.
                    evidence = row if row.get("status") == "conflict" else prior
                    final[slug] = {**evidence, "status": "conflict"}
    result = {
        "environment": ledger.environment,
        "summary": summary,
        "portfolios": ledger.portfolio_results(),
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


async def _finish_before(tasks: list[asyncio.Task[Any]], deadline: float) -> tuple[list[Any], bool]:
    """Spend only the remaining budget, then require cancellation acknowledgement."""
    if not tasks:
        return [], False
    _, pending = await asyncio.wait(
        tasks, timeout=max(0, deadline - asyncio.get_running_loop().time())
    )
    for task in pending:
        task.cancel()
    # Do not detach a task that may still execute orders. Cancellation-suppressing
    # code can delay this drain and therefore retains ownership (see README).
    return list(await asyncio.gather(*tasks, return_exceptions=True)), bool(pending)


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
    data = (
        MarketData(config, observer=cell.observe)
        if config.strategy.mode in ("value", "momentum")
        else MarketData(config, observer=cell.observe, enhanced=True)
    )
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
    data = (
        MarketData(config, observer=cell.observe)
        if config.strategy.mode in ("value", "momentum")
        else MarketData(config, observer=cell.observe, enhanced=True)
    )
    broker: Broker | None = None
    rpc = ReadOnlyRPC()
    signal_stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_stop.set)
    deadline = loop.time() + args.duration
    shutdown_deadline: float | None = None
    deadline_recorded = False

    def begin_shutdown() -> float:
        nonlocal shutdown_deadline
        if shutdown_deadline is None:
            ledger.request_stop()
            cell.invalidate("STOP_REQUESTED")
            _record(ledger, "SHUTDOWN_REQUESTED")
            shutdown_deadline = min(loop.time(), deadline) + args.shutdown_seconds
        return shutdown_deadline

    def note_deadline() -> None:
        nonlocal deadline_recorded
        if not deadline_recorded:
            _record(ledger, "SHUTDOWN_DEADLINE")
            deadline_recorded = True

    async def control() -> None:
        while True:
            ledger.record_clock(int(time.time() * 1000))
            cell.read()  # catches silent aging even while account I/O is in progress
            if shutdown_deadline is None and (
                signal_stop.is_set() or ledger.stop_requested() or loop.time() >= deadline
            ):
                begin_shutdown()
            if shutdown_deadline is not None and loop.time() >= shutdown_deadline:
                note_deadline()
                return
            await asyncio.sleep(min(0.25, max(0, (shutdown_deadline or deadline) - loop.time())))

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
            broker,
            ledger,
            config,
            session,
            read_exit_book=held_book,
            read_snapshot=cell.read,
            read_model_snapshot=data.current_snapshot,
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
    code = 2

    async def cleanup() -> None:
        nonlocal code
        limit = begin_shutdown()
        for task in tasks:
            task.cancel()
        _, expired = await _finish_before(tasks, limit)
        if expired:
            note_deadline()
            code = 2
        # Execution is conclusively stopped before transports or ownership close.
        closing = [asyncio.create_task(data.close()), asyncio.create_task(rpc.close())]
        if broker is not None:
            closing.append(asyncio.create_task(broker.close()))
        results, expired = await _finish_before(closing, limit)
        if expired:
            note_deadline()
            code = 2
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                _record(ledger, safe_reason(result))
                code = 2
        try:
            _record(ledger, "RUN_COMPLETED" if code == 0 else "RUN_UNRESOLVED")
            emit({"kind": "run_completed", "summary": asdict(ledger.summary())})
        finally:
            ledger.close()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sig)

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
        await data.__aenter__()
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
    except asyncio.CancelledError:
        begin_shutdown()
        _record(ledger, "RUN_CANCELLED")
        raise
    except Exception as exc:
        ledger.request_stop()
        _record(ledger, safe_reason(exc))
        raise
    finally:
        finalizing = asyncio.create_task(cleanup())
        cancelled = False
        while not finalizing.done():
            try:
                await asyncio.shield(finalizing)
            except asyncio.CancelledError:
                # Repeated caller cancellation must not release a live worker's lock.
                cancelled = True
        await finalizing
        if cancelled:
            raise asyncio.CancelledError
    return code


async def async_main(args: argparse.Namespace) -> int:
    if args.command == "archive":
        from btc5m.archive import archive_status

        emit(archive_status(args.source))
        return 0
    if args.command == "lab":
        if args.lab_action == "report":
            emit(json.loads((args.runtime / "report.json").read_text()))
            return 0
        from btc5m.lab import run_lab

        return await run_lab(args)
    if args.command == "credentials":
        return await configure_credentials(args)
    if args.command == "dashboard":
        from btc5m.dashboard import serve_dashboard
        from btc5m.dashboard_live import LiveDashboardReader

        async def dashboard_account() -> tuple[Any, str, Path]:
            credentials = load_credentials(args.env_file, None)
            path = runtime_path(repository(), credentials.wallet)
            client = await create_secure_client(
                private_key=credentials.private_key,
                wallet=credentials.wallet,
                credentials=credentials.api,
            )
            return client, credentials.wallet, path

        serve_dashboard(
            args.runtime,
            load_config(args.config),
            args.port,
            LiveDashboardReader(dashboard_account) if args.account else None,
        )
        return 0
    if args.command in ("stop", "status", "report"):
        if args.runtime.is_dir():
            from btc5m.comparison import paper_report, stop_paper

            if not (args.runtime / "paper.json").is_file():
                raise CLIError("RUNTIME_MISSING")
            if args.command == "stop":
                stop_paper(args.runtime)
                emit({"kind": "paper_stop_requested", "runtime": str(args.runtime.resolve())})
            else:
                emit(paper_report(args.runtime, records=getattr(args, "records", False)))
            return 0
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
    if getattr(args, "strategy", None) is not None:
        config = replace(config, strategy=replace(config.strategy, mode=args.strategy))
    if args.command == "paper":
        from btc5m.comparison import run_paper

        return await run_paper(args, config, emit)
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
