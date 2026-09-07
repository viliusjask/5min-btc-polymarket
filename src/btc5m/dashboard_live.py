"""Explicit account monitoring. Only existing authentication and read methods are used."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Awaitable, Callable, Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

from polymarket import AsyncSecureClient
from polymarket.models.clob.account import ClobTrade

from btc5m.broker import _all_pages
from btc5m.ledger import Ledger, normalize_wallet
from btc5m.rpc import ReadOnlyRPC

D = Decimal


def trade_rows(trades: Iterable[ClobTrade], wallet: str, owned: set[str]) -> list[dict[str, Any]]:
    """Project our maker legs, not the counterparty's total trade, onto a safe schema."""
    rows = []
    seen = set()
    for trade in trades:
        legs = (
            [
                (
                    trade.taker_order_id,
                    trade.asset_id,
                    trade.side,
                    trade.price,
                    trade.size,
                    trade.outcome,
                )
            ]
            if trade.trader_side == "TAKER" and trade.maker_address.lower() == wallet
            else [
                (m.order_id, m.asset_id, m.side, m.price, m.matched_amount, m.outcome)
                for m in trade.maker_orders
                if m.maker_address.lower() == wallet
            ]
        )
        if not legs:
            raise ValueError("TRADE_ACCOUNT_IDENTITY_MISMATCH")
        for order, asset, side, price, quantity, outcome in legs:
            if (trade.id, order) in seen:
                continue
            seen.add((trade.id, order))
            if not price.is_finite() or not quantity.is_finite() or quantity <= 0:
                raise ValueError("TRADE_AMOUNT_INVALID")
            rows.append(
                {
                    "id": trade.id,
                    "order_id": order,
                    "asset_id": str(asset),
                    "condition_id": str(trade.condition_id),
                    "side": side,
                    "price": price,
                    "quantity": quantity,
                    "outcome": outcome,
                    "status": trade.status,
                    "at_ms": int(trade.matched_at.timestamp() * 1000),
                    "bot_owned": order.lower() in owned,
                }
            )
    return sorted(rows, key=lambda r: r["at_ms"], reverse=True)


def bot_journal(path: Path, wallet: str) -> tuple[dict[str, Any], set[str]]:
    if not path.is_file():
        return {"status": "not_started", "realized_pnl": None, "fills": 0, "orders": 0}, set()
    ledger = Ledger(path, wallet, readonly=True)
    try:
        if ledger.environment != "live":
            raise ValueError("EXECUTION_ENVIRONMENT_MISMATCH")
        ledger.db.execute("BEGIN")
        summary = ledger.summary()
        return {
            "status": "recorded",
            "realized_pnl": summary.realized_net_pnl,
            "fees": summary.fees,
            "fills": ledger.db.execute("SELECT count(*) FROM fills").fetchone()[0],
            "orders": ledger.db.execute("SELECT count(*) FROM intents").fetchone()[0],
            "halts": summary.halts,
            "unresolved_orders": len(summary.unresolved_orders),
        }, set(ledger.owned_hashes())
    finally:
        ledger.close()


