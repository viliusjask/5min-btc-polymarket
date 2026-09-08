"""Bounded batches of public observations, separate from trading eligibility."""

from __future__ import annotations

import json
import uuid
from typing import Any


class PublicArchive:
    def __init__(self, *, max_bytes: int = 8 * 1024 * 1024, max_records: int = 20000) -> None:
        self.session_id = uuid.uuid4().hex
        self.max_bytes, self.max_records = max_bytes, max_records
        self.sequence = 0
        self.buffered_bytes = 0
        self.events: list[dict[str, Any]] = []
        self.gap: dict[str, Any] | None = None

    def record(self, record: dict[str, Any]) -> None:
        self.sequence += 1
        if self.gap is not None:
            self._drop(record["received_ms"], self.gap["code"])
            return
        # JSON detaches mutable exchange dictionaries and retains Decimal exactly.
        try:
            encoded = json.dumps(record, default=str, separators=(",", ":"), allow_nan=False)
        except (ValueError, TypeError, OverflowError, RecursionError):
            # A malformed public field must not change trading eligibility or leave
            # an unexplained sequence hole. Omit the remaining batch visibly.
            self._drop(record["received_ms"], "ARCHIVE_SERIALIZATION_FAILED")
            return
        size = len(encoded.encode()) + 32
        if size + self.buffered_bytes > self.max_bytes or len(self.events) >= self.max_records:
            self._drop(record["received_ms"], "ARCHIVE_BUFFER_OVERFLOW")
            return
        self.events.append({**json.loads(encoded), "sequence": self.sequence})
        self.buffered_bytes += size

    def _drop(self, received_ms: int, code: str) -> None:
        if self.gap is None:
            self.gap = {
                "code": code,
                "first_sequence": self.sequence,
                "first_received_ms": received_ms,
                "dropped_records": 0,
            }
        self.gap.update(last_sequence=self.sequence, received_ms=received_ms)
        self.gap["dropped_records"] += 1

    def drain(self) -> dict[str, Any]:
        events, gap = self.events, self.gap
        self.events, self.gap, self.buffered_bytes = [], None, 0
        return {"version": 1, "session_id": self.session_id, "events": events, "gap": gap}


def public_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """Only rule, settlement and trading interpretation fields; no chat/user payloads."""
    keys = (
        "slug",
        "conditionId",
        "condition_id",
        "market_slug",
        "description",
        "resolutionSource",
        "eventStartTime",
        "startTime",
        "endDate",
        "active",
        "closed",
        "archived",
        "negRisk",
        "accepting_orders",
        "enable_order_book",
        "neg_risk",
        "minimum_tick_size",
        "minimum_order_size",
        "tick_size",
        "min_order_size",
        "asset_id",
        "market",
        "timestamp",
        "hash",
        "outcomes",
        "clobTokenIds",
        "c",
        "v",
        "ao",
        "mts",
        "mos",
    )
    result = {k: raw[k] for k in keys if k in raw}
    for field, allowed in (
        ("eventMetadata", ("priceToBeat", "finalPrice")),
        ("fd", ("r", "e", "to")),
    ):
        if isinstance(raw.get(field), dict):
            result[field] = {k: raw[field][k] for k in allowed if k in raw[field]}
    for field, allowed in (("tokens", ("outcome", "token_id")), ("t", ("o", "t"))):
        if isinstance(raw.get(field), list):
            result[field] = [
                {k: row[k] for k in allowed if k in row}
                for row in raw[field]
                if isinstance(row, dict)
            ]
    if isinstance(raw.get("markets"), list):
        result["markets"] = [
            public_metadata(row) for row in raw["markets"] if isinstance(row, dict)
        ]
    return result
