"""Offline round-dataset extraction for the profitable-subset research layer.

The dataset is a fast, reproducible view of the checksummed capture tape. A committed
freeze record fixes what a development build may see; holdout rows are extracted only by
a separate command that refuses to run without a committed selection record. Every derived
number is computed by the same engine functions the live core uses, so the dataset cannot
silently disagree with it. See docs/plans/profitable-subset-research.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from btc5m.config import Config
from btc5m.domain import Snapshot
from btc5m.lab import implementation_id
from btc5m.lab_tape import Frame, Tape, encode
from btc5m.strategy import _safety_reason, fair_value

ROUND_MS = 300_000
PURGE_MS = 1_800_000
DEPTH_SHARES = (5, 25, 100)
# Fixed train/validation boundary from the plan; overridable per build for synthetic tapes.
TRAIN_VALIDATION_SPLIT_MS = int(datetime(2026, 9, 11, tzinfo=UTC).timestamp() * 1000)


class DatasetError(ValueError):
    """A safe operator reason for a dataset step, with no captured payload text."""


def _record_hash(record: dict[str, Any]) -> str:
    body = {key: value for key, value in record.items() if key != "sha256"}
    return hashlib.sha256(encode(body).encode()).hexdigest()


def freeze(source: Path, output: Path, *, now_ms: int | None = None) -> dict[str, Any]:
    """Write the committed boundary record that fixes what a development build may read.

    Reads the tape meta only (identity, frame high-water, last frame time). Derives the
    next round boundary after everything the tape already holds and the purged split
    edges. Refuses to overwrite an existing record so the boundary cannot move.
    """
    source, output = Path(source), Path(output)
    with Tape(source, readonly=True) as tape:
        identity, high_water, last_ms = tape.identity, tape.highwater(), tape.last_ms
    stamp = int(time.time() * 1000) if now_ms is None else now_ms
    cutoff_ms = (max(stamp, last_ms) // ROUND_MS + 1) * ROUND_MS
    record: dict[str, Any] = {
        "version": 1,
        "tape_identity": identity,
        "high_water": high_water,
        "last_ms": last_ms,
        "created_ms": stamp,
        "code_identity": implementation_id(),
        "cutoff_ms": cutoff_ms,
        "validation_end_ms": cutoff_ms - PURGE_MS,
        "holdout_start_ms": cutoff_ms + PURGE_MS,
    }
    record["sha256"] = _record_hash(record)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = output.open("x", encoding="utf-8")
    except FileExistsError:
        raise DatasetError("FREEZE_EXISTS") from None
    with handle:
        handle.write(encode(record))
    return record


def _load_freeze(freeze_file: Path) -> dict[str, Any]:
    """Read and integrity-check a committed freeze record before any extraction."""
    record = json.loads(Path(freeze_file).read_text())
    if not isinstance(record, dict) or _record_hash(record) != record.get("sha256"):
        raise DatasetError("FREEZE_RECORD_HASH_MISMATCH")
    return record


def _split_for(start_ms: int, record: dict[str, Any], train_end_ms: int, kind: str) -> str | None:
    """Assign a round to a split by its start, or None when it is out of scope.

    Development rounds start before the purged validation edge and outside the 30-minute
    purge band around the train/validation boundary. Holdout rounds start at or after the
    purged holdout edge. Purge bands drop rounds whose volatility window could leak across
    a boundary.
    """
    if kind == "holdout":
        return "holdout" if start_ms >= record["holdout_start_ms"] else None
    if start_ms >= record["validation_end_ms"]:
        return None
    if start_ms < train_end_ms - PURGE_MS:
        return "train"
    if start_ms >= train_end_ms + PURGE_MS:
        return "validation"
    return None


def _depth_notional(levels: tuple[Any, ...], shares: int) -> str | None:
    """USD cost to consume `shares` from a book side, or None if fewer are displayed.

    Screening and reporting only; a real fill walks the full ladder from the tape frame.
    """
    remaining, cost = Decimal(shares), Decimal(0)
    for level in levels:
        take = min(remaining, level.size)
        cost += take * level.price
        remaining -= take
        if remaining <= 0:
            return str(cost)
    return None


def _best(levels: tuple[Any, ...]) -> str | None:
    return str(levels[0].price) if levels else None


def _tick_values(frame: Frame, snap: Snapshot, config: Config) -> dict[str, Any]:
    """One tick row's derived numbers, all from the same engine functions the core uses."""
    features = fair_value(snap, config).features
    up, down = snap.up_book, snap.down_book
    values: dict[str, Any] = {
        "now_ms": frame.now_ms,
        "seconds_remaining": (snap.market.end_s * 1000 - frame.now_ms) / 1000,
        "spot": str(snap.spot.price),
        "twap60": str(snap.twap60.price),
        "realized_integral": features.get("realized_integral_usd_seconds"),
        "short_sigma": features.get("short_sigma"),
        "long_sigma": features.get("long_sigma"),
        "up_best_bid": _best(up.bids),
        "up_best_ask": _best(up.asks),
        "down_best_bid": _best(down.bids),
        "down_best_ask": _best(down.asks),
        "up_book_ts": up.timestamp_ms,
        "up_book_received": up.received_ms,
        "down_book_ts": down.timestamp_ms,
        "down_book_received": down.received_ms,
        "exchange_lead": _exchange_lead(snap),
        "rejection": _safety_reason(snap, config),
    }
    for token, book in (("up", up), ("down", down)):
        for shares in DEPTH_SHARES:
            values[f"{token}_ask_depth{shares}"] = _depth_notional(book.asks, shares)
    return values


