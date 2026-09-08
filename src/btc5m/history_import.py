"""Bounded, attributed OutcomeTick conversion for the existing paper replay.

Vendor receipt times remain vendor receipt times. Assumed trading terms, optional
Binance receipt latency and resolution availability are explicit study inputs.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import zipfile
from collections import Counter, deque
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, TextIO

from btc5m.config import Config
from btc5m.domain import Book, Level, Market, PricePoint
from btc5m.lab_tape import Tape, book_from, encode
from btc5m.strategy import SETTLEMENT_SOURCE, _safety_reason

D = Decimal
SOURCE_URL = (
    "https://github.com/Ligengxin96/polymarket-data-samples/releases/tag/samples-2026-09-04"
)
MAX_LINE = 8 * 1024 * 1024


@dataclass(frozen=True)
class HistoricalTerms:
    """Operator-declared historical assumptions, never final metadata backfilled in time."""

    tick_size: Decimal
    min_order_size: Decimal
    fee_rate: Decimal
    fee_exponent: int

    def __post_init__(self) -> None:
        if self.tick_size not in (D(".1"), D(".01"), D(".001"), D(".0001")):
            raise ValueError("INVALID_HISTORICAL_TICK")
        if not self.min_order_size.is_finite() or self.min_order_size <= 0:
            raise ValueError("INVALID_HISTORICAL_MINIMUM")
        if not self.fee_rate.is_finite() or not 0 <= self.fee_rate <= 1:
            raise ValueError("INVALID_HISTORICAL_FEE")
        if type(self.fee_exponent) is not int or not 1 <= self.fee_exponent <= 10:
            raise ValueError("INVALID_HISTORICAL_FEE_EXPONENT")


def _stamp(value: Any) -> int:
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if type(value) is not int or not 1_000_000_000_000 <= value < 100_000_000_000_000:
        raise ValueError("INVALID_HISTORY_TIMESTAMP")
    return value


def _number(value: Any, *, zero: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("INVALID_HISTORY_NUMBER")
    number = D(str(value))
    if not number.is_finite() or number < 0 or (not zero and number == 0):
        raise ValueError("INVALID_HISTORY_NUMBER")
    return number


def _exact(value: str) -> Decimal:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) > 60:
        raise ValueError("INVALID_EXACT_ORACLE_VALUE")
    with localcontext() as context:
        context.prec = 80
        return _number(D(value).scaleb(-18))


def _json(raw: str) -> Any:
    return json.loads(
        raw, parse_float=D, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x))
    )


def _lines(source: TextIO) -> Iterator[str]:
    while line := source.readline(MAX_LINE + 1):
        if len(line) > MAX_LINE:
            raise ValueError("HISTORY_RECORD_TOO_LARGE")
        if not line.strip():
            raise ValueError("EMPTY_HISTORY_RECORD")
        yield line


def _json_rows(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in _lines(source):
            row = _json(line)
            if not isinstance(row, dict):
                raise ValueError("INVALID_HISTORY_RECORD")
            yield row


def _fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("HISTORY_SOURCE_NOT_FILE:" + str(path))
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def _write(path: Path, record: dict[str, Any]) -> None:
    temporary = path.with_suffix(".writing")
    with temporary.open("w", encoding="utf-8") as output:
        output.write(encode(record) + "\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _list(value: Any) -> list[Any]:
    result = _json(value) if isinstance(value, str) else value
    if not isinstance(result, list):
        raise ValueError("INVALID_HISTORY_ARRAY")
    return result


def _markets(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    tokens: set[str] = set()
    for row in _json_rows(path):
        if len(result) >= 100000:
            raise ValueError("HISTORY_MARKET_LIMIT")
        start, end, raw = row["start_sec"], row["end_sec"], row["raw"]
        if type(start) is not int or type(end) is not int or end - start != 300 or start % 300:
            raise ValueError("INVALID_HISTORY_ROUND")
        slug, condition = row["slug"], row["condition_id"]
        if row["asset"] != "btc" or row["interval_sec"] != 300 or slug != f"btc-updown-5m-{start}":
            raise ValueError("INVALID_HISTORY_SERIES")
        if not isinstance(condition, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", condition):
            raise ValueError("INVALID_HISTORY_CONDITION")
        token_ids = row["token_ids"]
        if not isinstance(token_ids, list) or len(token_ids) != 2 or len(set(token_ids)) != 2:
            raise ValueError("INVALID_HISTORY_TOKENS")
        if any(
            not isinstance(t, str) or not t.isascii() or not t.isdigit() or int(t) <= 0
            for t in token_ids
        ):
            raise ValueError("INVALID_HISTORY_TOKENS")
        outcomes = _list(raw["outcomes"])
        if sorted(outcomes) != ["Down", "Up"] or _list(raw["clobTokenIds"]) != token_ids:
            raise ValueError("HISTORY_OUTCOME_TOKEN_MISMATCH")
        if raw["slug"] != slug or raw["conditionId"] != condition:
            raise ValueError("HISTORY_MARKET_IDENTITY_MISMATCH")
        rule = raw.get("cryptoMarketConfig", {})
        supported = (
            rule.get("twapEnabled") is True
            and rule.get("twapLookbackSeconds") == 60
            and raw.get("resolutionSource") == SETTLEMENT_SOURCE
        )
        label = None
        if row.get("resolved") is True:
            prices = row.get("outcome_prices")
            if prices not in (["1", "0"], ["0", "1"]):
                raise ValueError("INVALID_HISTORY_OUTCOME")
            label = outcomes[prices.index("1")]
        availability = None
        for key in ("umaEndDate", "closedTime"):
            if raw.get(key):
                stamp = datetime.fromisoformat(raw[key].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("HISTORY_RESOLUTION_TIMEZONE_REQUIRED")
                value = int(stamp.timestamp() * 1000)
                if value < end * 1000:
                    raise ValueError("HISTORY_RESOLUTION_BEFORE_END")
                availability = max(availability or 0, value)
        item = {
            "slug": slug,
            "condition": condition,
            "start": start,
            "end": end,
            "up": token_ids[outcomes.index("Up")],
            "down": token_ids[outcomes.index("Down")],
            "supported": supported,
            "winner": label,
            "availability_ms": availability,
            "strike": _exact(row["strike_value"]) if row.get("strike_value") else None,
        }
        if slug in result or tokens.intersection(token_ids):
            raise ValueError("DUPLICATE_HISTORY_MARKET")
        result[slug] = item
        tokens.update(token_ids)
    if not result:
        raise ValueError("EMPTY_HISTORY_MARKETS")
    return result


def _wire(
    row: dict[str, Any], markets: dict[str, dict[str, Any]], kind: str
) -> tuple[dict[str, Any], str, int, int, dict[str, Any]]:
    market = markets.get(row["slug"])
    if market is None:
        raise ValueError("HISTORY_UNKNOWN_MARKET")
    payload = row["payload"]
    token, source, receipt = (
        row.get("asset_id", payload.get("asset_id")),
        _stamp(row["event_ts_ms"]),
        _stamp(row["recv_ms"]),
    )
    if (
        token not in (market["up"], market["down"])
        or payload.get("asset_id") != token
        or payload.get("market") != market["condition"]
    ):
        raise ValueError("HISTORY_EVENT_IDENTITY_MISMATCH")
    if (
        _stamp(payload["timestamp"]) != source
        or row["event_type"] != kind
        or payload["event_type"] != kind
    ):
        raise ValueError("HISTORY_EVENT_ENVELOPE_MISMATCH")
    return market, token, source, receipt, payload


def _stage(
    db: sqlite3.Connection,
    paths: dict[str, Path],
    markets: dict[str, dict[str, Any]],
    lower: int,
    end: int,
    binance_latency_ms: int | None,
) -> dict[str, int]:
    counts: dict[str, int] = {}

    def put(kind: str, receipt: int, payload: dict[str, Any]) -> None:
        if lower <= receipt <= end:
            db.execute(
                "INSERT INTO events(kind,recv,data) VALUES (?,?,?)",
                (kind, receipt, encode(payload)),
            )

    for kind, path in paths.items():
        count = 0
        if kind == "markets":
            counts[kind] = len(markets)
            continue
        if kind in ("spot", "twap60"):
            with gzip.open(path, "rt", encoding="utf-8") as source_file:
                reader = csv.DictReader(_lines(source_file))
                if reader.fieldnames != [
                    "feed_ts_ms",
                    "value",
                    "full_accuracy_value",
                    "server_ts_ms",
                    "recv_ms",
                ]:
                    raise ValueError("HISTORY_ORACLE_COLUMNS")
                for row in reader:
                    if None in row or any(v is None for v in row.values()):
                        raise ValueError("HISTORY_ORACLE_ROW")
                    source, receipt = _stamp(row["feed_ts_ms"]), _stamp(row["recv_ms"])
                    server = _stamp(row["server_ts_ms"])
                    put(
                        kind,
                        receipt,
                        {
                            "kind": kind,
                            "timestamp_ms": source,
                            "received_ms": receipt,
                            "price": str(_exact(row["full_accuracy_value"])),
                            "server_ms": server,
                        },
                    )
                    count += 1
        elif kind == "binance":
            assert binance_latency_ms is not None
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if len(members) != 1 or not re.fullmatch(
                    r"BTCUSDT-aggTrades-\d{4}-\d{2}-\d{2}\.csv", members[0].filename
                ):
                    raise ValueError("HISTORY_BINANCE_ARCHIVE_MEMBER")
                with (
                    archive.open(members[0]) as binary,
                    io.TextIOWrapper(binary, encoding="utf-8") as text,
                ):
                    previous = -1
                    for values in csv.reader(_lines(text)):
                        if (
                            len(values) != 8
                            or values[6].lower() not in ("true", "false")
                            or values[7].lower() not in ("true", "false")
                        ):
                            raise ValueError("HISTORY_BINANCE_COLUMNS")
                        ident = int(values[0])
                        if ident <= previous:
                            raise ValueError("HISTORY_BINANCE_SEQUENCE")
                        previous = ident
                        microseconds = int(values[5])
                        if not 1_700_000_000_000_000 <= microseconds < 100_000_000_000_000_000:
                            raise ValueError("HISTORY_BINANCE_MICROSECONDS_REQUIRED")
                        stamp = microseconds // 1000
                        _number(values[2])
                        put(
                            kind,
                            stamp + binance_latency_ms,
                            {
                                "kind": "spot",
                                "timestamp_ms": stamp,
                                "received_ms": stamp + binance_latency_ms,
                                "price": str(_number(values[1])),
                            },
                        )
                        count += 1
        else:
            event_kind = {
                "books": "book",
                "trades": "last_trade_price",
                "best_bid_ask": "best_bid_ask",
            }[kind]
            for row in _json_rows(path):
                market, token, source, receipt, payload = _wire(row, markets, event_kind)
                item: dict[str, Any] = {
                    "token": token,
                    "slug": market["slug"],
                    "source": source,
                    "receipt": receipt,
                }
                if kind == "books":
                    levels: list[tuple[Level, ...]] = []
                    non_executable = False
                    for side in ("bids", "asks"):
                        pairs = [
                            (_number(p["price"], zero=True), _number(p["size"], zero=True))
                            for p in payload[side]
                        ]
                        if any(price > 1 for price, _ in pairs):
                            raise ValueError("HISTORY_INVALID_BOOK_PRICE")
                        if len({price for price, _ in pairs}) != len(pairs):
                            raise ValueError("HISTORY_DUPLICATE_BOOK_LEVEL")
                        non_executable |= any(price in (0, 1) or size == 0 for price, size in pairs)
                        book_levels = tuple(
                            Level(price, size)
                            for price, size in pairs
                            if 0 < price < 1 and size > 0
                        )
                        levels.append(book_levels)
                    if non_executable:
                        # Boundary prices occur in real expired-market snapshots. A
                        # partial filtered book could fabricate a better executable ask.
                        levels = [(), ()]
                        counts["non_executable_books"] = counts.get("non_executable_books", 0) + 1
                    item["book"] = asdict(Book(token, source, receipt, *levels))
                elif kind == "best_bid_ask":
                    bid, ask = (
                        _number(payload["best_bid"], zero=True),
                        _number(payload["best_ask"], zero=True),
                    )
                    if bid > 1 or ask > 1:
                        raise ValueError("HISTORY_INVALID_TOP")
                    item.update(bid=str(bid), ask=str(ask))
                else:
                    price, quantity = _number(payload["price"], zero=True), _number(payload["size"])
                    tx = payload.get("transaction_hash")
                    if (
                        price > 1
                        or payload["side"] not in ("BUY", "SELL")
                        or (tx is not None and not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx))
                    ):
                        raise ValueError("HISTORY_INVALID_TRADE")
                    if price in (0, 1):
                        # Real resolution-adjacent prints can be at the payout bounds.
                        # The current simulator rejects these as ordinary market flow.
                        counts["non_executable_trades"] = counts.get("non_executable_trades", 0) + 1
                        count += 1
                        continue
                    tx = tx.lower() if tx else None
                    identity = hashlib.sha256(
                        json.dumps(
                            [
                                market["condition"],
                                token,
                                source,
                                payload["side"],
                                str(price),
                                str(quantity),
                                tx,
                            ],
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest()
                    item["trade"] = {
                        "identity": identity,
                        "token_id": token,
                        "condition_id": market["condition"],
                        "side": payload["side"],
                        "price": str(price),
                        "quantity": str(quantity),
                        "timestamp_ms": source,
                        "received_ms": receipt,
                        "generation": 1,
                        "transaction_hash": tx,
                    }
                put(kind, receipt, item)
                count += 1
        counts[kind] = count
        db.commit()
    db.execute("CREATE INDEX event_receipts ON events(recv,id)")
    db.commit()
    return counts


def _convert(
    db: sqlite3.Connection,
    tape: Tape,
    markets: dict[str, dict[str, Any]],
    start: int,
    end: int,
    config: Config,
    terms: HistoricalTerms | None,
    profile: dict[str, Any],
) -> dict[str, Any]:
    from btc5m.domain import Snapshot

    spot: PricePoint | None = None
    twap: PricePoint | None = None
    history: deque[PricePoint] = deque()
    exchange: dict[int, PricePoint] = {}
    books: dict[str, Book] = {}
    tops: dict[str, dict[str, Any]] = {}
    boundaries: dict[int, PricePoint] = {}
    emitted_labels: set[str] = set()
    pending_trades: list[dict[str, Any]] = []
    seen_trades: dict[str, int] = {}
    causes: Counter[str] = Counter()
    max_gaps: Counter[str] = Counter()
    last_receipts: dict[str, int] = {}
    latest = 0
    bucket = -1
    buffered: list[tuple[str, int, dict[str, Any]]] = []
    count = 0
    supported = {m["start"]: m for m in markets.values()}
    source_identity = tape.identity
    retain_ms = (
        max(config.strategy.volatility_long_seconds, config.strategy.volatility_short_seconds)
        * 1000
        + 60000
    )

    def labels_at(now: int, *, final: bool = False) -> dict[str, Any]:
        updates = {}
        for slug, m in markets.items():
            if (
                slug in emitted_labels
                or not m["supported"]
                or m["end"] * 1000 > now
                or m["winner"] is None
            ):
                continue
            opening, closing = boundaries.get(m["start"] * 1000), boundaries.get(m["end"] * 1000)
            if opening is None or closing is None:
                continue
            actual = "Up" if closing.price >= opening.price else "Down"
            if actual != m["winner"] or (m["strike"] is not None and opening.price != m["strike"]):
                raise ValueError("HISTORY_SETTLEMENT_VALIDATION_MISMATCH:" + slug)
            delay = profile["resolution_delay_ms"]
            due = (
                m["availability_ms"] + delay
                if delay is not None and m["availability_ms"] is not None
                else None
            )
            if not (final or due is not None and due <= now):
                continue
            updates[slug] = {
                "condition_id": m["condition"],
                "opening": str(opening.price),
                "final": str(closing.price),
                "provenance": "archived_official_outcome_checked_exact_twap_boundaries",
                "availability": "modeled_resolution_delay"
                if due is not None and due <= now
                else "offline_end_of_import",
                "modeled_available_ms": due,
            }
            emitted_labels.add(slug)
        return updates

    def emit(now: int, *, final: bool = False) -> None:
        nonlocal count
        if now < start:
            pending_trades.clear()
            return
        m = supported.get(now // 300000 * 300)
        snap = None
        code = "UNKNOWN_HISTORICAL_TERMS" if terms is None else "MISSING_MARKET"
        pending = {
            token: top["receipt"]
            for token, top in tops.items()
            if token in books
            and (
                top["receipt"] > books[token].received_ms
                or top["source"] > books[token].timestamp_ms
            )
            and (
                D(top["bid"]) != (books[token].bids[0].price if books[token].bids else D(0))
                or D(top["ask"]) != (books[token].asks[0].price if books[token].asks else D(1))
            )
        }
        if terms is not None and m is not None:
            anchor = boundaries.get(m["start"] * 1000)
            if not m["supported"]:
                code = "UNSUPPORTED_HISTORICAL_RULE"
            elif spot is None or twap is None:
                code = "MISSING_ORACLE"
            elif any(t not in books for t in (m["up"], m["down"])):
                code = "MISSING_BOOK"
            elif any(t in pending for t in (m["up"], m["down"])):
                code = "HISTORICAL_DEPTH_INVALIDATED_BY_TOP"
            else:
                market = Market(
                    m["slug"],
                    m["condition"],
                    m["start"],
                    m["end"],
                    m["up"],
                    m["down"],
                    anchor.price if anchor else None,
                    "external_exact_twap60_boundary" if anchor else None,
                    SETTLEMENT_SOURCE,
                    terms.tick_size,
                    terms.min_order_size,
                    terms.fee_rate,
                    terms.fee_exponent,
                    True,
                    True,
                    "boundary" if anchor else "missing",
                    anchor.timestamp_ms if anchor else None,
                    min(books[m["up"]].received_ms, books[m["down"]].received_ms),
                    "explicit_external_history_assumptions",
                )
                candidate = Snapshot(
                    market,
                    books[m["up"]],
                    books[m["down"]],
                    spot,
                    twap,
                    tuple(history),
                    now,
                    tuple(exchange[k] for k in sorted(exchange)),
                )
                code = _safety_reason(candidate, config) or "CAPTURED"
                if code == "CAPTURED":
                    snap = candidate
        research = {
            "external_history": profile,
            "streams": {
                "session_id": source_identity,
                "generation": 1,
                "books": {t: asdict(b) for t, b in books.items()},
                "pending_books": pending,
                "trades": list(pending_trades),
            },
        }
        tape.append(
            now,
            snap,
            labels=labels_at(now, final=final),
            code=code,
            research=research,
            diagnostic={"component": "external_history", "code": code},
            max_gap_ms=config.data.max_price_age_ms,
        )
        pending_trades.clear()
        causes[code] += 1
        count += 1

    def accept(events: list[tuple[str, int, dict[str, Any]]]) -> None:
        nonlocal spot, twap, latest, books, tops, seen_trades
        for kind, receipt, raw in events:
            latest = receipt
            previous = last_receipts.get(kind)
            if previous is not None:
                max_gaps[kind] = max(max_gaps[kind], receipt - previous)
            last_receipts[kind] = receipt
            if kind in ("spot", "twap60", "binance"):
                point = PricePoint(
                    raw["kind"], raw["timestamp_ms"], raw["received_ms"], D(raw["price"])
                )
                if kind == "spot":
                    if spot is None or point.timestamp_ms > spot.timestamp_ms:
                        history.append(point)
                        spot = point
                elif kind == "twap60":
                    if twap is None or point.timestamp_ms > twap.timestamp_ms:
                        twap = point
                    if point.timestamp_ms % 300000 == 0:
                        old = boundaries.get(point.timestamp_ms)
                        if old and old.price != point.price:
                            raise ValueError("HISTORY_BOUNDARY_CONFLICT")
                        boundaries[point.timestamp_ms] = old or point
                else:
                    exchange[point.timestamp_ms // 100] = point
            elif kind == "books":
                book = book_from(raw["book"])
                if (
                    book.token_id not in books
                    or book.timestamp_ms >= books[book.token_id].timestamp_ms
                ):
                    books[book.token_id] = book
            elif kind == "best_bid_ask":
                old_top = tops.get(raw["token"])
                if old_top is None or raw["source"] >= old_top["source"]:
                    tops[raw["token"]] = raw
            elif kind == "trades" and raw["trade"]["identity"] not in seen_trades:
                pending_trades.append(raw["trade"])
                seen_trades[raw["trade"]["identity"]] = receipt
            while history and history[0].timestamp_ms < receipt - retain_ms:
                history.popleft()
        if latest:
            books = {t: b for t, b in books.items() if b.received_ms >= latest - 600000}
            tops = {t: v for t, v in tops.items() if v["receipt"] >= latest - 600000}
            seen_trades = {k: t for k, t in seen_trades.items() if t >= latest - 15000}
            for key in list(exchange):
                if exchange[key].timestamp_ms < latest - 60000:
                    del exchange[key]
            emit(latest)

    for kind, receipt, raw in db.execute("SELECT kind,recv,data FROM events ORDER BY recv,id"):
        if receipt // 500 != bucket and buffered:
            accept(buffered)
            buffered = []
        bucket = receipt // 500
        buffered.append((kind, receipt, _json(raw)))
        if len(buffered) > 100000:
            raise ValueError("HISTORY_EVENT_BUCKET_LIMIT")
    if buffered:
        accept(buffered)
    if latest >= start:
        emit(latest, final=True)
    if not count:
        raise ValueError("EMPTY_HISTORY_INTERVAL")
    return {
        "frames": count,
        "snapshot_causes": dict(causes),
        "max_input_receipt_gaps_ms": dict(max_gaps),
        "labels": len(emitted_labels),
        "markets_with_both_exact_boundaries": sum(
            m["start"] * 1000 in boundaries and m["end"] * 1000 in boundaries
            for m in markets.values()
        ),
        "source_first_ms": tape.db.execute("SELECT MIN(now_ms) FROM frames").fetchone()[0],
        "source_last_ms": latest,
        "tape_identity": tape.identity,
    }


def import_outcometick(
    *,
    markets: Path,
    books: Path,
    spot: Path,
    twap60: Path,
    destination: Path,
    start_ms: int,
    end_ms: int,
    config: Config,
    terms: HistoricalTerms | None = None,
    trades: Path | None = None,
    best_bid_ask: Path | None = None,
    binance: Path | None = None,
    binance_latency_ms: int | None = None,
    resolution_delay_ms: int | None = None,
) -> dict[str, Any]:
    """Import one explicit file set into a new directory; never modify a saved tape.

    The interval bounds receipts, inclusive at both endpoints. Price pre-roll supplies
    the configured history window; sources must actually contain it. No network calls.
    """
    _stamp(start_ms)
    _stamp(end_ms)
    if start_ms >= end_ms:
        raise ValueError("INVALID_HISTORY_INTERVAL")
    if (binance is None) != (binance_latency_ms is None):
        raise ValueError("HISTORY_BINANCE_EXPLICIT_LATENCY_REQUIRED")
    for value in (binance_latency_ms, resolution_delay_ms):
        if value is not None and (type(value) is not int or not 0 <= value <= 3600000):
            raise ValueError("INVALID_HISTORY_ASSUMED_DELAY")
    paths = {"markets": markets, "books": books, "spot": spot, "twap60": twap60}
    paths.update(
        {
            k: v
            for k, v in {"trades": trades, "best_bid_ask": best_bid_ask, "binance": binance}.items()
            if v is not None
        }
    )
    sources = {k: _fingerprint(p) for k, p in paths.items()}
    profile = {
        "provider": "outcometick",
        "source_url": "https://github.com/Ligengxin96/polymarket-data-samples",
        "reference_release": SOURCE_URL,
        "terms": asdict(terms) if terms else None,
        "trades_present": trades is not None,
        "binance_latency_ms": binance_latency_ms,
        "resolution_delay_ms": resolution_delay_ms,
        "limitations": [
            "sampled_full_depth_no_exchange_queue_continuity",
            "historical_acceptance_and_trading_terms_unknown",
            "vendor_receipts_not_our_live_latency",
            "archived_rules_not_a_historical_metadata_message_stream",
            "oracle_symbol_bound_by_explicit_source_selection",
        ]
        + (["binance_receipts_modeled_from_exchange_time"] if binance else ["binance_unavailable"])
        + (
            ["resolution_availability_modeled"]
            if resolution_delay_ms is not None
            else ["resolution_withheld_until_import_end"]
        )
        + ([] if best_bid_ask else ["no_unthrottled_top_invalidation"])
        + ([] if trades else ["public_trade_evidence_unavailable"]),
        "quality": "exploratory_assumed_execution" if terms else "strict_no_execution",
    }
    source_dir = Path(__file__).parent
    semantic_sources = {
        name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
        for name in (
            "history_import.py",
            "config.py",
            "domain.py",
            "lab_tape.py",
            "ledger.py",
            "capture_quality.py",
            "strategy.py",
        )
    }
    identity = {
        "version": 1,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "semantic_source_hashes": semantic_sources,
        "sources": sources,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "config_fingerprint": config.fingerprint,
        "profile": profile,
    }
    identity_hash = hashlib.sha256(encode(identity).encode()).hexdigest()
    if destination.exists():
        manifest = destination / "import.json"
        if not manifest.is_file():
            raise ValueError("HISTORY_DESTINATION_EXISTS")
        existing = json.loads(manifest.read_text())
        if existing.get("identity_hash") != identity_hash:
            raise ValueError("HISTORY_IMPORT_IDENTITY_CHANGED")
        if existing.get("status") != "complete" or not (destination / "capture.sqlite").is_file():
            raise ValueError("HISTORY_IMPORT_INCOMPLETE_USE_NEW_DESTINATION")
        return existing["report"]
    destination.mkdir(parents=True, mode=0o700)
    manifest = destination / "import.json"
    _write(manifest, {"status": "staging", "identity_hash": identity_hash, **identity})
    staging = destination / "staging.sqlite"
    partial = destination / "capture.sqlite.partial"
    db = sqlite3.connect(staging)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute(
            "CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,recv INTEGER NOT NULL,data TEXT NOT NULL)"
        )
        metadata = _markets(markets)
        lower = (
            start_ms
            - (
                max(
                    config.strategy.volatility_long_seconds,
                    config.strategy.volatility_short_seconds,
                )
                + 60
            )
            * 1000
        )
        counts = _stage(db, paths, metadata, lower, end_ms, binance_latency_ms)
        # Inputs may be large and mutable: attest that the exact parsed files remained unchanged.
        if sources != {k: _fingerprint(p) for k, p in paths.items()}:
            raise ValueError("HISTORY_SOURCE_CHANGED_DURING_IMPORT")
        sources = {k: {**v, "rows": counts[k]} for k, v in sources.items()}
        _write(manifest, {"status": "converting", "identity_hash": identity_hash, **identity})
        with Tape(partial) as tape:
            with tape.db:
                tape.db.execute(
                    "INSERT INTO meta VALUES (?,?)",
                    (
                        "external_history",
                        encode(
                            {
                                **profile,
                                "sources": sources,
                                "identity_hash": identity_hash,
                                "semantic_source_hashes": semantic_sources,
                            }
                        ),
                    ),
                )
            summary = _convert(db, tape, metadata, start_ms, end_ms, config, terms, profile)
            tape.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        os.link(partial, destination / "capture.sqlite")
        partial.unlink()
        report = {
            "complete": True,
            **summary,
            "sources": sources,
            "profile": profile,
            "semantic_source_hashes": semantic_sources,
            "normalization": {
                key: counts.get(key, 0) for key in ("non_executable_books", "non_executable_trades")
            },
            "capture": str((destination / "capture.sqlite").resolve()),
            "capabilities": {
                "fast_value": "modeled_binance_receipts" if binance else "missing_binance",
                "passive_execution": "sampled_queue_trade_evidence" if trades else "missing_trades",
            },
            "requested_start_ms": start_ms,
            "requested_end_ms": end_ms,
        }
        _write(
            manifest,
            {"status": "complete", "identity_hash": identity_hash, **identity, "report": report},
        )
        return json.loads(encode(report))
    except BaseException as exc:
        _write(
            manifest,
            {
                "status": "failed",
                "identity_hash": identity_hash,
                **identity,
                "error": type(exc).__name__ + ":" + str(exc)[:500],
            },
        )
        raise
    finally:
        db.close()
        # Staging is our disposable sorted cache, never an operator-supplied source.
        # Failed imports are not resumed, so their cache is equally unnecessary.
        staging.unlink(missing_ok=True)
