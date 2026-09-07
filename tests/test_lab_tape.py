from dataclasses import replace
from decimal import Decimal

import pytest
from test_strategy import make_snapshot

from btc5m.lab_tape import Tape, TapeError


def test_exact_snapshots_deduplicated_prices_and_asof_labels(tmp_path):
    path = tmp_path / "capture.sqlite"
    snap = make_snapshot()
    with Tape(path) as tape:
        first = tape.append(snap.now_ms, snap)
        tick_count = tape.db.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        second = tape.append(snap.now_ms + 500, replace(snap, now_ms=snap.now_ms + 500))
        assert tape.db.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == tick_count
        final_ms = snap.market.end_s * 1000 + 1000
        final = tape.append(
            final_ms,
            None,
            labels={
                snap.market.slug: {
                    "condition_id": snap.market.condition_id,
                    "opening": str(snap.market.reference_price),
                    "final": "100001",
                }
            },
        )
    with Tape(path, readonly=True) as tape:
        frames = list(tape.read_after(0))
        assert [f.ident for f in frames] == [first, second, final]
        assert frames[0].snapshot == snap
        assert frames[0].labels == {}
        assert frames[-1].labels[snap.market.slug]["final"] == "100001"
        assert frames[-1].snapshot is None


def test_tape_conflicting_label_invalidates_without_rewriting_history(tmp_path):
    snap = make_snapshot()
    label = {"condition_id": snap.market.condition_id, "opening": "100000", "final": "100001"}
    with Tape(tmp_path / "capture.sqlite") as tape:
        tape.append(snap.now_ms, snap)
        tape.append(snap.market.end_s * 1000 + 1, None, labels={snap.market.slug: label})
        tape.append(snap.market.end_s * 1000 + 2, None, labels={snap.market.slug: None})
        frames = list(tape.read_after(0))
        assert frames[-2].labels[snap.market.slug] == label
        assert frames[-1].labels[snap.market.slug] is None


def test_tape_rejects_time_reversal_and_detects_payload_corruption(tmp_path):
    snap = make_snapshot()
    with Tape(tmp_path / "capture.sqlite") as tape:
        tape.append(snap.now_ms, snap)
        with pytest.raises(TapeError, match="CLOCK"):
            tape.append(snap.now_ms - 1, snap)
        with tape.db:
            tape.db.execute("UPDATE frames SET payload=?", (b"broken",))
        with pytest.raises(TapeError, match="CORRUPT"):
            list(tape.read_after(0))


def test_future_receipt_is_not_replayed_as_already_known(tmp_path):
    snap = make_snapshot()
    snap = replace(
        snap, spot=replace(snap.spot, received_ms=snap.now_ms + 1, price=Decimal(100000))
    )
    with Tape(tmp_path / "capture.sqlite") as tape:
        with pytest.raises(TapeError, match="FUTURE_RECEIPT"):
            tape.append(snap.now_ms, snap)


def test_optional_research_inputs_round_trip_and_reject_future_receipts(tmp_path):
    snap = make_snapshot()
    data = {
        "version": 1,
        "exchange": {"trades": [{"received_ms": snap.now_ms, "quantity": "2", "sell": True}]},
    }
    with Tape(tmp_path / "capture.sqlite") as tape:
        tape.append(snap.now_ms, snap, research=data)
        tape.append(snap.now_ms + 1, None)
        frames = list(tape.read_after(0))
        assert frames[0].research == data
        assert frames[1].research is None
        with pytest.raises(TapeError, match="FUTURE_RECEIPT"):
            tape.append(snap.now_ms + 1, None, research={"received_ms": snap.now_ms + 2})