def _exchange_lead(snap: Snapshot) -> str | None:
    """Latest public exchange spot minus the Chainlink spot, when exchange data is aligned."""
    if not snap.exchange_history:
        return None
    latest = max(snap.exchange_history, key=lambda point: point.timestamp_ms)
    return str(latest.price - snap.spot.price)


def _flow_signed(frame: Frame) -> dict[str, str | None]:
    """Signed public exchange volume (buys minus sells) over 10/30/60 seconds, if valid."""
    windows = ((frame.research or {}).get("flow") or {}).get("windows") or {}
    signed: dict[str, str | None] = {}
    for seconds in (10, 30, 60):
        row = windows.get(str(seconds)) or {}
        if row.get("status") == "VALID":
            signed[f"signed_{seconds}s"] = str(
                Decimal(row.get("buy_quantity", "0")) - Decimal(row.get("sell_quantity", "0"))
            )
        else:
            signed[f"signed_{seconds}s"] = None
    return signed


_TICK_COLUMNS = (
    "round_slug",
    "frame_ident",
    "now_ms",
    "seconds_remaining",
    "spot",
    "twap60",
    "realized_integral",
    "short_sigma",
    "long_sigma",
    "up_best_bid",
    "up_best_ask",
    "down_best_bid",
    "down_best_ask",
    "up_ask_depth5",
    "up_ask_depth25",
    "up_ask_depth100",
    "down_ask_depth5",
    "down_ask_depth25",
    "down_ask_depth100",
    "up_book_ts",
    "up_book_received",
    "down_book_ts",
    "down_book_received",
    "exchange_lead",
    "rejection",
)
_ROUND_COLUMNS = (
    "slug",
    "start_ms",
    "end_ms",
    "split",
    "reference_price",
    "reference_status",
    "reference_source",
    "settlement_source",
    "fee_rate",
    "fee_exponent",
    "tick_size",
    "min_order_size",
    "final_label",
    "label_frame_ident",
    "label_received_ms",
    "valid_frames",
)


