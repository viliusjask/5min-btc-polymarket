"""Six independent simulated portfolios on one public feed; no account credentials."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from btc5m.config import STRATEGIES, Config
from btc5m.engine import Engine
from btc5m.ledger import Ledger, LedgerError
from btc5m.market_data import DataUnavailable, MarketData
from btc5m.paper import PaperBroker

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
            observations = ledger.observations()
            results[name] = {
                **ledger.portfolio_results()[name],
                "simulated_cash": summary.cash,
                "risk_reserved": summary.risk_reserve,
                "unresolved_orders": len(summary.unresolved_orders),
                "halts": summary.halts,
                "uncertain_rounds": sorted(
                    {r.get("slug") for r in observations if r.get("kind") == "paper_uncertainty"}
                ),
                "execution_reasons": dict(
                    Counter(
                        str(r.get("code"))
                        for r in observations
                        if r.get("kind") == "execution_result"
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
            "Resting orders require subsequent aggressive SELL volume at/below the quote after observed same-price queue depth; cancellations ahead are not credited.",
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
    master = Ledger(path / "observations.sqlite", MASTER_WALLET, environment="paper")
    ledgers: list[Ledger] = []
    tasks: list[asyncio.Task[Any]] = []
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    data = MarketData(config, enhanced=True, observer=master.record_observation)
    code = 0
    try:
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
        manifest_temporary = manifest_path.with_suffix(".tmp")
        manifest_temporary.write_text(json.dumps(manifest, indent=2) + "\n")
        os.replace(manifest_temporary, manifest_path)
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
        deadline, shutdown_deadline = loop.time() + args.duration, None
        last_results: dict[str, tuple[str, str]] = {}
        while True:
            data.retain_markets(
                tuple(p.market for ledger in ledgers for p in ledger.active_positions())
            )
            if producer.done():
                await producer
                raise LedgerError("PAPER_DATA_WORKER_STOPPED")
            if shutdown_deadline is None and (
                loop.time() >= deadline or stop.is_set() or master.stop_requested()
            ):
                shutdown_deadline = loop.time() + args.shutdown_seconds
                for ledger in ledgers:
                    ledger.request_stop()
            snapshot = data.current_snapshot()
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
                    break
            await asyncio.sleep(0.25)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await data.close()
        finally:
            for ledger in ledgers:
                ledger.close()
            master.close()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sig)
    summary_report = paper_report(path)
    output = path / "report.json"
    output.write_text(json.dumps(summary_report, default=str, indent=2) + "\n")
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
