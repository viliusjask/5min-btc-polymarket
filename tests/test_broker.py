"""Real pinned SDK methods with all network replaced at HTTP send."""

import asyncio
import json
from dataclasses import replace
from decimal import Decimal as D
from typing import Any

import httpx
import pytest
from eth_abi import decode, encode
from eth_account import Account
from polymarket.models.clob import ApiKeyCreds
from test_ledger import HASH, NOW, decision
from test_rpc import CONDITION, EXCHANGE, PUSD, TX, RPCFixture, receipt
from test_strategy import make_snapshot

from btc5m.broker import Broker, BrokerError, create_secure_client
from btc5m.config import Config
from btc5m.ledger import Ledger
from btc5m.rpc import ReadOnlyRPC

KEY = "0x" + "01" * 32
WALLET = Account.from_key(KEY).address.lower()
CREDS = ApiKeyCreds(
    key="00000000-0000-4000-8000-000000000001", secret="c3ludGhldGlj", passphrase="synthetic"
)
TOKEN = "123456789"
TOKEN2 = "987654321"


def market():
    return replace(
        make_snapshot().market, condition_id=CONDITION, up_token=TOKEN, down_token=TOKEN2
    )


def open_order(order_hash=HASH, status="MATCHED", matched="5", trades=("confirmed",)):
    return dict(
        id=order_hash,
        market=CONDITION,
        asset_id=TOKEN,
        owner=CREDS.key,
        maker_address=WALLET,
        side="BUY",
        price=".70",
        original_size="5",
        size_matched=matched,
        outcome="Up",
        order_type="FOK",
        status=status,
        associate_trades=list(trades),
        created_at=NOW // 1000,
    )


def trade(order_hash=HASH, *, ident="confirmed", status="CONFIRMED", size="5", tx=TX):
    return dict(
        id=ident,
        market=CONDITION,
        asset_id=TOKEN,
        owner=CREDS.key,
        maker_address=WALLET,
        taker_order_id=order_hash,
        side="BUY",
        trader_side="TAKER",
        price=".70",
        size=size,
        outcome="Up",
        status=status,
        fee_rate_bps="700",
        bucket_index=0,
        transaction_hash=tx,
        maker_orders=[],
        match_time=NOW // 1000,
        last_update=NOW // 1000,
    )


