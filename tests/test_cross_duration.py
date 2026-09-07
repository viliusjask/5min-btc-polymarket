from dataclasses import replace
from decimal import Decimal

from test_strategy import make_snapshot

from btc5m.config import Config
from btc5m.cross_duration import scan_pair
from btc5m.domain import Book, Level

D = Decimal


def compatible():
    short = make_snapshot()
    short = replace(short, market=replace(short.market, reference_price=D(80000)))
    long = replace(
        short.market,
        slug=f"btc-updown-15m-{short.market.end_s - 900}",
        start_s=short.market.end_s - 900,
        condition_id="long-condition",
        up_token="long-up",
        down_token="long-down",
        reference_price=D(80100),
    )

    def book(token, bid, ask):
        return Book(
            token, short.now_ms, short.now_ms, (Level(D(bid), D(100)),), (Level(D(ask), D(100)),)
        )

    short = replace(short, up_book=book(short.market.up_token, ".49", ".50"))
    return short, long, book(long.up_token, ".57", ".58"), book(long.down_token, ".40", ".41")


def test_lower_strike_up_higher_strike_down_is_the_correct_pair_with_real_depth_costs():
    short, long, up, down = compatible()
    result = scan_pair(short, long, up, down, Config(), short.now_ms)
    assert result["status"] == "QUOTE_CANDIDATE"
    assert result["up_market"] == short.market.slug
    assert result["down_market"] == long.slug
    assert D(result["minimum_payout"]) == 5
    assert D(result["protected_cost"]) < 5
    assert result["execution"] == "not_attempted"


def test_same_expiry_different_settlement_variable_is_never_called_arbitrage():
    short, long, up, down = compatible()
    changed = replace(long, settlement_source="different-30-second-average")
    assert (
        scan_pair(short, changed, up, down, Config(), short.now_ms)["status"]
        == "INCOMPATIBLE_SETTLEMENT"
    )
    assert (
        scan_pair(short, replace(long, end_s=long.end_s + 1), up, down, Config(), short.now_ms)[
            "status"
        ]
        == "INCOMPATIBLE_SETTLEMENT"
    )


def test_missing_anchor_stale_book_or_insufficient_size_are_visible():
    short, long, up, down = compatible()
    assert (
        scan_pair(
            short,
            replace(long, reference_price=None, reference_status="missing"),
            up,
            down,
            Config(),
            short.now_ms,
        )["status"]
        == "ANCHOR_UNAVAILABLE"
    )
    assert (
        scan_pair(
            short, long, up, replace(down, timestamp_ms=short.now_ms - 6000), Config(), short.now_ms
        )["status"]
        == "BOOK_UNAVAILABLE"
    )
    assert (
        scan_pair(
            short, long, up, replace(down, asks=(Level(D(".41"), D(1)),)), Config(), short.now_ms
        )["status"]
        == "INSUFFICIENT_DEPTH"
    )
