"""Bounded, read-only archive inspection and historical replay boundaries."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def _open(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        db.execute("BEGIN")
        if db.execute("SELECT value FROM meta WHERE key='version'").fetchone() != ("1",):
            raise ValueError("UNSUPPORTED_TAPE")
    except BaseException:
        db.close()
        raise
    return db


def _json(raw: str) -> dict[str, Any]:
    if len(raw) > 65536:
        raise ValueError("ARCHIVE_METADATA_TOO_LARGE")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("INVALID_ARCHIVE_METADATA")
    return value


def _bounds(db: sqlite3.Connection) -> dict[str, Any]:
    first = db.execute("SELECT id,now_ms FROM frames ORDER BY id LIMIT 1").fetchone()
    last = db.execute("SELECT id,now_ms FROM frames ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "tape_identity": db.execute("SELECT value FROM meta WHERE key='identity'").fetchone()[0],
        "source_highwater": last[0] if last else 0,
        "source_first_ms": first[1] if first else None,
        "source_last_ms": last[1] if last else None,
    }


def archive_status(path: Path) -> dict[str, Any]:
    """Index endpoint reads and bounded metadata only; no payload/label history scan."""
    path = path.resolve()
    with closing(_open(path)) as db:
        bounds = _bounds(db)
        quality = db.execute("SELECT value FROM meta WHERE key='capture_quality'").fetchone()
        research = db.execute("SELECT value FROM meta WHERE key='research_first_frame'").fetchone()
        first_research = (
            db.execute("SELECT now_ms FROM frames WHERE id=?", (int(research[0]),)).fetchone()
            if research
            else None
        )
        session = None
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='capture_sessions'"
        ).fetchone():
            row = db.execute(
                "SELECT data FROM capture_sessions ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            session = _json(row[0]) if row else None
    sizes = {}
    for suffix in ("", "-wal", "-shm"):
        try:
            sizes[suffix or "database"] = Path(str(path) + suffix).stat().st_size
        except FileNotFoundError:
            sizes[suffix or "database"] = 0
    return {
        **bounds,
        "source": str(path.resolve()),
        "receipt_range": {
            "first_ms": bounds["source_first_ms"],
            "last_ms": bounds["source_last_ms"],
        },
        "gaps": {**_json(quality[0]), "status": "available"}
        if quality
        else {"status": "not_instrumented"},
        "capabilities": {
            "snapshot_inputs": "recorded eligible snapshots; unavailable frames remain unavailable",
            "research_first_ms": first_research[0] if first_research else None,
            "latest_capture_session": session,
            "scope": "Session declarations and gap counters cover only their recorded ranges, not all earlier history.",
        },
        "size_bytes": {**sizes, "total": sum(sizes.values())},
        "size_sample": "Filesystem sizes sampled after the consistent metadata read; WAL can grow concurrently.",
    }


def historical_window(path: Path, start_ms: int, end_ms: int, *, warmup_ms: int) -> dict[str, Any]:
    if (
        type(start_ms) is not int
        or type(end_ms) is not int
        or start_ms < 0
        or start_ms >= end_ms
        or start_ms % 300000
        or end_ms % 300000
    ):
        raise ValueError("HISTORICAL_RANGE_REQUIRES_ORDERED_FIVE_MINUTE_BOUNDARIES")
    with closing(_open(path)) as db:
        bounds = _bounds(db)
        if (
            bounds["source_first_ms"] is None
            or start_ms < bounds["source_first_ms"] // 300000 * 300000
            or end_ms > bounds["source_last_ms"]
        ):
            raise ValueError("HISTORICAL_RANGE_OUTSIDE_ARCHIVE")
        if not db.execute(
            "SELECT id FROM frames INDEXED BY frames_time WHERE now_ms>=? AND now_ms<? LIMIT 1",
            (start_ms, end_ms),
        ).fetchone():
            raise ValueError("HISTORICAL_RANGE_HAS_NO_FRAMES")
        first = db.execute(
            "SELECT id,now_ms FROM frames INDEXED BY frames_time WHERE now_ms>=? ORDER BY now_ms,id LIMIT 1",
            (start_ms - warmup_ms,),
        ).fetchone()
        return {
            **bounds,
            "source_start": first[0] - 1,
            "entry_start_ms": start_ms,
            "entry_end_ms": end_ms,
            "warmup_requested_start_ms": start_ms - warmup_ms,
            "warmup_first_ms": first[1] if first[1] < start_ms else None,
            "warmup_available_span_ms": max(0, start_ms - first[1]),
            "warmup_scope": "Recorded receipt span only; gaps remain gaps. Snapshots retain only histories visible at their original capture.",
        }
