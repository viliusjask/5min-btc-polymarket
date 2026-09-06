"""Actual pinned SDK limit signing and cancellation, with synthetic HTTP only."""

import asyncio
import json
from decimal import Decimal as D

import httpx
import pytest
from test_broker import Venue, broker_fixture, market, open_order
from test_engine import snapshot
from test_experiments import mode
from test_ledger import NOW

from btc5m.broker import BrokerError
from btc5m.pairing import pair_decision


class PassiveVenue(Venue):
    def __init__(self):
        super().__init__()
        self.cancels = 0

    async def send(self, client, request, **kwargs):
        if request.url.path == "/order" and request.method == "POST":
            self.requests.append(request)
            self.posts += 1
            payload = json.loads(request.content)
            assert payload["orderType"] == "GTC"
            assert payload["postOnly"] is True
            assert "POLY_API_KEY" in request.headers
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "errorMsg": "",
                    "orderID": self.ack_hash,
                    "status": "live",
                    "makingAmount": "",
                    "takingAmount": "",
                    "tradeIDs": [],
                },
                request=request,
            )
        if request.url.path == "/order" and request.method == "DELETE":
            self.requests.append(request)
            self.cancels += 1
            assert json.loads(request.content) == {"orderID": self.ack_hash}
            return httpx.Response(
                200, json={"canceled": [self.ack_hash], "not_canceled": {}}, request=request
            )
        return await super().send(client, request, **kwargs)


def test_sdk_post_only_gtc_and_cancel_preserve_reserve_until_terminal_read(tmp_path, monkeypatch):
    async def run():
        venue = PassiveVenue()
        config = mode("passive_pairs")
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue, config=config)
        snap = snapshot()
        quote = pair_decision(snap, config, ())
        intent = ledger.reserve_entry(quote, market(), session, NOW)
        prepared = await broker.prepare(intent, market())
        assert venue.posts == 0 and prepared.reserved_quantity == D(5)
        assert json.loads(prepared.signed_payload)["post_only"] is True
        ledger.prepare(intent.intent_id, prepared)
        venue.ack_hash = prepared.order_hash
        ledger.mark_submitting(intent.intent_id)
        ledger.record_ack(intent.intent_id, await broker.post(prepared))
        order = ledger.order(intent.intent_id)
        assert order.state == "ACK"
        with pytest.raises(BrokerError, match="CANCEL_NOT_AUTHORIZED"):
            await broker.cancel(order)
        pending = ledger.request_cancel(intent.intent_id, NOW + 1)
        assert await broker.cancel(pending)
        assert ledger.order(intent.intent_id).remaining_reserve == intent.reserved_cash
        venue.order = {
            **open_order(prepared.order_hash, status="CANCELED", matched="0", trades=()),
            "order_type": "GTC",
            "price": str(intent.price_limit),
        }
        evidence = await broker.reconcile(ledger.order(intent.intent_id))
        assert evidence.terminal and not evidence.discrepancies
        ledger.apply_evidence(intent.intent_id, evidence)
        assert not ledger.unresolved_orders()
        assert ledger.summary(NOW).risk_reserve == 0
        assert venue.posts == 1 and venue.cancels == 1
        await broker.close()
        ledger.close()

    asyncio.run(run())


def test_sdk_rejects_passive_quote_that_has_become_marketable(tmp_path, monkeypatch):
    async def run():
        venue, config = PassiveVenue(), mode("inventory_pairs")
        broker, ledger, session = await broker_fixture(tmp_path, monkeypatch, venue, config=config)
        decision = pair_decision(snapshot(), config, ())
        intent = ledger.reserve_entry(decision, market(), session, NOW)
        venue.ask = str(intent.price_limit)
        with pytest.raises(BrokerError, match="PASSIVE_QUOTE_WOULD_CROSS"):
            await broker.prepare(intent, market())
        assert venue.posts == 0
        await broker.close()
        ledger.close()

    asyncio.run(run())