class Venue:
    def __init__(self):
        self.now = NOW
        self.posts = 0
        self.post_loss = False
        self.ack_hash = HASH
        self.requests = []
        self.trades: list[list[dict[str, Any]]] = [[]]
        self.order = None
        self.orders = []
        self.positions = []
        self.balance = 100000000
        self.inventory = {}
        self.fee = ".07"
        self.book_min = "5"
        self.book_tick = ".01"
        self.current_tick = ".01"
        self.bid = ".68"
        self.ask = ".70"
        self.invalid_auth = False
        self.repeat_cursor = False
        self.full_positions = False
        self.rpc = RPCFixture()
        self.rpc.receipt = receipt()
        self.rpc.receipt["logs"][0]["topics"][2] = "0x" + "00" * 12 + WALLET[2:]

    async def send(self, client, request, **kwargs):
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "polygon.drpc.org":
            body = json.loads(request.content)
            method, params = body["method"], body["params"]
            if method == "eth_call":
                data = params[0]["data"]
                selector = data[:10]
                if selector == "0x313ce567":
                    value = 6
                elif selector == "0x7f3ef6a8":
                    value = None
                elif selector == "0x70a08231":
                    value = self.balance
                elif selector == "0xdd62ed3e":
                    value = 100000000
                elif selector == "0xe985e9c5":
                    value = 1
                elif selector == "0x00fdd58e":
                    value = self.inventory.get(
                        str(decode(["address", "uint256"], bytes.fromhex(data[10:]))[1]), 0
                    )
                else:
                    from eth_utils import keccak

                    assert selector == "0x" + keccak(text="getCollateral()")[:4].hex(), selector
                    value = None
                result = (
                    "0x"
                    + encode(
                        ["address"] if value is None else ["uint256"],
                        [PUSD if value is None else value],
                    ).hex()
                )
                return httpx.Response(
                    200,
                    json={"jsonrpc": "2.0", "id": body["id"], "result": result},
                    request=request,
                )
            return self.rpc(request)
        if request.method == "POST":
            assert path == "/order", "forbidden mutation"
            self.posts += 1
            payload = json.loads(request.content)
            assert payload["orderType"] in ("FOK", "FAK")
            if self.post_loss:
                raise httpx.ReadTimeout("secret payload must never appear", request=request)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "errorMsg": "",
                    "orderID": self.ack_hash,
                    "status": "matched",
                    "makingAmount": "3.5",
                    "takingAmount": "5",
                    "tradeIDs": ["confirmed"],
                    "transactionsHashes": [],
                },
                request=request,
            )
        assert request.method == "GET", "forbidden mutation"
        if path in ("/balance-allowance", "/data/orders", "/data/trades") or path.startswith(
            "/data/order/"
        ):
            assert "POLY_API_KEY" in request.headers
            if self.invalid_auth:
                return httpx.Response(401, json={"error": "bad synthetic key"}, request=request)
        if path == "/balance-allowance":
            data = {
                "balance": str(
                    self.balance
                    if request.url.params.get("asset_type") == "COLLATERAL"
                    else self.inventory.get(request.url.params.get("token_id"), 0)
                ),
                "allowances": {EXCHANGE: 100000000},
            }
        elif path == "/data/orders":
            data = {"data": self.orders, "next_cursor": "LTE="}
        elif path.startswith("/data/order/"):
            if self.order is None:
                return httpx.Response(404, json={"error": "not found"}, request=request)
            data = self.order
        elif path == "/data/trades":
            cursor = request.url.params.get("next_cursor")
            page = int(cursor) if cursor and cursor.isdigit() else 0
            data = {
                "data": self.trades[min(page, len(self.trades) - 1)],
                "next_cursor": ("1" if self.repeat_cursor else str(page + 1))
                if page + 1 < len(self.trades) or self.repeat_cursor
                else "LTE=",
            }
            assert int(request.url.params["after"]) <= self.now // 1000 - 2
        elif path == "/positions":
            assert dict(request.url.params) == {
                "user": WALLET,
                "sizeThreshold": "0",
                "includeArchived": "true",
                "limit": "500",
                "offset": request.url.params["offset"],
            }
            offset = int(request.url.params["offset"])
            data = self.positions[offset : offset + 500]
            if self.full_positions:
                data = [
                    dict(
                        conditionId=CONDITION,
                        proxyWallet=WALLET,
                        asset=str(offset + i + 1),
                        size="0",
                    )
                    for i in range(500)
                ]
        elif path.startswith("/markets-by-token/"):
            data = {"condition_id": CONDITION}
        elif path.startswith("/clob-markets/"):
            data = {
                "fd": {"r": self.fee, "e": 1, "to": True},
                "mts": self.current_tick,
                "nr": False,
                "t": [{"t": TOKEN}, {"t": TOKEN2}],
                "c": CONDITION,
                "mos": self.book_min,
                "ao": True,
            }
        elif path.startswith("/markets/"):
            data = {
                "condition_id": CONDITION,
                "active": True,
                "accepting_orders": True,
                "closed": False,
                "neg_risk": False,
                "tokens": [{"token_id": TOKEN}, {"token_id": TOKEN2}],
            }
        elif path == "/book":
            data = {
                "market": CONDITION,
                "asset_id": request.url.params["token_id"],
                "timestamp": str(self.now),
                "hash": "synthetic",
                "bids": [{"price": self.bid, "size": "100"}],
                "asks": [{"price": self.ask, "size": "100"}],
                "min_order_size": self.book_min,
                "tick_size": self.book_tick,
                "neg_risk": False,
            }
        else:
            raise AssertionError(f"unexpected read {path}")
        return httpx.Response(200, json=data, request=request)


