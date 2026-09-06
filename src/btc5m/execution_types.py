"""Concrete execution evidence. Replayable data is excluded from record representations."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from btc5m.domain import Decision, Market, Side, Snapshot

OrderState = Literal["RESERVED", "PREPARED", "SUBMITTING", "ACK", "UNKNOWN", "SETTLED", "REJECTED"]


@dataclass(frozen=True)
class Intent:
    intent_id: str
    session_id: str
    market: Market
    token_id: str
    wallet: str
    side: Literal["BUY", "SELL"]
    principal: Decimal
    quantity: Decimal
    price_limit: Decimal
    reserved_cash: Decimal
    created_ms: int
    reason: str
    decision: Decision | None
    position_id: str
    state: OrderState = "RESERVED"
    order_hash: str | None = None
    confirmed_quantity: Decimal = Decimal(0)
    confirmed_principal: Decimal = Decimal(0)
    confirmed_fee: Decimal = Decimal(0)
    outstanding_quantity: Decimal = Decimal(0)
    remaining_reserve: Decimal = Decimal(0)
    trade_ids: tuple[str, ...] = ()
    pending_fill_ids: tuple[str, ...] = ()
    submission_reason: str = ""
    discrepancies: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparationMarket:
    entry_tick: Decimal
    book_tick: Decimal
    current_tick: Decimal
    reason: str
    protected_price: Decimal


@dataclass(frozen=True)
class SigningDomain:
    name: str = "Polymarket CTF Exchange"
    version: str = "2"
    chain_id: int = 137
    exchange: str = "0xE111180000d2663C0091e4f400237545B87B996B"


@dataclass(frozen=True)
class PreparedOrder:
    intent_id: str
    order_hash: str
    signed_payload: str = field(repr=False)
    reserved_cash: Decimal
    reserved_quantity: Decimal
    market_metadata: PreparationMarket | None = None
    signing_domain: SigningDomain = field(default_factory=SigningDomain)


@dataclass(frozen=True)
class OrderAck:
    classification: Literal["accepted", "rejected", "unknown"]
    order_hash: str | None = None
    trade_ids: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ConfirmedFill:
    chain_id: int
    transaction_hash: str
    log_index: int
    order_hash: str
    token_id: str
    wallet: str
    side: Literal["BUY", "SELL"]
    quantity: Decimal
    principal: Decimal
    fee: Decimal
    timestamp_ms: int
    block_number: int = 0
    block_hash: str = ""


@dataclass(frozen=True)
class OrderEvidence:
    fills: tuple[ConfirmedFill, ...]
    pending_fill_ids: tuple[str, ...]
    terminal: bool
    collateral_balance: Decimal | None
    token_balances: dict[str, Decimal]
    discrepancies: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolutionEvidence:
    condition_id: str
    chain_id: int
    block_number: int
    block_hash: str
    denominator: int
    numerators: tuple[int, int]
    token_payouts: tuple[tuple[str, Decimal], ...]
    source: str
    observed_ms: int


@dataclass(frozen=True)
class Position:
    position_id: str
    market: Market
    token_id: str
    wallet: str
    decision: Decision
    quantity: Decimal
    cost_basis: Decimal
    gross_entry_price: Decimal
    status: Literal["ACTIVE", "CLAIMABLE", "WORTHLESS"]
    exit_reason: str | None = None
    exit_problem: str | None = None
    claimable_value: Decimal = Decimal(0)


@dataclass(frozen=True)
class PreflightEvidence:
    wallet: str
    signer: str
    wallet_type: str
    chain_id: int | None
    collateral_balance: Decimal | None
    collateral_allowance: Decimal | None
    token_balances: dict[str, Decimal]
    token_approved: bool
    foreign_order_ids: tuple[str, ...]
    foreign_token_ids: tuple[str, ...]
    discrepancies: tuple[str, ...]
    discovery_complete: bool
    limitations: tuple[str, ...] = (
        "INDEX_IS_CANDIDATE_DISCOVERY_NOT_EXHAUSTIVE_ONCHAIN_OWNERSHIP",
        "DEDICATED_WALLET_NO_EXTERNAL_TRADING_REQUIRED",
        "ORDINARY_CTF_POSITIONS_ONLY",
        "OWNER_SIGNERS_ONLY_SESSION_KEYS_UNSUPPORTED",
        "SELL_MINIMUM_SHARES_CONSERVATIVE_LIVE_UNVERIFIED",
        "BUY_FEE_RESERVATION_IS_NOT_PROTOCOL_ALL_IN_CAP",
    )

    @property
    def entry_ready(self) -> bool:
        return (
            self.discovery_complete
            and not self.discrepancies
            and not self.foreign_order_ids
            and not self.foreign_token_ids
            and self.collateral_balance is not None
            and self.collateral_allowance is not None
            and self.token_approved
        )


@dataclass(frozen=True)
class LedgerSummary:
    wallet: str
    session_id: str | None
    cash: Decimal | None
    cash_movement: Decimal
    realized_net_pnl: Decimal
    fees: Decimal
    inventory: tuple[Position, ...]
    risk_reserve: Decimal
    position_risk: Decimal
    claimable_value: Decimal
    unresolved_orders: tuple[Intent, ...]
    halts: tuple[str, ...]
    daily_entries: int
    daily_realized_net_pnl: Decimal
    session_realized_net_pnl: Decimal
    stop_requested: bool


@dataclass(frozen=True)
class EngineResult:
    action: str
    reason: str
    intent_id: str | None = None


@dataclass(frozen=True)
class PendingCandidate:
    slug: str
    side: Side
    config_fingerprint: str
    condition_id: str
    token_id: str
    start_s: int
    end_s: int
    reference_price: Decimal | None
    reference_timestamp_ms: int | None
    settlement_source: str
    initial_spot_source_ms: int
    original_book_source_ms: int
    original_decision_ms: int


@dataclass(frozen=True)
class SnapshotInput:
    snapshot: Snapshot | None
    invalidation_generation: int