def _create_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE manifest(data TEXT NOT NULL);
        CREATE TABLE rounds(
            slug TEXT PRIMARY KEY, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
            split TEXT NOT NULL, reference_price TEXT, reference_status TEXT NOT NULL,
            reference_source TEXT, settlement_source TEXT NOT NULL, fee_rate TEXT NOT NULL,
            fee_exponent INTEGER NOT NULL, tick_size TEXT NOT NULL, min_order_size TEXT NOT NULL,
            final_label TEXT, label_frame_ident INTEGER, label_received_ms INTEGER,
            valid_frames INTEGER NOT NULL);
        CREATE TABLE ticks(
            round_slug TEXT NOT NULL, frame_ident INTEGER NOT NULL, now_ms INTEGER NOT NULL,
            seconds_remaining REAL NOT NULL, spot TEXT NOT NULL, twap60 TEXT NOT NULL,
            realized_integral TEXT, short_sigma REAL, long_sigma REAL,
            up_best_bid TEXT, up_best_ask TEXT, down_best_bid TEXT, down_best_ask TEXT,
            up_ask_depth5 TEXT, up_ask_depth25 TEXT, up_ask_depth100 TEXT,
            down_ask_depth5 TEXT, down_ask_depth25 TEXT, down_ask_depth100 TEXT,
            up_book_ts INTEGER, up_book_received INTEGER,
            down_book_ts INTEGER, down_book_received INTEGER,
            exchange_lead TEXT, rejection TEXT,
            PRIMARY KEY(round_slug, frame_ident));
        CREATE TABLE flow(
            round_slug TEXT NOT NULL, frame_ident INTEGER NOT NULL,
            signed_10s TEXT, signed_30s TEXT, signed_60s TEXT,
            PRIMARY KEY(round_slug, frame_ident));
        """
    )


def _stream_frames(tape: Tape, *, after: int, upper: int) -> Iterator[Frame]:
    """Yield checksummed frames with ident in (after, upper], in cursor batches."""
    cursor = after
    while cursor < upper:
        # Count only bounded IDs before decoding. A full read_after batch would
        # inspect post-freeze payloads even if we discarded their rows afterward.
        ids = tape.db.execute(
            "SELECT id FROM frames WHERE id>? AND id<=? ORDER BY id LIMIT 512",
            (cursor, upper),
        ).fetchall()
        if not ids:
            break
        batch = list(tape.read_after(cursor, limit=len(ids)))
        for frame in batch:
            if frame.ident > upper:
                return
            yield frame
        cursor = batch[-1].ident


def _extract(
    source: Path,
    freeze_file: Path,
    output_dir: Path,
    *,
    kind: str,
    train_end_ms: int | None,
) -> dict[str, Any]:
    """Shared development/holdout extractor. Reads the tape once, writes atomically."""
    source, freeze_file, output_dir = Path(source), Path(freeze_file), Path(output_dir)
    record = _load_freeze(freeze_file)
    if train_end_ms is None:
        train_end_ms = TRAIN_VALIDATION_SPLIT_MS
    config = Config()
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / ("holdout.sqlite" if kind == "holdout" else "dataset.sqlite")
    building = db_path.with_suffix(db_path.suffix + ".building")
    building.unlink(missing_ok=True)

    labels: dict[str, tuple[Any, int, int]] = {}
    accum: dict[str, dict[str, Any]] = {}
    idents: list[int] = []
    con = sqlite3.connect(building)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        _create_schema(con)
        with Tape(
            source,
            readonly=True,
            label_highwater=record["high_water"] if kind == "development" else None,
        ) as tape:
            if tape.identity != record["tape_identity"]:
                raise DatasetError("DATASET_SOURCE_IDENTITY_CHANGED")
            current_high = tape.highwater()
            after = record["high_water"] if kind == "holdout" else 0
            upper = current_high if kind == "holdout" else record["high_water"]
            for frame in _stream_frames(tape, after=after, upper=upper):
                for slug, label in frame.labels.items():
                    labels[slug] = (label, frame.ident, frame.now_ms)
                snap = frame.snapshot
                if snap is None:
                    continue
                split = _split_for(snap.market.start_s * 1000, record, train_end_ms, kind)
                if split is None:
                    continue
                idents.append(frame.ident)
                values = _tick_values(frame, snap, config)
                con.execute(
                    "INSERT INTO ticks VALUES (" + ",".join("?" * len(_TICK_COLUMNS)) + ")",
                    (snap.market.slug, frame.ident, *(values[c] for c in _TICK_COLUMNS[2:])),
                )
                signed = _flow_signed(frame)
                con.execute(
                    "INSERT INTO flow VALUES (?,?,?,?,?)",
                    (
                        snap.market.slug,
                        frame.ident,
                        signed["signed_10s"],
                        signed["signed_30s"],
                        signed["signed_60s"],
                    ),
                )
                _accumulate_round(accum, snap, split, values["rejection"] is None)
        _finalize_rounds(con, accum, labels)
        manifest = _manifest(
            kind=kind,
            source=source,
            freeze_file=freeze_file,
            record=record,
            train_end_ms=train_end_ms,
            config=config,
            idents=idents,
            current_high=current_high,
            accum=accum,
            labels=labels,
        )
        con.execute("INSERT INTO manifest VALUES (?)", (encode(manifest),))
        con.commit()
    except BaseException:
        con.close()
        building.unlink(missing_ok=True)
        raise
    con.close()
    os.replace(building, db_path)
    return manifest


def _accumulate_round(
    accum: dict[str, dict[str, Any]], snap: Snapshot, split: str, valid: bool
) -> None:
    market = snap.market
    entry = accum.get(market.slug)
    if entry is None or snap.now_ms >= entry["_seen_ms"]:
        accum[market.slug] = {
            "slug": market.slug,
            "start_ms": market.start_s * 1000,
            "end_ms": market.end_s * 1000,
            "split": split,
            "reference_price": None
            if market.reference_price is None
            else str(market.reference_price),
            "reference_status": market.reference_status,
            "reference_source": market.reference_source,
            "settlement_source": market.settlement_source,
            "fee_rate": str(market.fee_rate),
            "fee_exponent": market.fee_exponent,
            "tick_size": str(market.tick_size),
            "min_order_size": str(market.min_order_size),
            "valid_frames": (entry["valid_frames"] if entry else 0) + int(valid),
            "_seen_ms": snap.now_ms,
        }
    else:
        entry["valid_frames"] += int(valid)


def _finalize_rounds(
    con: sqlite3.Connection,
    accum: dict[str, dict[str, Any]],
    labels: dict[str, tuple[Any, int, int]],
) -> None:
    for slug, entry in accum.items():
        label = labels.get(slug)
        if label and label[0] is not None:
            entry["final_label"] = str(label[0]["final"])
            entry["label_frame_ident"] = label[1]
            entry["label_received_ms"] = label[2]
        else:
            entry["final_label"] = None
            entry["label_frame_ident"] = None
            entry["label_received_ms"] = None
        con.execute(
            "INSERT INTO rounds VALUES (" + ",".join("?" * len(_ROUND_COLUMNS)) + ")",
            tuple(entry[c] for c in _ROUND_COLUMNS),
        )


def _manifest(
    *,
    kind: str,
    source: Path,
    freeze_file: Path,
    record: dict[str, Any],
    train_end_ms: int,
    config: Config,
    idents: list[int],
    current_high: int,
    accum: dict[str, dict[str, Any]],
    labels: dict[str, tuple[Any, int, int]],
) -> dict[str, Any]:
    rounds_per_split: dict[str, int] = {}
    unlabeled_per_split: dict[str, int] = {}
    for entry in accum.values():
        split = entry["split"]
        rounds_per_split[split] = rounds_per_split.get(split, 0) + 1
        label = labels.get(entry["slug"])
        if not (label and label[0] is not None):
            unlabeled_per_split[split] = unlabeled_per_split.get(split, 0) + 1
    return {
        "version": 1,
        "kind": kind,
        "source": str(source.resolve()),
        "tape_identity": record["tape_identity"],
        "freeze_path": str(freeze_file.resolve()),
        "freeze_sha256": hashlib.sha256(freeze_file.read_bytes()).hexdigest(),
        "freeze_record_hash": record["sha256"],
        "freeze_high_water": record["high_water"],
        "high_water_at_build": current_high,
        "cursor_range": [min(idents), max(idents)] if idents else None,
        "code_identity": implementation_id(),
        "build_time_ms": int(time.time() * 1000),
        "train_end_ms": train_end_ms,
        "validation_end_ms": record["validation_end_ms"],
        "holdout_start_ms": record["holdout_start_ms"],
        "rounds_per_split": rounds_per_split,
        "unlabeled_per_split": unlabeled_per_split,
        "config": {
            "max_book_age_ms": config.data.max_book_age_ms,
            "max_price_age_ms": config.data.max_price_age_ms,
            "future_tolerance_ms": config.data.future_tolerance_ms,
            "paper_latency_ms": config.experiments.paper_latency_ms,
        },
        "flow_trader_ids": False,
    }


def build(
    source: Path, freeze_file: Path, output_dir: Path, *, train_end_ms: int | None = None
) -> dict[str, Any]:
    """Step 2: extract train and validation rows up to the freeze high-water."""
    return _extract(source, freeze_file, output_dir, kind="development", train_end_ms=train_end_ms)


def selection_record(
    freeze_record: dict[str, Any],
    *,
    rules_sha256: str,
    selected_rules: list[str],
    coefficients: dict[str, Any] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Build the record that must be committed before any holdout row is extracted.

    It binds the holdout to one freeze record and one rules file. A self SHA-256 makes a
    hand-edited rules or freeze hash detectable, so a changed selection cannot silently
    unlock a holdout that a later verdict would read.
    """
    record = {
        "version": 1,
        "freeze_record_hash": freeze_record["sha256"],
        "rules_sha256": rules_sha256,
        "selected_rules": list(selected_rules),
        "coefficients": coefficients,
        "created_ms": int(time.time() * 1000) if now_ms is None else now_ms,
    }
    record["sha256"] = _record_hash(record)
    return record


