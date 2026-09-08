"""Bounded, independent upkeep of the explicit paper runtime's event journals."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from btc5m.config import STRATEGIES
from btc5m.service import atomic_json
from btc5m.storage import (
    StorageError,
    _lock,
    _open,
    enable_compaction,
    maintain_storage,
    storage_status,
)


def _contained(path: Path, runtime: Path) -> Path:
    if not path.resolve().is_relative_to(runtime):
        raise StorageError("STORAGE_PATH_OUTSIDE_RUNTIME")
    return path


def _document(path: Path, runtime: Path, code: str) -> dict[str, Any]:
    _contained(path, runtime)
    try:
        if path.stat().st_size > 16 * 1024 * 1024:
            raise StorageError(code)
        document = json.loads(path.read_text())
        if not isinstance(document, dict):
            raise StorageError(code)
        return document
    except (OSError, ValueError) as exc:
        raise StorageError(code) from exc


def _study_journals(root: Path, runtime: Path) -> list[Path]:
    """Registration authorizes paths; disposable reports and directory names do not."""
    _contained(root, runtime)
    if not root.exists():
        return []
    manifest = _document(root / "study.json", runtime, "STORAGE_STUDY_REGISTRATION_INVALID")
    variants = manifest.get("variants")
    if (
        type(manifest.get("version")) is not int
        or manifest["version"] != 1
        or manifest.get("environment") != "paper-lab"
        or not isinstance(variants, list)
        or not variants
    ):
        raise StorageError("STORAGE_STUDY_REGISTRATION_INVALID")
    registered = set()
    for variant in variants:
        ident = variant.get("ident") if isinstance(variant, dict) else None
        if (
            not isinstance(ident, str)
            or not re.fullmatch(r"[0-9a-f]{20}", ident)
            or ident in registered
        ):
            raise StorageError("STORAGE_STUDY_VARIANT_INVALID")
        registered.add(ident)
    catalog = _contained(root / "study.sqlite", runtime)
    paths: list[Path] = []
    try:
        # Missing, damaged or oversized phase catalogs must not silently narrow the
        # maintenance scope. A new study still initializing can retry next invocation.
        with closing(
            sqlite3.connect(catalog.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        ) as db:
            db.execute("BEGIN")
            phases = db.execute("SELECT id,data FROM phases ORDER BY rowid LIMIT 4097")
            count = 0
            for phase_id, raw in phases:
                count += 1
                if count > 4096 or not isinstance(raw, str) or len(raw) > 1024 * 1024:
                    raise StorageError("STORAGE_STUDY_PHASE_CATALOG_TOO_LARGE")
                phase = json.loads(raw)
                if (
                    not isinstance(phase_id, str)
                    or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", phase_id)
                    or not isinstance(phase, dict)
                    or phase.get("id") != phase_id
                ):
                    raise StorageError("STORAGE_STUDY_PHASE_INVALID")
                ids = phase.get("variant_ids")
                if (
                    not isinstance(ids, list)
                    or not ids
                    or any(not isinstance(ident, str) or ident not in registered for ident in ids)
                    or len(set(ids)) != len(ids)
                ):
                    raise StorageError("STORAGE_STUDY_PHASE_VARIANTS_INVALID")
                paths.extend(root / phase_id / ident / "ledger.sqlite" for ident in ids)
            if not count:
                raise StorageError("STORAGE_STUDY_PHASE_CATALOG_EMPTY")
    except (sqlite3.Error, json.JSONDecodeError, OSError) as exc:
        raise StorageError("STORAGE_STUDY_PHASE_CATALOG_INVALID") from exc
    return paths


def paper_journals(runtime: Path) -> list[Path]:
    """Only known paper roots; never recursively discover a funded account or backup."""
    runtime = runtime.resolve()
    manifest = _document(runtime / "paper.json", runtime, "PAPER_RUNTIME_REQUIRED")
    strategies = manifest.get("strategies")
    if (
        manifest.get("environment") != "paper"
        or type(manifest.get("version")) is not int
        or manifest["version"] != 1
        or not isinstance(strategies, list)
        or not strategies
        or any(not isinstance(name, str) or name not in STRATEGIES for name in strategies)
        or len(set(strategies)) != len(strategies)
    ):
        raise StorageError("PAPER_RUNTIME_REQUIRED")
    paths = [
        runtime / "observations.sqlite",
        *(runtime / name / "ledger.sqlite" for name in strategies),
    ]
    for name in ("lab", "order-flow-lab"):
        paths.extend(_study_journals(runtime / name, runtime))
    result = []
    for path in sorted(set(paths)):
        _contained(path, runtime)
        if not path.is_file():
            continue
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
