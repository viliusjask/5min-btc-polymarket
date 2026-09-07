"""Replay attributed public SDK/HTTP payloads through the real adapter."""

import asyncio
import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from polymarket.models.clob.order_book import OrderBook
from polymarket.models.gamma.event import Event
from polymarket.models.rtds_events import (
    CryptoPricesChainlinkEvent,
    CryptoPricesChainlinkTwapEvent,
)
from polymarket.streams import CryptoPricesChainlinkTwapSpec, CryptoPricesSpec

from btc5m.config import Config
from btc5m.market_data import DataUnavailable, MarketData
from btc5m.strategy import evaluate

FIXTURES = Path(__file__).parent / "fixtures" / "market_data"
START = 1788711600
ANCHOR = Decimal("79697.534252279656349696")


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class Clock:
    def __init__(self) -> None:
        self.ms = START * 1000 + 4000
        self.elapsed = 100.0

    def wall(self) -> float:
        return self.ms / 1000

    def mono(self) -> float:
        return self.elapsed


class Stream:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[Any] = asyncio.Queue()

    def __aiter__(self) -> "Stream":
        return self

    async def __anext__(self) -> Any:
        event = await self.queue.get()
        if isinstance(event, Exception):
            raise event
        return event

    async def close(self) -> None:
        pass


class PublicFixtureClient:
    """Only external SDK I/O is substituted; SDK models and adapter state are real."""

    def __init__(self, venue: "Venue") -> None:
        self.venue = venue
        self.spot = Stream()
        self.twap = Stream()
        self.closed = False

    async def subscribe(self, spec: Any) -> Stream:
        if isinstance(spec, CryptoPricesChainlinkTwapSpec):
            assert spec.window_seconds == 60 and spec.symbols == ("btc/usd",)
            return self.twap
        assert isinstance(spec, CryptoPricesSpec)
        assert spec.topic == "prices.crypto.chainlink" and spec.symbols == ("btc/usd",)
        return self.spot

    async def get_order_book(self, *, token_id: str) -> OrderBook:
        await asyncio.sleep(0)
        return OrderBook.model_validate(self.venue.books[token_id])

    async def get_event(self, *, slug: str, include_chat: bool) -> Event:
        assert include_chat is False
        return Event.model_validate(self.venue.events[slug])

    async def close(self) -> None:
        self.closed = True


class Venue:
    def __init__(self) -> None:
        self.clock = Clock()
        self.event = fixture("gamma-event")
        self.market = fixture("clob-market")
        self.fees = fixture("clob-fees")
        self.books = {}
        for name in ("book-up", "book-down"):
            raw = fixture(name)
            raw["timestamp"] = str(self.clock.ms - 1000)
            self.books[raw["asset_id"]] = raw
        self.events = {self.event["slug"]: self.event}
        self.client = PublicFixtureClient(self)
        self.records: list[dict[str, object]] = []
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.request))

    def request(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.host == "gamma-api.polymarket.com":
            assert request.url.params["include_chat"] == "false"
            payload = self.events.get(request.url.path.split("/")[-1], self.event)
        elif request.url.path.startswith("/markets/"):
            payload = self.market
        elif request.url.path.startswith("/clob-markets/"):
            payload = self.fees
        else:
            raise AssertionError(f"unexpected public route {request.url}")
        return httpx.Response(200, json=payload, request=request)

    def adapter(self, config: Config | None = None) -> MarketData:
        return MarketData(
            config or Config(),
            client=self.client,
            http_client=self.http,
            clock=self.clock.wall,
            monotonic=self.clock.mono,
            observer=self.records.append,
        )

    async def emit(self, *, omit_boundary: bool = False, reverse: bool = False) -> None:
        # Translate the real 15:40 boundary to the separately captured 16:20 market.
        # Prices and source-time offsets remain unchanged; this is synthetic replay.
        rows = fixture("boundary-events")
        if reverse:
            rows.reverse()
        for row in rows:
            raw = copy.deepcopy(row["event"])
            raw["payload"]["timestamp"] += (START - 1788709200) * 1000
            if omit_boundary and raw["payload"]["timestamp"] == START * 1000:
                continue
            if raw["topic"].endswith(".twap"):
                model = CryptoPricesChainlinkTwapEvent.model_validate(raw)
                self.client.twap.queue.put_nowait(model)
            else:
                self.client.spot.queue.put_nowait(CryptoPricesChainlinkEvent.model_validate(raw))
        await settle()


async def settle() -> None:
    for _ in range(30):
        await asyncio.sleep(0)


def test_exact_source_boundary_and_full_precision_with_out_of_order_duplicates() -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit(reverse=True)
            await venue.emit()
            result = await data.snapshot()
            assert result.market.reference_price == ANCHOR
            assert result.market.reference_status == "boundary"
            assert result.market.reference_timestamp_ms == START * 1000
            assert len(result.history) == 3
            assert [point.timestamp_ms for point in result.history] == sorted(
                point.timestamp_ms for point in result.history
            )
            assert result.twap60.timestamp_ms == START * 1000 + 1000
            assert result.spot.kind == "spot"
            assert any(record["kind"] == "discovery" for record in venue.records)
            assert any(record["kind"] == "anchor" for record in venue.records)
            price_records = [r for r in venue.records if r["kind"] == "twap60"]
            assert any(r["price"] == str(ANCHOR) for r in price_records)
            assert all("received_ms" in r and "source_ms" in r for r in price_records)
        assert venue.client.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("captured_allowed", [True, False])
def test_missing_boundary_and_official_only_policy_never_use_neighbor(
    captured_allowed: bool,
) -> None:
    async def scenario() -> None:
        venue = Venue()
        config = replace(
            Config(), data=replace(Config().data, allow_captured_anchor=captured_allowed)
        )
        async with venue.adapter(config) as data:
            await venue.emit(omit_boundary=captured_allowed)
            result = await data.snapshot()
            assert result.market.reference_price is None
            assert result.market.reference_status == "missing"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "difference,status", [("0.000000000004", "official"), ("0.00000002", "conflict")]
)
def test_later_official_comparison_and_null_do_not_erase_state(
    difference: str, status: str
) -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            await data.snapshot()
            venue.event["eventMetadata"] = {"priceToBeat": str(ANCHOR + Decimal(difference))}
            result = await data.snapshot()
            assert result.market.reference_status == status
            stored = result.market.reference_price
            venue.event["eventMetadata"] = None
            result = await data.snapshot()
            assert result.market.reference_status == status
            assert result.market.reference_price == stored
            venue.event["eventMetadata"] = {"priceToBeat": str(ANCHOR)}
            result = await data.snapshot()
            assert result.market.reference_status == status

    asyncio.run(scenario())


