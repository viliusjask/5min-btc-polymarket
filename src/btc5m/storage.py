"""Lossless, opt-in compaction of paper journals.

Event IDs and SQL-visible rows never change. Payloads rotate into verified zlib
chunks in the same SQLite transaction that replaces their hot representation.
Financial tables and capture.sqlite are never rewritten by rotation.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import time
import zlib
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

MAX_CHUNK_BYTES = 4 * 1024 * 1024
DEFAULT_HOT_BYTES = 64 * 1024 * 1024
DEFAULT_HOT_MS = 2 * 60 * 60 * 1000
VERSION = 1
SOURCE_GUARDS = {
    "btc5m_event_guard_update": """CREATE TRIGGER btc5m_event_guard_update
        BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'EVENT_HISTORY_IMMUTABLE'); END""",
    "btc5m_event_guard_delete": """CREATE TRIGGER btc5m_event_guard_delete
        BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'EVENT_HISTORY_IMMUTABLE'); END""",
    "btc5m_event_guard_insert": """CREATE TRIGGER btc5m_event_guard_insert
        BEFORE INSERT ON events WHEN NEW.id!=-1
            AND NEW.id<=COALESCE((SELECT MAX(id) FROM events),0)
        BEGIN SELECT RAISE(ABORT,'EVENT_HISTORY_IMMUTABLE'); END""",
    "btc5m_event_guard_positive": """CREATE TRIGGER btc5m_event_guard_positive
        AFTER INSERT ON events WHEN NEW.id<=0 OR EXISTS(SELECT 1 FROM events WHERE id>NEW.id)
        BEGIN SELECT RAISE(ABORT,'EVENT_HISTORY_IMMUTABLE'); END""",
}


class StorageError(ValueError):
    """A visible storage failure; no corrupt event is silently omitted."""


def _encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _guard_manifest(db: sqlite3.Connection) -> dict[str, Any] | None:
    names = ",".join("?" for _ in SOURCE_GUARDS)
    actual = dict(
        db.execute(
            f"SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name IN ({names})",
            tuple(SOURCE_GUARDS),
        )
    )
    if not actual:
        return None
    if actual != SOURCE_GUARDS:
        raise StorageError("EVENT_ARCHIVE_SOURCE_GUARD_CHANGED")
    return {"version": 1, "definitions_sha256": hashlib.sha256(_encoded(SOURCE_GUARDS)).hexdigest()}


def protect_source(path: Path) -> dict[str, Any]:
    """Explicitly enforce append-only events before an online guarded copy.

    This small, atomic schema change is the only optional source mutation.
    Existing collector inserts keep working. Compacted journals use strict sync.
    """
    with _lock(path, ".compact.lock"), closing(_open(path, readonly=False)) as db:
        _paper(db)
        if db.execute("SELECT type FROM sqlite_master WHERE name='events'").fetchone() != (
            "table",
        ):
            raise StorageError("EVENT_ARCHIVE_GUARD_REQUIRES_LEGACY_FORMAT")
        db.execute("BEGIN IMMEDIATE")
        try:
            guard = _guard_manifest(db)
            if guard is None:
                for sql in SOURCE_GUARDS.values():
                    db.execute(sql)
                guard = _guard_manifest(db)
            db.commit()
        except BaseException:
            db.rollback()
            raise
    assert guard is not None
    return guard


def _drop_copied_guards(db: sqlite3.Connection) -> None:
    if _guard_manifest(db) is not None:
        with db:
            for name in SOURCE_GUARDS:
                db.execute(f'DROP TRIGGER "{name}"')


def _paper(db: sqlite3.Connection) -> None:
    values = dict(db.execute("SELECT key,value FROM meta WHERE key IN ('wallet','environment')"))
    if values.get("environment") != "paper" or not values.get("wallet"):
        raise StorageError("STORAGE_REQUIRES_PAPER_LEDGER")


def _compact(db: sqlite3.Connection) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='event_storage' AND type='table'"
    ).fetchone()
    if not row:
        return False
    if db.execute("SELECT version FROM event_storage WHERE id=1").fetchone() != (VERSION,):
        raise StorageError("UNSUPPORTED_EVENT_ARCHIVE_VERSION")
    return True


def _decode_chunk(row: tuple[Any, ...] | None) -> list[list[Any]]:
    if row is None:
        raise StorageError("EVENT_ARCHIVE_CHUNK_MISSING")
    first, last, count, raw_bytes, digest, payload = row
    if not isinstance(raw_bytes, int) or not 0 < raw_bytes <= MAX_CHUNK_BYTES:
        raise StorageError("EVENT_ARCHIVE_SIZE_INVALID")
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(payload, MAX_CHUNK_BYTES + 1)
        if (
            len(raw) != raw_bytes
            or not decoder.eof
            or decoder.unconsumed_tail
            or decoder.unused_data
            or hashlib.sha256(raw).hexdigest() != digest
        ):
            raise StorageError("EVENT_ARCHIVE_HASH_MISMATCH")
        items = json.loads(raw)
        if (
            not isinstance(items, list)
            or len(items) != count
            or not items
            or items[0][0] != first
            or items[-1][0] != last
        ):
            raise StorageError("EVENT_ARCHIVE_MANIFEST_MISMATCH")
        prior = 0
        for item in items:
            if (
                not isinstance(item, list)
                or len(item) != 4
                or type(item[0]) is not int
                or item[0] <= prior
                or not isinstance(item[1], str)
                or type(item[2]) is not int
                or not isinstance(item[3], str)
            ):
                raise StorageError("EVENT_ARCHIVE_RECORD_INVALID")
            prior = item[0]
        return items
    except (zlib.error, UnicodeDecodeError, json.JSONDecodeError, IndexError, TypeError) as exc:
        raise StorageError("EVENT_ARCHIVE_DECODE_FAILED") from exc


CHUNK_QUERY = """SELECT first_id,last_id,event_count,raw_bytes,sha256,payload
    FROM event_chunks WHERE id=?"""


def register_event_reader(db: sqlite3.Connection) -> None:
    """Register before any ledger SQL; legacy journals are not modified."""
    _compact(db)
    cache: OrderedDict[int, list[list[Any]]] = OrderedDict()

    def event_data(chunk: int, offset: int, ident: int, kind: str, stamp: int) -> str:
        if chunk not in cache:
            cache[chunk] = _decode_chunk(db.execute(CHUNK_QUERY, (chunk,)).fetchone())
            if len(cache) > 2:
                cache.popitem(last=False)
        cache.move_to_end(chunk)
        rows = cache[chunk]
        if type(offset) is not int or not 0 <= offset < len(rows):
            raise StorageError("EVENT_ARCHIVE_OFFSET_INVALID")
        row = rows[offset]
        if row[:3] != [ident, kind, stamp]:
            raise StorageError("EVENT_ARCHIVE_IDENTITY_MISMATCH")
        return row[3]

    db.create_function("btc5m_event_data", 5, event_data)


def enable_compaction(db: sqlite3.Connection) -> None:
    """Explicit schema migration, intended for an independent prepared copy."""
    _paper(db)
    register_event_reader(db)
    if _compact(db):
        return
    if db.in_transaction:
        raise StorageError("STORAGE_REQUIRES_IDLE_CONNECTION")
    # executescript owns the transaction; no partial DDL survives a failed migration.
    try:
        db.executescript("""
            BEGIN IMMEDIATE;
            ALTER TABLE events RENAME TO event_records;
            ALTER TABLE event_records ADD COLUMN chunk_id INTEGER;
            ALTER TABLE event_records ADD COLUMN chunk_offset INTEGER;
            CREATE TABLE event_chunks (
                id INTEGER PRIMARY KEY, first_id INTEGER NOT NULL, last_id INTEGER NOT NULL,
                event_count INTEGER NOT NULL, raw_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL, payload BLOB NOT NULL, created_ms INTEGER NOT NULL
            );
            CREATE TABLE event_storage (
                id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL,
                hot_events INTEGER NOT NULL, hot_bytes INTEGER NOT NULL,
                source_manifest TEXT
            );
            INSERT INTO event_storage SELECT 1,1,COUNT(*),
                COALESCE(SUM(length(CAST(data AS BLOB))),0),NULL FROM event_records;
            CREATE INDEX event_hot_ids ON event_records(id) WHERE chunk_id IS NULL;
            CREATE INDEX event_chunk_offsets ON event_records(chunk_id,chunk_offset)
                WHERE chunk_id IS NOT NULL;
            CREATE INDEX event_receipt_clock ON event_records(at_ms,id);
            CREATE VIEW events AS SELECT id,kind,at_ms,
                CASE WHEN chunk_id IS NULL THEN data
                ELSE btc5m_event_data(chunk_id,chunk_offset,id,kind,at_ms) END AS data
                FROM event_records;
            CREATE TRIGGER event_append INSTEAD OF INSERT ON events BEGIN
                INSERT INTO event_records(id,kind,at_ms,data)
                    VALUES (NEW.id,NEW.kind,NEW.at_ms,NEW.data);
            END;
            CREATE TRIGGER event_hot_insert AFTER INSERT ON event_records BEGIN
                UPDATE event_storage SET hot_events=hot_events+1,
                    hot_bytes=hot_bytes+length(CAST(NEW.data AS BLOB)) WHERE id=1;
            END;
            CREATE TRIGGER event_cold_update AFTER UPDATE OF chunk_id ON event_records
                WHEN OLD.chunk_id IS NULL AND NEW.chunk_id IS NOT NULL BEGIN
                UPDATE event_storage SET hot_events=hot_events-1,
                    hot_bytes=hot_bytes-length(CAST(OLD.data AS BLOB)) WHERE id=1;
            END;
            COMMIT;
        """)
    except BaseException:
        db.rollback()
        raise


def rotate_events(
    db: sqlite3.Connection,
    *,
    before_ms: int,
    max_hot_bytes: int = DEFAULT_HOT_BYTES,
    chunk_rows: int = 512,
    max_chunks: int = 1,
) -> dict[str, int]:
    """Compress outside the write transaction, then atomically replace exact rows."""
    if (
        type(before_ms) is not int
        or before_ms < 0
        or type(max_hot_bytes) is not int
        or max_hot_bytes < 0
        or type(chunk_rows) is not int
        or not 1 <= chunk_rows <= 2048
        or type(max_chunks) is not int
        or not 1 <= max_chunks <= 100000
    ):
        raise StorageError("INVALID_EVENT_ROTATION_POLICY")
    _paper(db)
    if not _compact(db):
        raise StorageError("EVENT_COMPACTION_NOT_ENABLED")
    if db.in_transaction:
        raise StorageError("STORAGE_REQUIRES_IDLE_CONNECTION")
    result = {"archived_events": 0, "chunks": 0, "raw_bytes": 0, "compressed_bytes": 0}
    for _ in range(max_chunks):
        hot_bytes = db.execute("SELECT hot_bytes FROM event_storage WHERE id=1").fetchone()[0]
        # The sparse hot index prevents rescanning previously compressed history.
        candidates = db.execute(
            """SELECT id,kind,at_ms,data FROM event_records INDEXED BY event_hot_ids
                WHERE chunk_id IS NULL AND (at_ms<? OR ?) ORDER BY id LIMIT ?""",
            (before_ms, hot_bytes > max_hot_bytes, chunk_rows),
        ).fetchall()
        if not candidates:
            break
        rows: list[tuple[Any, ...]] = []
        size = 2
        for row in candidates:
            encoded_size = len(_encoded(row)) + 1
            if size + encoded_size > MAX_CHUNK_BYTES:
                if not rows:
                    raise StorageError("EVENT_ARCHIVE_RECORD_TOO_LARGE")
                break
            rows.append(row)
            size += encoded_size
        raw = _encoded(rows)
        digest = hashlib.sha256(raw).hexdigest()
        payload = zlib.compress(raw, 6)
        manifest = (rows[0][0], rows[-1][0], len(rows), len(raw), digest, payload)
        # Verify the exact persisted representation before releasing any hot payload.
        if _decode_chunk(manifest) != [list(row) for row in rows]:
            raise StorageError("EVENT_ARCHIVE_VERIFY_FAILED")
        db.execute("BEGIN IMMEDIATE")
        try:
            cursor = db.execute(
                """INSERT INTO event_chunks(first_id,last_id,event_count,raw_bytes,sha256,
                    payload,created_ms) VALUES (?,?,?,?,?,?,?)""",
                (*manifest, time.time_ns() // 1000000),
            )
            chunk_id = cursor.lastrowid
            for offset, (ident, kind, stamp, data) in enumerate(rows):
                changed = db.execute(
                    """UPDATE event_records SET data='',chunk_id=?,chunk_offset=?
                        WHERE id=? AND kind=? AND at_ms=? AND data=? AND chunk_id IS NULL""",
                    (chunk_id, offset, ident, kind, stamp, data),
                ).rowcount
                if changed != 1:
                    raise StorageError("EVENT_ARCHIVE_CONCURRENT_CHANGE")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        result["archived_events"] += len(rows)
        result["chunks"] += 1
        result["raw_bytes"] += len(raw)
        result["compressed_bytes"] += len(payload)
    return result


def _open(path: Path, *, readonly: bool = True) -> sqlite3.Connection:
    db = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode={'ro' if readonly else 'rw'}", uri=True, timeout=1
    )
    try:
        register_event_reader(db)
    except BaseException:
        db.close()
        raise
    return db


def storage_status(path: Path) -> dict[str, Any]:
    """Read cheap counters and file sizes without decoding the event archive."""
    path = path.resolve()
    with closing(_open(path)) as db:
        _paper(db)
        db.execute("BEGIN")
        compact = _compact(db)
        maximum = db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
        if compact:
            hot_events, hot_bytes = db.execute(
                "SELECT hot_events,hot_bytes FROM event_storage WHERE id=1"
            ).fetchone()
            chunks, archived, raw_bytes, compressed = db.execute(
                """SELECT COUNT(*),COALESCE(SUM(event_count),0),COALESCE(SUM(raw_bytes),0),
                    COALESCE(SUM(length(payload)),0) FROM event_chunks"""
            ).fetchone()
        else:
            hot_events = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            hot_bytes, chunks, archived, raw_bytes, compressed = None, 0, 0, 0, 0
        free_bytes = (
            db.execute("PRAGMA freelist_count").fetchone()[0]
            * db.execute("PRAGMA page_size").fetchone()[0]
        )
    sizes = {}
    for suffix in ("", "-wal", "-shm"):
        try:
            sizes[suffix or "database"] = Path(str(path) + suffix).stat().st_size
        except FileNotFoundError:
            sizes[suffix or "database"] = 0
    return {
        "path": str(path),
        "format": "compact-events-v1" if compact else "legacy-json",
        "highwater": maximum,
        "hot_events": hot_events,
        "hot_payload_bytes": hot_bytes,
        "archived_events": archived,
        "chunks": chunks,
        "archive_raw_bytes": raw_bytes,
        "archive_compressed_bytes": compressed,
        "reusable_database_bytes": free_bytes,
        "size_bytes": {**sizes, "total": sum(sizes.values())},
        "retention": "All history retained; old payloads compressed, never expired.",
    }


def _event_hasher(db: sqlite3.Connection, highwater: int | None = None) -> tuple[int, int, Any]:
    digest, count, last = hashlib.sha256(), 0, 0
    query = "SELECT id,kind,at_ms,data FROM events"
    params: tuple[int, ...] = ()
    if highwater is not None:
        query += " WHERE id<=?"
        params = (highwater,)
    for row in db.execute(query + " ORDER BY id", params):
        digest.update(_encoded(row) + b"\n")
        count += 1
        last = row[0]
    return count, last, digest


def _event_digest(db: sqlite3.Connection, highwater: int | None = None) -> tuple[int, int, str]:
    count, last, digest = _event_hasher(db, highwater)
    return count, last, digest.hexdigest()


def _tables(db: sqlite3.Connection) -> set[str]:
    return {
        name
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if name not in {"events", "event_records", "event_chunks", "event_storage"}
        and not name.startswith("sqlite_")
    }


def _table_digest(db: sqlite3.Connection, quoted: str) -> str:
    digest = hashlib.sha256()
    for row in db.execute(f"SELECT * FROM {quoted} ORDER BY rowid"):
        digest.update(_encoded(row) + b"\n")
    return digest.hexdigest()


def _copy_tables(original: sqlite3.Connection, copied: sqlite3.Connection) -> None:
    tables = _tables(original)
    if tables != _tables(copied):
        raise StorageError("EVENT_ARCHIVE_NON_EVENT_SCHEMA_CHANGED")
    for name in sorted(tables):
        quoted = '"' + name.replace('"', '""') + '"'
        columns = original.execute(f"PRAGMA table_info({quoted})").fetchall()
        if columns != copied.execute(f"PRAGMA table_info({quoted})").fetchall():
            raise StorageError("EVENT_ARCHIVE_NON_EVENT_SCHEMA_CHANGED")
        copied.execute(f"DELETE FROM {quoted}")
        placeholders = ",".join("?" for _ in columns)
        copied.executemany(
            f"INSERT INTO {quoted} VALUES ({placeholders})",
            original.execute(f"SELECT * FROM {quoted} ORDER BY rowid"),
        )
        if _table_digest(original, quoted) != _table_digest(copied, quoted):
            raise StorageError("EVENT_ARCHIVE_NON_EVENT_COPY_MISMATCH")


def verify_storage(path: Path) -> dict[str, Any]:
    """Full explicit verification, including metadata counters and archive references."""
    with closing(_open(path)) as db:
        _paper(db)
        db.execute("BEGIN")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise StorageError("EVENT_ARCHIVE_SQLITE_INTEGRITY_FAILED")
        if _compact(db):
            for chunk, first, last, count, raw_bytes, digest, payload in db.execute(
                "SELECT id,first_id,last_id,event_count,raw_bytes,sha256,payload FROM event_chunks"
            ):
                rows = _decode_chunk((first, last, count, raw_bytes, digest, payload))
                index = db.execute(
                    """SELECT id,kind,at_ms,chunk_offset,data FROM event_records
                        WHERE chunk_id=? ORDER BY chunk_offset""",
                    (chunk,),
                ).fetchall()
                if index != [(*row[:3], offset, "") for offset, row in enumerate(rows)]:
                    raise StorageError("EVENT_ARCHIVE_INDEX_MISMATCH")
            if db.execute(
                """SELECT 1 FROM event_records r LEFT JOIN event_chunks c ON c.id=r.chunk_id
                    WHERE (r.chunk_id IS NOT NULL AND c.id IS NULL)
                        OR (r.chunk_id IS NULL AND r.chunk_offset IS NOT NULL) LIMIT 1"""
            ).fetchone():
                raise StorageError("EVENT_ARCHIVE_REFERENCE_MISSING")
            actual_hot = db.execute(
                """SELECT COUNT(*),COALESCE(SUM(length(CAST(data AS BLOB))),0)
                    FROM event_records WHERE chunk_id IS NULL"""
            ).fetchone()
            if (
                actual_hot
                != db.execute(
                    "SELECT hot_events,hot_bytes FROM event_storage WHERE id=1"
                ).fetchone()
            ):
                raise StorageError("EVENT_ARCHIVE_HOT_COUNTER_MISMATCH")
        try:
            count, last, digest = _event_digest(db)
        except sqlite3.OperationalError as exc:
            raise StorageError("EVENT_ARCHIVE_READ_FAILED") from exc
    return {"verified": True, "events": count, "highwater": last, "event_sha256": digest}


@contextmanager
def _lock(path: Path, suffix: str) -> Iterator[None]:
    fd = os.open(str(path.resolve()) + suffix, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StorageError("STORAGE_OWNER_LOCKED") from exc
        yield
    finally:
        os.close(fd)


def maintain_storage(
    path: Path,
    *,
    now_ms: int,
    max_chunks: int = 16,
    hot_ms: int = DEFAULT_HOT_MS,
    max_hot_bytes: int = DEFAULT_HOT_BYTES,
) -> dict[str, Any]:
    """Independent maintenance process; never waits indefinitely for SQLite/another maintainer."""
    if type(now_ms) is not int or type(hot_ms) is not int or now_ms < 0 or hot_ms < 0:
        raise StorageError("INVALID_EVENT_ROTATION_POLICY")
    with _lock(path, ".compact.lock"), closing(_open(path, readonly=False)) as db:
        db.execute("PRAGMA synchronous=FULL")
        result = rotate_events(
            db,
            before_ms=max(0, now_ms - hot_ms),
            max_hot_bytes=max_hot_bytes,
            max_chunks=max_chunks,
        )
    return {**result, "status": storage_status(path)}


def compact_copy(
    source: Path,
    destination: Path,
    *,
    before_ms: int,
    guarded: bool = False,
) -> dict[str, Any]:
    """Create a new compact, fully verified SQLite snapshot; never overwrite the source."""
    source, destination = source.resolve(), destination.resolve()
    if source == destination or destination.exists():
        raise StorageError("STORAGE_DESTINATION_EXISTS")
    if guarded:
        protect_source(source)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    # Interrupted destinations remain explicit incomplete copies, not silently overwritten.
    source_stat = source.stat()
    with (
        _lock(destination, ".lock"),
        _lock(destination, ".compact.lock"),
        closing(_open(source)) as original,
        closing(_open(destination, readonly=False)) as copied,
    ):
        # Pin a WAL read snapshot before stepping: separate-connection commits
        # otherwise restart incremental backup indefinitely on a busy collector.
        # Release it before compression so the source WAL can checkpoint again.
        original.execute("BEGIN")
        try:
            _paper(original)
            original.backup(
                copied,
                pages=256,
                sleep=0.01,
                # Returning to Python between steps also permits Ctrl-C.
                progress=lambda _status, _remaining, _total: None,
            )
        finally:
            original.rollback()
        copied.execute("PRAGMA journal_mode=DELETE")
        copied.execute("PRAGMA synchronous=FULL")
        count, highwater, digest = _event_digest(copied)
        source_guard = _guard_manifest(copied)
        if guarded and source_guard is None:
            raise StorageError("EVENT_ARCHIVE_SOURCE_GUARD_MISSING")
        _drop_copied_guards(copied)
        stat = source.stat()
        if (source_stat.st_dev, source_stat.st_ino) != (stat.st_dev, stat.st_ino):
            raise StorageError("EVENT_ARCHIVE_SOURCE_IDENTITY_CHANGED")
        manifest = {
            "source": str(source),
            "device": stat.st_dev,
            "inode": stat.st_ino,
            "events": count,
            "highwater": highwater,
            "event_sha256": digest,
            "created_ms": time.time_ns() // 1000000,
            "wallet": copied.execute("SELECT value FROM meta WHERE key='wallet'").fetchone()[0],
            "source_guard": source_guard,
        }
        enable_compaction(copied)
        with copied:
            copied.execute(
                "UPDATE event_storage SET source_manifest=? WHERE id=1",
                (_encoded(manifest).decode(),),
            )
        while rotate_events(copied, before_ms=before_ms, max_chunks=256)["archived_events"]:
            pass
        copied.execute("VACUUM")
        result = verify_storage(destination)
        if (result["events"], result["highwater"], result["event_sha256"]) != (
            count,
            highwater,
            digest,
        ):
            raise StorageError("EVENT_ARCHIVE_COPY_MISMATCH")
        return {
            **result,
            "source": str(source),
            "destination": str(destination),
            "status": storage_status(destination),
        }


def sync_compact_copy(source: Path, destination: Path) -> dict[str, Any]:
    """With the original writer stopped, verify its prefix and copy its exact final state.

    This does not replace any file. The caller must retain the original while it
    independently checks the final report and performs its controlled cutover.
    """
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise StorageError("STORAGE_DESTINATION_IS_SOURCE")
    with (
        _lock(source, ".lock"),
        _lock(source, ".compact.lock"),
        _lock(destination, ".lock"),
        _lock(destination, ".compact.lock"),
        closing(_open(source)) as original,
        closing(_open(destination, readonly=False)) as copied,
    ):
        _paper(original)
        _paper(copied)
        if not _compact(copied):
            raise StorageError("EVENT_COMPACTION_NOT_ENABLED")
        original.execute("BEGIN")
        raw_manifest = copied.execute(
            "SELECT source_manifest FROM event_storage WHERE id=1"
        ).fetchone()[0]
        if not raw_manifest:
            raise StorageError("EVENT_ARCHIVE_SOURCE_MANIFEST_MISSING")
        manifest = json.loads(raw_manifest)
        if any(
            db.execute("SELECT value FROM meta WHERE key='wallet'").fetchone()[0]
            != manifest.get("wallet")
            for db in (original, copied)
        ):
            raise StorageError("EVENT_ARCHIVE_WALLET_MISMATCH")
        stat = source.stat()
        if (manifest["source"], manifest["device"], manifest["inode"]) != (
            str(source),
            stat.st_dev,
            stat.st_ino,
        ):
            raise StorageError("EVENT_ARCHIVE_SOURCE_IDENTITY_CHANGED")
        prefix = _event_digest(original, manifest["highwater"])
        expected = (manifest["events"], manifest["highwater"], manifest["event_sha256"])
        if prefix != expected or _event_digest(copied, manifest["highwater"]) != expected:
            raise StorageError("EVENT_ARCHIVE_SOURCE_PREFIX_CHANGED")
        if (
            copied.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
            != manifest["highwater"]
        ):
            raise StorageError("EVENT_ARCHIVE_DESTINATION_HAS_NEW_EVENTS")
        appended = 0
        copied.execute("BEGIN IMMEDIATE")
        try:
            for row in original.execute(
                "SELECT id,kind,at_ms,data FROM events WHERE id>? ORDER BY id",
                (manifest["highwater"],),
            ):
                copied.execute("INSERT INTO events(id,kind,at_ms,data) VALUES (?,?,?,?)", row)
                appended += 1
            _copy_tables(original, copied)
            count, highwater, digest = _event_digest(original)
            manifest.update(
                events=count,
                highwater=highwater,
                event_sha256=digest,
                synced_ms=time.time_ns() // 1000000,
            )
            copied.execute(
                "UPDATE event_storage SET source_manifest=? WHERE id=1",
                (_encoded(manifest).decode(),),
            )
            copied.commit()
        except BaseException:
            copied.rollback()
            raise
        result = verify_storage(destination)
        if (result["events"], result["highwater"], result["event_sha256"]) != (
            count,
            highwater,
            digest,
        ):
            raise StorageError("EVENT_ARCHIVE_SYNC_MISMATCH")
        return {**result, "appended_events": appended}


def _read_manifest(db: sqlite3.Connection) -> dict[str, Any]:
    row = db.execute("SELECT source_manifest FROM event_storage WHERE id=1").fetchone()
    if not row or not row[0]:
        raise StorageError("EVENT_ARCHIVE_SOURCE_MANIFEST_MISSING")
    try:
        manifest = json.loads(row[0])
        if not isinstance(manifest, dict) or any(
            key not in manifest
            for key in (
                "source",
                "device",
                "inode",
                "wallet",
                "events",
                "highwater",
                "event_sha256",
            )
        ):
            raise StorageError("EVENT_ARCHIVE_SOURCE_MANIFEST_INVALID")
        return manifest
    except (json.JSONDecodeError, TypeError) as exc:
        raise StorageError("EVENT_ARCHIVE_SOURCE_MANIFEST_INVALID") from exc


def _check_guarded_source(
    source: Path,
    original: sqlite3.Connection,
    copied: sqlite3.Connection,
    manifest: dict[str, Any],
) -> None:
    _paper(original)
    _paper(copied)
    stat = source.stat()
    if (manifest["source"], manifest["device"], manifest["inode"]) != (
        str(source),
        stat.st_dev,
        stat.st_ino,
    ):
        raise StorageError("EVENT_ARCHIVE_SOURCE_IDENTITY_CHANGED")
    if any(
        db.execute("SELECT value FROM meta WHERE key='wallet'").fetchone()[0] != manifest["wallet"]
        for db in (original, copied)
    ):
        raise StorageError("EVENT_ARCHIVE_WALLET_MISMATCH")
    guard = _guard_manifest(original)
    if guard is None or guard != manifest.get("source_guard"):
        raise StorageError("EVENT_ARCHIVE_SOURCE_GUARD_MISSING_OR_CHANGED")


class PreparedGuardedSync:
    """A verified destination held under its SQLite write lock until context exit."""

    def __init__(
        self,
        source: Path,
        copied: sqlite3.Connection,
        manifest: dict[str, Any],
        state: tuple[int, int, Any],
    ) -> None:
        self.source, self.copied, self.manifest, self.state = source, copied, manifest, state
        self.active = True
        self.used = False

    def sync(self) -> dict[str, Any]:
        """Run only after stopping the source owner; work scales with its new tail."""
        if not self.active or self.used:
            raise StorageError("EVENT_ARCHIVE_PREFLIGHT_EXPIRED")
        if not self.copied.in_transaction:
            raise StorageError("EVENT_ARCHIVE_PREFLIGHT_LOCK_LOST")
        with (
            _lock(self.source, ".lock"),
            _lock(self.source, ".compact.lock"),
            closing(_open(self.source)) as original,
        ):
            self.used = True
            original.execute("BEGIN")
            _check_guarded_source(self.source, original, self.copied, self.manifest)
            source_highwater = original.execute(
                "SELECT COALESCE(MAX(id),0) FROM events"
            ).fetchone()[0]
            if source_highwater < self.manifest["highwater"]:
                raise StorageError("EVENT_ARCHIVE_SOURCE_PREFIX_CHANGED")
            count, last, digest = self.state
            digest = digest.copy()
            tail = hashlib.sha256()
            appended = 0
            try:
                for row in original.execute(
                    "SELECT id,kind,at_ms,data FROM events WHERE id>? ORDER BY id",
                    (self.manifest["highwater"],),
                ):
                    self.copied.execute(
                        "INSERT INTO events(id,kind,at_ms,data) VALUES (?,?,?,?)", row
                    )
                    encoded = _encoded(row) + b"\n"
                    tail.update(encoded)
                    digest.update(encoded)
                    appended += 1
                    last = row[0]
                actual_tail = hashlib.sha256()
                actual_count = 0
                for row in self.copied.execute(
                    "SELECT id,kind,at_ms,data FROM events WHERE id>? ORDER BY id",
                    (self.manifest["highwater"],),
                ):
                    actual_tail.update(_encoded(row) + b"\n")
                    actual_count += 1
                if (
                    actual_tail.digest() != tail.digest()
                    or actual_count != appended
                    or last != source_highwater
                ):
                    raise StorageError("EVENT_ARCHIVE_TAIL_MISMATCH")
                _copy_tables(original, self.copied)
                manifest = {
                    **self.manifest,
                    "events": count + appended,
                    "highwater": last,
                    "event_sha256": digest.hexdigest(),
                    "synced_ms": time.time_ns() // 1000000,
                }
                self.copied.execute(
                    "UPDATE event_storage SET source_manifest=? WHERE id=1",
                    (_encoded(manifest).decode(),),
                )
                self.copied.commit()
                self.used = True
            except BaseException:
                self.copied.rollback()
                self.used = True
                raise
            return {
                "verified": True,
                "verification_mode": "guarded-prefix-and-tail",
                "events": count + appended,
                "highwater": last,
                "event_sha256": digest.hexdigest(),
                "appended_events": appended,
                "tail_sha256": tail.hexdigest(),
            }


@contextmanager
def prepare_guarded_sync(source: Path, destination: Path) -> Iterator[PreparedGuardedSync]:
    """Perform expensive verification online, then hold the copy stable for short sync.

    Enter while the source collector is running. Stop that writer only after this
    yields. Each context holds one destination connection/write transaction; stage
    large collections in manageable groups per owning service. Any failed or
    interrupted context releases its locks and leaves committed history intact.
    """
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise StorageError("STORAGE_DESTINATION_IS_SOURCE")
    with (
        _lock(destination, ".lock"),
        _lock(destination, ".compact.lock"),
        closing(_open(destination, readonly=False)) as copied,
    ):
        _paper(copied)
        if not _compact(copied):
            raise StorageError("EVENT_COMPACTION_NOT_ENABLED")
        copied.execute("BEGIN IMMEDIATE")
        prepared = None
        try:
            manifest = _read_manifest(copied)
            with closing(_open(source)) as original:
                original.execute("BEGIN")
                _check_guarded_source(source, original, copied, manifest)
            checked = verify_storage(destination)
            expected = (manifest["events"], manifest["highwater"], manifest["event_sha256"])
            if (checked["events"], checked["highwater"], checked["event_sha256"]) != expected:
                raise StorageError("EVENT_ARCHIVE_DESTINATION_PREFIX_CHANGED")
            state = _event_hasher(copied)
            if (state[0], state[1], state[2].hexdigest()) != expected:
                raise StorageError("EVENT_ARCHIVE_DESTINATION_PREFIX_CHANGED")
            prepared = PreparedGuardedSync(source, copied, manifest, state)
            yield prepared
        finally:
            if prepared is not None:
                prepared.active = False
            copied.rollback()
