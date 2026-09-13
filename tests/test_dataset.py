"""Offline round-dataset extraction: freeze record, development build, holdout isolation."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from test_strategy import START, make_snapshot

from btc5m import cli, dataset
from btc5m.lab import implementation_id
from btc5m.lab_tape import Tape, encode

ROUND_MS = 300_000
PURGE_MS = 1_800_000


def _snapshot(start_s, now_ms, *, ask="0.70", move="200"):
    """A tradable snapshot for the round starting at start_s, stamped at now_ms."""
    snap = make_snapshot(ask=Decimal(ask), move=Decimal(move), now_ms=now_ms)
    market = replace(
        snap.market,
        slug=f"btc-updown-5m-{start_s}",
        start_s=start_s,
        end_s=start_s + 300,
        reference_timestamp_ms=start_s * 1000,
        metadata_received_ms=now_ms,
    )
    return replace(snap, market=market)


def _capture(path, snapshots, *, labels=None, heartbeat_s=None):
    """Append snapshot and label frames in time order; return the tape's SQLite path.

    snapshots: iterable of (start_s, offset_s) placing one tradable frame at
    (start_s + offset_s) * 1000. labels: iterable of (start_s, final, received_s).
    heartbeat_s: optional trailing snapshot-free frame to advance the tape clock.
    """
    events = [((start_s + off) * 1000, "snap", (start_s, off)) for start_s, off in snapshots]
    for start_s, final, received_s in labels or []:
        events.append((received_s * 1000, "label", (start_s, final)))
    if heartbeat_s is not None:
        events.append((heartbeat_s * 1000, "beat", None))
    events.sort(key=lambda event: event[0])
    with Tape(path) as tape:
        for now_ms, kind, payload in events:
            if kind == "snap":
                start_s, off = payload
                tape.append(now_ms, _snapshot(start_s, (start_s + off) * 1000))
            elif kind == "label":
                start_s, final = payload
                tape.append(
                    now_ms,
                    None,
                    labels={
                        f"btc-updown-5m-{start_s}": {
                            "condition_id": "condition",
                            "opening": "80000",
                            "final": final,
                        }
                    },
                )
            else:
                tape.append(now_ms, None)
    return path


def _append_round(tape, start_s, *, ask="0.70", move="200", final=None, label_at=None):
    """Append one round's opening snapshot frame and, optionally, its final label frame."""
    from decimal import Decimal

    snap = make_snapshot(ask=Decimal(ask), move=Decimal(move))
    market = replace(
        snap.market, slug=f"btc-updown-5m-{start_s}", start_s=start_s, end_s=start_s + 300
    )
    now_ms = (start_s + 180) * 1000
    snap = replace(
        snap,
        market=replace(market, metadata_received_ms=now_ms),
        now_ms=now_ms,
        spot=replace(snap.spot, timestamp_ms=now_ms, received_ms=now_ms),
        twap60=replace(snap.twap60, timestamp_ms=now_ms, received_ms=now_ms),
        up_book=replace(snap.up_book, timestamp_ms=now_ms, received_ms=now_ms),
        down_book=replace(snap.down_book, timestamp_ms=now_ms, received_ms=now_ms),
    )
    ident = tape.append(now_ms, snap)
    if final is not None:
        received = label_at if label_at is not None else (start_s + 300) * 1000 + 1000
        ident = tape.append(
            received,
            None,
            labels={
                snap.market.slug: {
                    "condition_id": market.condition_id,
                    "opening": str(market.reference_price),
                    "final": final,
                }
            },
        )
    return ident


def _tape_with_rounds(path, starts):
    with Tape(path) as tape:
        for start_s in starts:
            _append_round(tape, start_s, final="80500")


