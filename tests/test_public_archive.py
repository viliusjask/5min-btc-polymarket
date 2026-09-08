"""Public message history survives missing trading inputs without changing replay decisions."""

import asyncio
import json
import time
from contextlib import closing

import pytest
from polymarket.models.rtds_events import CryptoPricesChainlinkEvent, CryptoPricesChainlinkTwapEvent
from test_market_data import Venue
from test_streams import NOW, book

from btc5m.config import Config
from btc5m.lab_tape import Tape, TapeError
from btc5m.ledger import Ledger
from btc5m.market_data import MarketData
from btc5m.public_archive import PublicArchive
from btc5m.streams import PublicStreams, StreamError


@pytest.mark.parametrize("kind", ["spot", "twap60"])
def test_exact_oracle_survives_rejected_snapshot_and_persists_source_provenance(tmp_path, kind):
    async def run():
        venue = Venue()
        data = MarketData(
            Config(),
            client=venue.client,
            http_client=venue.http,
            clock=venue.clock.wall,
            observer=venue.records.append,
            capture_archive=True,
        )
        try:
            raw = {
                "type": "update",
                "timestamp": venue.clock.ms,
                "payload": {
                    "symbol": "btc/usd",
                    "timestamp": venue.clock.ms - 100,
                    "value": "79876.123456789012345678",
                },
            }
            if kind == "twap60":
                raw["payload"]["window_s"] = 60
                raw["payload"]["full_accuracy_value"] = "79876123456789012345678"
                raw["payload"]["value"] = "79876.12"
            model = CryptoPricesChainlinkEvent if kind == "spot" else CryptoPricesChainlinkTwapEvent
            data._ingest(kind, model.model_validate(raw))
            assert data.current_snapshot() is None
            archive = data.archive.drain()
            point = next(x for x in archive["events"] if x["kind"] == kind)
            assert point["price"] == "79876.123456789012345678"
            assert point["source_ms"] == venue.clock.ms - 100
            assert point["received_ms"] == venue.clock.ms
            assert point["envelope_ms"] == venue.clock.ms
            assert point["symbol"] == "btc/usd"
            assert point["window_seconds"] == (60 if kind == "twap60" else None)
            with closing(
                Ledger(tmp_path / "observations.sqlite", "0x" + "0" * 40, environment="paper")
            ) as ledger:
                ledger.record_observation(venue.records[-1])
                persisted = ledger.observations()[-1]
                assert persisted["price"] == point["price"]
                assert persisted["envelope_ms"] == point["envelope_ms"]
                assert persisted["symbol"] == "btc/usd"
            with Tape(tmp_path / "capture.sqlite") as tape:
                tape.append(venue.clock.ms, None, code="MISSING_MARKET", archive=archive)
                frame = next(tape.read_after(0))
                assert frame.snapshot is None and frame.code == "MISSING_MARKET"
                assert frame.archive == archive
        finally:
            await data.close()

    asyncio.run(run())


def test_wire_messages_keep_intermediate_books_hashes_and_invalid_delta():
    archive = PublicArchive()
    feed = PublicStreams(Config(), clock=lambda: NOW / 1000, archive=archive.record)
    feed.tokens, feed.condition_id = ("up", "down"), "condition"
    feed.ingest_market({**book(), "hash": "first"})
    delta = {
        "event_type": "price_change",
        "market": "condition",
        "timestamp": str(NOW),
        "price_changes": [
            {"asset_id": "up", "side": "BUY", "price": ".40", "size": "0", "hash": "second"}
        ],
    }
    feed.ingest_market(delta)
    with pytest.raises(StreamError, match="BOOK_SIDE"):
        feed.ingest_market(
            {**delta, "price_changes": [{**delta["price_changes"][0], "side": "invalid"}]}
        )
    feed.invalidate_market("TEST_GAP")
    rows = archive.drain()["events"]
    assert rows[0]["payload"]["hash"] == "first"
    assert rows[1]["payload"] == delta
    assert rows[2]["payload"]["price_changes"][0]["side"] == "invalid"
    assert rows[-1]["code"] == "TEST_GAP"
    assert [x["sequence"] for x in rows] == [1, 2, 3, 4]
    assert rows[0]["session_id"] == rows[-1]["session_id"] == feed.session_id
    assert rows[-1]["generation"] == rows[0]["generation"] + 1
    delta["price_changes"][0]["size"] = "999"
    assert rows[1]["payload"]["price_changes"][0]["size"] == "0"