async def collect_account(
    client: AsyncSecureClient, rpc: ReadOnlyRPC, wallet: str, journal: Path
) -> dict[str, Any]:
    wallet = normalize_wallet(wallet)
    if client.wallet.lower() != wallet:
        raise ValueError("ACCOUNT_IDENTITY_MISMATCH")
    owned: set[str] | None
    try:
        bot, owned = bot_journal(journal, wallet)
    except Exception:
        bot, owned = {"status": "unavailable", "realized_pnl": None}, None

    async def cash() -> Decimal:
        value, _, _, _ = await rpc.balances(wallet, set())
        if not value.is_finite() or value < 0:
            raise ValueError("CASH_INVALID")
        return value

    async def positions() -> dict[str, Any]:
        raw = await _all_pages(client.list_positions(user=wallet, size_threshold=0, page_size=500))
        rows: list[dict[str, Any]] = []
        seen = set()
        for row in raw:
            if (
                row.wallet is None
                or row.wallet.lower() != wallet
                or row.asset_id is None
                or row.size is None
                or not row.size.is_finite()
                or row.size < 0
                or str(row.asset_id) in seen
            ):
                raise ValueError("POSITION_IDENTITY_INVALID")
            seen.add(str(row.asset_id))
            if row.size == 0:
                continue
            for value in (row.current_value, row.avg_price, row.cur_price):
                if value is not None and (not value.is_finite() or value < 0):
                    raise ValueError("POSITION_VALUE_INVALID")
            rows.append(
                {
                    "asset_id": str(row.asset_id),
                    "title": row.title,
                    "outcome": row.outcome,
                    "quantity": row.size,
                    "average_price": row.avg_price,
                    "current_price": row.cur_price,
                    "current_value": row.current_value,
                    "redeemable": row.redeemable,
                }
            )
        total = (
            sum((r["current_value"] for r in rows), D(0))
            if all(r["current_value"] is not None for r in rows)
            else None
        )
        return {
            "rows": rows[:500],
            "total_value": total,
            "total_count": len(rows),
            "truncated": len(rows) > 500,
        }

    async def orders() -> list[dict[str, Any]]:
        raw = await _all_pages(client.list_open_orders())
        rows = []
        for row in raw:
            if row.maker_address.lower() != wallet:
                raise ValueError("ORDER_ACCOUNT_IDENTITY_MISMATCH")
            rows.append(
                {
                    "id": row.id,
                    "asset_id": str(row.asset_id),
                    "side": row.side,
                    "price": row.price,
                    "quantity": row.original_size,
                    "matched": row.size_matched,
                    "outcome": row.outcome,
                    "status": row.status,
                    "created_ms": int(row.created_at.timestamp() * 1000),
                    "bot_owned": row.id.lower() in owned if owned is not None else None,
                }
            )
        return rows

    async def trades() -> dict[str, Any]:
        # A bounded recent page, explicitly labelled. Never infer lifetime returns from it.
        page = await client.list_account_trades(
            after=str(int(time.time()) - 7 * 86400)
        ).first_page()
        rows = trade_rows(page.items, wallet, owned or set())
        if owned is None:
            for row in rows:
                row["bot_owned"] = None
        return {"rows": rows[:500], "truncated": page.has_more or len(rows) > 500, "window_days": 7}

    async def section(call: Callable[[], Awaitable[Any]]) -> dict[str, Any]:
        try:
            async with asyncio.timeout(25):
                value = await call()
            return {"status": "ok", "at_ms": int(time.time() * 1000), "value": value}
        except Exception:
            return {"status": "unavailable", "at_ms": int(time.time() * 1000), "value": None}

    values = await asyncio.gather(*(section(call) for call in (cash, positions, orders, trades)))
    return {
        "wallet": wallet,
        "wallet_type": client.wallet_type,
        "bot": bot,
        **dict(zip(("cash", "positions", "orders", "trades"), values, strict=True)),
    }


class LiveDashboardReader:
    """Cache safe account projections. Slow network reads never block the paper HTTP view."""

    def __init__(
        self, factory: Callable[[], Awaitable[tuple[AsyncSecureClient, str, Path]]]
    ) -> None:
        self.factory = factory
        self.lock = threading.Lock()
        self.loading = False
        self.closed = False
        self.attempt = 0.0
        self.data: dict[str, Any] = {"environment": "live", "status": "loading", "account": None}

    async def _collect(self) -> dict[str, Any]:
        client = None
        rpc = ReadOnlyRPC()
        try:
            async with asyncio.timeout(45):
                client, wallet, path = await self.factory()
                account = await collect_account(client, rpc, wallet, path)
                return {
                    "environment": "live",
                    "status": "ready",
                    "generated_ms": int(time.time() * 1000),
                    "account": account,
                }
        finally:
            try:
                if client is not None:
                    await client.close()
            finally:
                await rpc.close()

    def _refresh(self) -> None:
        try:
            data = asyncio.run(self._collect())
            data = json.loads(json.dumps(data, default=str, allow_nan=False))
        except Exception:
            # Do not include SDK exceptions: they can contain authenticated request material.
            data = {
                "environment": "live",
                "status": "unavailable",
                "account": None,
                "generated_ms": int(time.time() * 1000),
            }
        with self.lock:
            self.data, self.loading = data, False

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            if not self.closed and not self.loading and time.monotonic() - self.attempt >= 30:
                self.attempt, self.loading = time.monotonic(), True
                threading.Thread(target=self._refresh, daemon=True).start()
            return {**self.data, "refreshing": self.loading, "poll_seconds": 30}

    def close(self) -> None:
        with self.lock:
            self.closed = True