def test_official_anchor_conflict_persists_without_captured_point() -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit(omit_boundary=True)
            venue.event["eventMetadata"] = {"priceToBeat": "79697.53425227966"}
            assert (await data.snapshot()).market.reference_status == "official"
            venue.event["eventMetadata"] = {"priceToBeat": "79698"}
            assert (await data.snapshot()).market.reference_status == "conflict"
            venue.event["eventMetadata"] = None
            assert (await data.snapshot()).market.reference_status == "conflict"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case",
    [
        "wrong_start",
        "wrong_end",
        "wrong_slug",
        "changed_rules",
        "wrong_source",
        "missing_accepting",
        "missing_active",
        "negative_risk",
        "missing_fee",
        "unknown_fee",
        "fee_not_taker",
        "ambiguous_tokens",
    ],
)
def test_unsupported_wire_metadata_fails_closed(case: str) -> None:
    async def scenario() -> None:
        venue = Venue()
        market = venue.event["markets"][0]
        if case == "wrong_start":
            market["eventStartTime"] = market["startDate"]
        elif case == "wrong_end":
            market["endDate"] = market["eventStartTime"]
        elif case == "wrong_slug":
            market["slug"] = "btc-updown-5m-1788711300"
        elif case == "changed_rules":
            market["description"] = market["description"].replace(
                "greater than or equal to", "greater than"
            )
        elif case == "wrong_source":
            market["resolutionSource"] = "https://data.chain.link/streams/btc-usd"
        elif case == "missing_accepting":
            del venue.market["accepting_orders"]
        elif case == "missing_active":
            del venue.market["active"]
        elif case == "negative_risk":
            venue.market["neg_risk"] = True
        elif case == "missing_fee":
            del venue.fees["fd"]
        elif case == "unknown_fee":
            venue.fees["fd"]["newFormula"] = 1
        elif case == "fee_not_taker":
            venue.fees["fd"]["to"] = False
        else:
            market["outcomes"] = '["Up", "Up"]'
        async with venue.adapter() as data:
            await venue.emit()
            with pytest.raises(DataUnavailable):
                await data.snapshot()

    asyncio.run(scenario())


