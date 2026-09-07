from decimal import Decimal

import pytest

from btc5m.order_flow import OrderFlow

D = Decimal


def trade(ident, stamp, *, sell=True, price="80000", quantity="2"):
    return {
        "e": "aggTrade",
        "s": "BTCUSDT",
        "a": ident,
        "T": stamp,
        "p": price,
        "q": quantity,
        "m": sell,
    }


def test_executed_flow_uses_quantity_and_taker_direction_with_no_duplicates():
    flow = OrderFlow()
    for i in range(32):
        flow.trade(trade(i, 100000 + i * 1000, sell=i % 4 != 0), 100000 + i * 1000)
    flow.trade(trade(31, 131000), 131000)
    view = flow.view(131000)["windows"]["30"]
    assert view["status"] == "VALID"
    assert D(view["buy_quantity"]) == 14
    assert D(view["sell_quantity"]) == 46
    assert D(view["imbalance"]) == D("-32") / 60
    assert view["trades"] == 30
    assert len(flow.drain()["trades"]) == 32
    assert flow.drain()["trades"] == []


def test_gap_or_reconnect_requires_new_coverage_not_30_minute_warmup():
    flow = OrderFlow()
    for i in range(32):
        flow.trade(trade(i, 100000 + i * 1000), 100000 + i * 1000)
    flow.trade(trade(35, 132000), 132000)
    assert flow.view(132000)["windows"]["30"]["status"] == "FLOW_WARMUP"
    assert flow.view(140000)["status"] == "FLOW_STALE"
    flow.reset_trades("DISCONNECTED", 140000)
    assert flow.view(140000)["status"] == "DISCONNECTED"


@pytest.mark.parametrize(
    "change", [{"q": "NaN"}, {"m": "false"}, {"a": True}, {"s": "ETHUSDT"}, {"T": 100001}]
)
def test_rejects_invalid_or_future_trade_without_inventing_flow(change):
    flow = OrderFlow()
    with pytest.raises(ValueError):
        flow.trade({**trade(1, 100000), **change}, 100000)
    assert flow.view(100000)["status"] != "VALID"


def test_depth_is_a_full_snapshot_not_accumulated_size_and_stale_duplicates_do_not_refresh():
    flow = OrderFlow()
    payload = {
        "lastUpdateId": 1,
        "bids": [["80000", "9"], ["79999", "3"]],
        "asks": [["80001", "3"], ["80002", "1"]],
    }
    flow.depth(payload, 100000)
    pressure = flow.view(100000)["depth"]
    assert D(pressure["imbalance"]) == D(".5")
    assert pressure["timestamp_basis"] == "receipt_only"
    flow.depth(payload, 101000)
    assert flow.view(102001)["depth"]["status"] == "DEPTH_STALE"
    flow.depth({**payload, "lastUpdateId": 2, "bids": [["80000", "1"]]}, 102001)
    assert D(flow.view(102001)["depth"]["imbalance"]) < 0
    flow.reset_depth("DISCONNECTED", 102002)
    assert flow.view(102002)["depth"]["status"] == "DISCONNECTED"
