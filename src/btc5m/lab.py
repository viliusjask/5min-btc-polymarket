"""Registered experiment studies and future-only holdouts. No account/network adapter."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from btc5m.config import Config, load_config
from btc5m.domain import Side
from btc5m.lab_replay import Replay
from btc5m.lab_report import replay_report
from btc5m.lab_scoring import score_forecasts
from btc5m.lab_tape import Frame, Tape, encode
from btc5m.lab_variants import Valuations, Variant, default_variants, variant_from
from btc5m.service import atomic_json, notify

SEMANTIC_FILES = (
    "config.py",
    "domain.py",
    "engine.py",
    "execution_types.py",
    "ledger.py",
    "paper.py",
    "market_data.py",
    "streams.py",
    "strategy.py",
    "lab.py",
    "lab_tape.py",
    "lab_variants.py",
    "lab_replay.py",
    "lab_report.py",
    "lab_scoring.py",
)


def implementation_id() -> str:
    root = Path(__file__).parent
    return hashlib.sha256(
        b"".join(name.encode() + b"\0" + (root / name).read_bytes() for name in SEMANTIC_FILES)
    ).hexdigest()


def _database(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=5)
    os.chmod(path, 0o600)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS forecasts(slug TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS phases(id TEXT PRIMARY KEY, data TEXT NOT NULL);
    """)
    return db


