"""Six independent simulated portfolios on one public feed; no account credentials."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import time
from collections.abc import Callable
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from btc5m.config import STRATEGIES, Config
from btc5m.cross_duration import CrossDuration
from btc5m.engine import Engine
from btc5m.lab_tape import Tape
from btc5m.ledger import Ledger, LedgerError
from btc5m.market_data import DataUnavailable, MarketData
from btc5m.paper import PAPER_MATCHING_MODEL, PaperBroker
from btc5m.service import atomic_json, notify
from btc5m.strategy import SAMPLING_POLICY

MASTER_WALLET = "0x" + "00" * 20


def paper_report(path: Path, *, records: bool = False) -> dict[str, Any]:
    manifest = json.loads((path / "paper.json").read_text())
    if manifest.get("environment") != "paper" or manifest.get("version") != 1:
        raise LedgerError("INVALID_PAPER_MANIFEST")
    results: dict[str, Any] = {}
    for name in manifest["strategies"]:
        if name not in STRATEGIES:
            raise LedgerError("INVALID_PAPER_STRATEGY")
        wallet = "0x" + str(STRATEGIES.index(name) + 1).zfill(40)
        ledger = Ledger(path / name / "ledger.sqlite", wallet, readonly=True)
        try:
            ledger.db.execute("BEGIN")
            if ledger.environment != "paper":
                raise LedgerError("EXECUTION_ENVIRONMENT_MISMATCH")
            summary = ledger.summary()
            results[name] = {
                **ledger.portfolio_results()[name],
                "simulated_cash": summary.cash,
                "risk_reserved": summary.risk_reserve,
                "unresolved_orders": len(summary.unresolved_orders),
                "legacy_matching_orders": ledger.db.execute(
                    "SELECT COUNT(*) FROM intents i LEFT JOIN measurements m ON m.key='paper_order:'||i.id WHERE json_extract(i.data,'$.passive')=1 AND COALESCE(json_extract(m.data,'$.matching_model'),'')<>?",
                    (PAPER_MATCHING_MODEL,),
                ).fetchone()[0],
                "halts": summary.halts,
                "uncertain_rounds": [
                    r[0]
                    for r in ledger.db.execute(
                        "SELECT DISTINCT json_extract(data,'$.slug') FROM events WHERE kind='PUBLIC_OBSERVATION' AND json_extract(data,'$.kind')='paper_uncertainty' ORDER BY 1"
                    )
                ],
                "execution_reasons": dict(
                    ledger.db.execute(
                        "SELECT json_extract(data,'$.code'),COUNT(*) FROM events WHERE kind='PUBLIC_OBSERVATION' AND json_extract(data,'$.kind')='execution_result' GROUP BY 1"
                    )
                ),
            }
        finally:
            ledger.close()
    master = Ledger(path / "observations.sqlite", MASTER_WALLET, readonly=True)
    raw: dict[str, Any] = {}
    try:
        master.db.execute("BEGIN")
        screens = {
            f"{mode}:{reason}": count
            for mode, reason, count in master.db.execute(
                "SELECT json_extract(data,'$.mode'),json_extract(data,'$.decision.reason'),COUNT(*) FROM events WHERE kind='DECISION' GROUP BY 1,2"
            )
        }
        counts = dict(
            master.db.execute(
                "SELECT json_extract(data,'$.kind'),COUNT(*) FROM events WHERE kind='PUBLIC_OBSERVATION' GROUP BY 1"
            )
        )
        if records:
            raw = {"observations": master.observations(), "raw_decisions": master.decisions()}
    finally:
        master.close()
    return {
        "environment": "paper",
        "runtime": str(path.resolve()),
        "manifest": manifest,
        "portfolios": results,
        "screen_counts": dict(screens),
        "observation_counts": dict(counts),
        "limitations": [
            "Simulated fills and PnL, not venue execution or evidence of profitable live trading.",
            "Each portfolio is an independent counterfactual; simultaneous simulated orders do not compete with each other for public depth.",
            "Resting orders require subsequent direct SELL or complementary BUY volume. Same-price volume depletes the queue; trades strictly through the bid clear its obsolete queue. Book cancellations alone never create fills.",
            "Uncertain rounds with stream gaps must be excluded from performance conclusions.",
            "Simulated settlement assumes automatic zero-cost redemption after official labels; live redemption remains manual.",
        ],
        **raw,
    }


def stop_paper(path: Path) -> None:
    manifest = json.loads((path / "paper.json").read_text())
    if manifest.get("environment") != "paper":
        raise LedgerError("INVALID_PAPER_MANIFEST")
    Ledger.request_stop_at(path / "observations.sqlite")
    for name in manifest["strategies"]:
        if name not in STRATEGIES:
            raise LedgerError("INVALID_PAPER_STRATEGY")
        Ledger.request_stop_at(path / name / "ledger.sqlite")


async def run_paper(
    args: argparse.Namespace, config: Config, emit: Callable[[dict[str, Any]], None]
) -> int:
    selected = tuple(STRATEGIES) if args.strategies == "all" else tuple(args.strategies.split(","))
    if (
        not selected
        or len(set(selected)) != len(selected)
        or any(name not in STRATEGIES for name in selected)
    ):
        raise LedgerError("INVALID_PAPER_STRATEGIES")
    allocation = (config.risk.allocation_usd / len(selected)).quantize(
        Decimal(".01"), rounding=ROUND_DOWN
    )
    if allocation < config.risk.trade_budget_usd:
        raise LedgerError("PAPER_ALLOCATION_TOO_SMALL")
    path = args.runtime.resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    if shutil.disk_usage(path).free < 256 * 1024 * 1024:
        raise LedgerError("PAPER_DISK_RESERVE_REQUIRED")
    master = Ledger(path / "observations.sqlite", MASTER_WALLET, environment="paper")
    previous_ms = master.db.execute("SELECT at_ms FROM events ORDER BY id DESC LIMIT 1").fetchone()
    ledgers: list[Ledger] = []
    tasks: list[asyncio.Task[Any]] = []
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    data = MarketData(
        config,
        enhanced=True,
        observer=master.record_observation,
        capture_flow=getattr(args, "capture_flow", False),
        capture_archive=True,
    )
    code = 0
    lifecycle_started = False
    lifecycle_status = "failed"
    tape: Tape | None = None
    scanner: CrossDuration | None = None
    try:
        tape = Tape(path / "capture.sqlite")
        manifest = {
            "version": 1,
            "environment": "paper",
            "config_fingerprint": config.fingerprint,
            "strategies": selected,
            "total_allocation": str(config.risk.allocation_usd),
            "allocation_per_portfolio": str(allocation),
            "unused_allocation": str(config.risk.allocation_usd - allocation * len(selected)),
            "paper_latency_ms": config.experiments.paper_latency_ms,
        }
        manifest_path = path / "paper.json"
        if manifest_path.exists() and json.loads(manifest_path.read_text()) != json.loads(
            json.dumps(manifest)
        ):
            raise LedgerError("PAPER_CONFIGURATION_CHANGED_USE_NEW_RUNTIME")
        master.start_or_resume_session(config)
        master.clear_stop_request()
        atomic_json(manifest_path, manifest)
        assert data.archive is not None
        tape.start_capture(
            config,
            now_ms=int(time.time() * 1000),
            capture_flow=getattr(args, "capture_flow", False),
            session_id=data.archive.session_id,
        )
        cutoff = int(time.time() * 1000) - (config.strategy.volatility_long_seconds + 60) * 1000
        restored = data.restore_history(
            json.loads(row[0])
            for row in master.db.execute(
                "SELECT data FROM events WHERE kind='PUBLIC_OBSERVATION' AND at_ms>=? AND json_extract(data,'$.kind') IN ('spot','twap60','price_conflict') ORDER BY id",
                (cutoff,),
            )
        )
        if restored:
            emit(
                {
                    "kind": "paper_history_restored",
                    "points": restored,
                    "fresh_feed_still_required": True,
                }
            )
        brokers, engines = [], []
        for name in selected:
            risk = replace(
                config.risk,
                allocation_usd=allocation,
                daily_loss_usd=min(config.risk.daily_loss_usd, allocation),
                session_loss_usd=min(config.risk.session_loss_usd, allocation),
            )
            variant = replace(config, strategy=replace(config.strategy, mode=name), risk=risk)
            wallet = "0x" + str(STRATEGIES.index(name) + 1).zfill(40)
            ledger = Ledger(path / name / "ledger.sqlite", wallet, environment="paper")
            ledgers.append(ledger)
            session = ledger.start_or_resume_session(variant)
            ledger.clear_stop_request()
            broker = PaperBroker(
                ledger, variant, streams=data.streams, final_reference=data.final_reference
            )
            brokers.append(broker)
            engines.append(
                Engine(
                    broker,
                    ledger,
                    variant,
                    session,
                    read_exit_book=broker.book,
                    record_screens=False,
                )
            )
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await data.__aenter__()
        if getattr(args, "capture_flow", False):
            scanner = CrossDuration(data, config)
            tasks.append(asyncio.create_task(scanner.run()))
        now = int(time.time() * 1000)
        if previous_ms is not None and now - previous_ms[0] > config.data.max_price_age_ms:
            for broker in brokers:
                broker.observation_gap(now, "PAPER_RESTART_GAP")
            master.record_observation(
                {
                    "kind": "paper_recovery",
                    "received_ms": now,
                    "source_ms": previous_ms[0],
                    "code": "PAPER_RESTART_GAP",
                }
            )
        master.record_observation(
            {
                "kind": "paper_run",
                "received_ms": int(time.time() * 1000),
                "status": "started",
                "code": PAPER_MATCHING_MODEL,
                "source": SAMPLING_POLICY,
            }
        )
        lifecycle_started = True
        notify("READY=1\nSTATUS=Paper collector running")
        emit({"kind": "paper_started", **manifest, "runtime": str(path), "credentials_used": False})

        async def produce() -> None:
            last_code = None
            while True:
                try:
                    snapshot = await data.snapshot()
                    # One public record per variant, independent of its portfolio state.
                    master.record_snapshot(snapshot, config, modes=selected)
                    last_code = None
                except DataUnavailable as exc:
                    if exc.code != last_code:
                        emit({"kind": "paper_data_skip", "code": exc.code})
                        last_code = exc.code
                await asyncio.sleep(0.5)

        producer = asyncio.create_task(produce())
        tasks.append(producer)
        deadline = None if getattr(args, "continuous", False) else loop.time() + args.duration
        shutdown_deadline = None
        last_results: dict[str, tuple[str, str]] = {}
        last_heartbeat = 0.0
        last_capture = 0.0
        last_disk_check = loop.time()
        last_loop_ms = int(time.time() * 1000)
        while True:
            now = int(time.time() * 1000)
            interrupted = now - last_loop_ms > config.data.max_price_age_ms
            if interrupted:
                for broker in brokers:
                    broker.observation_gap(now, "PAPER_CAPTURE_GAP")
                master.record_observation(
                    {
                        "kind": "paper_interruption",
                        "received_ms": now,
                        "source_ms": last_loop_ms,
                        "code": "PAPER_CAPTURE_GAP",
                    }
                )
            last_loop_ms = now
            if loop.time() - last_disk_check >= 60:
                last_disk_check = loop.time()
                if shutil.disk_usage(path).free < 256 * 1024 * 1024:
                    raise LedgerError("PAPER_DISK_RESERVE_REQUIRED")
            data.retain_markets(
                tape.retained_markets(
                    tuple(p.market for ledger in ledgers for p in ledger.active_positions()),
                    now,
                )
            )
            if producer.done():
                await producer
                raise LedgerError("PAPER_DATA_WORKER_STOPPED")
            if shutdown_deadline is None and (
                (deadline is not None and loop.time() >= deadline)
                or stop.is_set()
                or master.stop_requested()
            ):
                shutdown_deadline = loop.time() + args.shutdown_seconds
                for ledger in ledgers:
                    ledger.request_stop()
            if loop.time() - last_heartbeat >= 5:
                master.record_observation(
                    {
                        "kind": "paper_heartbeat",
                        "received_ms": int(time.time() * 1000),
                        "status": "stopping" if shutdown_deadline is not None else "running",
                    }
                )
                last_heartbeat = loop.time()
                notify(
                    "WATCHDOG=1\nSTATUS="
                    + (
                        "Paper collector stopping"
                        if shutdown_deadline is not None
                        else "Paper collector running"
                    )
                )
            snapshot = None if interrupted else data.current_snapshot()
            if loop.time() - last_capture >= 0.5:
                # Capture the same current stream inputs used by the engines. Slow HTTP
                # discovery/label polling in produce() must not stall this recorder.
                assert tape is not None
                markets = dict(tape.known_markets)
                if snapshot:
                    markets[snapshot.market.slug] = snapshot.market
                labels: dict[str, Any] = {}
                for slug, market in markets.items():
                    final = data.final_reference(market)
                    if final is not None:
                        labels[slug] = {
                            "condition_id": market.condition_id,
                            "opening": str(final[0]),
                            "final": str(final[1]),
                        }
                    elif slug in tape.label_cache and data.final_reference_conflicted(market):
                        labels[slug] = None
                capture_ms = int(time.time() * 1000)
                research = data.streams.research_frame(capture_ms) if data.streams else None
                if research is not None and scanner is not None:
                    research["cross_duration"] = scanner.latest
                diagnostic = (
                    {
                        "code": "PAPER_CAPTURE_GAP",
                        "component": "recorder",
                        "received_ms": capture_ms,
                    }
                    if interrupted
                    else dict(data.snapshot_status)
                )
                tape.append(
                    capture_ms,
                    replace(snapshot, now_ms=capture_ms) if snapshot else None,
                    labels=labels,
                    code="CAPTURED" if snapshot else str(diagnostic["code"]),
                    research=research,
                    diagnostic=diagnostic,
                    max_gap_ms=config.data.max_price_age_ms,
                    archive=data.archive.drain(),
                )
                last_capture = loop.time()
            for name, broker, engine, ledger in zip(
                selected, brokers, engines, ledgers, strict=True
            ):
                broker.update(snapshot)
                now = int(time.time() * 1000)
                result = await engine.step(snapshot, None, now)
                key = (result.action, result.reason)
                if last_results.get(name) != key:
                    record = {
                        "kind": "execution_result",
                        "environment": "paper",
                        "mode": name,
                        "received_ms": now,
                        "status": result.action,
                        "code": result.reason,
                    }
                    emit(record)
                    ledger.record_observation(record)
                    last_results[name] = key
            if shutdown_deadline is not None:
                unresolved = any(
                    ledger.unresolved_orders() or ledger.active_positions() for ledger in ledgers
                )
                if not unresolved or loop.time() >= shutdown_deadline:
                    code = 2 if unresolved else 0
                    lifecycle_status = "unresolved" if unresolved else "stopped"
                    break
            await asyncio.sleep(0.25)
    finally:
        notify("STOPPING=1\nSTATUS=Saving paper runtime")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            async with asyncio.timeout(10):
                await data.close()
        except BaseException:
            lifecycle_status = "failed"
            raise
        finally:
            try:
                # Transports are closed: persist the last bounded archive batch even
                # when no complete trading snapshot was available at shutdown.
                if tape is not None and lifecycle_started and data.archive is not None:
                    archived = data.archive.drain()
                    if archived["events"] or archived["gap"]:
                        tape.append(
                            max(int(time.time() * 1000), tape.last_ms),
                            None,
                            code="COLLECTOR_STOPPED",
                            archive=archived,
                        )
                if lifecycle_started:
                    master.record_observation(
                        {
                            "kind": "paper_run",
                            "received_ms": int(time.time() * 1000),
                            "status": lifecycle_status,
                        }
                    )
            finally:
                for ledger in ledgers:
                    ledger.close()
                if tape is not None:
                    tape.close()
                master.close()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(sig)
    summary_report = paper_report(path)
    output = path / "report.json"
    atomic_json(output, summary_report)
    emit(
        {
            "kind": "paper_finished",
            "runtime": str(path),
            "report": str(output),
            "exit_code": code,
            "portfolios": summary_report["portfolios"],
        }
    )
    return code