def build_holdout(
    source: Path,
    freeze_file: Path,
    output_dir: Path,
    *,
    selection_file: Path | None,
    train_end_ms: int | None = None,
) -> dict[str, Any]:
    """Step 4: extract holdout rows, but only behind a committed, matching selection record.

    The rules-file and manifest hash checks that also gate the holdout verdict run at
    `evaluate --split holdout` (increment B4); here the freeze linkage and the selection
    record's own integrity are enforced so the refusal is testable from the start.
    """
    record = _load_freeze(freeze_file)
    if selection_file is None or not Path(selection_file).exists():
        raise DatasetError("SELECTION_RECORD_REQUIRED")
    selection = json.loads(Path(selection_file).read_text())
    if (
        not isinstance(selection, dict)
        or _record_hash(selection) != selection.get("sha256")
        or selection.get("freeze_record_hash") != record["sha256"]
    ):
        raise DatasetError("SELECTION_HASH_MISMATCH")
    return _extract(source, freeze_file, output_dir, kind="holdout", train_end_ms=train_end_ms)


def content_hash(db_path: Path) -> str:
    """A stable hash over the dataset's rows, ignoring manifest build time and page layout."""
    con = sqlite3.connect(db_path)
    try:
        parts: list[str] = []
        for table, order in (
            ("rounds", "slug"),
            ("ticks", "round_slug,frame_ident"),
            ("flow", "round_slug,frame_ident"),
        ):
            columns = [row[1] for row in con.execute(f"PRAGMA table_info({table})")]
            parts.append(table)
            for row in con.execute(f"SELECT * FROM {table} ORDER BY {order}"):
                parts.append(encode(dict(zip(columns, row, strict=True))))
    finally:
        con.close()
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def run_dataset(args: argparse.Namespace, emit: Callable[[dict[str, Any]], None]) -> int:
    """Dispatch a `btc5m dataset` action; all steps are read-only against the tape."""
    if args.source is None or args.output is None:
        raise DatasetError("SOURCE_AND_OUTPUT_REQUIRED")
    if args.dataset_action == "freeze":
        record = freeze(args.source, args.output)
        emit(
            {
                "kind": "dataset_freeze",
                "output": str(Path(args.output).resolve()),
                "tape_identity": record["tape_identity"],
                "high_water": record["high_water"],
                "cutoff_ms": record["cutoff_ms"],
                "validation_end_ms": record["validation_end_ms"],
                "holdout_start_ms": record["holdout_start_ms"],
            }
        )
        return 0
    if args.dataset_action in ("build", "build-holdout"):
        if args.freeze_file is None:
            raise DatasetError("FREEZE_RECORD_REQUIRED")
        if args.dataset_action == "build":
            manifest = build(
                args.source, args.freeze_file, args.output, train_end_ms=args.train_end
            )
        else:
            manifest = build_holdout(
                args.source,
                args.freeze_file,
                args.output,
                selection_file=args.selection,
                train_end_ms=args.train_end,
            )
        emit(
            {
                "kind": "dataset_build",
                "output": str(Path(args.output).resolve()),
                "manifest": manifest,
            }
        )
        return 0
    raise DatasetError("UNSUPPORTED_DATASET_ACTION")