def test_listing_date_is_not_round_start_and_opposite_order_maps_labels() -> None:
    async def scenario() -> None:
        venue = Venue()
        raw = venue.event["markets"][0]
        raw["outcomes"] = json.dumps(list(reversed(json.loads(raw["outcomes"]))))
        raw["clobTokenIds"] = json.dumps(list(reversed(json.loads(raw["clobTokenIds"]))))
        async with venue.adapter() as data:
            await venue.emit()
            result = await data.snapshot()
            assert result.market.start_s == START
            assert result.market.up_token == fixture("book-up")["asset_id"]
            assert result.market.down_token == fixture("book-down")["asset_id"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case",
    [
        "source_stale",
        "source_future",
        "silent_clock_jump",
        "book_stale",
        "book_seconds",
        "book_microseconds",
        "wrong_book_token",
    ],
)
def test_freshness_uses_source_time_and_monotonic_receipt(case: str) -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            if case == "source_stale":
                venue.clock.ms += 3000
            elif case == "source_future":
                venue.clock.ms -= 10000
            elif case == "silent_clock_jump":
                venue.clock.elapsed += 7
                # Wall clock remains unchanged: source freshness alone would pass.
            else:
                for raw in venue.books.values():
                    if case == "book_stale":
                        raw["timestamp"] = str(venue.clock.ms - 6000)
                    elif case == "book_seconds":
                        raw["timestamp"] = str(venue.clock.ms // 1000)
                    elif case == "book_microseconds":
                        raw["timestamp"] = str(venue.clock.ms * 1000)
                    else:
                        raw["asset_id"] = "12345"
            with pytest.raises(DataUnavailable):
                await data.snapshot()

    asyncio.run(scenario())


def test_fee_tick_and_minimum_are_refetched_and_books_must_agree() -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            assert (await data.snapshot()).market.fee_rate == Decimal(".07")
            venue.fees["fd"]["r"] = "0.08"
            venue.fees["mts"] = "0.001"
            venue.market["minimum_tick_size"] = "0.001"
            venue.market["minimum_order_size"] = 6
            venue.fees["mos"] = 6
            for raw in venue.books.values():
                raw["tick_size"] = "0.001"
                raw["min_order_size"] = "6"
            result = await data.snapshot()
            assert (
                result.market.fee_rate,
                result.market.tick_size,
                result.market.min_order_size,
            ) == (Decimal(".08"), Decimal(".001"), Decimal("6"))
            venue.fees["mts"] = "0.01"
            with pytest.raises(DataUnavailable):
                await data.snapshot()

    asyncio.run(scenario())


def test_held_token_book_works_without_feeds_discovery_or_asks() -> None:
    async def scenario() -> None:
        venue = Venue()
        token = fixture("book-up")["asset_id"]
        venue.books[token]["asks"] = []
        venue.event["slug"] = "unavailable"
        async with venue.adapter() as data:
            result = await data.book(token)
            assert result.token_id == token
            assert result.bids and result.asks == ()
            with pytest.raises(DataUnavailable):
                await data.snapshot()
            assert (await data.book(token)).bids == result.bids

    asyncio.run(scenario())


def test_empty_asks_are_preserved_for_strategy_visible_skip() -> None:
    async def scenario() -> None:
        venue = Venue()
        for raw in venue.books.values():
            raw["asks"] = []
        async with venue.adapter() as data:
            await venue.emit()
            result = await data.snapshot()
            assert not result.up_book.asks and not result.down_book.asks
            assert evaluate(result, Config()).reason == "MISSING_BOOK_SIDE"

    asyncio.run(scenario())


def test_snapshot_satisfies_core_rule_contract_and_observations_are_json_serializable() -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            result = await data.snapshot()
            assert evaluate(result, Config()).reason == "ENTRY_WINDOW"
            json.dumps(venue.records)

    asyncio.run(scenario())


def test_delayed_final_metadata_survives_current_discovery_failure_and_is_not_inferred() -> None:
    async def scenario() -> None:
        venue = Venue()
        old_slug = venue.event["slug"]
        async with venue.adapter() as data:
            await venue.emit()
            await data.snapshot()
            assert not any(r["kind"] == "final_reference" for r in venue.records)
            venue.clock.ms += 600000
            venue.clock.elapsed += 600
            venue.events[old_slug]["eventMetadata"] = {
                "priceToBeat": "79697.53425227966",
                "finalPrice": "79700.12345678",
            }
            with pytest.raises(DataUnavailable):
                await data.snapshot()
            finals = [r for r in venue.records if r["kind"] == "final_reference"]
            assert len(finals) == 1
            assert finals[0]["slug"] == old_slug
            assert finals[0]["source_ms"] == (START + 300) * 1000
            assert finals[0]["price"] == "79700.12345678"
            venue.events[old_slug]["eventMetadata"] = None
            venue.clock.elapsed += 31
            with pytest.raises(DataUnavailable):
                await data.snapshot()
            assert len([r for r in venue.records if r["kind"] == "final_reference"]) == 1
            venue.clock.ms += 3600000
            venue.clock.elapsed += 3600
            with pytest.raises(DataUnavailable):
                await data.snapshot()
            assert any(
                r["kind"] == "reference_retired" and r["final_status"] == "official"
                for r in venue.records
            )

    asyncio.run(scenario())


def test_restored_history_keeps_timestamps_gaps_conflicts_and_requires_new_feed():
    async def scenario():
        venue = Venue()
        data = venue.adapter()
        now = venue.clock.ms
        point = {
            "kind": "spot",
            "source": "prices.crypto.chainlink",
            "source_ms": now - 1000,
            "received_ms": now - 500,
            "price": "80000",
        }
        count = data.restore_history(
            [
                point,
                {**point, "source_ms": now - 10000},
                {**point, "source_ms": now + 1},
                {"kind": "price_conflict", "stream": "spot", "source_ms": now - 10000},
            ]
        )
        assert count == 2
        assert data._points["spot"][now - 1000].received_ms == now - 500
        assert now - 10000 in data._conflicting_points["spot"]
        assert now - 5000 not in data._points["spot"]
        with pytest.raises(DataUnavailable, match="STREAM_SILENT"):
            data._latest("spot", now)
        await data.close()

    asyncio.run(scenario())


def test_unpublished_final_is_explicitly_missing_at_retirement() -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            await data.snapshot()
            venue.clock.ms += 4000000
            venue.clock.elapsed += 4000
            with pytest.raises(DataUnavailable):
                await data.snapshot()
            assert any(
                r["kind"] == "reference_retired" and r["final_status"] == "missing"
                for r in venue.records
            )
            assert not any(r["kind"] == "final_reference" for r in venue.records)

    asyncio.run(scenario())


def test_restarted_paper_holding_reloads_official_final_even_after_normal_retirement():
    async def scenario():
        first = Venue()
        async with first.adapter() as data:
            await first.emit()
            market = (await data.snapshot()).market
        resumed = Venue()
        resumed.clock.ms += 7200000
        resumed.clock.elapsed += 7200
        resumed.events[market.slug]["eventMetadata"] = {
            "priceToBeat": str(market.reference_price),
            "finalPrice": "79700.12345678",
        }
        async with resumed.adapter() as data:
            data.retain_markets((market,))
            assert data.final_reference(market) is None
            await data._poll_due()
            assert data.final_reference(market) == (
                market.reference_price,
                Decimal("79700.12345678"),
            )
            data.retain_markets(())
            data._retire_rounds()
            assert market.slug not in data._rounds

    asyncio.run(scenario())


def test_observer_failure_rejects_entries_but_does_not_block_held_book() -> None:
    async def scenario() -> None:
        venue = Venue()

        def failing_observer(record: dict[str, object]) -> None:
            raise OSError("disk full")

        data = MarketData(
            Config(),
            client=venue.client,
            http_client=venue.http,
            clock=venue.clock.wall,
            monotonic=venue.clock.mono,
            observer=failing_observer,
        )
        async with data:
            await venue.emit()
            with pytest.raises(DataUnavailable, match="OBSERVER_FAILED"):
                await data.snapshot()
            assert (await data.book(fixture("book-up")["asset_id"])).bids

    asyncio.run(scenario())


def test_raw_source_gap_remains_visible_in_strategy_warmup() -> None:
    async def scenario() -> None:
        venue = Venue()
        venue.clock.ms = START * 1000 + 180000
        for book in venue.books.values():
            book["timestamp"] = str(venue.clock.ms - 1000)
        async with venue.adapter() as data:
            # Synthetic chronological SDK stream with a 65-second outage inside
            # the otherwise complete 30-minute warm-up. No adapter internals injected.
            template = next(
                r["event"]
                for r in fixture("boundary-events")
                if not r["event"]["topic"].endswith(".twap")
            )
            end = venue.clock.ms
            for offset in range(-1800000, 1, 5000):
                if -300000 < offset < -235000:
                    continue
                raw = copy.deepcopy(template)
                raw["payload"]["timestamp"] = end + offset
                raw["payload"]["value"] = str(Decimal("79700") + Decimal(offset % 17000) / 1000)
                venue.client.spot.queue.put_nowait(CryptoPricesChainlinkEvent.model_validate(raw))
            twap = next(
                r["event"]
                for r in fixture("boundary-events")
                if r["event"]["topic"].endswith(".twap")
            )
            twap["payload"]["timestamp"] = end
            venue.client.twap.queue.put_nowait(CryptoPricesChainlinkTwapEvent.model_validate(twap))
            venue.event["eventMetadata"] = {"priceToBeat": "79697.53425227966"}
            for _ in range(30):
                await settle()
            result = await data.snapshot()
            gaps = [
                b.timestamp_ms - a.timestamp_ms
                for a, b in zip(result.history, result.history[1:], strict=False)
            ]
            assert max(gaps) == 65000
            assert len(result.history) == 349
            decision = evaluate(result, Config())
            assert decision.reason == "INSUFFICIENT_HISTORY"
            assert decision.features["short_sampling_status"] == "INSUFFICIENT_COVERAGE"
            assert decision.features["long_sampling_status"] == "VALID"
            assert decision.features["long_irregular_seconds"] == 65

    asyncio.run(scenario())


def test_duplicate_conflicting_boundary_halts_round_even_after_valid_official_metadata() -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            await data.snapshot()
            raw = next(
                r["event"]
                for r in fixture("boundary-events")
                if r["event"]["topic"].endswith(".twap")
                and r["event"]["payload"]["timestamp"] == 1788709200000
            )
            raw["payload"]["timestamp"] = START * 1000
            raw["payload"]["value"] = "1"
            venue.client.twap.queue.put_nowait(CryptoPricesChainlinkTwapEvent.model_validate(raw))
            await settle()
            venue.event["eventMetadata"] = {"priceToBeat": "79697.53425227966"}
            with pytest.raises(DataUnavailable, match="PRICE_CONFLICT"):
                await data.snapshot()
            assert any(r["kind"] == "anchor" and r["status"] == "conflict" for r in venue.records)

    asyncio.run(scenario())


def test_official_probe_metadata_verifies_discriminating_boundary() -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            before = await data.snapshot()
            assert before.market.reference_price == ANCHOR
            # Only metadata is transplanted; the originating 15:40 event is retained
            # as an external fixture so its rounded JSON number is independent.
            venue.event["eventMetadata"] = fixture("official-after-boundary")["eventMetadata"]
            after = await data.snapshot()
            assert after.market.reference_status == "official"
            assert after.market.reference_price == Decimal("79697.53425227966")

    asyncio.run(scenario())


def test_independent_book_finishes_while_current_discovery_is_blocked() -> None:
    async def scenario() -> None:
        venue = Venue()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def delayed(request: httpx.Request) -> httpx.Response:
            entered.set()
            await release.wait()
            return venue.request(request)

        await venue.http.aclose()
        venue.http = httpx.AsyncClient(transport=httpx.MockTransport(delayed))
        async with venue.adapter() as data:
            task = asyncio.create_task(data.snapshot())
            await asyncio.wait_for(entered.wait(), 0.2)
            held = await asyncio.wait_for(data.book(fixture("book-up")["asset_id"]), 0.2)
            assert held.bids
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())


