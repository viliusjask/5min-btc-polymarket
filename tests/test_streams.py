from decimal import Decimal

import pytest

from btc5m.config import Config
from btc5m.streams import PublicStreams, StreamError

D = Decimal
NOW = 1_800_000_180_000


def stream():
    result = PublicStreams(Config(), clock=lambda: NOW / 1000)
    result.tokens = ("up", "down")
    result.condition_id = "condition"
    return result


def book(stamp=NOW):
    return {
        "event_type": "book",
        "asset_id": "up",
        "market": "condition",
        "timestamp": str(stamp),
        "bids": [{"price": ".40", "size": "10"}],
        "asks": [{"price": ".50", "size": "20"}],
    }


def test_stream_book_updates_zero_removal_and_ignores_older_full_snapshot():
    feed = stream()
    feed.ingest_market(book())
    feed.ingest_market(
        {
            "event_type": "price_change",
            "market": "condition",
            "timestamp": str(NOW),
            "price_changes": [
                {"asset_id": "up", "side": "BUY", "price": ".40", "size": "0"},
                {
                    "asset_id": "up",
                    "side": "BUY",
                    "price": ".41",
                    "size": "5",
                    "best_bid": ".41",
                    "best_ask": ".50",
                },
            ],
        }
    )
    assert feed.books["up"].bids[0].price == D(".41")
    assert len(feed.books["up"].bids) == 1
    feed.ingest_market(book(NOW - 100))
    assert feed.books["up"].bids[0].price == D(".41")


def test_trade_is_distinct_from_quote_and_duplicate_delivery_is_not_new_volume():
    feed = stream()
    feed.ingest_market(book())
    assert not feed.trades
    event = {
        "event_type": "last_trade_price",
        "market": "condition",
        "asset_id": "up",
        "timestamp": str(NOW),
        "price": ".40",
        "size": "3",
        "side": "SELL",
        "transaction_hash": "0x123",
    }
    feed.ingest_market(event)
    feed.ingest_market(event)
    assert len(feed.trades) == 1
    assert feed.trades[0].quantity == D(3)


def test_exchange_uses_trade_time_and_rejects_other_symbol():
    feed = stream()
    event = {"e": "aggTrade", "s": "BTCUSDT", "T": NOW - 10, "E": NOW, "p": "80000", "a": 1}
    feed.ingest_exchange(event)
    assert feed.exchange_history[-1].timestamp_ms == NOW - 10
    with pytest.raises(StreamError):
        feed.ingest_exchange({**event, "s": "ETHUSDT"})


def test_disconnection_invalidates_book_and_changes_generation():
    feed = stream()
    feed.ingest_market(book())
    before = feed.generation
    feed.invalidate_market("TEST_DISCONNECT")
    assert not feed.books
    assert feed.generation > before


def test_empty_ask_uses_venue_one_sentinel_without_inventing_depth():
    feed = stream()
    feed.ingest_market({**book(), "asks": []})
    feed.ingest_market(
        {
            "event_type": "price_change",
            "market": "condition",
            "timestamp": str(NOW),
            "price_changes": [
                {
                    "asset_id": "up",
                    "side": "BUY",
                    "price": ".40",
                    "size": "12",
                    "best_bid": ".40",
                    "best_ask": "1",
                }
            ],
        }
    )
    assert feed.books["up"].asks == ()
    assert feed.books["up"].bids[0].size == D(12)


def test_split_match_messages_withhold_incomplete_depth_until_removal_arrives():
    feed = stream()
    feed.ingest_market(book())
    generation = feed.generation
    event = {"event_type": "price_change", "market": "condition", "timestamp": str(NOW)}
    feed.ingest_market(
        {
            **event,
            "price_changes": [
                {
                    "asset_id": "up",
                    "side": "BUY",
                    "price": ".50",
                    "size": "5",
                    "best_bid": ".50",
                    "best_ask": "1",
                }
            ],
        }
    )
    assert "up" not in feed.books
    assert "up" in feed.pending_books
    feed.ingest_market(
        {
            **event,
            "price_changes": [
                {
                    "asset_id": "up",
                    "side": "SELL",
                    "price": ".50",
                    "size": "0",
                    "best_bid": ".50",
                    "best_ask": "1",
                }
            ],
        }
    )
    assert not feed.pending_books
    assert feed.books["up"].asks == ()
    assert feed.books["up"].bids[0].price == D(".50")
    assert feed.generation == generation


def test_incomplete_book_timeout_requires_reconnect_and_never_publishes():
    feed = stream()
    feed.ingest_market(book())
    feed.ingest_market(
        {
            "event_type": "price_change",
            "market": "condition",
            "timestamp": str(NOW),
            "price_changes": [
                {
                    "asset_id": "up",
                    "side": "BUY",
                    "price": ".30",
                    "size": "5",
                    "best_bid": ".45",
                    "best_ask": ".50",
                }
            ],
        }
    )
    assert "up" not in feed.books
    feed.clock = lambda: (NOW + 1001) / 1000
    with pytest.raises(StreamError, match="BOOK_SEQUENCE_MISMATCH"):
        feed.check_pending()