async def broker_fixture(tmp_path, monkeypatch, venue, *, config=None):
    config = config or Config()

    async def send(client, request, **kwargs):
        return await venue.send(client, request, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    client = await create_secure_client(private_key=KEY, wallet=WALLET, credentials=CREDS)
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET)
    session = ledger.start_or_resume_session(config)
    broker = Broker(
        client,
        ReadOnlyRPC(clock=lambda: venue.now / 1000),
        ledger,
        config,
        clock=lambda: venue.now / 1000,
    )
    preflight = await broker.preflight()
    assert preflight.entry_ready, (
        preflight.discrepancies,
        [(r.method, r.url.path) for r in venue.requests],
    )
    ledger.observe_account(
        preflight.collateral_balance, preflight.token_balances, preflight.discrepancies, now_ms=NOW
    )
    return broker, ledger, session


def test_no_network_actual_synthetic_eoa_constructor(monkeypatch):
    async def run():
        async def forbidden(*args, **kwargs):
            raise AssertionError("no network allowed")

        monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
        client = await create_secure_client(private_key=KEY, wallet=WALLET, credentials=CREDS)
        assert client.wallet.lower() == WALLET and client.wallet_type == "EOA"
        await client.close()

    asyncio.run(run())


def test_sdk_version_and_unrecognized_session_wallet_are_rejected(monkeypatch):
    async def run():
        import btc5m.broker as module

        monkeypatch.setattr(module, "version", lambda name: "0.9.1")
        with pytest.raises(BrokerError, match="SDK_VERSION"):
            await create_secure_client(private_key=KEY, wallet=WALLET, credentials=CREDS)
        monkeypatch.setattr(module, "version", lambda name: "0.9.0")
        with pytest.raises(BrokerError, match="UNSUPPORTED_SIGNER"):
            await create_secure_client(private_key=KEY, wallet="0x" + "22" * 20, credentials=CREDS)

    asyncio.run(run())


