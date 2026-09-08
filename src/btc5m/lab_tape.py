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
import sys
import uuid
import zlib
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import Any

from btc5m.capture_quality import advance_quality
from btc5m.config import Config
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
    research: dict[str, Any] | None = None
    diagnostic: dict[str, Any] | None = None
    archive: dict[str, Any] | None = None


class Tape:
    def __init__(
        self, path: Path, *, readonly: bool = False, label_highwater: int | None = None
    ) -> None:
        if label_highwater is not None and (
            not readonly or type(label_highwater) is not int or label_highwater < 0
        ):
            raise TapeError("INVALID_TAPE_LABEL_HIGHWATER")
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
                    CREATE TABLE IF NOT EXISTS capture_sessions(id TEXT PRIMARY KEY,
                        started_ms INTEGER NOT NULL, data TEXT NOT NULL);
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
            highwater = self.highwater()
            if label_highwater is not None and label_highwater > highwater:
                raise TapeError("INVALID_TAPE_LABEL_HIGHWATER")
            self.label_cache = self.labels_at(
                highwater if label_highwater is None else label_highwater
            )
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

    def start_capture(
        self, config: Config, *, now_ms: int, capture_flow: bool, session_id: str | None = None
    ) -> str:
        """A prospective producer record; never alters prior frames or study identities."""
        if self.readonly:
            raise TapeError("READ_ONLY")
        ident = session_id or uuid.uuid4().hex
        source = Path(__file__).parent
        files = (
            "market_data.py",
            "streams.py",
            "public_archive.py",
            "lab_tape.py",
            "comparison.py",
            "order_flow.py",
            "capture_quality.py",
            "config.py",
            "domain.py",
            "ledger.py",
        )
        record = {
            "version": 1,
            "id": ident,
            "started_ms": now_ms,
            "tape_identity": self.identity,
            "next_frame_id": self.highwater() + 1,
            "previous_frame_ms": self.last_ms or None,
            "config_fingerprint": config.fingerprint,
            "config": asdict(config),
            "capture_flow": capture_flow,
            "python": sys.version.split()[0],
            "polymarket_client": version("polymarket-client"),
            "source_hashes": {
                name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in files
            },
            "semantics": {
                "oracle": "SDK normalized BTC/USD Chainlink spot and TWAP60; accepted exact Decimal ticks",
                "oracle_full_accuracy_value": "TWAP E18 field becomes exact Decimal value in SDK; raw field not exposed or reconstructed",
                "book_sequence": "local_receipt_order_not_exchange_queue",
                "book_scope": "current subscribed Polymarket market; REST books for retained positions",
                "exchange": "Binance BTCUSDT aggTrade; normalized depth20 when capture_flow is true",
                "timestamps": "source timestamps retained; received_ms is local wall clock",
                "durability": "archive batches commit with FULL synchronous WAL frames, normally every 500ms",
                "overflow": "bounded buffer drops remainder of batch with an explicit sequence gap",
                "retention": "no automatic archive pruning",
                "eligibility": "archive presence does not certify a valid trading snapshot",
                "continuity": "new process has no prior exchange stream continuity",
            },
        }
        with self.db:
            self.db.execute(
                "INSERT INTO capture_sessions VALUES (?,?,?)", (ident, now_ms, encode(record))
            )
        return ident

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
        research: dict[str, Any] | None = None,
        diagnostic: dict[str, Any] | None = None,
        archive: dict[str, Any] | None = None,
        max_gap_ms: int | None = None,
    ) -> int:
        if self.readonly:
            raise TapeError("READ_ONLY")
        if type(now_ms) is not int or now_ms < self.last_ms:
            raise TapeError("TAPE_CLOCK_REVERSED")
        if snapshot and snapshot.now_ms != now_ms:
            raise TapeError("TAPE_CLOCK_MISMATCH")

        def receipts(value: Any) -> None:
            if isinstance(value, dict):
                if "received_ms" in value and (
                    type(value["received_ms"]) is not int or value["received_ms"] > now_ms
                ):
                    raise TapeError("TAPE_FUTURE_RECEIPT")
                for child in value.values():
                    receipts(child)
            elif isinstance(value, list | tuple):
                for child in value:
                    receipts(child)

        receipts(research)
        receipts(diagnostic)
        if archive is not None:
            receipts({key: value for key, value in archive.items() if key != "events"})
            for event in archive.get("events", []):
                # Raw provider fields are evidence (including malformed/future claims),
                # not our local receipt clock. Validate the archive envelope only.
                receipts({key: value for key, value in event.items() if key != "payload"})
        if diagnostic is not None and (
            max_gap_ms is None or not isinstance(diagnostic.get("code"), str)
        ):
            raise TapeError("INVALID_CAPTURE_DIAGNOSTIC")
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
                payload = zlib.compress(
                    encode(
                        {
                            "snapshot": raw,
                            "code": code,
                            "research": research,
                            "diagnostic": diagnostic,
                            "archive": archive,
                        }
                    ).encode(),
                    1,
                )
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
                if diagnostic is not None:
                    prior = self.db.execute(
                        "SELECT value FROM meta WHERE key='capture_quality'"
                    ).fetchone()
                    assert max_gap_ms is not None
                    quality = advance_quality(
                        json.loads(prior[0]) if prior else None,
                        frame_id=ident,
                        now_ms=now_ms,
                        available=snapshot is not None,
                        diagnostic=diagnostic,
                        max_gap_ms=max_gap_ms,
                    )
                    self.db.execute(
                        "INSERT OR REPLACE INTO meta VALUES ('capture_quality',?)",
                        (encode(quality),),
                    )
                if research is not None:
                    self.db.execute(
                        "INSERT OR IGNORE INTO meta VALUES ('research_first_frame',?)",
                        (str(ident),),
                    )
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
                yield Frame(
                    ident,
                    now_ms,
                    snap,
                    labels,
                    item["code"],
                    item.get("research"),
                    item.get("diagnostic"),
                    item.get("archive"),
                )
            except (ValueError, KeyError, TypeError, zlib.error) as exc:
                raise TapeError("TAPE_CORRUPT_FRAME") from exc
            if len(self.points) > 20000:
                self.points.clear()
