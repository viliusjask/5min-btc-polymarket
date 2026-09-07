"""Paper collateral conversions; no SDK, signer, approval or network access."""

from dataclasses import replace
from decimal import Decimal

from btc5m.config import PAIR_STRATEGIES
from btc5m.domain import Decision, Market, Side, require_decimal
from btc5m.execution_types import Position
from btc5m.lab_tape import encode
from btc5m.ledger import Ledger, LedgerError, _day

D = Decimal


def _allowed(ledger: Ledger, session: str) -> None:
    ledger._write()
    if ledger.environment != "paper":
        raise LedgerError("PAPER_ONLY_OPERATION")
    if ledger.config is None or ledger._meta("session") != session:
        raise LedgerError("SESSION_REQUIRED")


def split_pair(
    ledger: Ledger, market: Market, quantity: Decimal, session: str, now_ms: int
) -> None:
    _allowed(ledger, session)
    require_decimal(quantity, "quantity", positive=True)
    ident = "paper_conversion:split:" + market.slug
    with ledger.db:
        prior = ledger.db.execute("SELECT data FROM measurements WHERE key=?", (ident,)).fetchone()
        if prior:
            import json

            old = json.loads(prior[0])
            if D(old["quantity"]) != quantity or old["condition_id"] != market.condition_id:
                raise LedgerError("CONVERSION_IDENTITY_CHANGED")
            return
        assert ledger.config is not None
        summary = ledger.summary(now_ms)
        if summary.halts or summary.stop_requested:
            raise LedgerError("ENTRIES_HALTED")
        if ledger.active_positions() or ledger.unresolved_orders():
            raise LedgerError("EXPOSURE_UNRESOLVED")
        if (
            ledger.config.strategy.mode not in PAIR_STRATEGIES
            or quantity < market.min_order_size
            or not market.active
            or not market.accepting_orders
            or not market.start_s * 1000 <= now_ms < market.end_s * 1000
        ):
            raise LedgerError("SPLIT_MARKET_NOT_ELIGIBLE")
        ledger.check_reservation(quantity, summary)
        cap = ledger.config.risk.max_entries_per_day
        count = ledger.db.execute(
            "SELECT COUNT(*) FROM measurements WHERE key LIKE 'paper_conversion:split:%' AND json_extract(data,'$.day')=?",
            (_day(now_ms),),
        ).fetchone()[0]
        if cap and count >= cap:
            raise LedgerError("DAILY_ENTRY_LIMIT")
        positions = []
        for side in Side:
            decision = Decision(
                market.slug,
                side,
                "PAPER_SPLIT",
                None,
                D(0),
                D(0),
                D(0),
                D(0),
                D(0),
                None,
                None,
                None,
                {"mode": ledger.config.strategy.mode, "paper_split_session": session},
            )
            pos = Position(
                ident + ":" + side.value,
                market,
                market.token(side),
                ledger.wallet,
                decision,
                quantity,
                quantity / 2,
                D(".5"),
                "ACTIVE",
            )
            ledger._save_position(pos)
            positions.append(pos.position_id)
        record = {
            "kind": "PAPER_SPLIT",
            "day": _day(now_ms),
            "received_ms": now_ms,
            "quantity": str(quantity),
            "condition_id": market.condition_id,
            "slug": market.slug,
            "position_ids": positions,
            "cash": str(-quantity),
            "pnl": "0",
            "fee": "0",
        }
        ledger.db.execute(
            "INSERT INTO accounting VALUES (?,?,?,?,?,?)",
            (ident, session, _day(now_ms), str(-quantity), "0", "0"),
        )
        ledger.db.execute("INSERT INTO measurements VALUES (?,?)", (ident, encode(record)))
        ledger._event("PAPER_CONVERSION", now_ms, record)


def merge_pair(
    ledger: Ledger, market: Market, quantity: Decimal, session: str, now_ms: int, operation_id: str
) -> None:
    _allowed(ledger, session)
    require_decimal(quantity, "quantity", positive=True)
    ident = "paper_conversion:merge:" + operation_id
    with ledger.db:
        old = ledger.db.execute("SELECT data FROM measurements WHERE key=?", (ident,)).fetchone()
        if old:
            import json

            raw = json.loads(old[0])
            if D(raw["quantity"]) != quantity or raw["condition_id"] != market.condition_id:
                raise LedgerError("CONVERSION_IDENTITY_CHANGED")
            return
        if ledger.unresolved_orders():
            raise LedgerError("MERGE_ORDERS_UNRESOLVED")
        positions = [
            p for p in ledger.active_positions() if p.market.condition_id == market.condition_id
        ]
        if (
            len(positions) != 2
            or {p.token_id for p in positions} != {market.up_token, market.down_token}
            or any(p.quantity < quantity for p in positions)
        ):
            raise LedgerError("INSUFFICIENT_MATCHED_INVENTORY")
        basis = D(0)
        for p in positions:
            consumed = p.cost_basis * quantity / p.quantity
            basis += consumed
            ledger._save_position(
                replace(p, quantity=p.quantity - quantity, cost_basis=p.cost_basis - consumed)
            )
        record = {
            "kind": "PAPER_MERGE",
            "day": _day(now_ms),
            "received_ms": now_ms,
            "quantity": str(quantity),
            "condition_id": market.condition_id,
            "slug": market.slug,
            "position_ids": [p.position_id for p in positions],
            "cash": str(quantity),
            "pnl": str(quantity - basis),
            "fee": "0",
        }
        ledger.db.execute(
            "INSERT INTO accounting VALUES (?,?,?,?,?,?)",
            (ident, session, _day(now_ms), str(quantity), str(quantity - basis), "0"),
        )
        ledger.db.execute("INSERT INTO measurements VALUES (?,?)", (ident, encode(record)))
        ledger._event("PAPER_CONVERSION", now_ms, record)