def test_external_http_and_book_hangs_have_deadlines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("btc5m.market_data.HTTP_TIMEOUT", 0.02)

    async def scenario() -> None:
        venue = Venue()

        async def hang_http(request: httpx.Request) -> httpx.Response:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def hang_book(*, token_id: str) -> OrderBook:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        await venue.http.aclose()
        venue.http = httpx.AsyncClient(transport=httpx.MockTransport(hang_http))
        monkeypatch.setattr(venue.client, "get_order_book", hang_book)
        async with venue.adapter() as data:
            with pytest.raises(DataUnavailable, match="HTTP_UNAVAILABLE"):
                await asyncio.wait_for(data.snapshot(), 0.2)
            with pytest.raises(DataUnavailable, match="BOOK_UNAVAILABLE"):
                await asyncio.wait_for(data.book(fixture("book-up")["asset_id"]), 0.2)

    asyncio.run(scenario())


def test_invalid_discovery_records_raw_provenance_for_diagnosis() -> None:
    async def scenario() -> None:
        venue = Venue()
        venue.event["markets"][0]["eventStartTime"] = None
        async with venue.adapter() as data:
            with pytest.raises(DataUnavailable):
                await data.snapshot()
            discovery = [r for r in venue.records if r["kind"] == "discovery"]
            assert len(discovery) == 1
            raw_event = discovery[0]["raw_event"]
            provenance = discovery[0]["provenance"]
            assert isinstance(raw_event, dict) and isinstance(provenance, str)
            assert raw_event["markets"][0]["eventStartTime"] is None
            assert "include_chat=false" in provenance

    asyncio.run(scenario())


