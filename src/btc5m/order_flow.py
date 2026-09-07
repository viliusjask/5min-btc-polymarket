"""Public exchange flow with explicit continuity and causal rolling features."""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from btc5m.domain import require_decimal, require_integer

D = Decimal


class OrderFlow:
    def __init__(self) -> None:
        self.trades: deque[dict[str, Any]] = deque()
        self.pending: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.latest_depth: dict[str, Any] | None = None
        self.trade_status = "FLOW_WARMUP"
        self.depth_status = "DEPTH_MISSING"
        self.generation = 0

    def reset_trades(self, reason: str, now_ms: int) -> None:
        self.trades.clear()
        self.generation += 1
        self.trade_status = reason
        self.events.append({"kind": "flow_gap", "code": reason, "received_ms": now_ms})

    def reset_depth(self, reason: str, now_ms: int) -> None:
        self.latest_depth = None
        self.depth_status = reason
        self.events.append({"kind": "depth_gap", "code": reason, "received_ms": now_ms})

    def trade(self, raw: dict[str, Any], now_ms: int) -> None:
        if (
            raw.get("e") != "aggTrade"
            or raw.get("s") != "BTCUSDT"
            or type(raw.get("m")) is not bool
        ):
            raise ValueError("FLOW_TRADE_SCHEMA")
        ident, stamp = raw.get("a"), raw.get("T")
        if type(ident) is not int or type(stamp) is not int:
            raise ValueError("FLOW_TRADE_SCHEMA")
        require_integer(ident, "aggregate_id")
        require_integer(stamp, "trade_timestamp")
        price, quantity = D(raw["p"]), D(raw["q"])
        require_decimal(price, "price", positive=True)
        require_decimal(quantity, "quantity", positive=True)
        if not 0 <= now_ms - stamp <= 5000:
            raise ValueError("FLOW_TRADE_TIME")
        item = {
            "id": ident,
            "source_ms": stamp,
            "received_ms": now_ms,
            "price": str(price),
            "quantity": str(quantity),
            "sell": raw["m"],
        }
        if self.trades:
            prior = self.trades[-1]
            if ident == prior["id"]:
                if any(item[k] != prior[k] for k in item if k != "received_ms"):
                    raise ValueError("FLOW_TRADE_ID_CONFLICT")
                return
            if ident < prior["id"] or stamp < prior["source_ms"]:
                raise ValueError("FLOW_TRADE_REVERSED")
            if ident != prior["id"] + 1 or now_ms - prior["received_ms"] > 5000:
                self.reset_trades("FLOW_SEQUENCE_GAP", now_ms)
        if len(self.pending) >= 100000 or len(self.trades) >= 500000:
            raise ValueError("FLOW_BUFFER_LIMIT")
        self.trades.append(item)
        self.pending.append(item)
        self.trade_status = "VALID"
        while len(self.trades) > 1 and self.trades[1]["source_ms"] <= stamp - 65000:
            self.trades.popleft()

    def depth(self, raw: dict[str, Any], now_ms: int) -> None:
        ident = raw.get("lastUpdateId")
        if type(ident) is not int:
            raise ValueError("DEPTH_SCHEMA")
        require_integer(ident, "depth_update_id")
        if self.latest_depth and ident <= self.latest_depth["update_id"]:
            if ident < self.latest_depth["update_id"]:
                raise ValueError("DEPTH_REVERSED")
            return
        parsed: dict[str, list[tuple[Decimal, Decimal]]] = {}
        for side in ("bids", "asks"):
            rows = raw.get(side)
            if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
                raise ValueError("DEPTH_SCHEMA")
            values = [(D(p), D(q)) for p, q in rows]
            for p, q in values:
                require_decimal(p, "depth_price", positive=True)
                require_decimal(q, "depth_quantity", positive=True)
            if len({p for p, _ in values}) != len(values):
                raise ValueError("DEPTH_DUPLICATE_LEVEL")
            parsed[side] = sorted(values, reverse=side == "bids")
        if parsed["bids"][0][0] >= parsed["asks"][0][0]:
            raise ValueError("DEPTH_CROSSED")
        weighted = {
            side: sum((q * (20 - i) for i, (_, q) in enumerate(rows)), D(0))
            for side, rows in parsed.items()
        }
        self.latest_depth = {
            "update_id": ident,
            "received_ms": now_ms,
            "timestamp_basis": "receipt_only",
            "imbalance": str((weighted["bids"] - weighted["asks"]) / sum(weighted.values())),
            "bids": [[str(p), str(q)] for p, q in parsed["bids"]],
            "asks": [[str(p), str(q)] for p, q in parsed["asks"]],
        }
        self.depth_status = "VALID"
        if len(self.events) >= 100000:
            raise ValueError("FLOW_BUFFER_LIMIT")
        self.events.append({"kind": "exchange_depth", **self.latest_depth})

    def view(self, now_ms: int) -> dict[str, Any]:
        latest = self.trades[-1] if self.trades else None
        status = self.trade_status
        if latest and (now_ms - latest["source_ms"] > 2000 or latest["received_ms"] > now_ms):
            status = "FLOW_STALE"
        depth = dict(self.latest_depth or {})
        depth["status"] = self.depth_status
        if self.latest_depth and not 0 <= now_ms - depth["received_ms"] <= 1500:
            depth["status"] = "DEPTH_STALE"
        windows: dict[str, Any] = {}
        for seconds in (10, 30, 60):
            target = now_ms - seconds * 1000
            prior = next((p for p in reversed(self.trades) if p["source_ms"] <= target), None)
            selected = [
                p
                for p in self.trades
                if target < p["source_ms"] <= now_ms and p["received_ms"] <= now_ms
            ]
            code = (
                status
                if status != "VALID"
                else "VALID"
                if prior and target - prior["source_ms"] <= 2000 and selected
                else "FLOW_WARMUP"
            )
            row: dict[str, Any] = {"status": code, "trades": len(selected)}
            if code == "VALID":
                assert prior is not None and latest is not None
                buys = sum((D(p["quantity"]) for p in selected if not p["sell"]), D(0))
                sells = sum((D(p["quantity"]) for p in selected if p["sell"]), D(0))
                start, end = D(prior["price"]), D(selected[-1]["price"])
                row.update(
                    buy_quantity=str(buys),
                    sell_quantity=str(sells),
                    imbalance=str((buys - sells) / (buys + sells)),
                    return_bps=str((end / start - 1) * 10000),
                    start_price=str(start),
                    end_price=str(end),
                    start_source_ms=prior["source_ms"],
                    source_ms=selected[-1]["source_ms"],
                )
            windows[str(seconds)] = row
        return {
            "received_ms": now_ms,
            "status": status,
            "generation": self.generation,
            "source_ms": latest["source_ms"] if latest else None,
            "windows": windows,
            "depth": depth,
        }

    def drain(self) -> dict[str, Any]:
        trades, events = self.pending, self.events
        self.pending, self.events = [], []
        return {"trades": trades, "events": events}
