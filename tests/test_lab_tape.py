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
