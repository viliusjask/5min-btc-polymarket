"""Pinned SDK execution and account reads; no automatic wallet/key/approval actions.

Construct authenticated clients only from explicit existing credentials. The
public indexed holdings scan finds candidate ERC1155 IDs, not an exhaustive
at-block ownership proof. All candidates and ledger-known balances are checked
onchain. Unknown submissions are never reposted.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import asdict
from decimal import ROUND_DOWN, Decimal
from importlib.metadata import version
from typing import Any, cast

import httpx
from polymarket import AsyncSecureClient
from polymarket.errors import RequestRejectedError
from polymarket.models.clob import ApiKeyCreds
from polymarket.models.clob.account import ClobTrade, OpenOrder
from polymarket.models.clob.order_response import RejectedOrder
from polymarket.models.clob.orders import SignedOrder
from polymarket.models.data.portfolio import Position as IndexedPosition
from polymarket.models.types import ClobAssetId
from polymarket.pagination import AsyncPaginator

from btc5m.config import Config
from btc5m.domain import Market
from btc5m.execution_types import (
    ConfirmedFill,
    Intent,
    OrderAck,
    OrderEvidence,
    PreflightEvidence,
    PreparedOrder,
    ResolutionEvidence,
)
from btc5m.ledger import Ledger, normalize_wallet
from btc5m.rpc import EXCHANGE, SCALE, ReadOnlyRPC, canonical_order_hash

D = Decimal
SIGNATURE_TYPES = {"EOA": 0, "POLY_PROXY": 1, "GNOSIS_SAFE": 2, "DEPOSIT_WALLET": 3}
REJECTIONS = frozenset(
    {
        "unmatched",
        "market_not_ready",
        "not_enough_balance",
        "invalid_nonce",
        "invalid_expiration",
        "post_only_would_cross",
        "post_only_mode",
        "fok_not_filled",
        "fak_not_filled",
    }
)


class BrokerError(Exception):
    """Safe reason code, never a request/payload/credential representation."""


async def create_secure_client(
    *, private_key: str, wallet: str, credentials: ApiKeyCreds
) -> AsyncSecureClient:
    """Explicit live/account-mode factory. Local construction never repairs auth."""
    if version("polymarket-client") != "0.9.0":
        raise BrokerError("SDK_VERSION_UNSUPPORTED")
    if (
        not private_key
        or not wallet
        or not all((credentials.key, credentials.secret, credentials.passphrase))
    ):
        raise BrokerError("EXPLICIT_EXISTING_CREDENTIALS_REQUIRED")
    normalize_wallet(wallet)
    try:
        client = await AsyncSecureClient._create(
            private_key=private_key,
            wallet=wallet,
            credentials=credentials,
            validate_credentials=False,
            api_key=None,
            logger=None,
        )
    except Exception:
        raise BrokerError("SECURE_CONSTRUCTION_FAILED") from None
    if (
        client.wallet.lower() != wallet.lower()
        or client.wallet_type not in SIGNATURE_TYPES
        or client._ctx.signer_type != "OWNER"
    ):
        await client.close()
        raise BrokerError("UNSUPPORTED_SIGNER_RELATIONSHIP")
    return client


async def _all_pages[T](paginator: AsyncPaginator[T]) -> tuple[T, ...]:
    rows: list[T] = []
    seen: set[str] = set()
    try:
        async with asyncio.timeout(15):
            async for page in paginator:
                rows.extend(page.items)
                if not page.has_more:
                    return tuple(rows)
                if not page.next_cursor or page.next_cursor in seen or len(seen) >= 1000:
                    raise BrokerError("ACCOUNT_PAGINATION_INCOMPLETE")
                seen.add(page.next_cursor)
    except BrokerError:
        raise
    except Exception:
        raise BrokerError("ACCOUNT_READ_FAILED") from None
    raise BrokerError("ACCOUNT_PAGINATION_INCOMPLETE")


class Broker:
    def __init__(
        self,
        client: AsyncSecureClient,
        rpc: ReadOnlyRPC,
        ledger: Ledger,
        config: Config,
        *,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client, self.rpc, self.ledger, self.config = client, rpc, ledger, config
        self.http = http or httpx.AsyncClient(timeout=5)
        self.clock = clock
        self._prepare_lock = asyncio.Lock()
        self._prepared: dict[str, tuple[Intent, int]] = {}
        self._posted: set[str] = set()
        self.last_preflight: PreflightEvidence | None = None

    async def close(self) -> None:
        await self.client.close()
        await self.rpc.close()
        await self.http.aclose()

    async def _get(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        try:
            response = await self.http.get(url, params=params, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception:
            raise BrokerError("PUBLIC_READ_FAILED") from None

    async def _holdings(self) -> dict[str, Decimal]:
        candidates: dict[str, Decimal] = {}
        seen_pages: set[str] = set()
        async with asyncio.timeout(15):
            for offset in range(0, 10001, 500):
                raw = await self._get(
                    "https://data-api.polymarket.com/positions",
                    params={
                        "user": self.ledger.wallet,
                        "sizeThreshold": 0,
                        "includeArchived": "true",
                        "limit": 500,
                        "offset": offset,
                    },
                )
                if not isinstance(raw, list) or len(raw) > 500:
                    raise BrokerError("HOLDINGS_SCAN_INCOMPLETE")
                identity = json.dumps(raw, sort_keys=True)
                if identity in seen_pages:
                    raise BrokerError("HOLDINGS_SCAN_INCOMPLETE")
                seen_pages.add(identity)
                for item in raw:
                    try:
                        row = IndexedPosition.model_validate(item)
                        if (
                            row.wallet is None
                            or row.asset_id is None
                            or row.size is None
                            or row.wallet.lower() != self.ledger.wallet
                            or not str(row.asset_id).isdigit()
                            or row.size < 0
                            or not row.size.is_finite()
                        ):
                            raise ValueError
                    except Exception:
                        raise BrokerError("HOLDINGS_IDENTITY_INVALID") from None
                    token = str(row.asset_id)
                    if token in candidates and candidates[token] != row.size:
                        raise BrokerError("HOLDINGS_SCAN_CONFLICT")
                    candidates[token] = row.size
                if len(raw) < 500:
                    return candidates
        raise BrokerError("HOLDINGS_SCAN_INCOMPLETE")

    async def preflight(self) -> PreflightEvidence:
        wallet = self.ledger.wallet
        cash = allowance = None
        balances: dict[str, Decimal] = {}
        foreign_orders: tuple[str, ...] = ()
        foreign_tokens: tuple[str, ...] = ()
        discrepancies = []
        approved = complete = False
        chain = None
        try:
            async with asyncio.timeout(40):
                if version("polymarket-client") != "0.9.0":
                    raise BrokerError("SDK_VERSION_UNSUPPORTED")
                if (
                    self.client.wallet.lower() != wallet
                    or self.client.wallet_type not in SIGNATURE_TYPES
                    or self.client._ctx.signer_type != "OWNER"
                ):
                    raise BrokerError("UNSUPPORTED_SIGNER_RELATIONSHIP")
                await self.rpc.chain()
                chain = 137
                if self.client.wallet_type != "EOA":
                    code = await self.rpc.request("eth_getCode", [wallet, "latest"])
                    if not isinstance(code, str) or code in ("0x", "0x0"):
                        raise BrokerError("WALLET_NOT_DEPLOYED")
                try:
                    cache = await self.client.get_balance_allowance(asset_type="COLLATERAL")
                except Exception:
                    raise BrokerError("ACCOUNT_READ_FAILED") from None
                orders = await _all_pages(self.client.list_open_orders())
                foreign_orders = tuple(
                    sorted(o.id for o in orders if o.id.lower() not in self.ledger.owned_hashes())
                )
                candidates = await self._holdings()
                complete = True
                known = self.ledger.known_inventory()
                cash, allowance, approved, balances = await self.rpc.balances(
                    wallet, set(candidates) | set(known)
                )
                foreign_tokens = tuple(
                    sorted(t for t, balance in balances.items() if balance > 0 and t not in known)
                )
                if D(cache.balance) / SCALE != cash:
                    discrepancies.append("CLOB_CASH_CACHE_DISCREPANCY")
                cached_allowance = max(
                    (
                        D(value) / SCALE
                        for spender, value in cache.allowances.items()
                        if spender.lower() == EXCHANGE.lower()
                    ),
                    default=D(0),
                )
                if min(allowance, cached_allowance) < self.config.risk.trade_budget_usd:
                    discrepancies.append("COLLATERAL_ALLOWANCE_REQUIRED")
                if not approved:
                    discrepancies.append("TOKEN_APPROVAL_REQUIRED")
                for token in known:
                    token_cache = await self.client.get_balance_allowance(
                        asset_type="CONDITIONAL", asset_id=token
                    )
                    if D(token_cache.balance) / SCALE != balances[token]:
                        discrepancies.append("CLOB_TOKEN_CACHE_DISCREPANCY")
                for token, indexed_size in candidates.items():
                    if indexed_size != balances[token]:
                        discrepancies.append("INDEX_BALANCE_DISCREPANCY")
        except BrokerError as exc:
            discrepancies.append(str(exc))
        except Exception:
            discrepancies.append("PREFLIGHT_READ_FAILED")
        result = PreflightEvidence(
            wallet,
            str(self.client.signer),
            self.client.wallet_type,
            chain,
            cash,
            allowance,
            balances,
            approved,
            foreign_orders,
            foreign_tokens,
            tuple(sorted(set(discrepancies))),
            complete,
        )
        self.last_preflight = result
        return result

    async def prepare(self, intent: Intent, market: Market) -> PreparedOrder:
        async with self._prepare_lock:
            try:
                async with asyncio.timeout(20):
                    if (
                        intent.market != market
                        or intent.wallet != self.ledger.wallet
                        or intent.state != "RESERVED"
                    ):
                        raise BrokerError("INTENT_IDENTITY_INVALID")
                    ctx = self.client._ctx
                    fresh = await ctx.order_metadata.fetch_current_market(
                        ctx, token_id=cast(ClobAssetId, intent.token_id)
                    )
                    book = await self.client.get_order_book(asset_id=intent.token_id)
                    flags = await self._get(
                        "https://clob.polymarket.com/markets/" + market.condition_id
                    )
                    fee_wire = await self._get(
                        "https://clob.polymarket.com/clob-markets/" + market.condition_id
                    )
                    if (
                        not isinstance(flags, dict)
                        or flags.get("active") is not True
                        or flags.get("accepting_orders") is not True
                        or flags.get("closed") is not False
                        or flags.get("neg_risk") is not False
                        or flags.get("condition_id") != market.condition_id
                        or not isinstance(fee_wire, dict)
                        or not isinstance(fee_wire.get("fd"), dict)
                        or set(fee_wire["fd"]) < {"r", "e"}
                        or fee_wire.get("ao") is not True
                    ):
                        raise BrokerError("MARKET_NOT_ACCEPTING")
                    if (
                        fresh.neg_risk
                        or book.neg_risk
                        or fresh.token_ids != {market.up_token, market.down_token}
                        or fresh.tick_size != market.tick_size
                        or book.tick_size != market.tick_size
                        or book.min_order_size != market.min_order_size
                        or book.condition_id != market.condition_id
                        or book.asset_id != intent.token_id
                        or fresh.fee_info.rate != market.fee_rate
                        or fresh.fee_info.exponent != market.fee_exponent
                        or D(str(fee_wire["fd"]["r"])) != market.fee_rate
                        or D(str(fee_wire["fd"]["e"])) != market.fee_exponent
                    ):
                        raise BrokerError("METADATA_CHANGED")
                    now = int(self.clock() * 1000)
                    if book.timestamp is None:
                        raise BrokerError("BOOK_TIMESTAMP_MISSING")
                    book_ms = int(book.timestamp.timestamp() * 1000)
                    if (
                        not -self.config.data.future_tolerance_ms
                        <= now - book_ms
                        <= self.config.data.max_book_age_ms
                    ):
                        raise BrokerError("STALE_BOOK")
                    quantity = intent.quantity.quantize(D(".01"), rounding=ROUND_DOWN)
                    if intent.side == "BUY":
                        signed = await self.client.create_market_order(
                            asset_id=intent.token_id,
                            side="BUY",
                            amount=intent.principal,
                            max_price=intent.price_limit,
                            order_type="FOK",
                        )
                    else:
                        if quantity <= 0 or quantity < book.min_order_size:
                            raise BrokerError("UNEXITABLE_DUST")
                        signed = await self.client.create_market_order(
                            asset_id=intent.token_id,
                            side="SELL",
                            shares=quantity,
                            min_price=intent.price_limit,
                            order_type="FAK",
                        )
                    self._validate_signed(intent, market, signed)
                    quantity = (
                        D(signed.taker_amount if intent.side == "BUY" else signed.maker_amount)
                        / SCALE
                    )
                    prepared = PreparedOrder(
                        intent.intent_id,
                        canonical_order_hash(signed),
                        json.dumps(asdict(signed), separators=(",", ":")),
                        intent.reserved_cash if intent.side == "BUY" else D(0),
                        quantity,
                    )
                    self._prepared[intent.intent_id] = (intent, book_ms)
                    return prepared
            except BrokerError:
                raise
            except Exception:
                raise BrokerError("PREPARATION_FAILED") from None

    def _validate_signed(self, intent: Intent, market: Market, signed: SignedOrder) -> None:
        expected_signer = (
            self.client.wallet
            if self.client.wallet_type == "DEPOSIT_WALLET"
            else self.client.signer
        )
        if (
            signed.maker.lower() != intent.wallet
            or signed.signer.lower() != expected_signer.lower()
            or signed.signature_type != SIGNATURE_TYPES[self.client.wallet_type]
            or signed.token_id != intent.token_id
            or signed.side != intent.side
            or signed.expiration != 0
            or signed.post_only
            or signed.order_type != ("FOK" if intent.side == "BUY" else "FAK")
            or signed.maker_amount <= 0
            or signed.taker_amount <= 0
        ):
            raise BrokerError("SIGNED_IDENTITY_INVALID")
        maker, taker = D(signed.maker_amount) / SCALE, D(signed.taker_amount) / SCALE
        if intent.side == "BUY":
            if (
                maker != intent.principal
                or taker < intent.quantity
                or taker < market.min_order_size
                or maker / taker > intent.price_limit
                or maker * (1 + market.fee_rate) > intent.reserved_cash
            ):
                raise BrokerError("SIGNED_RESERVATION_INVALID")
        elif (
            maker > intent.quantity
            or maker < market.min_order_size
            or taker / maker < intent.price_limit
        ):
            raise BrokerError("SIGNED_RESERVATION_INVALID")

    async def post(self, prepared: PreparedOrder) -> OrderAck:
        intent_id = prepared.intent_id
        stored = self.ledger.order(intent_id)
        if (
            intent_id in self._posted
            or stored.state != "SUBMITTING"
            or stored.order_hash != prepared.order_hash
            or intent_id not in self._prepared
        ):
            raise BrokerError("POST_NOT_AUTHORIZED_OR_ALREADY_ATTEMPTED")
        intent, book_ms = self._prepared[intent_id]
        now = int(self.clock() * 1000)
        if (
            now - book_ms > self.config.data.max_book_age_ms
            or now - intent.created_ms > self.config.data.max_price_age_ms
        ):
            return OrderAck("rejected", prepared.order_hash, reason="STALE_BEFORE_POST")
        if intent.side == "BUY":
            tau = intent.market.end_s - now / 1000
            low, high = (
                self.config.strategy.entry_min_seconds,
                self.config.strategy.entry_max_seconds,
            )
            if self.config.strategy.mode == "momentum":
                low, high = (
                    self.config.strategy.momentum_min_seconds,
                    self.config.strategy.momentum_max_seconds,
                )
            if not low <= tau <= high or self.ledger.stop_requested():
                return OrderAck("rejected", prepared.order_hash, reason="ENTRY_WINDOW_CLOSED")
        try:
            signed = SignedOrder(**json.loads(prepared.signed_payload))
            self._validate_signed(intent, intent.market, signed)
            if canonical_order_hash(signed) != prepared.order_hash:
                raise BrokerError("PREPARED_HASH_MISMATCH")
        except Exception:
            raise BrokerError("PREPARED_PAYLOAD_INVALID") from None
        self._posted.add(intent_id)
        try:
            async with asyncio.timeout(15):
                result = await self.client.post_order(signed)
            if isinstance(result, RejectedOrder):
                return OrderAck(
                    "rejected" if result.code in REJECTIONS else "unknown",
                    prepared.order_hash,
                    reason="VENUE_" + result.code.upper(),
                )
            return OrderAck("accepted", str(result.order_id).lower(), tuple(result.trade_ids))
        except Exception:
            return OrderAck("unknown", prepared.order_hash, reason="POST_RESPONSE_UNKNOWN")

    def _matched_trade(self, trade: ClobTrade, order: Intent) -> Decimal | None:
        if trade.taker_order_id.lower() == order.order_hash:
            if (
                trade.asset_id != order.token_id
                or trade.condition_id != order.market.condition_id
                or trade.side != order.side
                or trade.maker_address.lower() != order.wallet
                or trade.trader_side != "TAKER"
            ):
                raise BrokerError("TRADE_IDENTITY_MISMATCH")
            return trade.size
        for maker in trade.maker_orders:
            if maker.order_id.lower() == order.order_hash:
                if (
                    maker.asset_id != order.token_id
                    or maker.maker_address.lower() != order.wallet
                    or maker.side != order.side
                    or trade.condition_id != order.market.condition_id
                ):
                    raise BrokerError("TRADE_IDENTITY_MISMATCH")
                return maker.matched_amount
        return None

    async def reconcile(self, order: Intent) -> OrderEvidence:
        fills: dict[tuple[int, str, int], ConfirmedFill] = {}
        pending: set[str] = set(order.trade_ids)
        discrepancies = []
        cash = None
        balances: dict[str, Decimal] = {}
        terminal = False
        try:
            async with asyncio.timeout(40):
                if order.order_hash is None or order.wallet != self.ledger.wallet:
                    raise BrokerError("ORDER_IDENTITY_INVALID")
                venue_order: OpenOrder | None = None
                try:
                    venue_order = await self.client.get_order(order_id=order.order_hash)
                except RequestRejectedError as exc:
                    if exc.status != 404:
                        raise BrokerError("ACCOUNT_READ_FAILED") from None
                if venue_order is not None:
                    if (
                        venue_order.id.lower() != order.order_hash
                        or venue_order.asset_id != order.token_id
                        or venue_order.condition_id != order.market.condition_id
                        or venue_order.maker_address.lower() != order.wallet
                        or venue_order.side != order.side
                    ):
                        raise BrokerError("ORDER_IDENTITY_MISMATCH")
                    pending.update(venue_order.associate_trades)
                trades = await _all_pages(
                    self.client.list_account_trades(
                        asset_id=order.token_id, after=str(max(0, order.created_ms // 1000 - 2))
                    )
                )
                seen: dict[str, ClobTrade] = {}
                matched_total = D(0)
                receipts: dict[str, tuple[ConfirmedFill, ...]] = {}
                for trade in trades:
                    size = self._matched_trade(trade, order)
                    if size is None:
                        continue
                    if trade.id in seen:
                        if trade != seen[trade.id]:
                            raise BrokerError("TRADE_IDENTITY_CONFLICT")
                        continue
                    seen[trade.id] = trade
                    if size <= 0 or not size.is_finite():
                        raise BrokerError("TRADE_SIZE_INVALID")
                    matched_total += size
                    pending.discard(trade.id)
                    if trade.status == "CONFIRMED":
                        try:
                            tx = str(trade.transaction_hash).lower()
                            if tx not in receipts:
                                receipts[tx] = await self.rpc.confirmed_fills(
                                    order, tx, int(trade.updated_at.timestamp() * 1000)
                                )
                            for fill in receipts[tx]:
                                key = (fill.chain_id, fill.transaction_hash, fill.log_index)
                                if key in fills and fills[key] != fill:
                                    raise BrokerError("FILL_IDENTITY_CONFLICT")
                                fills[key] = fill
                        except Exception:
                            pending.add(trade.id)
                            discrepancies.append("RECEIPT_EVIDENCE_INCOMPLETE")
                    elif trade.status != "FAILED":
                        pending.add(trade.id)
                confirmed_qty = sum((f.quantity for f in fills.values()), D(0))
                confirmed_principal = sum((f.principal for f in fills.values()), D(0))
                full = (
                    confirmed_principal >= order.principal
                    if order.side == "BUY"
                    else confirmed_qty >= order.quantity
                )
                terminal = (
                    (
                        full
                        or (
                            venue_order is not None
                            and venue_order.status.upper()
                            in ("MATCHED", "CANCELED", "CANCELLED", "EXPIRED", "REJECTED")
                            and matched_total >= venue_order.size_matched
                            and confirmed_qty <= venue_order.size_matched
                        )
                    )
                    and not pending
                    and not discrepancies
                )
                cash, _, _, balances = await self.rpc.balances(
                    order.wallet, set(self.ledger.known_inventory()) | {order.token_id}
                )
        except BrokerError as exc:
            discrepancies.append(str(exc))
        except Exception:
            discrepancies.append("RECONCILIATION_READ_FAILED")
        return OrderEvidence(
            tuple(fills.values()),
            tuple(sorted(pending)),
            terminal and not discrepancies,
            cash,
            balances,
            tuple(sorted(set(discrepancies))),
        )

    async def resolve(self, market: Market) -> ResolutionEvidence | None:
        return await self.rpc.resolve(market)