def test_closed_adapter_never_starts_new_feed_or_book() -> None:
    async def scenario() -> None:
        venue = Venue()
        data = venue.adapter()
        await data.close()
        await data.close()
        with pytest.raises(DataUnavailable, match="CLOSED"):
            await data.book(fixture("book-up")["asset_id"])
        with pytest.raises(DataUnavailable, match="INVALID_LIFECYCLE"):
            await data.__aenter__()

    asyncio.run(scenario())


def test_round_retention_is_bounded_during_discovery_not_only_next_poll() -> None:
    async def scenario() -> None:
        venue = Venue()
        first_slug = venue.event["slug"]
        async with venue.adapter() as data:
            for index in range(13):
                start = START + index * 300
                slug = f"btc-updown-5m-{start}"
                raw = copy.deepcopy(fixture("gamma-event"))
                raw["slug"] = raw["markets"][0]["slug"] = slug
                raw["startTime"] = raw["markets"][0]["eventStartTime"] = datetime.fromtimestamp(
                    start, UTC
                ).isoformat()
                raw["endDate"] = raw["markets"][0]["endDate"] = datetime.fromtimestamp(
                    start + 300, UTC
                ).isoformat()
                venue.events[slug] = raw
                venue.event = raw
                venue.market["market_slug"] = slug
                venue.clock.ms = start * 1000 + 4000
                venue.clock.elapsed += 300
                for book in venue.books.values():
                    book["timestamp"] = str(venue.clock.ms - 1000)
                with pytest.raises(DataUnavailable):
                    await data.snapshot()
            assert any(
                r["kind"] == "reference_retired" and r["slug"] == first_slug for r in venue.records
            )

    asyncio.run(scenario())


