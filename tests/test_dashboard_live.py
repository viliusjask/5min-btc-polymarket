import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from polymarket.pagination import AsyncPaginator, Page

from btc5m.dashboard_live import LiveDashboardReader, bot_journal, collect_account, trade_rows
from btc5m.ledger import Ledger

D = Decimal
WALLET = "0x" + "1" * 40
OTHER = "0x" + "2" * 40


def pages(items):
    async def fetch(cursor):
        return Page(tuple(items), False)

    return AsyncPaginator(fetch)


def trade(**overrides):
    values = dict(
        id="trade1",
        trader_side="TAKER",
        maker_address=WALLET,
        taker_order_id="order1",
        asset_id="123",
        condition_id="market",
        side="BUY",
        price=D(".4"),
        size=D("10"),
        outcome="Up",
        status="CONFIRMED",
        matched_at=datetime(2026, 9, 7, tzinfo=UTC),
        owner="SECRET_API_KEY",
        maker_orders=(),
        transaction_hash="0xreceipt",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_maker_fill_uses_only_own_leg_and_never_exposes_api_owner():
    own = SimpleNamespace(
        order_id="own",
        asset_id="456",
        maker_address=WALLET,
        side="SELL",
        price=D(".6"),
        matched_amount=D("3"),
        outcome="Down",
        owner="SECRET",
    )
    other = SimpleNamespace(**{**vars(own), "maker_address": OTHER, "order_id": "foreign"})
    rows = trade_rows([trade(trader_side="MAKER", maker_orders=(other, own))], WALLET, {"own"})
    assert len(rows) == 1
    assert rows[0]["quantity"] == D("3")
    assert rows[0]["side"] == "SELL"
    assert rows[0]["outcome"] == "Down"
    assert rows[0]["bot_owned"] is True
    assert "SECRET" not in json.dumps(rows, default=str)


class Client:
    wallet = WALLET
    wallet_type = "DEPOSIT_WALLET"

    def list_open_orders(self):
        return pages([])

    def list_positions(self, **kwargs):
        return pages(
            [
                SimpleNamespace(
                    wallet=WALLET,
                    asset_id="123",
                    size=D("10"),
                    current_value=D("4"),
                    avg_price=D(".3"),
                    cur_price=D(".4"),
                    title="Test market",
                    outcome="Up",
                    redeemable=False,
                )
            ]
        )

    def list_account_trades(self, **kwargs):
        return pages([trade()])


class RPC:
    async def balances(self, wallet, tokens):
        assert wallet == WALLET and tokens == set()
        return D("100"), D("0"), False, {}


def test_real_monitor_reads_account_without_creating_a_live_ledger(tmp_path):
    path = tmp_path / "live.sqlite"
    data = asyncio.run(collect_account(Client(), RPC(), WALLET, path))
    assert data["cash"]["value"] == D("100")
    assert data["positions"]["value"]["rows"][0]["current_value"] == D("4")
    assert data["bot"]["status"] == "not_started"
    assert data["trades"]["value"]["rows"][0]["bot_owned"] is False
    assert not path.exists()
    assert "SECRET" not in json.dumps(data, default=str)


def test_failed_cash_read_stays_unknown_without_hiding_other_account_sections(tmp_path):
    class FailedRPC:
        async def balances(self, *args):
            raise RuntimeError("SECRET PRIVATE KEY")

    data = asyncio.run(collect_account(Client(), FailedRPC(), WALLET, tmp_path / "live.sqlite"))
    assert data["cash"]["value"] is None
    assert data["cash"]["status"] == "unavailable"
    assert data["positions"]["status"] == "ok"
    assert "SECRET" not in json.dumps(data, default=str)


def test_account_identity_mismatch_is_rejected(tmp_path):
    client = Client()
    client.wallet = OTHER
    with pytest.raises(ValueError, match="ACCOUNT_IDENTITY_MISMATCH"):
        asyncio.run(collect_account(client, RPC(), WALLET, tmp_path / "live.sqlite"))


def test_local_live_journal_is_read_only_and_paper_is_rejected(tmp_path):
    path = tmp_path / "live.sqlite"
    ledger = Ledger(path, WALLET)
    ledger.close()
    before = path.read_bytes()
    data, owned = bot_journal(path, WALLET)
    assert data["realized_pnl"] == D(0)
    assert data["fills"] == 0
    assert owned == set()
    assert path.read_bytes() == before
    paper = tmp_path / "paper.sqlite"
    ledger = Ledger(paper, WALLET, environment="paper")
    ledger.close()
    with pytest.raises(ValueError, match="EXECUTION_ENVIRONMENT_MISMATCH"):
        bot_journal(paper, WALLET)


def test_reader_is_lazy_and_never_exposes_auth_errors():
    calls = []

    async def factory():
        calls.append(True)
        raise RuntimeError("SECRET_API_KEY")

    reader = LiveDashboardReader(factory)
    assert calls == []
    reader._refresh()
    reader.close()
    result = reader.snapshot()
    assert calls == [True]
    assert result["status"] == "unavailable"
    assert "SECRET" not in json.dumps(result)


def test_recent_trade_page_truncation_is_visible_and_bad_positions_stay_unknown(tmp_path):
    client = Client()

    async def fetch(cursor):
        return Page((trade(),), True, "next")

    client.list_account_trades = lambda **kw: AsyncPaginator(fetch)
    client.list_positions = lambda **kw: pages([SimpleNamespace(wallet=OTHER)])
    data = asyncio.run(collect_account(client, RPC(), WALLET, tmp_path / "live.sqlite"))
    assert data["trades"]["value"]["truncated"] is True
    assert data["positions"]["value"] is None
    assert data["cash"]["value"] == D(100)