def test_archive_buffer_bounds_bytes_and_records_dropped_sequence_range():
    archive = PublicArchive(max_bytes=600, max_records=4)
    archive.record({"kind": "small", "received_ms": NOW, "payload": "small"})
    for i in range(5):
        archive.record({"kind": "huge", "received_ms": NOW + i, "payload": "x" * 1000})
    archive.record({"kind": "small", "received_ms": NOW + 5})
    assert archive.buffered_bytes <= 600
    frame = archive.drain()
    assert len(frame["events"]) == 1
    assert frame["gap"]["dropped_records"] == 6
    assert frame["gap"]["first_sequence"] == 2
    assert frame["gap"]["last_sequence"] == 7
    archive.record({"kind": "small", "received_ms": NOW + 6})
    assert archive.drain()["events"][0]["sequence"] == 8
    assert archive.buffered_bytes == 0
    bounded_count = PublicArchive(max_records=1)
    for _ in range(2):
        bounded_count.record({"kind": "tick", "received_ms": NOW})
    assert bounded_count.drain()["gap"]["dropped_records"] == 1


def test_capture_session_is_additive_and_future_archive_receipts_fail(tmp_path):
    path = tmp_path / "capture.sqlite"
    with Tape(path) as tape:
        tape.append(NOW, None, code="OLD")
        before = tape.db.execute("SELECT payload,checksum FROM frames WHERE id=1").fetchone()
        identity = tape.identity
        first = tape.start_capture(Config(), now_ms=NOW + 1, capture_flow=True)
        tape.append(NOW + 1, None, archive={"version": 1, "session_id": first, "events": []})
        with pytest.raises(TapeError, match="FUTURE_RECEIPT"):
            tape.append(NOW + 2, None, archive={"events": [{"received_ms": NOW + 3}]})
        tape.append(
            NOW + 2,
            None,
            archive={
                "events": [
                    {"received_ms": NOW + 2, "payload": {"received_ms": "invalid source claim"}}
                ]
            },
        )
    with Tape(path) as tape:
        second = tape.start_capture(Config(), now_ms=NOW + 2, capture_flow=False)
        assert second != first and tape.identity == identity
        assert tape.db.execute("SELECT value FROM meta WHERE key='version'").fetchone() == ("1",)
        assert (
            tape.db.execute("SELECT payload,checksum FROM frames WHERE id=1").fetchone() == before
        )
        sessions = [
            json.loads(row[0])
            for row in tape.db.execute("SELECT data FROM capture_sessions ORDER BY started_ms")
        ]
        assert sessions[0]["config_fingerprint"] == Config().fingerprint
        assert sessions[0]["source_hashes"]["market_data.py"]
        assert sessions[0]["semantics"]["book_sequence"] == "local_receipt_order_not_exchange_queue"
        assert sessions[1]["capture_flow"] is False
        assert list(tape.read_after(0))[0].archive is None


def test_metadata_archive_keeps_rule_fee_and_book_headers_not_unrelated_payload():
    async def run():
        venue = Venue()
        venue.event["unrelated_chat"] = "do not retain"
        data = MarketData(
            Config(),
            client=venue.client,
            http_client=venue.http,
            clock=venue.clock.wall,
            monotonic=venue.clock.mono,
            capture_archive=True,
        )
        try:
            await data._refresh_market(venue.clock.ms)
            rows = data.archive.drain()["events"]
            metadata = [x for x in rows if x["kind"] == "public_metadata"]
            assert any(
                x["payload"].get("description") == venue.event["description"] for x in metadata
            )
            assert any(
                x["payload"].get("fd") == {**venue.fees["fd"], "r": str(venue.fees["fd"]["r"])}
                for x in metadata
            )
            assert any("tick_size" in x["payload"] for x in metadata)
            assert "unrelated_chat" not in json.dumps(rows)
        finally:
            await data.close()

    asyncio.run(run())