def test_unresolved_market_is_retained_across_long_outage_until_official_label(tmp_path):
    path = tmp_path / "capture.sqlite"
    snap = make_snapshot()
    with Tape(path) as tape:
        tape.append(snap.now_ms, snap)
        tape.append(snap.market.end_s * 1000 + 7200000, None)
        assert snap.market.slug in tape.known_markets
    with Tape(path) as tape:
        assert tape.known_markets[snap.market.slug] == snap.market
        tape.append(
            tape.last_ms + 1,
            None,
            labels={
                snap.market.slug: {
                    "condition_id": snap.market.condition_id,
                    "opening": str(snap.market.reference_price),
                    "final": "80500",
                }
            },
        )
        assert snap.market.slug not in tape.known_markets


def test_label_backlog_rotates_within_adapter_limit_and_keeps_original_holdings(tmp_path):
    market = make_snapshot().market
    with Tape(tmp_path / "capture.sqlite") as tape:
        tape.known_markets = {str(i): replace(market, slug=str(i)) for i in range(19)}
        held = (replace(market, slug="baseline-held"),)
        visited = set()
        for slot in range(19):
            selected = tape.retained_markets(held, slot * 30000)
            assert len(selected) <= 6
            assert selected[0] == held[0]
            visited.update(m.slug for m in selected)
        assert visited == {*tape.known_markets, "baseline-held"}


def test_capture_diagnostics_separate_unavailable_spans_from_delays_and_survive_restart(tmp_path):
    import json

    path = tmp_path / "capture.sqlite"
    snap = make_snapshot()
    t = snap.now_ms
    with Tape(path) as tape:
        legacy = tape.append(t, None)  # old causes cannot be recovered or reclassified
        first = tape.append(
            t + 500, replace(snap, now_ms=t + 500), diagnostic={"code": "CAPTURED"}, max_gap_ms=5000
        )
        tape.append(
            t + 1000, None, diagnostic={"code": "STALE_DATA", "component": "spot"}, max_gap_ms=5000
        )
        tape.append(
            t + 1500, None, diagnostic={"code": "STALE_DATA", "component": "spot"}, max_gap_ms=5000
        )
    with Tape(path) as tape:
        tape.append(
            t + 7500,
            None,
            diagnostic={"code": "BOOK_RESYNC_PENDING", "component": "up_book"},
            max_gap_ms=5000,
        )
        tape.append(
            t + 8000,
            replace(snap, now_ms=t + 8000),
            diagnostic={"code": "CAPTURED"},
            max_gap_ms=5000,
        )
        quality = json.loads(
            tape.db.execute("SELECT value FROM meta WHERE key='capture_quality'").fetchone()[0]
        )
        assert quality["first_frame"] == first
        assert quality["frames"] == 5 and quality["available_frames"] == 2
        assert quality["unavailable_spans"] == 1
        assert quality["recorder_delays"] == 1 and quality["max_interval_ms"] == 6000
        assert quality["causes"] == {"spot:STALE_DATA": 2, "up_book:BOOK_RESYNC_PENDING": 1}
        assert quality["max_unavailable_span_ms"] == 7000
        assert quality["current_unavailable_since_ms"] is None
        frames = list(tape.read_after(legacy))
        assert frames[1].diagnostic["code"] == "STALE_DATA"
        assert not tape.db.execute("SELECT 1 FROM meta WHERE key='research_first_frame'").fetchone()


def test_capture_diagnostic_counters_rollback_with_frame(tmp_path):
    import json
    import sqlite3

    with Tape(tmp_path / "capture.sqlite") as tape:
        tape.append(1000, None, diagnostic={"code": "NO_METADATA"}, max_gap_ms=5000)
        tape.db.execute(
            "CREATE TRIGGER reject_label BEFORE INSERT ON labels BEGIN SELECT RAISE(ABORT, 'fixture'); END"
        )
        with pytest.raises(sqlite3.IntegrityError):
            tape.append(
                9000,
                None,
                diagnostic={"code": "NO_METADATA"},
                max_gap_ms=5000,
                labels={"fixture": {"final": "1"}},
            )
        assert tape.highwater() == 1
        q = json.loads(
            tape.db.execute("SELECT value FROM meta WHERE key='capture_quality'").fetchone()[0]
        )
        assert q["frames"] == 1 and q["recorder_delays"] == 0
