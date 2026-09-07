"""Exact public decision inputs, shared by independent paper experiments.

Ticks are stored once; each compressed frame references precisely the histories visible
at that capture, rather than reconstructing them using information received later.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import uuid
import zlib
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from btc5m.domain import Book, Level, Market, PricePoint, Snapshot
from btc5m.ledger import _market


class TapeError(ValueError):
    pass


def encode(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"), allow_nan=False)


def book_from(raw: dict[str, Any]) -> Book:
    return Book(
        raw["token_id"],
        raw["timestamp_ms"],
        raw["received_ms"],
        *(
            tuple(Level(Decimal(p["price"]), Decimal(p["size"])) for p in raw[side])
            for side in ("bids", "asks")
        ),
    )


@dataclass(frozen=True)
class Frame:
    ident: int
    now_ms: int
    snapshot: Snapshot | None
    labels: dict[str, Any]
    code: str


class Tape:
    def __init__(self, path: Path, *, readonly: bool = False) -> None:
        self.path, self.readonly = path.resolve(), readonly
        self.lock: int | None = None
        self.tick_ids: dict[PricePoint, int] = {}
        self.points: dict[int, PricePoint] = {}
        if not readonly:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.lock = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(self.lock)
                self.lock = None
                raise TapeError("TAPE_WRITER_LOCKED") from None
        try:
            self.db = sqlite3.connect(
                f"{self.path.as_uri()}?mode={'ro' if readonly else 'rwc'}", uri=True, timeout=5
            )
            if not readonly:
                os.chmod(self.path, 0o600)
                self.db.execute("PRAGMA journal_mode=WAL")
                self.db.execute("PRAGMA synchronous=FULL")
                self.db.executescript("""
                    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS ticks(id INTEGER PRIMARY KEY, data TEXT UNIQUE NOT NULL);
                    CREATE TABLE IF NOT EXISTS frames(id INTEGER PRIMARY KEY, now_ms INTEGER NOT NULL,
                        slug TEXT, payload BLOB NOT NULL, checksum TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS frames_time ON frames(now_ms);
                    CREATE INDEX IF NOT EXISTS frames_slug ON frames(slug,id);
                    CREATE TABLE IF NOT EXISTS markets(slug TEXT PRIMARY KEY, data TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS labels(frame_id INTEGER NOT NULL, slug TEXT NOT NULL,
                        data TEXT NOT NULL, PRIMARY KEY(frame_id,slug));
                """)
                with self.db:
                    self.db.execute("INSERT OR IGNORE INTO meta VALUES ('version','1')")
                    self.db.execute(
                        "INSERT OR IGNORE INTO meta VALUES ('identity',?)", (uuid.uuid4().hex,)
                    )
            if self.db.execute("SELECT value FROM meta WHERE key='version'").fetchone() != ("1",):
                raise TapeError("UNSUPPORTED_TAPE")
            self.identity = self.db.execute(
                "SELECT value FROM meta WHERE key='identity'"
            ).fetchone()[0]
            self.last_ms = self.db.execute("SELECT COALESCE(MAX(now_ms),0) FROM frames").fetchone()[
                0
            ]
            self.label_cache = self.labels_at(self.highwater())
            self.known_markets: dict[str, Market] = {}
            if not readonly:
                # Backfill the initial tape format without changing any captured frame.
                if not self.db.execute("SELECT 1 FROM markets LIMIT 1").fetchone():
                    with self.db:
                        for slug, payload in self.db.execute(
                            "SELECT slug,payload FROM frames WHERE id IN (SELECT MAX(id) FROM frames WHERE slug IS NOT NULL GROUP BY slug)"
                        ).fetchall():
                            market = json.loads(zlib.decompress(payload))["snapshot"]["market"]
                            self.db.execute(
                                "INSERT INTO markets VALUES (?,?)", (slug, encode(market))
                            )
                self.known_markets = {
                    slug: _market(json.loads(raw))
                    for slug, raw in self.db.execute("SELECT slug,data FROM markets")
                }
                self._prune_markets(self.last_ms)
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> Tape:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        if hasattr(self, "db"):
            self.db.close()
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None

    def highwater(self) -> int:
        return self.db.execute("SELECT COALESCE(MAX(id),0) FROM frames").fetchone()[0]

    def labels_at(self, ident: int) -> dict[str, Any]:
        return {
            slug: json.loads(raw)
            for slug, raw in self.db.execute(
                "SELECT l.slug,l.data FROM labels l JOIN "
                "(SELECT slug,MAX(frame_id) AS last FROM labels WHERE frame_id<=? GROUP BY slug) x "
                "ON l.slug=x.slug AND l.frame_id=x.last",
                (ident,),
            )
        }

    def _tick(self, point: PricePoint) -> int:
        if point not in self.tick_ids:
            raw = encode(asdict(point))
            self.db.execute("INSERT OR IGNORE INTO ticks(data) VALUES (?)", (raw,))
            self.tick_ids[point] = self.db.execute(
                "SELECT id FROM ticks WHERE data=?", (raw,)
            ).fetchone()[0]
        return self.tick_ids[point]

    def _prune_markets(self, now_ms: int) -> None:
        # Missing official labels survive long outages. Resolved markets keep the
        # adapter's existing one-hour verification period.
        self.known_markets = {
            k: m
            for k, m in self.known_markets.items()
            if m.end_s * 1000 >= now_ms - 3600000 or self.label_cache.get(k) is None
        }

    def retained_markets(self, held: tuple[Market, ...], now_ms: int) -> tuple[Market, ...]:
        """Share the adapter's six recovery slots without an unbounded polling backlog.

        Original holdings keep priority. Rotate other captured markets every 30 seconds;
        their durable identities remain queued until an official label is available.
        """
        selected = {m.slug: m for m in held}
        available = max(0, 6 - len(selected))
        waiting = [m for slug, m in sorted(self.known_markets.items()) if slug not in selected]
        if available and waiting:
            offset = (now_ms // 30000 * available) % len(waiting)
            for i in range(min(available, len(waiting))):
                market = waiting[(offset + i) % len(waiting)]
                selected[market.slug] = market
        return tuple(selected.values())

    def append(
        self,
        now_ms: int,
        snapshot: Snapshot | None,
        *,
        labels: dict[str, Any] | None = None,
        code: str = "CAPTURED",
    ) -> int:
        if self.readonly:
            raise TapeError("READ_ONLY")
        if type(now_ms) is not int or now_ms < self.last_ms:
            raise TapeError("TAPE_CLOCK_REVERSED")
        if snapshot and snapshot.now_ms != now_ms:
            raise TapeError("TAPE_CLOCK_MISMATCH")
        try:
            with self.db:
                raw: dict[str, Any] | None = None
                if snapshot:
                    points = (
                        snapshot.spot,
                        snapshot.twap60,
                        *snapshot.history,
                        *snapshot.exchange_history,
                    )
                    if (
                        any(p.received_ms > now_ms for p in points)
                        or any(
                            b.received_ms > now_ms for b in (snapshot.up_book, snapshot.down_book)
                        )
                        or snapshot.market.metadata_received_ms > now_ms
                    ):
                        raise TapeError("TAPE_FUTURE_RECEIPT")
                    raw = {
                        "market": asdict(snapshot.market),
                        "up_book": asdict(snapshot.up_book),
                        "down_book": asdict(snapshot.down_book),
                        "spot": self._tick(snapshot.spot),
                        "twap60": self._tick(snapshot.twap60),
                        "history": [self._tick(p) for p in snapshot.history],
                        "exchange_history": [self._tick(p) for p in snapshot.exchange_history],
                    }
                    self.db.execute(
                        "INSERT OR REPLACE INTO markets VALUES (?,?)",
                        (snapshot.market.slug, encode(raw["market"])),
                    )
                payload = zlib.compress(encode({"snapshot": raw, "code": code}).encode(), 1)
                cursor = self.db.execute(
                    "INSERT INTO frames(now_ms,slug,payload,checksum) VALUES (?,?,?,?)",
                    (
                        now_ms,
                        snapshot.market.slug if snapshot else None,
                        payload,
                        hashlib.sha256(payload).hexdigest(),
                    ),
                )
                ident = cursor.lastrowid
                assert ident is not None
                updates = {
                    k: v
                    for k, v in (labels or {}).items()
                    if k not in self.label_cache or v != self.label_cache[k]
                }
                for slug, label in updates.items():
                    self.db.execute(
                        "INSERT INTO labels VALUES (?,?,?)", (ident, slug, encode(label))
                    )
            self.last_ms = now_ms
            self.label_cache.update(updates)
            if snapshot:
                self.known_markets[snapshot.market.slug] = snapshot.market
            self._prune_markets(now_ms)
            if len(self.tick_ids) > 20000:
                self.tick_ids.clear()
            return ident
        except BaseException:
            # IDs inserted in a rolled-back transaction cannot survive in the cache.
            self.tick_ids.clear()
            raise

    def _points(self, ids: list[int]) -> None:
        missing = sorted(set(ids).difference(self.points))
        for start in range(0, len(missing), 500):
            batch = missing[start : start + 500]
            for ident, raw in self.db.execute(
                "SELECT id,data FROM ticks WHERE id IN (" + ",".join("?" for _ in batch) + ")",
                batch,
            ):
                point = json.loads(raw)
                point["price"] = Decimal(point["price"])
                self.points[ident] = PricePoint(**point)
        if any(ident not in self.points for ident in ids):
            raise TapeError("TAPE_CORRUPT_TICK")

    def read_after(self, cursor: int, *, limit: int = 128) -> Iterator[Frame]:
        rows = self.db.execute(
            "SELECT id,now_ms,payload,checksum FROM frames WHERE id>? ORDER BY id LIMIT ?",
            (cursor, limit),
        ).fetchall()  # release the read transaction before a slow evaluator consumes it
        for ident, now_ms, payload, checksum in rows:
            if hashlib.sha256(payload).hexdigest() != checksum:
                raise TapeError("TAPE_CORRUPT_FRAME")
            try:
                item = json.loads(zlib.decompress(payload))
                raw = item["snapshot"]
                snap = None
                if raw:
                    self._points(
                        [raw["spot"], raw["twap60"], *raw["history"], *raw["exchange_history"]]
                    )
                    snap = Snapshot(
                        _market(raw["market"]),
                        book_from(raw["up_book"]),
                        book_from(raw["down_book"]),
                        self.points[raw["spot"]],
                        self.points[raw["twap60"]],
                        tuple(self.points[p] for p in raw["history"]),
                        now_ms,
                        tuple(self.points[p] for p in raw["exchange_history"]),
                    )
                labels = {
                    k: json.loads(v)
                    for k, v in self.db.execute(
                        "SELECT slug,data FROM labels WHERE frame_id=?", (ident,)
                    )
                }
                yield Frame(ident, now_ms, snap, labels, item["code"])
            except (ValueError, KeyError, TypeError, zlib.error) as exc:
                raise TapeError("TAPE_CORRUPT_FRAME") from exc
            if len(self.points) > 20000:
                self.points.clear()
