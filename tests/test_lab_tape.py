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