def test_history_has_a_hard_point_bound_even_on_unexpected_subsecond_feed() -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            template = next(
                r["event"]
                for r in fixture("boundary-events")
                if not r["event"]["topic"].endswith(".twap")
            )
            for offset in range(5000):
                raw = copy.deepcopy(template)
                raw["payload"]["timestamp"] = venue.clock.ms - 6000 + offset
                venue.client.spot.queue.put_nowait(CryptoPricesChainlinkEvent.model_validate(raw))
            twap = next(
                r["event"]
                for r in fixture("boundary-events")
                if r["event"]["topic"].endswith(".twap")
            )
            twap["payload"]["timestamp"] = venue.clock.ms - 1000
            venue.client.twap.queue.put_nowait(CryptoPricesChainlinkTwapEvent.model_validate(twap))
            await settle()
            result = await data.snapshot()
            assert len(result.history) <= 3820
            assert result.history[-1].timestamp_ms == venue.clock.ms - 1001
            assert len(set(p.timestamp_ms for p in result.history)) == len(result.history)

    asyncio.run(scenario())


def test_stream_disconnect_then_resume_preserves_actual_source_gap() -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            before = await data.snapshot()
            venue.client.spot.queue.put_nowait(ConnectionError("synthetic read failure"))
            await settle()
            with pytest.raises(DataUnavailable, match="STREAM_SILENT"):
                await data.snapshot()
            assert (await data.book(before.market.up_token)).bids
            venue.clock.ms += 5000
            venue.clock.elapsed += 5
            for book in venue.books.values():
                book["timestamp"] = str(venue.clock.ms - 1000)
            for row in fixture("boundary-events")[-2:]:
                raw = copy.deepcopy(row["event"])
                raw["payload"]["timestamp"] = venue.clock.ms - 1000
                if raw["topic"].endswith(".twap"):
                    venue.client.twap.queue.put_nowait(
                        CryptoPricesChainlinkTwapEvent.model_validate(raw)
                    )
                else:
                    venue.client.spot.queue.put_nowait(
                        CryptoPricesChainlinkEvent.model_validate(raw)
                    )
            await asyncio.sleep(1.05)
            await settle()
            after = await data.snapshot()
            assert len(after.history) == len(before.history) + 1
            assert after.history[-1].timestamp_ms - before.history[-1].timestamp_ms == 7000
            assert any(r["kind"] == "stream_unavailable" for r in venue.records)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "token",
    ["", "-1", "0", "abc", str(2**256), "1" * 5000],
    ids=["empty", "negative", "zero", "nonnumeric", "uint256_overflow", "huge_integer"],
)
def test_invalid_held_token_is_a_data_outcome_without_external_io(token: str) -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            with pytest.raises(DataUnavailable, match="INVALID_TOKEN"):
                await data.book(token)

    asyncio.run(scenario())


def test_delayed_official_rule_change_cannot_supply_calibration_label() -> None:
    async def scenario() -> None:
        venue = Venue()
        async with venue.adapter() as data:
            await venue.emit()
            await data.snapshot()
            venue.clock.ms += 600000
            venue.clock.elapsed += 600
            venue.event["description"] = "This market now resolves from spot price."
            venue.event["eventMetadata"] = {"finalPrice": "79700"}
            with pytest.raises(DataUnavailable):
                await data.snapshot()
            assert not any(r["kind"] == "final_reference" for r in venue.records)
            assert any(
                r["kind"] == "metadata_unavailable" and r["code"] == "UNSUPPORTED_RULE"
                for r in venue.records
            )

    asyncio.run(scenario())


