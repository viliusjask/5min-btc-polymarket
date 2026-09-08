"""Fresh CLOB signing ticks may refine compatible legacy endpoint headers."""

import asyncio
from decimal import Decimal as D

import pytest
from test_market_data import Venue

from btc5m.market_data import CLOB, DataUnavailable


@pytest.mark.parametrize(
    "market_tick,book_tick", [(".01", ".01"), (".001", ".01"), (".01", ".001")]
)
def test_supported_tick_refinement_preserves_canonical_grid_and_source_values(
    market_tick, book_tick
):
    async def run():
        venue = Venue()
        venue.fees["mts"] = ".001"
        venue.market["minimum_tick_size"] = market_tick
        for book in venue.books.values():
            book["tick_size"] = book_tick
            book["bids"][0]["price"] = ".001"
        async with venue.adapter() as data:
            await venue.emit()
            snapshot = await data.snapshot()
            assert snapshot.market.tick_size == D(".001")
            assert any(level.price == D(".001") for level in snapshot.up_book.bids)
            assert snapshot.up_book.timestamp_ms == venue.clock.ms - 1000
            accepted = [r for r in venue.records if r.get("code") == "COMPATIBLE_TICK_REFINEMENT"]
            expected_count = int(D(market_tick) != D(".001")) + 2 * int(D(book_tick) != D(".001"))
            assert len(accepted) == expected_count
            for record in accepted:
                assert record["provenance"]["canonical_tick"] == "0.001"
                assert record["provenance"]["reported_tick"] == "0.01"
                assert record["source"] == f"{CLOB}/clob-markets/{snapshot.market.condition_id}"
                assert record["endpoint"] in (
                    f"{CLOB}/book",
                    f"{CLOB}/markets/{snapshot.market.condition_id}",
                )
            assert all(D(book["tick_size"]) == D(book_tick) for book in venue.books.values())

    asyncio.run(run())


@pytest.mark.parametrize(
    "canonical,reported", [(".01", ".001"), (".001", ".0025"), (".001", ".03")]
)
@pytest.mark.parametrize("endpoint", ["market", "book"])
def test_refinement_does_not_admit_reverse_nondividing_or_unsupported_ticks(
    canonical, reported, endpoint
):
    async def run():
        venue = Venue()
        venue.fees["mts"] = canonical
        venue.market["minimum_tick_size"] = reported if endpoint == "market" else canonical
        for book in venue.books.values():
            book["tick_size"] = reported if endpoint == "book" else canonical
        async with venue.adapter() as data:
            await venue.emit()
            with pytest.raises(DataUnavailable):
                await data.snapshot()
            assert data.current_snapshot() is None

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["off_grid", "minimum", "condition", "fee", "tokens", "closed"])
def test_tick_refinement_preserves_price_and_nontick_guards(fault):
    async def run():
        venue = Venue()
        venue.fees["mts"] = ".001"
        book = next(iter(venue.books.values()))
        if fault == "off_grid":
            book["bids"][0]["price"] = ".0011"
        elif fault == "minimum":
            book["min_order_size"] = "6"
        elif fault == "condition":
            book["market"] = "0x" + "ab" * 32
        elif fault == "fee":
            venue.fees["fd"]["to"] = False
        elif fault == "tokens":
            venue.fees["t"][0]["t"] = "123"
        else:
            venue.market["accepting_orders"] = False
        async with venue.adapter() as data:
            await venue.emit()
            with pytest.raises(
                DataUnavailable, match="BOOK_TICK_MISMATCH" if fault == "off_grid" else None
            ):
                await data.snapshot()
            assert data.current_snapshot() is None

    asyncio.run(run())


@pytest.mark.parametrize("off_grid", [False, True])
def test_tick_diagnostics_survive_the_public_ledger_filter(tmp_path, off_grid):
    from btc5m.ledger import Ledger

    async def run():
        venue = Venue()
        venue.fees["mts"] = ".001"
        if off_grid:
            next(iter(venue.books.values()))["bids"][0]["price"] = ".0011"
        ledger = Ledger(tmp_path / "public.sqlite", "0x" + "11" * 20)
        async with venue.adapter() as data:
            data._observer = ledger.record_observation
            await venue.emit()
            if off_grid:
                with pytest.raises(DataUnavailable, match="BOOK_TICK_MISMATCH"):
                    await data.snapshot()
            else:
                await data.snapshot()
            assert not data._observer_failed
            rows = ledger.observations()
            accepted = next(r for r in rows if r.get("code") == "COMPATIBLE_TICK_REFINEMENT")
            assert accepted["tick_size"] == "0.001"
            assert accepted["provenance"] == {"canonical_tick": "0.001", "reported_tick": "0.01"}
            assert accepted["source"].startswith(f"{CLOB}/clob-markets/")
            assert accepted["endpoint"].startswith(f"{CLOB}/markets/")
            if off_grid:
                rejected = next(r for r in rows if r.get("code") == "BOOK_TICK_MISMATCH")
                assert rejected["price"] == "0.0011" and rejected["tick_size"] == "0.001"
        ledger.close()

    asyncio.run(run())
