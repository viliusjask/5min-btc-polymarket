"""Wallet-scoped SQLite journal. Decimal accounting changes commit atomically.

Only the trading owner can mutate execution state. Status readers use SQLite read
mode; a stop request is the single permitted independent control write. No public
record or summary contains the replayable signed payload column.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from btc5m.config import PAIR_STRATEGIES, STRATEGIES, Config, strategy_for_round
from btc5m.domain import Decision, Market, Side, Snapshot, require_decimal
from btc5m.execution_types import (
    ConfirmedFill,
    Intent,
    LedgerSummary,
    OrderAck,
    OrderEvidence,
    OrderState,
    Position,
    PreparedOrder,
    ResolutionEvidence,
    SigningDomain,
)

D = Decimal
TERMINAL = ("SETTLED", "REJECTED")


class LedgerError(Exception):
    """A safe machine-readable accounting/control reason."""


def normalize_wallet(wallet: str) -> str:
    if not re.fullmatch(r"0x[0-9a-f]{40}", wallet.lower()):
        raise LedgerError("INVALID_WALLET")
    return wallet.lower()


def runtime_path(repository: Path, wallet: str) -> Path:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    common = Path(result.stdout.strip()).resolve()
    return common.parent / ".runtime" / normalize_wallet(wallet) / "ledger.sqlite"


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _market(raw: dict[str, Any]) -> Market:
    for key in ("reference_price", "tick_size", "min_order_size", "fee_rate"):
        if raw[key] is not None:
            raw[key] = D(raw[key])
    return Market(**raw)


def _decision(raw: dict[str, Any] | None) -> Decision | None:
    if raw is None:
        return None
    for key in (
        "price_limit",
        "buy_principal",
        "max_total_reserved",
        "expected_shares",
        "minimum_receive_shares",
        "estimated_buy_fee",
        "terminal_surplus_proxy",
    ):
        if raw[key] is not None:
            raw[key] = D(raw[key])
    raw["side"] = Side(raw["side"]) if raw["side"] else None
    return Decision(**raw)


def _intent(raw: str) -> Intent:
    data = json.loads(raw)
    data["market"] = _market(data["market"])
    data["decision"] = _decision(data["decision"])
    for key in (
        "principal",
        "quantity",
        "price_limit",
        "reserved_cash",
        "confirmed_quantity",
        "confirmed_principal",
        "confirmed_fee",
        "outstanding_quantity",
        "remaining_reserve",
    ):
        data[key] = D(data[key])
    for key in ("trade_ids", "pending_fill_ids", "discrepancies"):
        data[key] = tuple(data[key])
    return Intent(**data)


def _position(raw: str) -> Position:
    data = json.loads(raw)
    data["market"] = _market(data["market"])
    data["decision"] = _decision(data["decision"])
    for key in ("quantity", "cost_basis", "gross_entry_price", "claimable_value"):
        data[key] = D(data[key])
    return Position(**data)


def _day(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000, UTC).date().isoformat()


class Ledger:
    def __init__(
        self, path: Path, wallet: str, *, readonly: bool = False, environment: str = "live"
    ) -> None:
        if environment not in ("live", "paper"):
            raise LedgerError("INVALID_ENVIRONMENT")
        self.environment = environment
        self.path, self.wallet, self.readonly = path.resolve(), normalize_wallet(wallet), readonly
        self.config: Config | None = None
        self._lock: int | None = None
        if readonly:
            self.db = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, timeout=5)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.path.parent, 0o700)
            self._lock = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(self._lock)
                self._lock = None
                raise LedgerError("WALLET_LOCKED") from None
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            os.chmod(self.path, 0o600)
            self.db = sqlite3.connect(self.path, timeout=5)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, created_ms INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS intents (id TEXT PRIMARY KEY, opening_round TEXT UNIQUE, state TEXT NOT NULL, data TEXT NOT NULL, signed_payload TEXT);
                CREATE TABLE IF NOT EXISTS positions (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS fills (chain INTEGER, tx TEXT, log INTEGER, intent_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(chain,tx,log));
                CREATE TABLE IF NOT EXISTS accounting (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, day TEXT NOT NULL, cash TEXT NOT NULL, pnl TEXT NOT NULL, fee TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, at_ms INTEGER NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS measurements (key TEXT PRIMARY KEY, data TEXT NOT NULL);
            """)
            prior = self._meta("wallet")
            if prior and prior != self.wallet:
                self.close()
                raise LedgerError("WALLET_MISMATCH")
            prior_environment = self._meta("environment") or "live"
            has_data = self.db.execute("SELECT 1 FROM sessions LIMIT 1").fetchone()
            if (has_data or self._meta("environment")) and prior_environment != environment:
                self.close()
                raise LedgerError("EXECUTION_ENVIRONMENT_MISMATCH")
            with self.db:
                self._set("wallet", self.wallet)
                self._set("environment", environment)
            for suffix in ("", "-wal", "-shm", ".lock"):
                file = Path(str(self.path) + suffix)
                if file.exists():
                    os.chmod(file, 0o600)
        if self._meta("wallet") != self.wallet:
            self.close()
            raise LedgerError("WALLET_MISMATCH")
        if readonly:
            self.environment = self._meta("environment") or "live"

    def close(self) -> None:
        self.db.close()
        if self._lock is not None:
            fcntl.flock(self._lock, fcntl.LOCK_UN)
            os.close(self._lock)
            self._lock = None

    def _write(self) -> None:
        if self.readonly:
            raise LedgerError("READ_ONLY")

    def _meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    def _halt(self, reason: str) -> None:
        halts = set(json.loads(self._meta("halts") or "[]"))
        halts.add(reason)
        self._set("halts", _json(sorted(halts)))

    def _save(self, order: Intent) -> None:
        self.db.execute(
            "UPDATE intents SET state=?,data=? WHERE id=?",
            (order.state, _json(asdict(order)), order.intent_id),
        )

    def _save_position(self, position: Position) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO positions VALUES (?,?)",
            (position.position_id, _json(asdict(position))),
        )

    def _event(self, kind: str, now_ms: int, data: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO events(kind,at_ms,data) VALUES (?,?,?)", (kind, now_ms, _json(data))
        )

    def start_or_resume_session(self, config: Config, *, new_session: bool = False) -> str:
        self._write()
        with self.db:
            current = self._meta("session")
            if current:
                old = self.db.execute(
                    "SELECT fingerprint FROM sessions WHERE id=?", (current,)
                ).fetchone()[0]
                if (new_session or old != config.fingerprint) and (
                    self.unresolved_orders() or self.open_position()
                ):
                    raise LedgerError("EXPOSURE_PREVENTS_SESSION_CHANGE")
                if old == config.fingerprint and not new_session:
                    self.config = config
                    self._abandon_unposted()
                    return current
            session = uuid.uuid4().hex
            self.db.execute(
                "INSERT INTO sessions VALUES (?,?,?)",
                (session, config.fingerprint, int(time.time() * 1000)),
            )
            self._set("session", session)
            self.config = config
            self._abandon_unposted()
            return session

    def _abandon_unposted(self) -> None:
        for order in self.unresolved_orders():
            if order.state in ("RESERVED", "PREPARED"):
                self._save(
                    replace(
                        order,
                        state="REJECTED",
                        reason="ABANDONED_BEFORE_POST",
                        remaining_reserve=D(0),
                        outstanding_quantity=D(0),
                    )
                )

    def order(self, intent_id: str) -> Intent:
        row = self.db.execute("SELECT data FROM intents WHERE id=?", (intent_id,)).fetchone()
        if not row:
            raise LedgerError("UNKNOWN_INTENT")
        return _intent(row[0])

    def unresolved_orders(self) -> tuple[Intent, ...]:
        return tuple(
            _intent(row[0])
            for row in self.db.execute(
                "SELECT data FROM intents WHERE state NOT IN ('SETTLED','REJECTED') ORDER BY rowid"
            )
        )

    def owned_hashes(self) -> frozenset[str]:
        return frozenset(
            order.order_hash
            for row in self.db.execute("SELECT data FROM intents")
            if (order := _intent(row[0])).order_hash is not None
        )

    def positions(self) -> tuple[Position, ...]:
        return tuple(
            _position(row[0])
            for row in self.db.execute("SELECT data FROM positions ORDER BY rowid")
        )

    def open_position(self) -> Position | None:
        active = self.active_positions()
        if len(active) > 1:
            modes = {p.decision.features.get("mode") for p in active}
            if (
                len(active) != 2
                or len(modes) != 1
                or next(iter(modes)) not in PAIR_STRATEGIES
                or len({p.market.condition_id for p in active}) != 1
                or len({p.token_id for p in active}) != 2
            ):
                raise LedgerError("MULTIPLE_ACTIVE_POSITIONS")
        return active[0] if active else None

    def active_positions(self) -> tuple[Position, ...]:
        return tuple(p for p in self.positions() if p.status == "ACTIVE" and p.quantity > 0)

    def round_orders(self, slug: str) -> tuple[Intent, ...]:
        return tuple(
            _intent(row[0])
            for row in self.db.execute(
                "SELECT data FROM intents WHERE json_extract(data,'$.market.slug')=? ORDER BY rowid",
                (slug,),
            )
        )

    def known_inventory(self) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        for p in self.positions():
            result[p.token_id] = result.get(p.token_id, D(0)) + p.quantity
        for order in self.unresolved_orders():
            result.setdefault(order.token_id, D(0))
        return result

    def summary(self, now_ms: int | None = None) -> LedgerSummary:
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        # A savepoint begins a read transaction even on readonly connections;
        # nested use neither commits nor replaces a caller's existing snapshot.
        self.db.execute("SAVEPOINT summary_read")
        try:
            return self._summary_snapshot(now_ms)
        finally:
            self.db.execute("RELEASE SAVEPOINT summary_read")

    def _summary_snapshot(self, now_ms: int) -> LedgerSummary:
        current = self._meta("session")
        rows = self.db.execute("SELECT session_id,day,cash,pnl,fee FROM accounting").fetchall()
        cash_move = sum((D(r[2]) for r in rows), D(0))
        pnl = sum((D(r[3]) for r in rows), D(0))
        base = self._meta("initial_cash")
        inventory, orders = self.positions(), self.unresolved_orders()
        day_start = now_ms // 86400000 * 86400000
        # An entry slot represents a filled round or still-possible opening,
        # not a quote that is definitively closed without a fill. Include all
        # BUY intents: a pair's later successful quote has no opening_round key.
        daily_rounds = {
            slug
            for slug, state, quantity in self.db.execute(
                "SELECT json_extract(data,'$.market.slug'),state,json_extract(data,'$.confirmed_quantity') FROM intents WHERE json_extract(data,'$.side')='BUY' AND json_extract(data,'$.created_ms')>=? AND json_extract(data,'$.created_ms')<?",
                (day_start, day_start + 86400000),
            )
            if state not in TERMINAL or D(quantity) > 0
        }
        return LedgerSummary(
            self.wallet,
            current,
            D(base) + cash_move if base is not None else None,
            cash_move,
            pnl,
            sum((D(r[4]) for r in rows), D(0)),
            inventory,
            sum((o.remaining_reserve for o in orders), D(0)),
            sum((p.cost_basis for p in inventory if p.status == "ACTIVE"), D(0)),
            sum((p.claimable_value for p in inventory), D(0)),
            orders,
            tuple(
                sorted(
                    set(
                        json.loads(self._meta("halts") or "[]")
                        + json.loads(self._meta("account_halts") or "[]")
                        + [code for order in orders for code in order.discrepancies]
                    )
                )
            ),
            len(daily_rounds),
            sum((D(r[3]) for r in rows if r[1] == _day(now_ms)), D(0)),
            sum((D(r[3]) for r in rows if r[0] == current), D(0)),
            self.stop_requested(),
        )

    def observe_account(
        self,
        cash: Decimal | None,
        tokens: dict[str, Decimal],
        discrepancies: tuple[str, ...],
        *,
        now_ms: int,
    ) -> None:
        self._write()
        with self.db:
            reasons = list(discrepancies)
            if cash is not None:
                require_decimal(cash, "cash")
                if (
                    self._meta("initial_cash") is None
                    and not discrepancies
                    and not any(tokens.values())
                ):
                    self._set("initial_cash", str(cash))
                elif self.summary(now_ms).cash != cash:
                    reasons.append("CASH_DISCREPANCY")
            else:
                reasons.append("MISSING_CASH_BALANCE")
            known = self.known_inventory()
            for token, balance in tokens.items():
                require_decimal(balance, "token_balance")
                if known.get(token, D(0)) != balance:
                    reasons.append("TOKEN_DISCREPANCY")
            if known.keys() - tokens.keys():
                reasons.append("MISSING_TOKEN_BALANCE")
            self._set("account_halts", _json(sorted(set(reasons))))
            self._event(
                "ACCOUNT", now_ms, {"cash": cash, "tokens": tokens, "discrepancies": discrepancies}
            )

    def check_entry(self, decision: Decision, market: Market, session_id: str, now_ms: int) -> None:
        """Read-only risk check; reserve_entry repeats it under the atomic write lock."""
        if self.config is None or self._meta("session") != session_id:
            raise LedgerError("SESSION_REQUIRED")
        summary = self.summary(now_ms)
        if self.stop_requested() or summary.halts:
            raise LedgerError("ENTRIES_HALTED")
        mode = decision.features.get("mode", self.config.strategy.mode)
        pair = mode in PAIR_STRATEGIES
        active = self.active_positions()
        if summary.unresolved_orders or (active and not pair):
            raise LedgerError("EXPOSURE_UNRESOLVED")
        if pair and (
            mode != strategy_for_round(self.config, market.start_s)
            or any(
                p.market.condition_id != market.condition_id
                or p.decision.features.get("mode") != mode
                for p in active
            )
        ):
            raise LedgerError("PAIR_EXPOSURE_MISMATCH")
        if (
            decision.side is None
            or decision.reason != "ENTRY"
            or decision.slug != market.slug
            or decision.price_limit is None
            or decision.buy_principal <= 0
        ):
            raise LedgerError("INVALID_ENTRY")
        reserve = decision.max_total_reserved
        risk = self.config.risk
        self.check_reservation(reserve, summary)
        if pair and not active:
            # An opening creates directional exposure. Require enough headroom
            # for a cap-priced completion before allowing that first fill; only
            # the actual order is reserved below, and all existing limits apply.
            completion_funding = max(
                reserve,
                decision.minimum_receive_shares * self.config.experiments.pair_max_cost,
            )
            self.check_reservation(completion_funding, summary)
        if pair and summary.position_risk + reserve > risk.trade_budget_usd:
            raise LedgerError("PAIR_BUDGET_LIMIT")
        prior = self.round_orders(market.slug)
        if (
            risk.max_entries_per_day > 0
            and summary.daily_entries >= risk.max_entries_per_day
            and not (pair and prior)
        ):
            raise LedgerError("DAILY_ENTRY_LIMIT")
        if prior and not pair:
            raise LedgerError("ROUND_ALREADY_ATTEMPTED")
        if pair:
            if len(prior) >= self.config.experiments.pair_max_orders_per_round:
                raise LedgerError("PAIR_ORDER_LIMIT")
            if prior and (
                prior[0].decision is None or prior[0].decision.features.get("mode") != mode
            ):
                raise LedgerError("ROUND_STRATEGY_MISMATCH")
            if any(
                p.exit_reason
                for p in self.positions()
                if p.market.condition_id == market.condition_id
            ):
                raise LedgerError("PAIR_EXIT_LATCHED")
            if any(o.side == "SELL" for o in prior):
                raise LedgerError("PAIR_ROUND_CLOSED")
            if (
                decision.features.get("order_type") != "GTC"
                or decision.minimum_receive_shares * decision.price_limit != decision.buy_principal
            ):
                raise LedgerError("INVALID_PAIR_QUOTE")

    def check_reservation(self, reserve: Decimal, summary: LedgerSummary) -> None:
        """Common cash/loss limits for order spending and paper collateral conversion."""
        if self.config is None:
            raise LedgerError("SESSION_REQUIRED")
        require_decimal(reserve, "reserve", positive=True)
        risk = self.config.risk
        if reserve > risk.trade_budget_usd or reserve > risk.allocation_usd:
            raise LedgerError("ALLOCATION_LIMIT")
        if summary.cash is None or reserve > summary.cash - summary.risk_reserve:
            raise LedgerError("INSUFFICIENT_CASH")
        exposure = summary.position_risk + summary.risk_reserve + reserve
        if (
            max(D(0), -summary.daily_realized_net_pnl) + exposure > risk.daily_loss_usd
            or max(D(0), -summary.session_realized_net_pnl) + exposure > risk.session_loss_usd
        ):
            raise LedgerError("LOSS_LIMIT")

    def reserve_entry(
        self, decision: Decision, market: Market, session_id: str, now_ms: int
    ) -> Intent:
        self._write()
        if self.config is None or self._meta("session") != session_id:
            raise LedgerError("SESSION_REQUIRED")
        with self.db:
            self.db.execute('UPDATE meta SET value=value WHERE key="wallet"')
            self.check_entry(decision, market, session_id, now_ms)
            assert decision.side is not None and decision.price_limit is not None
            reserve = decision.max_total_reserved
            ident = uuid.uuid4().hex
            pair = decision.features.get("mode") in PAIR_STRATEGIES
            prior = self.round_orders(market.slug)
            existing = next(
                (p for p in self.active_positions() if p.token_id == market.token(decision.side)),
                None,
            )
            intent = Intent(
                ident,
                session_id,
                market,
                market.token(decision.side),
                self.wallet,
                "BUY",
                decision.buy_principal,
                decision.minimum_receive_shares,
                decision.price_limit,
                reserve,
                now_ms,
                "ENTRY",
                decision,
                existing.position_id if pair and existing else ident,
                outstanding_quantity=decision.minimum_receive_shares,
                remaining_reserve=reserve,
                passive=pair,
            )
            try:
                self.db.execute(
                    "INSERT INTO intents VALUES (?,?,?,?,NULL)",
                    (
                        ident,
                        None if pair and prior else market.slug,
                        "RESERVED",
                        _json(asdict(intent)),
                    ),
                )
            except sqlite3.IntegrityError:
                raise LedgerError("ROUND_ALREADY_ATTEMPTED") from None
            self._event("RESERVED", now_ms, {"intent_id": ident, "reason": "ENTRY"})
            return intent

    def reserve_exit(
        self,
        position: Position,
        quantity: Decimal,
        price_limit: Decimal,
        reason: str,
        session_id: str,
        now_ms: int,
        *,
        passive: bool = False,
    ) -> Intent:
        self._write()
        if self.config is None or self._meta("session") != session_id:
            raise LedgerError("SESSION_REQUIRED")
        require_decimal(quantity, "quantity", positive=True)
        require_decimal(price_limit, "price_limit", positive=True)
        if passive and self.environment != "paper":
            raise LedgerError("PAPER_ONLY_OPERATION")
        with self.db:
            actual = next(
                (p for p in self.active_positions() if p.position_id == position.position_id), None
            )
            if (
                actual is None
                or actual.position_id != position.position_id
                or actual.quantity != position.quantity
                or quantity > actual.quantity
                or price_limit >= 1
                or any(
                    not passive
                    or not o.passive
                    or o.side != "SELL"
                    or o.position_id == actual.position_id
                    for o in self.unresolved_orders()
                )
            ):
                raise LedgerError("EXIT_EXPOSURE_UNRECONCILED")
            ident = uuid.uuid4().hex
            intent = Intent(
                ident,
                session_id,
                actual.market,
                actual.token_id,
                self.wallet,
                "SELL",
                D(0),
                quantity,
                price_limit,
                D(0),
                now_ms,
                reason,
                actual.decision,
                actual.position_id,
                outstanding_quantity=quantity,
                passive=passive,
            )
            self.db.execute(
                "INSERT INTO intents VALUES (?,NULL,?,?,NULL)",
                (ident, "RESERVED", _json(asdict(intent))),
            )
            self._event("RESERVED", now_ms, {"intent_id": ident, "reason": reason})
            return intent

    def prepare(self, intent_id: str, prepared: PreparedOrder) -> None:
        self._write()
        with self.db:
            order = self.order(intent_id)
            if (
                order.state != "RESERVED"
                or prepared.intent_id != intent_id
                or prepared.reserved_cash > order.reserved_cash
                or prepared.reserved_quantity > order.quantity
                or prepared.reserved_quantity <= 0
                or prepared.signing_domain
                != (
                    SigningDomain("BTC5m PAPER", "1", 0, "0x" + "00" * 20)
                    if self.environment == "paper"
                    else SigningDomain()
                )
            ):
                raise LedgerError("INVALID_PREPARATION")
            self.db.execute(
                "UPDATE intents SET signed_payload=? WHERE id=?",
                (prepared.signed_payload, intent_id),
            )
            self._save(
                replace(
                    order,
                    state="PREPARED",
                    order_hash=prepared.order_hash,
                    quantity=prepared.reserved_quantity,
                    outstanding_quantity=prepared.reserved_quantity,
                )
            )
            self._event(
                "PREPARED",
                order.created_ms,
                {
                    "intent_id": intent_id,
                    "order_hash": prepared.order_hash,
                    "signing_domain": asdict(prepared.signing_domain),
                    "market_metadata": asdict(prepared.market_metadata)
                    if prepared.market_metadata
                    else None,
                },
            )

    def abandon(self, intent_id: str, reason: str) -> None:
        self._write()
        with self.db:
            order = self.order(intent_id)
            if order.state not in ("RESERVED", "PREPARED"):
                raise LedgerError("CANNOT_ABANDON_POSTED")
            self._save(
                replace(
                    order,
                    state="REJECTED",
                    reason=reason,
                    remaining_reserve=D(0),
                    outstanding_quantity=D(0),
                )
            )

    def mark_submitting(self, intent_id: str) -> None:
        self._write()
        with self.db:
            order = self.order(intent_id)
            if order.state != "PREPARED":
                raise LedgerError("NOT_PREPARED")
            self._save(replace(order, state="SUBMITTING"))
            self._event("SUBMITTING", int(time.time() * 1000), {"intent_id": intent_id})

    def request_cancel(self, intent_id: str, now_ms: int) -> Intent:
        """A cancellation request never releases reserves or asserts no late fills."""
        self._write()
        with self.db:
            order = self.order(intent_id)
            if not order.passive or order.state in TERMINAL or order.order_hash is None:
                raise LedgerError("CANCEL_NOT_OWNED_ACTIVE_ORDER")
            order = replace(
                order,
                cancel_requested_ms=order.cancel_requested_ms
                if order.cancel_requested_ms is not None
                else now_ms,
            )
            self._save(order)
            self._event(
                "CANCEL_REQUESTED", now_ms, {"intent_id": intent_id, "order_hash": order.order_hash}
            )
            return order

    def record_ack(self, intent_id: str, ack: OrderAck) -> None:
        self._write()
        with self.db:
            order = self.order(intent_id)
            if order.state not in ("SUBMITTING", "UNKNOWN", "ACK"):
                raise LedgerError("NOT_SUBMITTED")
            state = {"accepted": "ACK", "rejected": "REJECTED", "unknown": "UNKNOWN"}[
                ack.classification
            ]
            reason = ack.reason or order.reason
            if ack.order_hash is not None and ack.order_hash.lower() != order.order_hash:
                state, reason = "UNKNOWN", "ACK_HASH_MISMATCH"
                self._halt(reason)
            self._save(
                replace(
                    order,
                    state=cast(OrderState, state),
                    submission_reason=reason,
                    trade_ids=tuple(sorted(set(order.trade_ids + ack.trade_ids))),
                    remaining_reserve=D(0) if state == "REJECTED" else order.remaining_reserve,
                    outstanding_quantity=D(0)
                    if state == "REJECTED"
                    else order.outstanding_quantity,
                )
            )
            self._event(state, int(time.time() * 1000), {"intent_id": intent_id, "reason": reason})

    def apply_evidence(self, intent_id: str, evidence: OrderEvidence) -> None:
        self._write()
        with self.db:
            order = self.order(intent_id)
            if order.state in ("RESERVED", "PREPARED", "REJECTED"):
                raise LedgerError("UNPOSTED_FILL_EVIDENCE")
            for fill in evidence.fills:
                order = self._apply_fill(order, fill)
            terminal = (
                evidence.terminal and not evidence.pending_fill_ids and not evidence.discrepancies
            )
            state = "SETTLED" if terminal else order.state
            self._save(
                replace(
                    order,
                    state=cast(OrderState, state),
                    pending_fill_ids=evidence.pending_fill_ids,
                    discrepancies=evidence.discrepancies,
                    remaining_reserve=D(0) if terminal else order.remaining_reserve,
                    outstanding_quantity=D(0)
                    if terminal
                    else max(D(0), order.quantity - order.confirmed_quantity),
                )
            )
            # Partial evidence may precede other settlements. Balance checks happen
            # after all cumulative fills in this evidence have been applied.
            if evidence.collateral_balance is not None:
                self.observe_account(
                    evidence.collateral_balance,
                    evidence.token_balances,
                    (),
                    now_ms=int(time.time() * 1000),
                )

    def _apply_fill(self, order: Intent, fill: ConfirmedFill) -> Intent:
        if (
            fill.chain_id != (0 if self.environment == "paper" else 137)
            or fill.wallet.lower() != self.wallet
            or fill.token_id != order.token_id
            or fill.order_hash.lower() != order.order_hash
            or fill.side != order.side
            or fill.log_index < 0
        ):
            raise LedgerError("FILL_IDENTITY_MISMATCH")
        for key in ("quantity", "principal", "fee"):
            require_decimal(getattr(fill, key), key, positive=key != "fee")
        identity = (fill.chain_id, fill.transaction_hash.lower(), fill.log_index)
        duplicate = self.db.execute(
            "SELECT intent_id,data FROM fills WHERE chain=? AND tx=? AND log=?", identity
        ).fetchone()
        if duplicate:
            if duplicate != (order.intent_id, _json(asdict(fill))):
                raise LedgerError("FILL_IDENTITY_CONFLICT")
            return order
        positions = {p.position_id: p for p in self.positions()}
        prior = positions.get(order.position_id)
        cash = -(fill.principal + fill.fee) if order.side == "BUY" else fill.principal - fill.fee
        pnl = D(0)
        if order.side == "BUY":
            if order.decision is None:
                raise LedgerError("MISSING_SOURCE_DECISION")
            q = (prior.quantity if prior else D(0)) + fill.quantity
            basis = (prior.cost_basis if prior else D(0)) + fill.principal + fill.fee
            gross = (
                (prior.gross_entry_price * prior.quantity if prior else D(0)) + fill.principal
            ) / q
            pos = Position(
                order.position_id,
                order.market,
                order.token_id,
                self.wallet,
                order.decision,
                q,
                basis,
                gross,
                "ACTIVE",
                prior.exit_reason if prior else None,
                prior.exit_problem if prior else None,
            )
        else:
            if prior is None or fill.quantity > prior.quantity or fill.fee > fill.principal:
                raise LedgerError("SELL_EXCEEDS_HOLDING_OR_PROCEEDS")
            basis = prior.cost_basis * fill.quantity / prior.quantity
            pnl = cash - basis
            pos = replace(
                prior, quantity=prior.quantity - fill.quantity, cost_basis=prior.cost_basis - basis
            )
        self._save_position(pos)
        self.db.execute(
            "INSERT INTO fills VALUES (?,?,?,?,?)",
            (*identity, order.intent_id, _json(asdict(fill))),
        )
        self.db.execute(
            "INSERT INTO accounting VALUES (?,?,?,?,?,?)",
            (
                ":".join(map(str, identity)),
                order.session_id,
                _day(fill.timestamp_ms),
                str(cash),
                str(pnl),
                str(fill.fee),
            ),
        )
        principal, fee = order.confirmed_principal + fill.principal, order.confirmed_fee + fill.fee
        reserve = (
            max(D(0), order.reserved_cash * (1 - principal / order.principal))
            if order.side == "BUY"
            else D(0)
        )
        if order.side == "BUY" and principal + fee > order.reserved_cash:
            self._halt("RESERVE_BREACH")
        return replace(
            order,
            confirmed_quantity=order.confirmed_quantity + fill.quantity,
            confirmed_principal=principal,
            confirmed_fee=fee,
            remaining_reserve=reserve,
        )

    def note_exit(self, position_id: str, reason: str, problem: str | None, now_ms: int) -> None:
        self._write()
        with self.db:
            position = next(p for p in self.positions() if p.position_id == position_id)
            self._save_position(
                replace(position, exit_reason=position.exit_reason or reason, exit_problem=problem)
            )
            self._event(
                "EXIT_REASON",
                now_ms,
                {"position_id": position_id, "reason": reason, "problem": problem},
            )

    def apply_resolution(self, market: Market, evidence: ResolutionEvidence, now_ms: int) -> None:
        self._write()
        with self.db:
            if any(o.market.condition_id == market.condition_id for o in self.unresolved_orders()):
                raise LedgerError("RESOLUTION_ORDER_UNCERTAINTY")
            if json.loads(self._meta("account_halts") or "[]"):
                raise LedgerError("RESOLUTION_ACCOUNT_UNCERTAINTY")
            payouts = dict(evidence.token_payouts)
            if (
                evidence.chain_id != (0 if self.environment == "paper" else 137)
                or evidence.condition_id != market.condition_id
                or evidence.source
                != ("PAPER_OFFICIAL_FINAL" if self.environment == "paper" else "CTF_FINALIZED")
                or evidence.denominator <= 0
                or evidence.numerators not in ((evidence.denominator, 0), (0, evidence.denominator))
                or set(payouts) != {market.up_token, market.down_token}
                or set(payouts.values()) != {D(0), D(1)}
            ):
                raise LedgerError("UNVERIFIED_RESOLUTION")
            for pos in self.positions():
                if (
                    pos.market.condition_id != market.condition_id
                    or pos.status != "ACTIVE"
                    or pos.quantity == 0
                ):
                    continue
                if payouts[pos.token_id] == 1:
                    self._save_position(
                        replace(pos, status="CLAIMABLE", claimable_value=pos.quantity)
                    )
                else:
                    session = self.position_session(pos)
                    self.db.execute(
                        "INSERT INTO accounting VALUES (?,?,?,?,?,?)",
                        (
                            "resolution:" + pos.position_id,
                            session,
                            _day(now_ms),
                            "0",
                            str(-pos.cost_basis),
                            "0",
                        ),
                    )
                    self._save_position(replace(pos, status="WORTHLESS", cost_basis=D(0)))
                self._event("RESOLUTION", now_ms, asdict(evidence))

    def settle_paper_claims(self, now_ms: int) -> None:
        """Simulated automatic payout; never enabled for a funded journal."""
        if self.environment != "paper":
            raise LedgerError("PAPER_ONLY_OPERATION")
        self._write()
        with self.db:
            for position in self.positions():
                if position.status != "CLAIMABLE" or position.claimable_value <= 0:
                    continue
                self.db.execute(
                    "INSERT INTO accounting VALUES (?,?,?,?,?,?)",
                    (
                        "paper_claim:" + position.position_id,
                        self.position_session(position),
                        _day(now_ms),
                        str(position.claimable_value),
                        str(position.claimable_value - position.cost_basis),
                        "0",
                    ),
                )
                self._save_position(
                    replace(position, quantity=D(0), cost_basis=D(0), claimable_value=D(0))
                )
                self._event(
                    "PAPER_PAYOUT",
                    now_ms,
                    {
                        "position_id": position.position_id,
                        "cash": str(position.claimable_value),
                        "assumption": "automatic zero-cost simulated redemption",
                    },
                )

    def position_session(self, position: Position) -> str:
        session = position.decision.features.get("paper_split_session")
        if self.environment == "paper" and isinstance(session, str) and session:
            return session
        return self.order(position.position_id).session_id

    def request_stop(self) -> None:
        self._write()
        with self.db:
            self._set("stop", "1")

    @staticmethod
    def request_stop_at(path: Path) -> None:
        db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True, timeout=5)
        try:
            with db:
                db.execute("INSERT OR REPLACE INTO meta VALUES ('stop','1')")
        finally:
            db.close()

    def stop_requested(self) -> bool:
        return self._meta("stop") == "1"

    def record_observation(self, record: dict[str, object]) -> None:
        """Synchronous MarketData observer; only documented public fields persist."""
        self._write()
        allowed = {
            "kind",
            "received_ms",
            "received_utc",
            "slug",
            "stream",
            "source_ms",
            "price",
            "source",
            "status",
            "captured_price",
            "official_price",
            "provenance",
            "token_id",
            "condition_id",
            "tick_size",
            "min_order_size",
            "bids",
            "asks",
            "code",
            "error_type",
            "endpoint",
            "stage",
            "opening_status",
            "final_status",
            "reference_status",
            "side",
            "config_fingerprint",
            "initial_spot_source_ms",
            "original_book_source_ms",
            "original_decision_ms",
            "spot_source_ms",
            "book_source_ms",
            "book_minus_spot_ms",
            "start_s",
            "end_s",
            "reference_price",
            "reference_timestamp_ms",
            "settlement_source",
            "held_quantity",
            "covered_quantity",
            "full_depth",
            "gross_price",
            "gross_proceeds",
            "estimated_sell_fee",
            "estimated_net_proceeds",
            "identity",
            "transaction_hash",
            "quantity",
            "timestamp_ms",
            "generation",
            "mode",
        }
        safe = {key: value for key, value in record.items() if key in allowed}
        if record.get("kind") == "metadata_rejected":
            field = record.get("compared_field")
            if field not in ("condition_id", "tick_size", "min_order_size"):
                raise LedgerError("INVALID_PUBLIC_OBSERVATION")
            safe["compared_field"] = field
            for key in ("expected", "actual"):
                value = record.get(key)
                if not isinstance(value, str | Decimal) or len(str(value)) > 128:
                    raise LedgerError("INVALID_PUBLIC_OBSERVATION")
                safe[key] = str(value)
            if "supported_ticks" in record:
                ticks = record["supported_ticks"]
                if (
                    not isinstance(ticks, list | tuple)
                    or any(not re.fullmatch(r"0\.[0-9]{1,8}", str(tick)) for tick in ticks)
                    or len(ticks) > 8
                ):
                    raise LedgerError("INVALID_PUBLIC_OBSERVATION")
                safe["supported_ticks"] = [str(tick) for tick in ticks]
        kind = safe.get("kind")
        stamp = safe.get("received_ms")
        if not isinstance(kind, str) or type(stamp) is not int or len(_json(safe)) > 200000:
            raise LedgerError("INVALID_PUBLIC_OBSERVATION")
        with self.db:
            self._event("PUBLIC_OBSERVATION", stamp, safe)
            if kind == "discovery":
                slug, source = safe.get("slug"), safe.get("source_ms")
                if (
                    isinstance(slug, str)
                    and re.fullmatch(r"btc-updown-5m-[0-9]{10}", slug)
                    and type(source) is int
                    and int(slug.rsplit("-", 1)[1]) * 1000 == source
                ):
                    data = {
                        "kind": "calibration",
                        "slug": slug,
                        "target_ms": source + 180000,
                        "status": "pending",
                        "config_fingerprint": self.config.fingerprint if self.config else None,
                    }
                    self.db.execute(
                        "INSERT OR IGNORE INTO measurements VALUES (?,?)",
                        ("calibration:" + slug, _json(data)),
                    )
        self.record_clock(stamp)

    def observations(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT data FROM events WHERE kind='PUBLIC_OBSERVATION' ORDER BY id"
            )
        )

    def measurements(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            json.loads(row[0])
            for row in self.db.execute("SELECT data FROM measurements ORDER BY rowid")
        )

    def decisions(self) -> tuple[dict[str, Any], ...]:
        """Paired public strategy screens, with no private execution payloads."""
        return tuple(
            json.loads(row[0])
            for row in self.db.execute("SELECT data FROM events WHERE kind='DECISION' ORDER BY id")
        )

    def record_clock(self, now_ms: int) -> None:
        self._write()
        with self.db:
            for key, raw in self.db.execute("SELECT key,data FROM measurements").fetchall():
                data = json.loads(raw)
                if (
                    data.get("kind") == "calibration"
                    and data.get("status") == "pending"
                    and now_ms > data["target_ms"] + 2000
                ):
                    data["status"] = "missing"
                    data["missing_recorded_ms"] = now_ms
                    self.db.execute(
                        "UPDATE measurements SET data=? WHERE key=?", (_json(data), key)
                    )

    def record_snapshot(
        self, snapshot: Snapshot, config: Config, *, modes: tuple[str, ...] = ("value", "momentum")
    ) -> tuple[Decision, ...]:
        from btc5m.strategy import evaluate

        self._write()
        decisions = tuple(
            evaluate(snapshot, replace(config, strategy=replace(config.strategy, mode=mode)))
            for mode in modes
        )
        with self.db:
            market = snapshot.market
            target = (market.end_s - 120) * 1000
            key = "calibration:" + market.slug
            pending = {
                "kind": "calibration",
                "slug": market.slug,
                "target_ms": target,
                "status": "pending",
                "config_fingerprint": config.fingerprint,
            }
            self.db.execute(
                "INSERT OR IGNORE INTO measurements VALUES (?,?)", (key, _json(pending))
            )
            for mode, decision in zip(modes, decisions, strict=True):
                data = {
                    "kind": "candidate",
                    "slug": market.slug,
                    "mode": mode,
                    "now_ms": snapshot.now_ms,
                    "decision": asdict(decision),
                    "config_fingerprint": config.fingerprint,
                }
                self._event("DECISION", snapshot.now_ms, data)
                if decision.reason == "ENTRY":
                    data.update(
                        market=asdict(market),
                        spot=asdict(snapshot.spot),
                        twap60=asdict(snapshot.twap60),
                        up_book=asdict(snapshot.up_book),
                        down_book=asdict(snapshot.down_book),
                    )
                    self.db.execute(
                        "INSERT OR IGNORE INTO measurements VALUES (?,?)",
                        ("candidate:" + market.slug + ":" + mode, _json(data)),
                    )
            current = json.loads(
                self.db.execute("SELECT data FROM measurements WHERE key=?", (key,)).fetchone()[0]
            )
            if current["status"] == "pending" and target <= snapshot.now_ms <= target + 2000:
                current.update(
                    status="observed",
                    now_ms=snapshot.now_ms,
                    spot=asdict(snapshot.spot),
                    twap60=asdict(snapshot.twap60),
                    market=asdict(market),
                    decisions=[asdict(d) for d in decisions],
                    up_book=asdict(snapshot.up_book),
                    down_book=asdict(snapshot.down_book),
                )
                self.db.execute("UPDATE measurements SET data=? WHERE key=?", (_json(current), key))
        self.record_clock(snapshot.now_ms)
        return decisions

    def portfolio_results(self) -> dict[str, Any]:
        """Attribute actual journal cash/PnL to the policy that created each order."""
        self.db.execute("SAVEPOINT portfolio_read")
        try:
            return self._portfolio_results()
        finally:
            self.db.execute("RELEASE SAVEPOINT portfolio_read")

    def _portfolio_results(self) -> dict[str, Any]:
        orders = {row[0]: _intent(row[1]) for row in self.db.execute("SELECT id,data FROM intents")}
        positions = {p.position_id: p for p in self.positions()}
        conversions = {
            key: json.loads(raw)
            for key, raw in self.db.execute(
                "SELECT key,data FROM measurements WHERE key LIKE 'paper_conversion:%'"
            )
        }
        mapping = {
            f"{chain}:{tx}:{log}": orders[intent_id]
            for chain, tx, log, intent_id in self.db.execute(
                "SELECT chain,tx,log,intent_id FROM fills"
            )
        }
        by_mode: dict[str, Any] = {
            mode: {
                "cash_movement": D(0),
                "realized_net_pnl": D(0),
                "fees": D(0),
                "orders": 0,
                "fills": 0,
                "conversions": 0,
                "rounds": {},
                "open_cost_basis": D(0),
                "claimable_value": D(0),
            }
            for mode in STRATEGIES
        }
        for saved_order in orders.values():
            mode = (
                str(saved_order.decision.features.get("mode", "value"))
                if saved_order.decision
                else "value"
            )
            if mode not in by_mode:
                continue
            by_mode[mode]["orders"] += 1
            by_mode[mode]["rounds"].setdefault(
                saved_order.market.slug,
                {"realized_net_pnl": D(0), "fees": D(0), "unresolved": False, "filled": False},
            )
            if saved_order.state not in TERMINAL:
                by_mode[mode]["rounds"][saved_order.market.slug]["unresolved"] = True
        for position in positions.values():
            mode = str(position.decision.features.get("mode", "value"))
            if mode in by_mode:
                by_mode[mode]["rounds"].setdefault(
                    position.market.slug,
                    {"realized_net_pnl": D(0), "fees": D(0), "unresolved": False, "filled": False},
                )
        for ident, cash, pnl, fee in self.db.execute("SELECT id,cash,pnl,fee FROM accounting"):
            order: Intent | Position | None = mapping.get(ident)
            if order is None and ident.startswith(("resolution:", "paper_claim:")):
                origin = ident.split(":", 1)[1]
                order = orders.get(origin) or positions.get(origin)
            if order is None and ident in conversions:
                order = positions.get(conversions[ident]["position_ids"][0])
            if order is None:
                continue
            mode = str(order.decision.features.get("mode", "value")) if order.decision else "value"
            if mode not in by_mode:
                continue
            data = by_mode[mode]
            data["cash_movement"] += D(cash)
            data["realized_net_pnl"] += D(pnl)
            data["fees"] += D(fee)
            data["fills"] += int(ident in mapping)
            if ident in conversions:
                data["conversions"] += 1
                data["rounds"][order.market.slug]["converted"] = True
            data["rounds"][order.market.slug]["realized_net_pnl"] += D(pnl)
            data["rounds"][order.market.slug]["fees"] += D(fee)
            if ident in mapping:
                data["rounds"][order.market.slug]["filled"] = True
        for position in self.positions():
            mode = str(position.decision.features.get("mode", "value"))
            if mode in by_mode:
                data = by_mode[mode]
                data["open_cost_basis"] += position.cost_basis
                data["claimable_value"] += position.claimable_value
                if position.quantity > 0 and position.status != "WORTHLESS":
                    data["rounds"][position.market.slug]["unresolved"] = True
        for data in by_mode.values():
            data["attempted_rounds"] = len(data["rounds"])
            data["filled_rounds"] = sum(r["filled"] for r in data["rounds"].values())
            data["completed_rounds"] = sum(
                r["filled"] and not r["unresolved"] for r in data["rounds"].values()
            )
        return by_mode

    def clear_stop_request(self) -> None:
        """Only explicit run startup calls this once, before awaited account setup."""
        self._write()
        with self.db:
            self._set("stop", "0")
            self._event("STOP_CLEARED", int(time.time() * 1000), {})