def test_freeze_records_boundaries_and_hash(tmp_path):
    source = tmp_path / "capture.sqlite"
    _tape_with_rounds(source, [START, START + 300])
    with Tape(source, readonly=True) as tape:
        identity, high_water, last_ms = tape.identity, tape.highwater(), tape.last_ms

    now_ms = last_ms + 12_345
    output = tmp_path / "freeze.json"
    record = dataset.freeze(source, output, now_ms=now_ms)

    cutoff = (max(now_ms, last_ms) // ROUND_MS + 1) * ROUND_MS
    assert record["tape_identity"] == identity
    assert record["high_water"] == high_water
    assert record["last_ms"] == last_ms
    assert record["created_ms"] == now_ms
    assert record["code_identity"] == implementation_id()
    assert record["cutoff_ms"] == cutoff
    assert record["validation_end_ms"] == cutoff - PURGE_MS
    assert record["holdout_start_ms"] == cutoff + PURGE_MS

    on_disk = json.loads(output.read_text())
    assert on_disk == record
    body = {k: v for k, v in record.items() if k != "sha256"}
    assert record["sha256"] == hashlib.sha256(encode(body).encode()).hexdigest()


def test_freeze_refuses_existing_output_and_leaves_it_unchanged(tmp_path):
    source = tmp_path / "capture.sqlite"
    _tape_with_rounds(source, [START])
    output = tmp_path / "freeze.json"
    output.write_text("sentinel")

    with pytest.raises(dataset.DatasetError, match="FREEZE_EXISTS"):
        dataset.freeze(source, output, now_ms=(START + 600) * 1000)
    assert output.read_text() == "sentinel"


def test_freeze_opens_source_read_only(tmp_path):
    source = tmp_path / "capture.sqlite"
    _tape_with_rounds(source, [START])
    lock = source.parent / (source.name + ".lock")
    lock.unlink(missing_ok=True)

    dataset.freeze(source, tmp_path / "freeze.json", now_ms=(START + 600) * 1000)
    assert not lock.exists()


def test_cli_freeze_writes_record_then_refuses_overwrite(tmp_path, capsys):
    source = tmp_path / "capture.sqlite"
    _tape_with_rounds(source, [START])
    output = tmp_path / "freeze.json"

    code = cli.main(["dataset", "freeze", "--source", str(source), "--output", str(output)])
    assert code == 0
    assert json.loads(output.read_text())["tape_identity"]
    emitted = json.loads(capsys.readouterr().out.strip())
    assert emitted["kind"] == "dataset_freeze"

    assert cli.main(["dataset", "freeze", "--source", str(source), "--output", str(output)]) == 2
    assert "FREEZE_EXISTS" in capsys.readouterr().err


def test_cli_build_and_holdout_dispatch_and_required_inputs(tmp_path, capsys):
    source = tmp_path / "capture.sqlite"
    _capture(source, snapshots=[(START, 60)], heartbeat_s=START + 7200)
    freeze_file = tmp_path / "freeze.json"
    record = dataset.freeze(source, freeze_file, now_ms=(START + 7200) * 1000)
    base = ["--source", str(source), "--output", str(tmp_path / "dev")]
    assert cli.main(["dataset", "build", *base]) == 2
    assert "FREEZE_RECORD_REQUIRED" in capsys.readouterr().err
    assert cli.main(["dataset", "build"]) == 2
    assert "SOURCE_AND_OUTPUT_REQUIRED" in capsys.readouterr().err

    args = [*base, "--freeze", str(freeze_file)]
    train_end = datetime.fromtimestamp(START + 7200, tz=UTC).isoformat()
    assert cli.main(["dataset", "build", *args, "--train-end", train_end]) == 0
    event = json.loads(capsys.readouterr().out)
    assert event["manifest"]["rounds_per_split"] == {"train": 1}
    assert (tmp_path / "dev" / "dataset.sqlite").exists()

    assert cli.main(["dataset", "build-holdout", *args]) == 2
    assert "SELECTION_RECORD_REQUIRED" in capsys.readouterr().err
    assert not (tmp_path / "dev" / "holdout.sqlite").exists()
    holdout_s = record["holdout_start_ms"] // 1000
    _append(source, snapshots=[(holdout_s + 300, 60)])
    selection_file = tmp_path / "selection.json"
    selection_file.write_text(
        encode(dataset.selection_record(record, rules_sha256="abc", selected_rules=["H1-a"]))
    )
    assert cli.main(["dataset", "build-holdout", *args, "--selection", str(selection_file)]) == 0
    event = json.loads(capsys.readouterr().out)
    assert event["manifest"]["rounds_per_split"] == {"holdout": 1}
    assert (tmp_path / "dev" / "holdout.sqlite").exists()


def test_development_never_decodes_post_freeze_payloads_or_labels(tmp_path):
    source = tmp_path / "capture.sqlite"
    _capture(source, snapshots=[(START, 60)], heartbeat_s=START + 7200)
    freeze_file = tmp_path / "freeze.json"
    record = dataset.freeze(source, freeze_file, now_ms=(START + 7200) * 1000)
    _append(
        source,
        snapshots=[(START + 20000, 60)],
        labels=[(START, "80500", START + 8000)],
    )
    with sqlite3.connect(source) as con:
        con.execute("UPDATE frames SET payload=? WHERE id>?", (b"unreadable", record["high_water"]))
        con.execute(
            "UPDATE labels SET data=? WHERE frame_id>?", ("unreadable", record["high_water"])
        )
    manifest = dataset.build(
        source, freeze_file, tmp_path / "dev", train_end_ms=(START + 7200) * 1000
    )
    assert manifest["rounds_per_split"] == {"train": 1}
    assert manifest["unlabeled_per_split"] == {"train": 1}


def _read(db_path, query):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(query).fetchall()
    finally:
        con.close()


def test_build_extracts_rounds_ticks_and_null_label(tmp_path):
    source = tmp_path / "capture.sqlite"
    _capture(
        source,
        snapshots=[
            (START, 60),
            (START, 120),
            (START, 180),
            (START + 3600, 60),
            (START + 3600, 120),
            (START + 7200, 60),
        ],
        labels=[(START, "80500", START + 305), (START + 7200, "80500", START + 7505)],
        heartbeat_s=START + 50000,
    )
    freeze = tmp_path / "freeze.json"
    record = dataset.freeze(source, freeze, now_ms=(START + 50000) * 1000)

    out = tmp_path / "dev"
    manifest = dataset.build(source, freeze, out, train_end_ms=record["validation_end_ms"])
    db = out / "dataset.sqlite"

    rounds = {
        row[0]: row[1:]
        for row in _read(
            db, "SELECT slug,split,final_label,label_frame_ident,valid_frames FROM rounds"
        )
    }
    assert set(rounds) == {
        f"btc-updown-5m-{START}",
        f"btc-updown-5m-{START + 3600}",
        f"btc-updown-5m-{START + 7200}",
    }
    assert all(row[0] == "train" for row in rounds.values())
    assert rounds[f"btc-updown-5m-{START}"][1] == "80500"
    r1 = rounds[f"btc-updown-5m-{START + 3600}"]
    assert r1[1] is None and r1[2] is None  # gap round: no label, no label frame

    tick_counts = dict(_read(db, "SELECT round_slug,COUNT(*) FROM ticks GROUP BY round_slug"))
    assert tick_counts[f"btc-updown-5m-{START}"] == 3
    assert tick_counts[f"btc-updown-5m-{START + 3600}"] == 2
    assert tick_counts[f"btc-updown-5m-{START + 7200}"] == 1

    assert manifest["rounds_per_split"] == {"train": 3}
    assert manifest["unlabeled_per_split"] == {"train": 1}
    assert manifest["tape_identity"] == record["tape_identity"]


def _append(path, snapshots=(), labels=()):
    """Append more frames to an existing tape; caller keeps times after the last frame."""
    events = [((start_s + off) * 1000, "snap", (start_s, off)) for start_s, off in snapshots]
    for start_s, final, received_s in labels:
        events.append((received_s * 1000, "label", (start_s, final)))
    events.sort(key=lambda event: event[0])
    with Tape(path) as tape:
        for now_ms, kind, payload in events:
            if kind == "snap":
                start_s, off = payload
                tape.append(now_ms, _snapshot(start_s, (start_s + off) * 1000))
            else:
                start_s, final = payload
                tape.append(
                    now_ms,
                    None,
                    labels={
                        f"btc-updown-5m-{start_s}": {
                            "condition_id": "condition",
                            "opening": "80000",
                            "final": final,
                        }
                    },
                )


def test_build_assigns_splits_and_excludes_purge_and_late_rounds(tmp_path):
    train_end_s = START + 100_000
    source = tmp_path / "capture.sqlite"
    _capture(
        source,
        snapshots=[
            (START, 60),
            (START + 300, 60),
            (train_end_s, 60),  # purge band around the train/validation boundary
            (START + 102_000, 60),
            (START + 102_300, 60),
            (START + 200_000, 60),  # at or after the purged validation edge
        ],
    )
    freeze = tmp_path / "freeze.json"
    record = dataset.freeze(source, freeze, now_ms=(START + 200_060) * 1000)
    assert (START + 102_300) * 1000 < record["validation_end_ms"] < (START + 200_000) * 1000

    dataset.build(source, freeze, tmp_path / "dev", train_end_ms=train_end_s * 1000)
    splits = dict(_read(tmp_path / "dev" / "dataset.sqlite", "SELECT slug,split FROM rounds"))
    assert splits == {
        f"btc-updown-5m-{START}": "train",
        f"btc-updown-5m-{START + 300}": "train",
        f"btc-updown-5m-{START + 102_000}": "validation",
        f"btc-updown-5m-{START + 102_300}": "validation",
    }


def test_build_is_deterministic_and_ignores_frames_after_the_freeze(tmp_path):
    source = tmp_path / "capture.sqlite"
    _capture(
        source,
        snapshots=[(START, 60), (START + 3600, 60)],
        labels=[(START, "80500", START + 305)],
        heartbeat_s=START + 7200,
    )
    freeze = tmp_path / "freeze.json"
    dataset.freeze(source, freeze, now_ms=(START + 7200) * 1000)

    first = dataset.build(source, freeze, tmp_path / "a", train_end_ms=(START + 7200) * 1000)
    hash_a = dataset.content_hash(tmp_path / "a" / "dataset.sqlite")

    # A late label for the unlabeled development round and new holdout-region frames.
    _append(
        source,
        snapshots=[(START + 20_000, 60)],
        labels=[(START + 3600, "80500", START + 8000)],
    )
    dataset.build(source, freeze, tmp_path / "b", train_end_ms=(START + 7200) * 1000)
    hash_b = dataset.content_hash(tmp_path / "b" / "dataset.sqlite")

    assert hash_a == hash_b
    rounds = dict(_read(tmp_path / "b" / "dataset.sqlite", "SELECT slug,final_label FROM rounds"))
    assert rounds[f"btc-updown-5m-{START + 3600}"] is None  # late label stays invisible
    assert first["rounds_per_split"] == {"train": 2}


def test_build_refuses_wrong_identity_and_tampered_freeze(tmp_path):
    source_a = tmp_path / "a.sqlite"
    _capture(source_a, snapshots=[(START, 60)], heartbeat_s=START + 7200)
    freeze = tmp_path / "freeze.json"
    dataset.freeze(source_a, freeze, now_ms=(START + 7200) * 1000)

    source_b = tmp_path / "b.sqlite"
    _capture(source_b, snapshots=[(START, 60)], heartbeat_s=START + 7200)
    with pytest.raises(dataset.DatasetError, match="DATASET_SOURCE_IDENTITY_CHANGED"):
        dataset.build(source_b, freeze, tmp_path / "dev")

    tampered = json.loads(freeze.read_text())
    tampered["cutoff_ms"] += ROUND_MS
    (tmp_path / "bad.json").write_text(encode(tampered))
    with pytest.raises(dataset.DatasetError, match="FREEZE_RECORD_HASH_MISMATCH"):
        dataset.build(source_a, tmp_path / "bad.json", tmp_path / "dev2")


def test_build_records_engine_rejection_without_fabricating_a_book(tmp_path):
    source = tmp_path / "capture.sqlite"
    good = _snapshot(START, (START + 60) * 1000)
    blocked = _snapshot(START, (START + 120) * 1000)
    blocked = replace(blocked, market=replace(blocked.market, accepting_orders=False))
    with Tape(source) as tape:
        tape.append((START + 60) * 1000, good)
        tape.append((START + 120) * 1000, blocked)
        tape.append((START + 7200) * 1000, None)
    freeze = tmp_path / "freeze.json"
    dataset.freeze(source, freeze, now_ms=(START + 7200) * 1000)

    dataset.build(source, freeze, tmp_path / "dev", train_end_ms=(START + 7200) * 1000)
    ticks = dict(
        _read(
            tmp_path / "dev" / "dataset.sqlite",
            "SELECT seconds_remaining,rejection FROM ticks ORDER BY frame_ident",
        )
    )
    assert ticks[240.0] is None  # first frame is tradable
    assert ticks[180.0] == "MARKET_NOT_ACCEPTING"
    valid = _read(tmp_path / "dev" / "dataset.sqlite", "SELECT valid_frames FROM rounds")
    assert valid == [(1,)]


def test_build_depth_and_sigma_match_hand_computed_values(tmp_path):
    source = tmp_path / "capture.sqlite"
    _capture(source, snapshots=[(START, 60)], heartbeat_s=START + 7200)
    freeze = tmp_path / "freeze.json"
    dataset.freeze(source, freeze, now_ms=(START + 7200) * 1000)

    dataset.build(source, freeze, tmp_path / "dev", train_end_ms=(START + 7200) * 1000)
    row = _read(
        tmp_path / "dev" / "dataset.sqlite",
        "SELECT up_ask_depth5,up_ask_depth25,up_ask_depth100,down_ask_depth5,"
        "short_sigma,long_sigma FROM ticks",
    )[0]
    assert row[:4] == ("3.50", "17.50", "70.00", "1.50")
    assert abs(row[4] - 5**0.5) < 1e-9 and abs(row[5] - 5**0.5) < 1e-9


def test_build_stores_signed_flow_when_present(tmp_path):
    source = tmp_path / "capture.sqlite"
    with Tape(source) as tape:
        tape.append(
            (START + 60) * 1000,
            _snapshot(START, (START + 60) * 1000),
            research={
                "version": 1,
                "flow": {
                    "windows": {
                        "10": {"status": "VALID", "buy_quantity": "3", "sell_quantity": "1"},
                        "30": {"status": "VALID", "buy_quantity": "2", "sell_quantity": "5"},
                        "60": {"status": "FLOW_WARMUP"},
                    }
                },
            },
        )
        tape.append((START + 7200) * 1000, None)
    freeze = tmp_path / "freeze.json"
    dataset.freeze(source, freeze, now_ms=(START + 7200) * 1000)

    manifest = dataset.build(source, freeze, tmp_path / "dev", train_end_ms=(START + 7200) * 1000)
    flow = _read(
        tmp_path / "dev" / "dataset.sqlite", "SELECT signed_10s,signed_30s,signed_60s FROM flow"
    )
    assert flow == [("2", "-3", None)]
    assert manifest["flow_trader_ids"] is False


def test_build_holdout_refuses_without_matching_selection_then_isolates_rounds(tmp_path):
    source = tmp_path / "capture.sqlite"
    _capture(
        source,
        snapshots=[(START, 60), (START + 3600, 60)],
        labels=[(START, "80500", START + 305), (START + 3600, "80500", START + 3665)],
        heartbeat_s=START + 7200,
    )
    freeze = tmp_path / "freeze.json"
    record = dataset.freeze(source, freeze, now_ms=(START + 7200) * 1000)
    dataset.build(source, freeze, tmp_path / "dev", train_end_ms=record["validation_end_ms"])
    dev_slugs = {
        r[0] for r in _read(tmp_path / "dev" / "dataset.sqlite", "SELECT slug FROM rounds")
    }

    holdout_s = record["holdout_start_ms"] // 1000
    _append(
        source,
        snapshots=[(holdout_s + 300, 60), (holdout_s + 600, 60)],
        labels=[
            (holdout_s + 300, "80500", holdout_s + 665),
            (holdout_s + 600, "80500", holdout_s + 965),
        ],
    )

    with pytest.raises(dataset.DatasetError, match="SELECTION_RECORD_REQUIRED"):
        dataset.build_holdout(source, freeze, tmp_path / "h", selection_file=None)

    good = dataset.selection_record(record, rules_sha256="abc", selected_rules=["H1-a"])
    bad = dict(good)
    bad["rules_sha256"] = "def"  # a changed rules hash breaks the self SHA-256
    (tmp_path / "bad.json").write_text(encode(bad))
    with pytest.raises(dataset.DatasetError, match="SELECTION_HASH_MISMATCH"):
        dataset.build_holdout(source, freeze, tmp_path / "h", selection_file=tmp_path / "bad.json")

    (tmp_path / "sel.json").write_text(encode(good))
    dataset.build_holdout(source, freeze, tmp_path / "h", selection_file=tmp_path / "sel.json")
    holdout = _read(tmp_path / "h" / "holdout.sqlite", "SELECT slug,split,start_ms FROM rounds")
    holdout_slugs = {r[0] for r in holdout}
    assert all(r[1] == "holdout" and r[2] >= record["holdout_start_ms"] for r in holdout)
    assert holdout_slugs and holdout_slugs.isdisjoint(dev_slugs)
