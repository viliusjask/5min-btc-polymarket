"""Bounded, independent upkeep of the explicit paper runtime's event journals."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from btc5m.service import atomic_json
from btc5m.storage import (
    StorageError,
    _lock,
    _open,
    enable_compaction,
    maintain_storage,
    storage_status,
)


def paper_journals(runtime: Path) -> list[Path]:
    """Only known paper roots; never recursively discover a funded account or backup."""
    runtime = runtime.resolve()
    manifest = json.loads((runtime / "paper.json").read_text())
    if manifest.get("environment") != "paper" or manifest.get("version") != 1:
        raise StorageError("PAPER_RUNTIME_REQUIRED")
    paths = [runtime / "observations.sqlite", *runtime.glob("*/ledger.sqlite")]
    for name in ("lab", "order-flow-lab"):
        root = runtime / name
        if root.is_dir():
            paths.extend(root.glob("*/*/ledger.sqlite"))
    result = []
    for path in sorted(set(paths)):
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(runtime):
            raise StorageError("STORAGE_PATH_OUTSIDE_RUNTIME")
        result.append(path)
    return result


def maintain_runtime(
    runtime: Path, *, now_ms: int, enable_new: bool = False, budget_seconds: float = 45
) -> dict[str, Any]:
    """Rotate existing archives; explicitly allow only small new legacy journals.

    Every reader must support the decoder before enable_new is selected. Large legacy
    journals require a verified compact-copy migration to actually release disk space.
    The cursor rotates fairly across invocations if the wall-clock budget is exhausted.
    """
    runtime = runtime.resolve()
    if type(now_ms) is not int or now_ms < 0 or not 0 < budget_seconds <= 300:
        raise StorageError("INVALID_EVENT_ROTATION_POLICY")
    paths = paper_journals(runtime)
    report_path = runtime / "storage-report.json"
    with _lock(runtime / "storage-maintenance", ".lock"):
        previous = json.loads(report_path.read_text()) if report_path.is_file() else {}
        after = previous.get("last_path", "")
        keys = {path: str(path.relative_to(runtime)) for path in paths}
        ordered = [p for p in paths if keys[p] > after] + [p for p in paths if keys[p] <= after]
        outcomes: dict[str, Any] = {}
        started = time.monotonic()
        last_path = after
        for path in ordered:
            if outcomes and time.monotonic() - started >= budget_seconds:
                break
            key = keys[path]
            last_path = key
            try:
                status = storage_status(path)
                if status["format"] == "legacy-json":
                    if not enable_new or status["size_bytes"]["total"] > 8 * 1024 * 1024:
                        outcomes[key] = {"state": "migration_required", "status": status}
                        continue
                    with _lock(path, ".compact.lock"), closing(_open(path, readonly=False)) as db:
                        db.execute("PRAGMA synchronous=FULL")
                        enable_compaction(db)
                is_source = path.name == "observations.sqlite"
                result = maintain_storage(
                    path,
                    now_ms=now_ms,
                    hot_ms=7200000 if is_source else 600000,
                    max_hot_bytes=(64 if is_source else 2) * 1024 * 1024,
                    max_chunks=32 if is_source else 8,
                )
                outcomes[key] = {"state": "maintained", **result}
            except (OSError, ValueError, sqlite3.Error) as exc:
                code = str(exc)
                outcomes[key] = {
                    "state": "error",
                    "code": code
                    if re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", code)
                    else "STORAGE_" + type(exc).__name__.upper(),
                }
        # Preserve unresolved reports for journals not reached in this bounded pass.
        journals = {
            k: v for k, v in previous.get("journals", {}).items() if k in set(keys.values())
        }
        journals.update(outcomes)
        result = {
            "version": 1,
            "started_ms": now_ms,
            "completed_ms": time.time_ns() // 1000000,
            "last_path": last_path,
            "processed": len(outcomes),
            "known_journals": len(paths),
            "ok": len(journals) == len(paths)
            and all(v["state"] == "maintained" for v in journals.values()),
            "journals": journals,
            "retention": "All source, trade and experiment history retained losslessly.",
        }
        atomic_json(report_path, result)
        return result
