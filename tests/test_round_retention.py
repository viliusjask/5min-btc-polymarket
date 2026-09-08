"""Rotating recovered markets cannot evict the current round's reference evidence."""

import asyncio
from dataclasses import replace

import pytest
from test_market_data import Venue
from test_market_refresh import attach_books


@pytest.mark.parametrize("conflicted", [False, True])
def test_expired_recovery_rotation_preserves_current_snapshot_and_conflict(conflicted):
    async def run():
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            snapshot = await data.snapshot()
            attach_books(data, venue, snapshot)
            current = data._rounds[snapshot.market.slug]
            current.conflict = conflicted
            # Recovery can restore older rounds AFTER the current one. Three
            # six-market rotations exceed the total bound before the next poll.
            for batch in range(3):
                markets = []
                for i in range(6):
                    start = snapshot.market.start_s - (20 + batch * 6 + i) * 300
                    markets.append(
                        replace(
                            snapshot.market,
                            slug=f"btc-updown-5m-{start}",
                            start_s=start,
                            end_s=start + 300,
                        )
                    )
                data.retain_markets(tuple(markets))
            await data.snapshot()
            assert data._rounds[snapshot.market.slug] is current
            assert current.conflict is conflicted
            assert set(data._rounds) == {snapshot.market.slug, *(m.slug for m in markets)}
            assert not any(
                r["kind"] == "reference_retired" and r["slug"] == snapshot.market.slug
                for r in venue.records
            )
            fresh = data.current_snapshot()
            if conflicted:
                assert fresh is None
                assert data.snapshot_status["code"] == "ROUND_REFERENCE_CONFLICT"
            else:
                assert fresh is not None
                assert fresh.spot == snapshot.spot
                assert fresh.market == snapshot.market

    asyncio.run(run())


def test_count_limit_keeps_newest_rounds_when_recent_history_is_restored_late():
    async def run():
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            snapshot = await data.snapshot()
            attach_books(data, venue, snapshot)
            # At four seconds into this round, all twelve prior rounds still
            # fit the existing one-hour-after-expiry retention horizon.
            for age in range(1, 13):
                start = snapshot.market.start_s - age * 300
                data.retain_markets(
                    (
                        replace(
                            snapshot.market,
                            slug=f"btc-updown-5m-{start}",
                            start_s=start,
                            end_s=start + 300,
                        ),
                    )
                )
            data.retain_markets(())
            await data.snapshot()
            assert {state.start_s for state in data._rounds.values()} == {
                snapshot.market.start_s - age * 300 for age in range(12)
            }
            assert data.current_snapshot() is not None

    asyncio.run(run())