def test_invalid_credentials_preflight_never_repairs_or_mutates(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, _ = await broker_fixture(tmp_path, monkeypatch, venue)
        venue.invalid_auth = True
        result = await broker.preflight()
        assert not result.entry_ready and "ACCOUNT_READ_FAILED" in result.discrepancies
        assert venue.posts == 0
        assert all(r.method == "GET" or r.url.host == "polygon.drpc.org" for r in venue.requests)
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_sdk_exact_principal_hash_and_lost_post_response_no_retry(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        intent = ledger.reserve_entry(decision(), market(), session, NOW)
        prepared = await broker.prepare(intent, intent.market)
        payload = json.loads(prepared.signed_payload)
        assert payload["maker_amount"] == 3500000 and payload["taker_amount"] == 5000000
        assert payload["signature_type"] == 0 and payload["order_type"] == "FOK"
        assert "signature" not in repr(prepared)
        ledger.prepare(intent.intent_id, prepared)
        ledger.mark_submitting(intent.intent_id)
        venue.post_loss = True
        ack = await broker.post(prepared)
        assert ack.classification == "unknown" and "secret payload" not in repr(ack)
        assert venue.posts == 1
        ledger.record_ack(intent.intent_id, ack)
        with pytest.raises(BrokerError):
            await broker.post(prepared)
        assert venue.posts == 1
        ev = await broker.reconcile(ledger.order(intent.intent_id))
        assert not ev.terminal
        ledger.apply_evidence(intent.intent_id, ev)
        assert ledger.summary(NOW).risk_reserve == D("3.75")
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_prepare_refreshes_sdk_cache_and_rejects_changed_fee(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        intent = ledger.reserve_entry(decision(), market(), session, NOW)
        await broker.prepare(intent, intent.market)
        venue.fee = ".08"
        with pytest.raises(BrokerError, match="METADATA_CHANGED"):
            await broker.prepare(intent, intent.market)
        assert venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_confirmed_receipts_across_all_account_pages_mixed_failure_and_dedup(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        intent = ledger.reserve_entry(decision(), market(), session, NOW)
        prepared = await broker.prepare(intent, intent.market)
        ledger.prepare(intent.intent_id, prepared)
        ledger.mark_submitting(intent.intent_id)
        venue.ack_hash = prepared.order_hash
        ledger.record_ack(intent.intent_id, await broker.post(prepared))
        venue.order = open_order(
            prepared.order_hash, matched="6", trades=("failed", "confirmed", "duplicate")
        )
        venue.trades = [
            [trade(prepared.order_hash, ident="failed", status="FAILED", size="1")],
            [trade(prepared.order_hash), trade(prepared.order_hash, ident="duplicate")],
        ]
        venue.rpc.receipt["logs"][0]["topics"][1] = prepared.order_hash
        venue.balance = 96426500
        venue.inventory = {TOKEN: 5000000}
        ev = await broker.reconcile(ledger.order(intent.intent_id))
        assert ev.terminal and not ev.pending_fill_ids
        assert len(ev.fills) == 1 and ev.fills[0].quantity == 5
        ledger.apply_evidence(intent.intent_id, ev)
        ledger.apply_evidence(
            intent.intent_id, await broker.reconcile(ledger.order(intent.intent_id))
        )
        assert ledger.open_position().cost_basis == D("3.5735")
        assert ledger.summary(NOW).fees == D(".0735")
        await broker.close()
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "status",
    [
        "MATCHED",
        "MATCHED_NOT_BROADCASTED",
        "MINED",
        "RETRYING",
        "TRADE_STATUS_MINED",
        "FUTURE_STATUS",
    ],
)
def test_provisional_and_unknown_trade_schema_never_finalize(tmp_path, monkeypatch, status):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        intent = ledger.reserve_entry(decision(), market(), session, NOW)
        prepared = await broker.prepare(intent, intent.market)
        ledger.prepare(intent.intent_id, prepared)
        ledger.mark_submitting(intent.intent_id)
        venue.order = open_order(prepared.order_hash)
        venue.trades = [[trade(prepared.order_hash, status=status)]]
        ev = await broker.reconcile(ledger.order(intent.intent_id))
        assert not ev.terminal and not ev.fills
        assert ev.pending_fill_ids or ev.discrepancies
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_repeated_account_cursor_blocks_reconciliation(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        intent = ledger.reserve_entry(decision(), market(), session, NOW)
        prepared = await broker.prepare(intent, intent.market)
        ledger.prepare(intent.intent_id, prepared)
        ledger.mark_submitting(intent.intent_id)
        venue.repeat_cursor = True
        ev = await broker.reconcile(ledger.order(intent.intent_id))
        assert not ev.terminal and "ACCOUNT_PAGINATION_INCOMPLETE" in ev.discrepancies
        await broker.close()
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("bad", ["dust", "wallet", "missing", "cap", "foreign_order"])
def test_preflight_foreign_dust_identity_and_incomplete_scan_block_entry(
    tmp_path, monkeypatch, bad
):
    async def run():
        venue = Venue()
        broker, ledger, _ = await broker_fixture(tmp_path, monkeypatch, venue)
        row = dict(
            conditionId=CONDITION,
            proxyWallet=WALLET,
            asset="42",
            size="0.000001",
            currentValue="0",
            redeemable=True,
        )
        if bad == "dust":
            venue.positions = [row]
            venue.inventory = {"42": 1}
        elif bad == "wallet":
            venue.positions = [row | {"proxyWallet": "0x" + "22" * 20}]
        elif bad == "missing":
            venue.positions = [row | {"size": None}]
        elif bad == "cap":
            venue.full_positions = True
        else:
            venue.orders = [open_order("0x" + "33" * 32, status="LIVE")]
        result = await broker.preflight()
        assert not result.entry_ready
        if bad == "dust":
            assert result.foreign_token_ids == ("42",) and result.token_balances["42"] == D(
                ".000001"
            )
        if bad == "cap":
            assert not result.discovery_complete
        assert result.limitations and venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_indexed_holdings_complete_multipage_and_zero_size_candidates(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, _ = await broker_fixture(tmp_path, monkeypatch, venue)
        venue.positions = [
            dict(conditionId=CONDITION, proxyWallet=WALLET, asset=str(i + 1), size="0")
            for i in range(501)
        ]
        result = await broker.preflight()
        assert result.discovery_complete and result.entry_ready
        assert len(result.token_balances) == 501
        offsets = [r.url.params["offset"] for r in venue.requests if r.url.path == "/positions"]
        assert offsets[-2:] == ["0", "500"]
        await broker.close()
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "entry_tick,book_tick,current_tick,bid,floor,allowed",
    [
        (".01", ".001", ".001", ".995", ".99", True),
        (".01", ".01", ".001", ".995", ".99", True),
        (".001", ".001", ".01", ".99", ".98", False),
        (".01", ".005", ".0025", ".995", ".99", True),
        (".01", ".01", ".005", ".995", ".99", True),
        (".01", ".005", ".0025", ".994", ".99", False),
        (".01", ".005", ".001", ".995", ".99", True),
        (".01", ".0025", ".001", ".995", ".99", False),
    ],
)
def test_sell_current_tick_refinement_is_precise_and_audited(
    tmp_path, monkeypatch, entry_tick, book_tick, current_tick, bid, floor, allowed
):
    async def run():
        from test_engine import held

        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        pos = held(ledger, session, venue, minimum=".01")
        # Historical tick is position context; venue source changes independently.
        pos = replace(pos, market=replace(pos.market, tick_size=D(entry_tick)))
        venue.book_tick = book_tick
        venue.current_tick = current_tick
        venue.bid = bid
        intent = replace(
            ledger.reserve_exit(
                ledger.open_position(), D("3.257891"), D(floor), "TIME", session, NOW
            ),
            market=pos.market,
        )
        if allowed:
            prepared = await broker.prepare(intent, intent.market)
            raw = json.loads(prepared.signed_payload)
            assert raw["maker_amount"] == 3250000 and raw["order_type"] == "FAK"
            assert prepared.market_metadata.current_tick == D(current_tick)
            assert prepared.market_metadata.book_tick == D(book_tick)
            assert prepared.market_metadata.entry_tick == D(entry_tick)
            assert D(raw["taker_amount"]) / D(raw["maker_amount"]) >= D(floor)
        else:
            with pytest.raises(BrokerError):
                await broker.prepare(intent, intent.market)
        assert venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_entry_tick_disagreement_remains_blocked(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        venue.current_tick = ".001"
        intent = ledger.reserve_entry(decision(), market(), session, NOW)
        with pytest.raises(BrokerError, match="METADATA_CHANGED"):
            await broker.prepare(intent, intent.market)
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_preflight_wrong_chain_is_explicit_and_blocks_all_order_actions(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, _ = await broker_fixture(tmp_path, monkeypatch, venue)
        venue.rpc.chain = "0x1"
        result = await broker.preflight()
        assert "WRONG_CHAIN" in result.discrepancies and result.chain_id is None
        assert venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad", ["raw_minimum", "raw_token", "raw_tick", "book_token", "missing_accepting"]
)
def test_preparation_keeps_all_current_identity_and_minimum_guards(tmp_path, monkeypatch, bad):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        original = venue.send

        async def send(client, request, **kwargs):
            result = await original(client, request, **kwargs)
            if request.url.path.startswith("/clob-markets/"):
                data = result.json()
                if bad == "raw_minimum":
                    data["mos"] = "6"
                if bad == "raw_token":
                    data["t"] = [{"t": "42"}, {"t": TOKEN2}]
                if bad == "raw_tick":
                    data["mts"] = ".001"
                return httpx.Response(200, json=data, request=request)
            if request.url.path == "/book" and bad == "book_token":
                return httpx.Response(200, json=result.json() | {"asset_id": "42"}, request=request)
            if request.url.path.startswith("/markets/") and bad == "missing_accepting":
                data = result.json()
                data.pop("accepting_orders")
                return httpx.Response(200, json=data, request=request)
            return result

        monkeypatch.setattr(venue, "send", send)
        intent = ledger.reserve_entry(decision(), market(), session, NOW)
        with pytest.raises(BrokerError):
            await broker.prepare(intent, intent.market)
        assert venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_clock_reversal_before_post_rejects_newly_future_evidence(tmp_path, monkeypatch):
    async def run():
        venue = Venue()
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue)
        intent = ledger.reserve_entry(decision(), market(), session, NOW)
        prepared = await broker.prepare(intent, intent.market)
        ledger.prepare(intent.intent_id, prepared)
        ledger.mark_submitting(intent.intent_id)
        venue.now -= 10000
        ack = await broker.post(prepared)
        assert ack.classification == "rejected" and venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())
