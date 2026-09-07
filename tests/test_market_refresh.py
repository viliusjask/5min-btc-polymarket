"""Metadata admission and book recovery stay independent of settlement polling."""

import asyncio
from dataclasses import replace

import pytest
from test_market_data import Venue

from btc5m.config import Config
from btc5m.market_data import DataUnavailable
from btc5m.streams import PublicStreams


def advance(venue, data, seconds, *, prices=True):
    venue.clock.ms += seconds * 1000
    venue.clock.elapsed += seconds
    for book in venue.books.values():
        book["timestamp"] = str(venue.clock.ms)
    if prices:
        for kind, points in data._points.items():
            latest = points[max(points)]
            points[venue.clock.ms] = replace(
                latest, timestamp_ms=venue.clock.ms, received_ms=venue.clock.ms
            )
            data._receipts[kind] = venue.clock.mono()


def attach_books(data, venue, snapshot):
    streams = PublicStreams(Config(), clock=venue.clock.wall, observer=data._stream_observation)
    streams.tokens = (snapshot.market.up_token, snapshot.market.down_token)
    streams.condition_id = snapshot.market.condition_id
    streams.books = {b.token_id: b for b in (snapshot.up_book, snapshot.down_book)}
    data.streams = streams
    return streams


def test_slow_settlement_poll_does_not_hold_current_market_refresh():
    async def run():
        venue = Venue()
        started, release = asyncio.Event(), asyncio.Event()
        original = venue.client.get_event

        async def slow(**kwargs):
            started.set()
            await release.wait()
            return await original(**kwargs)

        async with venue.adapter() as data:
            await venue.emit()
            await data.snapshot()
            venue.client.get_event = slow
            advance(venue, data, 31)
            task = asyncio.create_task(data.snapshot())
            try:
                snapshot = await asyncio.wait_for(asyncio.shield(task), 0.2)
                assert snapshot.now_ms == venue.clock.ms
                await asyncio.wait_for(started.wait(), 0.2)
                assert not release.is_set()
            finally:
                release.set()
                await task

    asyncio.run(run())


def test_book_disconnect_blocks_old_rest_book_but_recovers_without_expiring_metadata():
    async def run():
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            snapshot = await data.snapshot()
            streams = attach_books(data, venue, snapshot)
            streams.invalidate_market("BOOK_STREAM_DISCONNECTED")
            assert data.current_snapshot() is None
            assert data.snapshot_status["code"] == "BOOK_RESYNC_PENDING"
            assert data.snapshot_status["book_invalidation_reason"] == "BOOK_STREAM_DISCONNECTED"
            # Complete fresh books recover synchronization, without any metadata HTTP response.
            streams.books = {b.token_id: b for b in (snapshot.up_book, snapshot.down_book)}
            assert data.current_snapshot() is not None

    asyncio.run(run())


def test_tick_invalidation_survives_transport_recovery_until_validated_refresh():
    async def run():
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            snapshot = await data.snapshot()
            streams = attach_books(data, venue, snapshot)
            streams.invalidate_market("TICK_SIZE_CHANGED")
            streams.invalidate_market("BOOK_STREAM_DISCONNECTED")
            streams.books = {b.token_id: b for b in (snapshot.up_book, snapshot.down_book)}
            assert data.current_snapshot() is None
            assert data.snapshot_status["code"] == "METADATA_INVALIDATED"
            assert data.snapshot_status["metadata_invalidation_reason"] == "TICK_SIZE_CHANGED"
            await data.snapshot()
            assert data.current_snapshot() is not None

    asyncio.run(run())


def test_successful_metadata_refresh_is_retained_while_price_feed_is_stale():
    async def run():
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            await data.snapshot()
            advance(venue, data, 6, prices=False)
            with pytest.raises(DataUnavailable):
                await data.snapshot()
            assert data.current_snapshot() is None
            assert data.snapshot_status["component"] == "spot"
            assert data.snapshot_status["code"] in ("STALE_DATA", "STREAM_SILENT")
            assert data.snapshot_status["metadata_age_ms"] < 1
            advance(venue, data, 0)
            assert data.current_snapshot() is not None

    asyncio.run(run())


@pytest.mark.parametrize("code", ["TICK_SIZE_CHANGED", "BOOK_OUT_OF_ORDER"])
def test_invalidation_during_http_refresh_cannot_publish_pre_invalidation_books(code):
    async def run():
        venue = Venue()
        entered, release = asyncio.Event(), asyncio.Event()
        original = venue.client.get_order_book

        async def slow(**kwargs):
            book = await original(**kwargs)
            entered.set()
            await release.wait()
            return book

        async with venue.adapter() as data:
            await venue.emit()
            snapshot = await data.snapshot()
            streams = attach_books(data, venue, snapshot)
            advance(venue, data, 3)
            venue.client.get_order_book = slow
            task = asyncio.create_task(data.snapshot())
            await asyncio.wait_for(entered.wait(), 0.2)
            streams.invalidate_market(code)
            release.set()
            with pytest.raises(DataUnavailable, match="BOOK_GENERATION_CHANGED"):
                await task
            assert data.current_snapshot() is None
            venue.client.get_order_book = original
            await data.snapshot()
            assert data.current_snapshot() is not None

    asyncio.run(run())


def test_conflicting_refresh_revokes_still_young_metadata():
    async def run():
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            snapshot = await data.snapshot()
            attach_books(data, venue, snapshot)
            advance(venue, data, 3)
            venue.market["minimum_tick_size"] = ".001" if venue.fees["mts"] != ".001" else ".01"
            with pytest.raises(DataUnavailable, match="TRADING_METADATA_CHANGED"):
                await data.snapshot()
            assert data.current_snapshot() is None
            assert data.snapshot_status["code"] == "METADATA_INVALIDATED"
            assert (
                data.snapshot_status["metadata_invalidation_reason"] == "TRADING_METADATA_CHANGED"
            )

    asyncio.run(run())


def test_crossed_rest_depth_does_not_revoke_valid_metadata_and_stream_books():
    async def run():
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            snapshot = await data.snapshot()
            streams = attach_books(data, venue, snapshot)
            advance(venue, data, 3)
            streams.books = {
                b.token_id: replace(b, timestamp_ms=venue.clock.ms, received_ms=venue.clock.ms)
                for b in (snapshot.up_book, snapshot.down_book)
            }
            for book in venue.books.values():
                book["bids"] = [{"price": ".9", "size": "100"}]
                book["asks"] = [{"price": ".1", "size": "100"}]
            with pytest.raises(DataUnavailable, match="CROSSED_BOOK"):
                await data.snapshot()
            assert data.current_snapshot() is not None
            # Recovery cannot silently renew the metadata's five-second lifetime.
            advance(venue, data, 3)
            assert data.current_snapshot() is None
            assert data.snapshot_status["code"] == "METADATA_CACHE_EXPIRED"

    asyncio.run(run())


def test_close_cancels_and_joins_blocked_settlement_poll():
    async def run():
        venue = Venue()
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def blocked(**kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async with venue.adapter() as data:
            await venue.emit()
            await data.snapshot()
            venue.client.get_event = blocked
            advance(venue, data, 31)
            await data.snapshot()
            await asyncio.wait_for(started.wait(), 0.2)
            await asyncio.wait_for(data.close(), 0.2)
            assert cancelled.is_set()
            assert all(task.done() for task in data._tasks)

    asyncio.run(run())
