#!/usr/bin/env python3
"""Explicit storage adapter for an unchanged, separately pinned paper-lab package.

Run using that checkout's Python with -I. This file imports no trading package
until its source, interpreter, study, tape and decoder identities are verified.
"""

from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import types
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class LauncherError(ValueError):
    """Sanitized, machine-readable startup rejection."""


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _git(checkout: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(checkout), *args], stderr=subprocess.DEVNULL, timeout=15
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise LauncherError("PINNED_GIT_VERIFICATION_FAILED") from exc


def verify_source(checkout: Path, commit: str) -> tuple[str, dict[str, str]]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise LauncherError("FULL_PINNED_COMMIT_REQUIRED")
    if (
        Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
        or _git(checkout, "rev-parse", "HEAD").decode().strip() != commit
    ):
        raise LauncherError("PINNED_CHECKOUT_MISMATCH")
    expected = {}
    for record in _git(
        checkout, "ls-tree", "-rz", commit, "--", "src/btc5m", "pyproject.toml", "uv.lock"
    ).split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        mode, kind, blob = header.decode().split()
        name = raw_path.decode()
        if mode not in ("100644", "100755") or kind != "blob":
            raise LauncherError("PINNED_SOURCE_MUST_BE_REGULAR_FILES")
        expected[name] = blob
    if not {"src/btc5m/lab.py", "src/btc5m/cli.py", "pyproject.toml", "uv.lock"} <= expected.keys():
        raise LauncherError("PINNED_SOURCE_INCOMPLETE")
    package = checkout / "src/btc5m"
    actual = set()
    for path in package.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise LauncherError("PINNED_SOURCE_SYMLINK")
        if path.is_file():
            actual.add(path.relative_to(checkout).as_posix())
    if actual != {n for n in expected if n.startswith("src/btc5m/")}:
        raise LauncherError("PINNED_SOURCE_FILES_CHANGED")
    payloads, hashes = {}, {}
    for name, blob in expected.items():
        path = checkout / name
        if path.is_symlink() or not path.resolve().is_relative_to(checkout):
            raise LauncherError("PINNED_SOURCE_SYMLINK")
        data = path.read_bytes()
        if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != blob:
            raise LauncherError("PINNED_SOURCE_CONTENT_CHANGED")
        payloads[name], hashes[name] = data, hashlib.sha256(data).hexdigest()
    try:
        tree = ast.parse(payloads["src/btc5m/lab.py"])
        declarations = [
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "SEMANTIC_FILES"
                for target in node.targets
            )
        ]
        if len(declarations) != 1:
            raise ValueError
        names = declarations[0]
        if not isinstance(names, tuple) or not names or len(set(names)) != len(names):
            raise ValueError
        if not all(isinstance(n, str) and re.fullmatch(r"[a-z_]+\.py", n) for n in names):
            raise ValueError
        identity = hashlib.sha256(
            b"".join(n.encode() + b"\0" + payloads["src/btc5m/" + n] for n in names)
        ).hexdigest()
    except (SyntaxError, ValueError, KeyError, TypeError) as exc:
        raise LauncherError("PINNED_SEMANTIC_FILES_UNSUPPORTED") from exc
    return identity, hashes


def load_storage(path: Path, expected_sha256: str) -> types.ModuleType:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise LauncherError("STORAGE_SHA256_REQUIRED")
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        raise LauncherError("STORAGE_HASH_MISMATCH")
    # Execute the bytes that were hashed, not a second filesystem read or a package import.
    module = types.ModuleType("_btc5m_pinned_storage")
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)
    if not callable(getattr(module, "register_event_reader", None)):
        raise LauncherError("STORAGE_READER_REQUIRED")
    return module


@contextmanager
def install_decoder(register: Callable[[sqlite3.Connection], None]) -> Iterator[None]:
    original = sqlite3.connect

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        db = original(*args, **kwargs)
        try:
            register(db)
        except BaseException:
            db.close()
            raise
        return db

    sqlite3.connect = connect
    try:
        yield
    finally:
        sqlite3.connect = original


