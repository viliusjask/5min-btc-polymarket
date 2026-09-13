"""Offline round-dataset extraction: freeze record, development build, holdout isolation."""

import hashlib
import json
from dataclasses import replace

import pytest
from test_strategy import START, make_snapshot

from btc5m import cli, dataset
from btc5m.lab import implementation_id
from btc5m.lab_tape import Tape, encode

ROUND_MS = 300_000
PURGE_MS = 1_800_000


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
