"""Prospective capture counters, committed in the same transaction as each frame.

Counts describe recorder samples, not independent opportunities or elapsed-time
availability. A rejected snapshot is distinct from a delay between recorder samples.
Old frames without diagnostics are deliberately excluded, not guessed or rewritten.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def read_quality(path: Path) -> dict[str, Any]:
    """Read only the bounded aggregate; never scan or rewrite the growing tape."""
    if not path.is_file():
        return {"status": "not_instrumented"}
    try:
        db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=1)
        try:
            raw = db.execute("SELECT value FROM meta WHERE key='capture_quality'").fetchone()
        finally:
            db.close()
        if raw is None:
            return {"status": "not_instrumented"}
        if len(raw[0]) > 65536:
            raise ValueError("CAPTURE_QUALITY_TOO_LARGE")
        quality = json.loads(raw[0])
        if not isinstance(quality, dict) or not isinstance(quality.get("frames"), int):
            raise ValueError("INVALID_CAPTURE_QUALITY")
        return {**quality, "status": "available"}
    except (OSError, ValueError, sqlite3.Error):
        return {"status": "unavailable"}


def advance_quality(
    previous: dict[str, Any] | None,
    *,
    frame_id: int,
    now_ms: int,
    available: bool,
    diagnostic: dict[str, Any],
    max_gap_ms: int,
) -> dict[str, Any]:
    if max_gap_ms <= 0:
        raise ValueError("INVALID_CAPTURE_GAP_LIMIT")
    q = (
        dict(previous)
        if previous
        else {
            "first_frame": frame_id,
            "first_ms": now_ms,
            "last_ms": now_ms,
            "frames": 0,
            "available_frames": 0,
            "unavailable_spans": 0,
            "recorder_delays": 0,
            "max_interval_ms": 0,
            "max_unavailable_span_ms": 0,
            "current_unavailable_since_ms": None,
            "max_gap_ms": max_gap_ms,
            "causes": {},
        }
    )
    if q["max_gap_ms"] != max_gap_ms:
        raise ValueError("CAPTURE_GAP_LIMIT_CHANGED")
    interval = now_ms - q["last_ms"]
    q["max_interval_ms"] = max(q["max_interval_ms"], interval)
    q["recorder_delays"] += int(interval > max_gap_ms)
    q["frames"] += 1
    q["last_ms"], q["last_frame"], q["latest"] = now_ms, frame_id, diagnostic
    if q["current_unavailable_since_ms"] is not None:
        q["max_unavailable_span_ms"] = max(
            q["max_unavailable_span_ms"], now_ms - q["current_unavailable_since_ms"]
        )
    if available:
        q["available_frames"] += 1
        q["current_unavailable_since_ms"] = None
    else:
        if q["current_unavailable_since_ms"] is None:
            q["unavailable_spans"] += 1
            q["current_unavailable_since_ms"] = now_ms
        q["causes"] = dict(q["causes"])
        key = str(diagnostic.get("component", "snapshot")) + ":" + str(diagnostic["code"])
        q["causes"][key] = q["causes"].get(key, 0) + 1
    return q