def _document(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise LauncherError("IDENTITY_DOCUMENT_TOO_LARGE")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise LauncherError("IDENTITY_DOCUMENT_INVALID")
    return value


def _checkpoint(runtime: Path) -> dict[str, str]:
    db = sqlite3.connect((runtime / "study.sqlite").as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        return dict(db.execute("SELECT key,value FROM meta WHERE key IN ('cursor','now_ms')"))
    finally:
        db.close()


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _registration(runtime: Path, identity: dict[str, Any]) -> str:
    digest = hashlib.sha256(_json(identity)).hexdigest()
    directory = runtime / "storage-adapters"
    directory.mkdir(mode=0o700, exist_ok=True)
    _sync_directory(runtime)
    path = directory / (digest + ".json")
    if path.exists():
        if _document(path).get("identity") != identity:
            raise LauncherError("ADAPTER_PROVENANCE_MISMATCH")
        return digest
    record = {
        "identity": identity,
        "registered_ms": time.time_ns() // 1000000,
        "checkpoint": _checkpoint(runtime),
    }
    # Link a complete fsynced record into place; a killed write never becomes valid provenance.
    temporary = directory / (".pending-" + uuid.uuid4().hex)
    with temporary.open("xb") as output:
        os.chmod(temporary, 0o600)
        output.write(_json(record) + b"\n")
        output.flush()
        os.fsync(output.fileno())
    try:
        os.link(temporary, path)
        _sync_directory(directory)
    finally:
        temporary.unlink()
    return digest


def _record_run(runtime: Path, value: dict[str, Any]) -> None:
    path = runtime / "storage-adapter-runs.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        raw = _json({**value, "at_ms": time.time_ns() // 1000000}) + b"\n"
        written = 0
        while written < len(raw):
            written += os.write(fd, raw[written:])
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_directory(runtime)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--storage-module", type=Path, required=True)
    parser.add_argument("--storage-sha256", required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify identities without launching or writing provenance",
    )
    args = parser.parse_args(argv)
    checkout, runtime, source, config = (
        getattr(args, name).resolve() for name in ("checkout", "runtime", "source", "config")
    )
    if not sys.flags.isolated or Path(sys.prefix).resolve() != checkout / ".venv":
        raise LauncherError("USE_PINNED_VENV_PYTHON_WITH_ISOLATED_FLAG")
    implementation, source_hashes = verify_source(checkout, args.commit)
    manifest = _document(runtime / "study.json")
    if (
        manifest.get("environment") != "paper-lab"
        or manifest.get("implementation") != implementation
    ):
        raise LauncherError("PINNED_STUDY_IMPLEMENTATION_MISMATCH")
    if Path(manifest.get("source", "")).resolve() != source:
        raise LauncherError("PINNED_SOURCE_PATH_MISMATCH")
    db = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        if db.execute("SELECT value FROM meta WHERE key='identity'").fetchone() != (
            manifest.get("tape_identity"),
        ):
            raise LauncherError("PINNED_TAPE_IDENTITY_MISMATCH")
    finally:
        db.close()
    package = checkout / "src/btc5m"
    spec = importlib.util.find_spec("btc5m")
    if (
        spec is None
        or spec.origin is None
        or Path(spec.origin).resolve() != package / "__init__.py"
    ):
        raise LauncherError("PINNED_PACKAGE_IMPORT_PATH_MISMATCH")
    storage_path = args.storage_module.resolve()
    storage = load_storage(storage_path, args.storage_sha256)
    # Only the previously verified pinned package is now eligible to be imported.
    lab = importlib.import_module("btc5m.lab")
    if lab.implementation_id() != implementation:
        raise LauncherError("PINNED_RUNTIME_IMPLEMENTATION_MISMATCH")
    if config.suffix != ".toml":
        raise LauncherError("EXPLICIT_TOML_CONFIG_REQUIRED")
    try:
        cfg = importlib.import_module("btc5m.config").load_config(config)
    except (OSError, ValueError, TypeError) as exc:
        raise LauncherError("PINNED_CONFIG_INVALID") from exc
    if cfg.fingerprint != manifest.get("base_config"):
        raise LauncherError("PINNED_CONFIG_IDENTITY_MISMATCH")
    cli = importlib.import_module("btc5m.cli")
    for name, module in tuple(sys.modules.items()):
        if name == "btc5m" or name.startswith("btc5m."):
            location = Path(getattr(module, "__file__", "")).resolve()
            if (
                not location.is_relative_to(package)
                or location.relative_to(checkout).as_posix() not in source_hashes
            ):
                raise LauncherError("PINNED_MODULE_IMPORT_PATH_MISMATCH")
    identity = {
        "adapter_version": 1,
        "launcher": str(Path(__file__).resolve()),
        "launcher_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "storage_module": str(storage_path),
        "storage_sha256": args.storage_sha256,
        "checkout": str(checkout),
        "commit": args.commit,
        "source_hashes": source_hashes,
        "original_implementation": implementation,
        "study_sha256": hashlib.sha256((runtime / "study.json").read_bytes()).hexdigest(),
        "source": str(source),
        "tape_identity": manifest["tape_identity"],
        "runtime": str(runtime),
        "config": str(config),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "config_fingerprint": cfg.fingerprint,
        "python": sys.version,
        "venv": sys.prefix,
        "distributions": sorted(
            [d.metadata["Name"], d.version] for d in importlib.metadata.distributions()
        ),
    }
    if args.verify_only:
        print(json.dumps({"verified": True, "identity": identity}, sort_keys=True))
        return 0
    lock = os.open(runtime / "storage-adapter.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LauncherError("STORAGE_ADAPTER_ALREADY_RUNNING") from exc
        fingerprint = _registration(runtime, identity)
        run = {"run_id": uuid.uuid4().hex, "adapter": fingerprint}
        _record_run(runtime, {**run, "event": "started", "checkpoint": _checkpoint(runtime)})
        previous = sys.argv
        sys.argv = [
            "btc5m",
            "lab",
            "run",
            "--runtime",
            str(runtime),
            "--source",
            str(source),
            "--config",
            str(config),
        ]
        if args.continuous:
            sys.argv.append("--continuous")
        try:
            with install_decoder(storage.register_event_reader):
                result = cli.main()
            code = 0 if result is None else int(result)
        except BaseException as exc:
            _record_run(runtime, {**run, "event": "failed", "exception_type": type(exc).__name__})
            raise
        else:
            _record_run(
                runtime,
                {
                    **run,
                    "event": "finished" if code == 0 else "failed",
                    "exit_code": code,
                    "checkpoint": _checkpoint(runtime),
                },
            )
            return code
        finally:
            sys.argv = previous
    finally:
        os.close(lock)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (LauncherError, OSError, sqlite3.DatabaseError, json.JSONDecodeError) as exc:
        code = str(exc) if isinstance(exc, LauncherError) else type(exc).__name__
        print(json.dumps({"error": code}), file=sys.stderr)
        raise SystemExit(2) from None