async def advance_fixture_feeds(venue: Venue, milliseconds: int) -> None:
    """Advance only the external clock/SDK payloads, preserving real adapter state."""
    venue.clock.ms += milliseconds
    venue.clock.elapsed += milliseconds / 1000
    for book in venue.books.values():
        book["timestamp"] = str(venue.clock.ms - 1000)
    for row in fixture("boundary-events")[-2:]:
        raw = copy.deepcopy(row["event"])
        raw["payload"]["timestamp"] = venue.clock.ms - 1000
        if raw["topic"].endswith(".twap"):
            venue.client.twap.queue.put_nowait(CryptoPricesChainlinkTwapEvent.model_validate(raw))
        else:
            venue.client.spot.queue.put_nowait(CryptoPricesChainlinkEvent.model_validate(raw))
    await settle()


@pytest.mark.parametrize(
    "advance_ms,book_age_ms,expected_code",
    [
        (1000, 1000, None),
        (4000, 1000, "STALE_DATA"),
        (2000, 4000, "STALE_DATA"),
        (297000, 1000, "ROUND_CHANGED"),
    ],
    ids=[
        "returned_time_advances",
        "price_ages_during_metadata",
        "book_ages_during_metadata",
        "round_changes_during_metadata",
    ],
)
def test_explicit_snapshot_time_advances_during_metadata(
    advance_ms: int,
    book_age_ms: int,
    expected_code: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        venue = Venue()
        initial = venue.clock.ms
        finished_books = asyncio.Event()
        completed = 0
        original_book = venue.client.get_order_book

        async def read_book(*, token_id: str) -> OrderBook:
            nonlocal completed
            result = await original_book(token_id=token_id)
            completed += 1
            if completed == 2:
                finished_books.set()
            return result

        async def delayed_metadata(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/clob-markets/"):
                await finished_books.wait()
                venue.clock.ms += advance_ms
                venue.clock.elapsed += advance_ms / 1000
            return venue.request(request)

        monkeypatch.setattr(venue.client, "get_order_book", read_book)
        await venue.http.aclose()
        venue.http = httpx.AsyncClient(transport=httpx.MockTransport(delayed_metadata))
        for raw in venue.books.values():
            raw["timestamp"] = str(initial - book_age_ms)
        async with venue.adapter() as data:
            await venue.emit()
            if expected_code is not None:
                with pytest.raises(DataUnavailable, match=expected_code):
                    await data.snapshot(now_ms=initial)
            else:
                result = await data.snapshot(now_ms=initial)
                assert result.now_ms == initial + advance_ms
                assert result.now_ms - result.spot.timestamp_ms == 4000

    asyncio.run(scenario())


@pytest.mark.parametrize("target", ["event", "market"])
@pytest.mark.parametrize("field", ["description", "resolutionSource"])
def test_delayed_current_rule_conflict_survives_cached_supported_discovery(
    target: str,
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        venue = Venue()
        delayed = copy.deepcopy(venue.event)

        async def get_event(*, slug: str, include_chat: bool) -> Event:
            assert slug == delayed["slug"] and include_chat is False
            return Event.model_validate(delayed)

        monkeypatch.setattr(venue.client, "get_event", get_event)
        async with venue.adapter() as data:
            await venue.emit()
            assert (await data.snapshot()).market.reference_status == "boundary"
            candidate = delayed if target == "event" else delayed["markets"][0]
            candidate[field] = "unsupported spot settlement rule"
            await advance_fixture_feeds(venue, 31000)
            result = await data.snapshot()
            assert result.market.reference_status == "conflict"
            assert evaluate(result, Config()).reason == "REFERENCE_CONFLICT"
            assert any(
                r["kind"] == "metadata_unavailable" and r["code"] == "UNSUPPORTED_RULE"
                for r in venue.records
            )
            # Both subsequent raw and SDK cached supported copies cannot undo
            # incompatible official evidence already observed for this identity.
            delayed.clear()
            delayed.update(copy.deepcopy(venue.event))
            await advance_fixture_feeds(venue, 31000)
            assert (await data.snapshot()).market.reference_status == "conflict"
            assert any(
                r["kind"] == "anchor"
                and r["status"] == "conflict"
                and "SDK get_event" in str(r["provenance"])
                for r in venue.records
            )
            assert (await data.book(result.market.up_token)).bids

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["network_error", "missing_optional_anchor"])
def test_delayed_current_metadata_unavailability_remains_retryable(
    outcome: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        venue = Venue()

        async def get_event(*, slug: str, include_chat: bool) -> Event:
            if outcome == "network_error":
                raise ConnectionError("synthetic read failure")
            raw = copy.deepcopy(venue.event)
            raw["eventMetadata"] = None
            return Event.model_validate(raw)

        monkeypatch.setattr(venue.client, "get_event", get_event)
        async with venue.adapter() as data:
            await venue.emit()
            await data.snapshot()
            await advance_fixture_feeds(venue, 31000)
            assert (await data.snapshot()).market.reference_status == "boundary"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case,field,expected,actual",
    [
        ("book_tick", "tick_size", ".01", ".001"),
        ("book_minimum", "min_order_size", "5", "6"),
        ("book_condition", "condition_id", None, "0x" + "ab" * 32),
        ("flags_tick", "tick_size", ".01", ".001"),
        ("flags_minimum", "min_order_size", "5", "6"),
        ("unsupported_tick", "tick_size", None, ".02"),
    ],
)
def test_rejected_metadata_public_diagnostic_survives_ledger(
    tmp_path, case, field, expected, actual
):
    from btc5m.ledger import Ledger

    async def run():
        venue = Venue()
        ledger = Ledger(tmp_path / "observe.sqlite", "0x" + "00" * 20)
        first = next(iter(venue.books.values()))
        if case == "book_tick":
            first["tick_size"] = actual
        elif case == "book_minimum":
            first["min_order_size"] = actual
        elif case == "book_condition":
            first["market"] = actual
        elif case == "flags_tick":
            venue.market["minimum_tick_size"] = actual
        elif case == "flags_minimum":
            venue.market["minimum_order_size"] = actual
        else:
            venue.fees["mts"] = actual
        data = MarketData(
            Config(),
            client=venue.client,
            http_client=venue.http,
            clock=venue.clock.wall,
            monotonic=venue.clock.mono,
            observer=ledger.record_observation,
        )
        async with data:
            await venue.emit()
            with pytest.raises(DataUnavailable, match="^TRADING_METADATA_CHANGED$"):
                await data.snapshot()
        rows = [r for r in ledger.observations() if r["kind"] == "metadata_rejected"]
        assert rows and rows[0]["compared_field"] == field
        row = rows[0]
        assert (
            row["slug"] == venue.event["slug"]
            and row["condition_id"] == venue.market["condition_id"]
        )
        assert (
            row["endpoint"] and row["actual"] == str(Decimal(actual))
            if field != "condition_id"
            else row["actual"] == actual
        )
        if case == "unsupported_tick":
            assert set(row["supported_ticks"]) == {
                "0.1",
                "0.01",
                "0.005",
                "0.001",
                "0.0025",
                "0.0001",
            }
        elif field == "condition_id":
            assert row["expected"] == venue.market["condition_id"]
        else:
            assert Decimal(row["expected"]) == Decimal(expected)
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize("first", ["unsupported_tick", "flags_tick"])
def test_metadata_diagnostic_preserves_first_rejection_before_later_bad_field(first):
    async def run():
        venue = Venue()
        if first == "unsupported_tick":
            venue.fees["mts"] = ".02"
            venue.market["minimum_tick_size"] = None
        else:
            venue.market["minimum_tick_size"] = ".001"
            venue.market["minimum_order_size"] = None
        async with venue.adapter() as data:
            with pytest.raises(DataUnavailable, match="^TRADING_METADATA_CHANGED$"):
                await data.snapshot()
        assert any(
            row["kind"] == "metadata_rejected" and row["compared_field"] == "tick_size"
            for row in venue.records
        )

    asyncio.run(run())


@pytest.mark.parametrize("resume", [True, False])
def test_stale_prices_pause_entries_without_immediate_transport_reconnect(monkeypatch, resume):
    async def scenario():
        venue = Venue()
        closed = []

        async def close():
            closed.append(True)

        venue.client.spot.close = close
        venue.client.twap.close = close
        original_timeout = asyncio.timeout
        # Keep the actual cancellation boundary; scale monotonic waits for a fast fixture.
        monkeypatch.setattr(asyncio, "timeout", lambda delay: original_timeout(delay / 100))
        async with venue.adapter() as data:
            await venue.emit()
            before = await data.snapshot()
            venue.clock.ms += 6000
            venue.clock.elapsed += 6
            for book in venue.books.values():
                book["timestamp"] = str(venue.clock.ms - 1000)
            await asyncio.sleep(0.065)
            with pytest.raises(DataUnavailable, match="STREAM_SILENT"):
                await data.snapshot()
            assert not closed
            if resume:
                await advance_fixture_feeds(venue, 0)
                after = await data.snapshot()
                assert not closed
                assert len(after.history) == len(before.history) + 1
                assert after.history[-1].timestamp_ms > before.history[-1].timestamp_ms
            else:
                await asyncio.sleep(0.105)
                assert len(closed) == 2
                assert any(r["kind"] == "stream_unavailable" for r in venue.records)

    asyncio.run(scenario())
