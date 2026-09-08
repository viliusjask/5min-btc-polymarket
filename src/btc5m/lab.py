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

from btc5m.archive import historical_window
from btc5m.config import Config, load_config
from btc5m.domain import Side
from btc5m.flow_signals import order_flow_variants
from btc5m.lab_replay import Replay
from btc5m.lab_report import replay_report
from btc5m.lab_scoring import score_forecasts
from btc5m.lab_tape import Frame, Tape, encode
from btc5m.lab_variants import (
    Valuations,
    Variant,
    default_variants,
    original_six_variants,
    variant_from,
)
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
    "archive.py",
    "lab_tape.py",
    "lab_variants.py",
    "lab_replay.py",
    "lab_report.py",
    "lab_scoring.py",
    "order_flow.py",
    "flow_signals.py",
    "cross_duration.py",
    "pairing.py",
    "paper_conversions.py",
    "split_engine.py",
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
        CREATE TABLE IF NOT EXISTS research(frame_id INTEGER PRIMARY KEY, at_ms INTEGER NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS scans(at_ms INTEGER PRIMARY KEY, data TEXT NOT NULL);
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
    if manifest.get("historical"):
        raise ValueError("HISTORICAL_STUDY_IS_EXPLORATORY")
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


def registered_variants(config: Config, suite: str, *, dense: bool = False) -> tuple[Variant, ...]:
    if (
        suite not in ("directional", "order-flow", "original-six")
        or suite != "directional"
        and dense
    ):
        raise ValueError("INVALID_LAB_SUITE")
    if suite == "original-six":
        return original_six_variants(config)
    if suite == "order-flow":
        return order_flow_variants(config)
    return default_variants(config, dense=dense)


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
        suite: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        variant_ids: tuple[str, ...] | None = None,
    ) -> None:
        self.path = runtime.resolve()
        if (start_ms is None) != (end_ms is None):
            raise ValueError("HISTORICAL_START_AND_END_REQUIRED")
        if start_ms is not None and explore_rounds is not None:
            raise ValueError("HISTORICAL_RANGE_REPLACES_EXPLORE_ROUNDS")
        if (
            start_ms is not None
            and self.path.exists()
            and not (self.path / "study.json").exists()
            and any(p.name != "worker.lock" for p in self.path.iterdir())
        ):
            raise ValueError("HISTORICAL_REQUIRES_NEW_STUDY_RUNTIME")
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = os.open(self.path / "worker.lock", os.O_CREAT | os.O_RDWR, 0o600)
        self.runners: dict[tuple[str, str], Replay] = {}
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.lock)
            raise ValueError("LAB_WORKER_ALREADY_RUNNING") from None
        try:
            manifest_path = self.path / "study.json"
            existing = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
            if manifest_path.exists() and not isinstance(existing, dict):
                raise ValueError("INVALID_LAB_MANIFEST")
            # Replay restores labels at its own cursor below. Do not eagerly parse
            # labels appended after a historical study's frozen archive boundary.
            self.tape = Tape(
                source,
                readonly=True,
                label_highwater=0
                if start_ms is not None or existing and existing.get("historical")
                else None,
            )
            if isinstance(existing, dict):
                self.manifest: dict[str, Any] = existing
                if (
                    dense is not None
                    and dense != self.manifest["dense"]
                    or explore_rounds is not None
                    and explore_rounds * 300000
                    != self.manifest["explore_end_ms"] - self.manifest["start_ms"]
                    or variants is not None
                    and json.loads(encode([v.record() for v in variants]))
                    != self.manifest["variants"]
                    or suite is not None
                    and suite != self.manifest.get("suite", "directional")
                    or start_ms is not None
                    and (
                        not self.manifest.get("historical")
                        or start_ms != self.manifest["start_ms"]
                        or end_ms != self.manifest["explore_end_ms"]
                    )
                    or variant_ids is not None
                    and list(variant_ids) != [v["ident"] for v in self.manifest["variants"]]
                ):
                    raise ValueError("LAB_TRIALS_CHANGED_USE_NEW_STUDY")
            else:
                explore_rounds = 288 if explore_rounds is None else explore_rounds
                dense = bool(dense)
                suite = suite or "directional"
                registered = registered_variants(config, suite, dense=dense)
                if type(explore_rounds) is not int or not 12 <= explore_rounds <= 2016:
                    raise ValueError("EXPLORE_ROUNDS_MUST_BE_12_TO_2016")
                source_start = 0
                if suite == "order-flow":
                    first_id = self.tape.db.execute(
                        "SELECT value FROM meta WHERE key='research_first_frame'"
                    ).fetchone()
                    if first_id is None:
                        raise ValueError("FLOW_RECORDING_REQUIRED_START_PAPER_WITH_CAPTURE_FLOW")
                    source_start = int(first_id[0]) - 1
                first = self.tape.db.execute(
                    "SELECT now_ms FROM frames WHERE id>? ORDER BY id LIMIT 1", (source_start,)
                ).fetchone()
                stamp = first[0] if first else int(time.time() * 1000)
                start = (stamp // 300000 + 1) * 300000
                selected = variants if variants is not None else registered
                if variant_ids is not None:
                    known = {v.ident: v for v in selected}
                    if (
                        not variant_ids
                        or len(set(variant_ids)) != len(variant_ids)
                        or not set(variant_ids) <= known.keys()
                    ):
                        raise ValueError("SELECT_UNIQUE_REGISTERED_VARIANTS")
                    selected = tuple(known[ident] for ident in variant_ids)
                if not selected or len({v.ident for v in selected}) != len(selected):
                    raise ValueError("LAB_REQUIRES_UNIQUE_REGISTERED_VARIANTS")
                historical = None
                if start_ms is not None:
                    assert end_ms is not None
                    historical = historical_window(
                        source,
                        start_ms,
                        end_ms,
                        warmup_ms=max(
                            v.config.strategy.volatility_long_seconds + 60 for v in selected
                        )
                        * 1000,
                    )
                    if historical["tape_identity"] != self.tape.identity:
                        raise ValueError("LAB_SOURCE_IDENTITY_CHANGED")
                    # Flow history begins only where the recorder explicitly enabled it.
                    if suite == "order-flow" and (first is None or first[0] >= end_ms):
                        raise ValueError("FLOW_RECORDING_REQUIRED_IN_HISTORICAL_RANGE")
                    source_start = max(source_start, historical["source_start"])
                    if source_start != historical["source_start"]:
                        warmup = self.tape.db.execute(
                            "SELECT now_ms FROM frames WHERE id>? ORDER BY id LIMIT 1",
                            (source_start,),
                        ).fetchone()[0]
                        historical.update(
                            source_start=source_start,
                            warmup_first_ms=warmup if warmup < start_ms else None,
                            warmup_available_span_ms=max(0, start_ms - warmup),
                        )
                    start = start_ms
                self.manifest = json.loads(
                    encode(
                        {
                            "version": 1,
                            "suite": suite,
                            "source_start": source_start,
                            "environment": "paper-lab",
                            "source": str(source.resolve()),
                            "tape_identity": self.tape.identity,
                            "implementation": implementation_id(),
                            "created_ms": int(time.time() * 1000),
                            "base_config": config.fingerprint,
                            "start_ms": start,
                            "explore_end_ms": end_ms
                            if historical
                            else start + explore_rounds * 300000,
                            **({"historical": historical} if historical else {}),
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
            self.historical = self.manifest.get("historical")
            self.source_cap = self.historical["source_highwater"] if self.historical else None
            if self.source_cap is not None and self.tape.highwater() < self.source_cap:
                raise ValueError("HISTORICAL_SOURCE_TRUNCATED")
            self.db = _database(self.path / "study.sqlite")
            exploration = {
                "id": "explore",
                "kind": "exploratory",
                "start_ms": self.manifest["start_ms"],
                "end_ms": self.manifest["explore_end_ms"] if self.historical else None,
                "variant_ids": list(self.variants),
            }
            with self.db:
                self.db.execute(
                    "INSERT OR IGNORE INTO phases VALUES (?,?)", ("explore", encode(exploration))
                )
                if self.historical:
                    self.db.executemany(
                        "INSERT OR IGNORE INTO forecasts VALUES (?,?)",
                        (
                            (
                                f"btc-updown-5m-{stamp // 1000}",
                                encode(
                                    {
                                        "slug": f"btc-updown-5m-{stamp // 1000}",
                                        "target_ms": stamp + 180000,
                                        "status": "pending",
                                    }
                                ),
                            )
                            for stamp in range(
                                self.manifest["start_ms"], self.manifest["explore_end_ms"], 300000
                            )
                        ),
                    )
            self.cursor = int(self._meta("cursor") or self.manifest.get("source_start", 0))
            self.now_ms = int(self._meta("now_ms") or 0)
            if self.source_cap is not None and self.cursor > self.source_cap:
                raise ValueError("HISTORICAL_CURSOR_OUTSIDE_ARCHIVE")
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
        if self.historical and any(
            p["kind"] != "exploratory" or p["end_ms"] != self.manifest["explore_end_ms"]
            for p in self.phases
        ):
            raise ValueError("HISTORICAL_STUDY_IS_EXPLORATORY")
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
                    self.runners[key] = runner
                    if self.source_cap is not None and runner.cursor > self.source_cap:
                        raise ValueError("HISTORICAL_CURSOR_OUTSIDE_ARCHIVE")
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
                    elif runner.cursor == 0 and self.manifest.get("source_start", 0):
                        runner.cursor = self.manifest["source_start"]
                        runner.labels = self.tape.labels_at(runner.cursor)
                        with runner.ledger.db:
                            runner.ledger._set("lab_cursor", str(runner.cursor))
                            runner.ledger._set("lab_labels", encode(runner.labels))
                    if self.historical:
                        runner.labels = self.tape.labels_at(runner.cursor)

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
            if self.historical:
                first = max(first, self.manifest["start_ms"] // 1000)
            for missed in range(first, slot, 300):
                key = f"btc-updown-5m-{missed}"
                self.db.execute(
                    "INSERT INTO forecasts VALUES (?,?) ON CONFLICT(slug) DO UPDATE SET data=excluded.data WHERE json_extract(forecasts.data,'$.status')='pending'"
                    if self.historical
                    else "INSERT OR IGNORE INTO forecasts VALUES (?,?)",
                    (
                        key,
                        encode(
                            {"slug": key, "target_ms": (missed + 180) * 1000, "status": "missing"}
                        ),
                    ),
                )
            predicate = ""
            parameters: tuple[Any, ...] = (frame.now_ms,)
            if self.historical:
                # Only the prior/current receipt round can have become overdue;
                # do not revisit the entire pre-registered historical interval.
                predicate = " AND slug IN (?,?)"
                parameters += (slug, f"btc-updown-5m-{first}")
            self.db.execute(
                "UPDATE forecasts SET data=json_set(data,'$.status','missing') WHERE json_extract(data,'$.status')='pending' AND json_extract(data,'$.target_ms')+2000<?"
                + predicate,
                parameters,
            )

    async def advance(self, *, limit: int = 32) -> int:
        self.refresh_phases()
        cursor = min([self.cursor, *(r.cursor for r in self.runners.values())])
        if self.source_cap is not None:
            # Count only the bounded next batch, so read_after never decodes newer
            # frames, including when the source has nonconsecutive row IDs.
            limit = len(
                self.tape.db.execute(
                    "SELECT id FROM frames WHERE id>? AND id<=? ORDER BY id LIMIT ?",
                    (cursor, self.source_cap, limit),
                ).fetchall()
            )
            if not limit:
                return 0
        count = 0
        for frame in self.tape.read_after(cursor, limit=limit):
            cache = Valuations(frame.snapshot) if frame.snapshot else None
            for runner in self.runners.values():
                await runner.apply(frame, cache)
            if frame.ident > self.cursor:
                with self.db:
                    if (
                        not self.historical
                        or self.manifest["start_ms"]
                        <= frame.now_ms
                        < self.manifest["explore_end_ms"]
                    ):
                        self._forecast(frame, cache)
                    elif self.now_ms < self.manifest["explore_end_ms"] <= frame.now_ms:
                        self.db.execute(
                            "UPDATE forecasts SET data=json_set(data,'$.status','missing') WHERE json_extract(data,'$.status')='pending'"
                        )
                    if frame.research is not None and self.manifest.get("suite") == "order-flow":
                        self.db.execute(
                            "INSERT INTO research VALUES (?,?,?)",
                            (frame.ident, frame.now_ms, encode(frame.research.get("flow", {}))),
                        )
                        scan = frame.research.get("cross_duration")
                        if scan is not None:
                            self.db.execute(
                                "INSERT OR IGNORE INTO scans VALUES (?,?)",
                                (scan["received_ms"], encode(scan)),
                            )
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
        historical = None
        if self.historical:
            unresolved = []
            for (_, ident), runner in self.runners.items():
                positions = len(runner.ledger.active_positions())
                claimable = [
                    p
                    for p in runner.ledger.positions()
                    if p.status == "CLAIMABLE" and p.claimable_value > 0
                ]
                orders = len(runner.ledger.unresolved_orders())
                if positions or claimable or orders:
                    unresolved.append(
                        {
                            "ident": ident,
                            "open_positions": positions,
                            "claimable_positions": len(claimable),
                            "claimable_value": str(sum(p.claimable_value for p in claimable)),
                            "unresolved_orders": orders,
                        }
                    )
            historical = {
                **self.historical,
                "complete": self.cursor == self.source_cap
                and all(r.cursor == self.source_cap for r in self.runners.values()),
                "unresolved_variants": unresolved,
                "interpretation": "Selected historical entries are exploratory. Later frames and official labels stop at the frozen archive limit; unresolved exposure is not counted as a completed return.",
            }
        return json.loads(
            encode(
                {
                    "environment": "paper-lab",
                    "suite": self.manifest.get("suite", "directional"),
                    "status": "complete" if historical and historical["complete"] else "running",
                    "generated_ms": int(time.time() * 1000),
                    "as_of_ms": self.now_ms,
                    "source_highwater": self.source_cap
                    if self.historical
                    else self.tape.highwater(),
                    **({"historical": historical} if historical else {}),
                    "cursor": self.cursor,
                    "implementation": self.manifest["implementation"],
                    "trial_count": len(self.variants),
                    "explore_end_ms": self.manifest["explore_end_ms"],
                    "phases": phases,
                    "forecasts": score_forecasts(forecasts),
                    "research": self.research_report(),
                    "limitations": [
                        "Paper execution on recorded public inputs; no venue orders. Independent variants cannot have their PnL added together.",
                        "Original-six uses paper --strategies all per-wallet capital and loss limits; other suites use independent $100 wallets. Fixed trade budgets and loss guards remain active; cash is not replenished.",
                        "The recording cadence bounds execution precision. Latency variants wait at least their configured delay and then require subsequent protected depth.",
                        "Uncertain rounds are excluded from clean completed profit. Missing marks can conceal larger drawdowns; bid marks do not guarantee a full exit.",
                        "All rankings are exploratory until a frozen later-data test completes. Thirty completed rounds is a reporting/selection gate, not statistical proof.",
                        "No market impact, maker rebates, gas, or actual redemption latency is modeled. Official labels enable zero-cost paper payouts.",
                    ],
                }
            )
        )

    def research_report(self) -> dict[str, Any] | None:
        if self.manifest.get("suite") != "order-flow":
            return None
        flow = self.db.execute(
            "SELECT data FROM research ORDER BY frame_id DESC LIMIT 1"
        ).fetchone()
        scans = self.db.execute("SELECT data FROM scans ORDER BY at_ms DESC LIMIT 50").fetchall()
        reasons = {
            code: count
            for code, count in self.db.execute(
                "SELECT json_extract(data,'$.status'),COUNT(*) FROM scans GROUP BY json_extract(data,'$.status')"
            )
        }
        return {
            "flow": json.loads(flow[0]) if flow else None,
            "scanner": {
                "checks": sum(reasons.values()),
                "reasons": reasons,
                "latest": [
                    {k: v for k, v in json.loads(r[0]).items() if k != "inputs"} for r in scans
                ],
                "candidates": reasons.get("QUOTE_CANDIDATE", 0),
                "execution": "not_attempted",
            },
        }

    def auto_freeze(self) -> dict[str, Any] | None:
        if (
            self.historical
            or self._meta("auto_frozen")
            or self.now_ms < self.manifest["explore_end_ms"]
        ):
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
    if args.lab_action == "variants":
        print(
            encode(
                {
                    "suite": args.suite or "directional",
                    "variants": [
                        v.record()
                        for v in registered_variants(
                            config, args.suite or "directional", dense=bool(args.dense)
                        )
                    ],
                }
            )
        )
        return 0
    if args.lab_action == "freeze":
        print(encode(freeze(args.runtime, args.variants.split(","), test_rounds=args.test_rounds)))
        return 0
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        with Study(
            args.source,
            args.runtime,
            config,
            dense=args.dense,
            explore_rounds=args.explore_rounds,
            suite=args.suite,
            start_ms=getattr(args, "start", None),
            end_ms=getattr(args, "end", None),
            variant_ids=tuple(args.variants.split(","))
            if getattr(args, "variants", None) is not None
            else None,
        ) as study:
            if study.historical and args.continuous:
                raise ValueError("HISTORICAL_STUDY_REQUIRES_FINITE_RUN")
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
            if report["status"] != "complete":
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