def test_default_paper_collector_flushes_shutdown_tail_without_a_tradable_snapshot(
    tmp_path, monkeypatch
):
    from test_comparison import AnonymousData

    from btc5m import cli, comparison

    class Source(AnonymousData):
        async def __aenter__(self):
            assert self.archive is not None
            self.archive.record({"kind": "start_tick", "received_ms": int(time.time() * 1000)})
            return self

        async def close(self):
            self.archive.record({"kind": "last_tick", "received_ms": int(time.time() * 1000)})

    monkeypatch.setattr(comparison, "MarketData", Source)
    args = cli.parse_args(["paper", "--duration", ".01", "--runtime", str(tmp_path)])
    assert asyncio.run(comparison.run_paper(args, Config(), lambda record: None)) == 0
    with Tape(tmp_path / "capture.sqlite", readonly=True) as tape:
        frames = list(tape.read_after(0))
        assert all(frame.snapshot is None for frame in frames)
        events = [event for frame in frames for event in frame.archive["events"]]
        assert [x["kind"] for x in events] == ["start_tick", "last_tick"]
        assert frames[-1].code == "COLLECTOR_STOPPED"
        session = tape.db.execute("SELECT id FROM capture_sessions").fetchone()[0]
        assert all(frame.archive["session_id"] == session for frame in frames)


def test_binance_archive_preserves_multiple_ticks_inside_the_sampling_bucket():
    archive = PublicArchive()
    feed = PublicStreams(Config(), clock=lambda: NOW / 1000, archive=archive.record)
    for ident, stamp, price in ((1, NOW - 20, "79000.001"), (2, NOW - 10, "79000.002")):
        feed.ingest_exchange(
            {
                "e": "aggTrade",
                "s": "BTCUSDT",
                "a": ident,
                "T": stamp,
                "E": stamp + 5,
                "p": price,
                "q": "0.000001",
                "m": False,
            }
        )
    assert len(feed.exchange_history) == 1
    events = archive.drain()["events"]
    assert [event["payload"]["p"] for event in events] == ["79000.001", "79000.002"]
    assert [event["payload"]["a"] for event in events] == [1, 2]


@pytest.mark.parametrize("stream", ["market", "exchange"])
def test_malformed_provider_timestamp_cannot_poison_the_archive_receipt_envelope(tmp_path, stream):
    archive = PublicArchive()
    feed = PublicStreams(Config(), clock=lambda: NOW / 1000, archive=archive.record)
    feed.tokens, feed.condition_id = ("up", "down"), "condition"
    malformed = {"received_ms": "bad provider field"}
    event = (
        {**book(), "timestamp": malformed}
        if stream == "market"
        else {"e": "aggTrade", "s": "BTCUSDT", "T": malformed, "p": "79000", "a": 1}
    )
    with pytest.raises(StreamError, match="INVALID_TIMESTAMP"):
        (feed.ingest_market if stream == "market" else feed.ingest_exchange)(event)
    feed.invalidate_market("BOOK_STREAM_DISCONNECTED")
    batch = archive.drain()
    assert batch["events"][0]["source_ms"] is None
    key = "timestamp" if stream == "market" else "T"
    assert batch["events"][0]["payload"][key] == malformed
    with Tape(tmp_path / "capture.sqlite") as tape:
        tape.append(NOW, None, archive=batch)
        assert next(tape.read_after(0)).archive == batch


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_public_field_records_archive_gap_without_changing_book_eligibility(
    tmp_path, invalid
):
    archive = PublicArchive()
    feed = PublicStreams(Config(), clock=lambda: NOW / 1000, archive=archive.record)
    feed.tokens, feed.condition_id = ("up", "down"), "condition"
    feed.ingest_market({**book(), "fee_rate_bps": invalid})
    assert feed.books["up"].asks[0].price == 0.5
    batch = archive.drain()
    assert batch["events"] == []
    assert batch["gap"]["code"] == "ARCHIVE_SERIALIZATION_FAILED"
    assert batch["gap"]["first_sequence"] == batch["gap"]["last_sequence"] == 1
    assert batch["gap"]["dropped_records"] == 1
    with Tape(tmp_path / "capture.sqlite") as tape:
        tape.append(NOW, None, archive=batch)
        feed.ingest_market(book())
        recovery = archive.drain()
        assert recovery["events"][0]["sequence"] == 2
        assert recovery["gap"] is None
        tape.append(NOW, None, archive=recovery)
        assert [frame.archive for frame in tape.read_after(0)] == [batch, recovery]
