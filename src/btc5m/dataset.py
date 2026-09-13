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
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from btc5m.lab import implementation_id
from btc5m.lab_tape import Tape, encode

ROUND_MS = 300_000
PURGE_MS = 1_800_000
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


def run_dataset(args: argparse.Namespace, emit: Callable[[dict[str, Any]], None]) -> int:
    """Dispatch a `btc5m dataset` action; all steps are read-only against the tape."""
    if args.dataset_action == "freeze":
        if args.source is None or args.output is None:
            raise DatasetError("SOURCE_AND_OUTPUT_REQUIRED")
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
    raise DatasetError("UNSUPPORTED_DATASET_ACTION")