def freeze(
    runtime: Path,
    variant_ids: list[str],
    *,
    now_ms: int | None = None,
    test_rounds: int = 288,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = json.loads((runtime / "study.json").read_text())
    if (
        manifest.get("environment") != "paper-lab"
        or manifest.get("implementation") != implementation_id()
    ):
        raise ValueError("LAB_IMPLEMENTATION_CHANGED_USE_NEW_STUDY")
    if not variant_ids or len(set(variant_ids)) != len(variant_ids) or len(variant_ids) > 8:
        raise ValueError("SELECT_ONE_TO_EIGHT_UNIQUE_VARIANTS")
    if not set(variant_ids) <= {v["ident"] for v in manifest["variants"]}:
        raise ValueError("UNKNOWN_VARIANT")
    if type(test_rounds) is not int or not 12 <= test_rounds <= 2016:
        raise ValueError("TEST_ROUNDS_MUST_BE_12_TO_2016")
    with Tape(Path(manifest["source"]), readonly=True) as tape:
        if tape.identity != manifest["tape_identity"]:
            raise ValueError("LAB_SOURCE_IDENTITY_CHANGED")
        stamp = max(int(time.time() * 1000) if now_ms is None else now_ms, tape.last_ms)
        start = (stamp // 300000 + 1) * 300000
        phase = {
            "id": "test-" + uuid.uuid4().hex[:12],
            "kind": "holdout",
            "created_ms": stamp,
            "start_ms": start,
            "end_ms": start + test_rounds * 300000,
            "variant_ids": variant_ids,
            "source_highwater": tape.highwater(),
            "implementation": manifest["implementation"],
            "selection": selection or {"method": "operator preselected"},
            "allocation_per_variant": "100",
            "mutable": False,
        }
    db = _database(runtime / "study.sqlite")
    try:
        with db:
            db.execute("INSERT INTO phases VALUES (?,?)", (phase["id"], encode(phase)))
    finally:
        db.close()
    return phase


class Study:
    def __init__(
        self,
        source: Path,
        runtime: Path,
        config: Config,
        *,
        dense: bool | None = None,
        variants: tuple[Variant, ...] | None = None,
        explore_rounds: int | None = None,
    ) -> None:
        self.path = runtime.resolve()
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = os.open(self.path / "worker.lock", os.O_CREAT | os.O_RDWR, 0o600)
        self.runners: dict[tuple[str, str], Replay] = {}
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.lock)
            raise ValueError("LAB_WORKER_ALREADY_RUNNING") from None
        try:
            self.tape = Tape(source, readonly=True)
            manifest_path = self.path / "study.json"
            if manifest_path.exists():
                self.manifest = json.loads(manifest_path.read_text())
                if (
                    dense is not None
                    and dense != self.manifest["dense"]
                    or explore_rounds is not None
                    and explore_rounds * 300000
                    != self.manifest["explore_end_ms"] - self.manifest["start_ms"]
                    or variants is not None
                    and json.loads(encode([v.record() for v in variants]))
                    != self.manifest["variants"]
                ):
                    raise ValueError("LAB_TRIALS_CHANGED_USE_NEW_STUDY")
            else:
                explore_rounds = 288 if explore_rounds is None else explore_rounds
                dense = bool(dense)
                if type(explore_rounds) is not int or not 12 <= explore_rounds <= 2016:
                    raise ValueError("EXPLORE_ROUNDS_MUST_BE_12_TO_2016")
                first = self.tape.db.execute(
                    "SELECT now_ms FROM frames ORDER BY id LIMIT 1"
                ).fetchone()
                stamp = first[0] if first else int(time.time() * 1000)
                start = (stamp // 300000 + 1) * 300000
                selected = (
                    variants if variants is not None else default_variants(config, dense=dense)
                )
                if not selected or len({v.ident for v in selected}) != len(selected):
                    raise ValueError("LAB_REQUIRES_UNIQUE_REGISTERED_VARIANTS")
                self.manifest = json.loads(
                    encode(
                        {
                            "version": 1,
                            "environment": "paper-lab",
                            "source": str(source.resolve()),
                            "tape_identity": self.tape.identity,
                            "implementation": implementation_id(),
                            "created_ms": int(time.time() * 1000),
                            "base_config": config.fingerprint,
                            "start_ms": start,
                            "explore_end_ms": start + explore_rounds * 300000,
                            "dense": dense,
                            "variants": [v.record() for v in selected],
                            "selection_policy": {
                                "minimum_clean_completed_rounds": 30,
                                "maximum_selected": 3,
                                "positive_clean_profit_required": True,
                                "control": "control-value",
                                "test_rounds": 288,
                            },
                        }
                    )
                )
                atomic_json(manifest_path, self.manifest)
            if self.manifest.get("implementation") != implementation_id():
                raise ValueError("LAB_IMPLEMENTATION_CHANGED_USE_NEW_STUDY")
            if (
                self.manifest.get("version") != 1
                or self.manifest.get("environment") != "paper-lab"
                or self.manifest.get("tape_identity") != self.tape.identity
            ):
                raise ValueError("LAB_SOURCE_IDENTITY_CHANGED")
            if self.manifest["base_config"] != config.fingerprint:
                raise ValueError("LAB_CONFIGURATION_CHANGED_USE_NEW_STUDY")
            self.variants = {v.ident: v for v in map(variant_from, self.manifest["variants"])}
            self.db = _database(self.path / "study.sqlite")
            exploration = {
                "id": "explore",
                "kind": "exploratory",
                "start_ms": self.manifest["start_ms"],
                "end_ms": None,
                "variant_ids": list(self.variants),
            }
            with self.db:
                self.db.execute(
                    "INSERT OR IGNORE INTO phases VALUES (?,?)", ("explore", encode(exploration))
                )
            self.cursor = int(self._meta("cursor") or 0)
            self.now_ms = int(self._meta("now_ms") or 0)
            self.labels = self.tape.labels_at(self.cursor)
            self.phases: list[dict[str, Any]] = []
            self.refresh_phases()
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> Study:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def refresh_phases(self) -> None:
        self.phases = [
            json.loads(row[0]) for row in self.db.execute("SELECT data FROM phases ORDER BY rowid")
        ]
        for phase in self.phases:
            for ident in phase["variant_ids"]:
                key = phase["id"], ident
                if key not in self.runners:
                    runner = Replay(
                        self.path / phase["id"] / ident / "ledger.sqlite",
                        self.variants[ident],
                        self.tape.identity,
                        phase["start_ms"],
                        phase["end_ms"],
                    )
                    if runner.cursor == 0 and phase["kind"] == "holdout":
                        # No entry before the future boundary. Initialize at the frozen
                        # input watermark, without replaying earlier trades or labels.
                        with runner.ledger.db:
                            runner.ledger._set("lab_cursor", str(phase["source_highwater"]))
                            runner.ledger._set(
                                "lab_labels", encode(self.tape.labels_at(phase["source_highwater"]))
                            )
                        runner.cursor = phase["source_highwater"]
                        runner.labels = self.tape.labels_at(runner.cursor)
                    self.runners[key] = runner

    def _forecast(self, frame: Frame, cache: Valuations | None) -> None:
        slot = frame.now_ms // 300000 * 300
        slug = f"btc-updown-5m-{slot}"
        old = self.db.execute("SELECT data FROM forecasts WHERE slug=?", (slug,)).fetchone()
        row = (
            json.loads(old[0])
            if old
            else {"slug": slug, "target_ms": (slot + 180) * 1000, "status": "pending"}
        )
        if row["status"] == "pending" and frame.now_ms >= row["target_ms"]:
            if frame.now_ms > row["target_ms"] + 2000 or frame.snapshot is None:
                if frame.now_ms > row["target_ms"] + 2000:
                    row["status"] = "missing"
            else:
                snap = frame.snapshot
                # Independent of entry eligibility; use the central value even if no
                # contract passes its price/surplus screen.
                base = next(iter(self.variants.values())).config
                control = Variant(
                    "forecast",
                    "forecast",
                    "Forecast",
                    replace(base, strategy=replace(base.strategy, mode="value")),
                )
                fast = replace(
                    control,
                    config=replace(base, strategy=replace(base.strategy, mode="fast_value")),
                )
                assert cache is not None
                value, faster = cache.get(control), cache.get(fast)
                mid = (
                    float((snap.up_book.bids[0].price + snap.up_book.asks[0].price) / 2)
                    if snap.up_book.bids
                    and snap.up_book.asks
                    and snap.up_book.bids[0].price < snap.up_book.asks[0].price
                    else None
                )
                row.update(
                    status="observed",
                    at_ms=frame.now_ms,
                    probability=value.probability_up,
                    fast_probability=faster.probability_up,
                    market_probability=mid if value.reason == "VALID" else None,
                    model_reason=value.reason,
                    fast_reason=faster.reason,
                    condition_id=snap.market.condition_id,
                    reference=str(snap.market.reference_price),
                    scenario_floor_up=value.floors.get(Side.UP),
                    scenario_floor_down=value.floors.get(Side.DOWN),
                )
        self.db.execute("INSERT OR REPLACE INTO forecasts VALUES (?,?)", (slug, encode(row)))
        # A missing capture cannot vanish from the denominator when the process resumes.
        if self.now_ms:
            first = self.now_ms // 300000 * 300
            for missed in range(first, slot, 300):
                key = f"btc-updown-5m-{missed}"
                self.db.execute(
                    "INSERT OR IGNORE INTO forecasts VALUES (?,?)",
                    (
                        key,
                        encode(
                            {"slug": key, "target_ms": (missed + 180) * 1000, "status": "missing"}
                        ),
                    ),
                )
            self.db.execute(
                "UPDATE forecasts SET data=json_set(data,'$.status','missing') WHERE json_extract(data,'$.status')='pending' AND json_extract(data,'$.target_ms')+2000<?",
                (frame.now_ms,),
            )

    async def advance(self, *, limit: int = 32) -> int:
        self.refresh_phases()
        cursor = min([self.cursor, *(r.cursor for r in self.runners.values())])
        count = 0
        for frame in self.tape.read_after(cursor, limit=limit):
            cache = Valuations(frame.snapshot) if frame.snapshot else None
            for runner in self.runners.values():
                await runner.apply(frame, cache)
            if frame.ident > self.cursor:
                with self.db:
                    self._forecast(frame, cache)
                    self.db.execute(
                        "INSERT OR REPLACE INTO meta VALUES ('cursor',?)", (str(frame.ident),)
                    )
                    self.db.execute(
                        "INSERT OR REPLACE INTO meta VALUES ('now_ms',?)", (str(frame.now_ms),)
                    )
                self.labels.update(frame.labels)
                self.cursor, self.now_ms = frame.ident, frame.now_ms
            count += 1
            await asyncio.sleep(0)
        return count

    def forecasts(self) -> list[dict[str, Any]]:
        rows = [
            json.loads(row[0])
            for row in self.db.execute("SELECT data FROM forecasts ORDER BY slug")
        ]
        from decimal import Decimal

        for row in rows:
            label = self.labels.get(row["slug"])
            if (
                label
                and label["condition_id"] == row.get("condition_id")
                and row.get("reference") not in (None, "None")
                and abs(Decimal(label["opening"]) - Decimal(row["reference"]))
                <= Decimal(".00000001")
            ):
                row["outcome"] = int(Decimal(label["final"]) >= Decimal(label["opening"]))
            else:
                row["outcome"] = None
        return rows

    def report(self) -> dict[str, Any]:
        phases = []
        forecasts = self.forecasts()
        for phase in self.phases:
            results = [
                replay_report(self.runners[phase["id"], ident]) for ident in phase["variant_ids"]
            ]
            subset = [
                r
                for r in forecasts
                if phase["start_ms"] <= int(r["slug"].rsplit("-", 1)[1]) * 1000
                and (
                    phase["end_ms"] is None
                    or int(r["slug"].rsplit("-", 1)[1]) * 1000 < phase["end_ms"]
                )
            ]
            phases.append({**phase, "variants": results, "forecasts": score_forecasts(subset)})
        return json.loads(
            encode(
                {
                    "environment": "paper-lab",
                    "status": "running",
                    "generated_ms": int(time.time() * 1000),
                    "as_of_ms": self.now_ms,
                    "source_highwater": self.tape.highwater(),
                    "cursor": self.cursor,
                    "implementation": self.manifest["implementation"],
                    "trial_count": len(self.variants),
                    "explore_end_ms": self.manifest["explore_end_ms"],
                    "phases": phases,
                    "forecasts": score_forecasts(forecasts),
                    "limitations": [
                        "Paper execution on recorded public inputs; no venue orders. Independent variants cannot have their PnL added together.",
                        "Same $100 starting capital and fixed trade budget, with existing daily/session loss guards; cash is not replenished.",
                        "The recording cadence bounds execution precision. Latency variants wait at least their configured delay and then require subsequent protected depth.",
                        "Uncertain rounds are excluded from clean completed profit. Missing marks can conceal larger drawdowns; bid marks do not guarantee a full exit.",
                        "All rankings are exploratory until a frozen later-data test completes. Thirty completed rounds is a reporting/selection gate, not statistical proof.",
                        "No market impact, maker rebates, gas, or actual redemption latency is modeled. Official labels enable zero-cost paper payouts.",
                    ],
                }
            )
        )

    def auto_freeze(self) -> dict[str, Any] | None:
        if self._meta("auto_frozen") or self.now_ms < self.manifest["explore_end_ms"]:
            return None
        cutoff = self.manifest["explore_end_ms"]
        for prior in self.phases:
            if (
                prior.get("selection", {}).get("automatic")
                and prior["selection"]["exploration_end_ms"] == cutoff
            ):
                with self.db:
                    self.db.execute(
                        "INSERT OR REPLACE INTO meta VALUES ('auto_frozen',?)", (prior["id"],)
                    )
                return None
        ranked = [
            replay_report(r, before_ms=cutoff)
            for (phase, _), r in self.runners.items()
            if phase == "explore"
        ]
        qualified = [
            r
            for r in ranked
            if r["clean_completed_rounds"] >= 30
            and r["clean_completed_pnl"] > 0
            and r["unresolved_rounds"] == 0
        ]
        qualified.sort(key=lambda r: (-r["clean_completed_pnl"], r["ident"]))
        chosen = [r["ident"] for r in qualified[:3]]
        control = next(
            (v.ident for v in self.variants.values() if v.name == "control-value"),
            next(iter(self.variants)),
        )
        if control not in chosen:
            chosen.append(control)
        selection = {
            "automatic": True,
            "method": "predeclared top-three positive clean profit; minimum30 completed rounds; plus Value control",
            "exploration_end_ms": cutoff,
            "qualified_count": len(qualified),
            "trial_count": len(ranked),
            "selected_exploration_results": [r for r in ranked if r["ident"] in chosen],
            "reason": "qualified shortlist" if qualified else "insufficient evidence; control only",
        }
        phase = freeze(self.path, chosen, selection=selection)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('auto_frozen',?)", (phase["id"],))
        self.refresh_phases()
        return phase

    def close(self) -> None:
        for runner in self.runners.values():
            runner.close()
        if hasattr(self, "db"):
            self.db.close()
        if hasattr(self, "tape"):
            self.tape.close()
        os.close(self.lock)


async def run_lab(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.lab_action == "freeze":
        print(encode(freeze(args.runtime, args.variants.split(","), test_rounds=args.test_rounds)))
        return 0
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        with Study(
            args.source, args.runtime, config, dense=args.dense, explore_rounds=args.explore_rounds
        ) as study:
            notify("READY=1\nSTATUS=Paper experiment worker running")
            last_report = 0.0
            while not stop.is_set():
                if shutil.disk_usage(study.path).free < 512 * 1024 * 1024:
                    raise ValueError("LAB_DISK_RESERVE_REQUIRED")
                count = await study.advance(limit=8)
                if time.monotonic() - last_report >= 10 or not count and not args.continuous:
                    study.auto_freeze()
                    atomic_json(study.path / "report.json", study.report())
                    notify(f"WATCHDOG=1\nSTATUS=Experiment cursor {study.cursor}")
                    last_report = time.monotonic()
                if not count:
                    if not args.continuous:
                        break
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=1)
                    except TimeoutError:
                        pass
            report = study.report()
            report["status"] = "stopped"
            atomic_json(study.path / "report.json", report)
            print(
                encode(
                    {
                        "kind": "lab_stopped",
                        "cursor": study.cursor,
                        "trial_count": len(study.variants),
                        "runtime": str(study.path),
                    }
                )
            )
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
    return 0
