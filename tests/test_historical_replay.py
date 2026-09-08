import asyncio
import json
import sqlite3
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import pytest
from test_strategy import START, make_snapshot

from btc5m.cli import parse_args
from btc5m.config import STRATEGIES, Config, load_config
from btc5m.lab import Study, freeze
from btc5m.lab_tape import Tape
from btc5m.lab_variants import Variant

BEGIN, END = START * 1000, (START + 300) * 1000


def snapshot_at(stamp, start=START):
    snap = make_snapshot(now_ms=stamp)
    return replace(
        snap,
        market=replace(
            snap.market, slug=f"btc-updown-5m-{start}", start_s=start, end_s=start + 300
        ),
    )


def source_tape(path, *, labels=True):
    snap = snapshot_at(BEGIN + 180000)
    with Tape(path) as tape:
        tape.append(BEGIN - 4000000, None)
        for offset in (180000, 185000, 190000):
            before = snapshot_at(BEGIN - 300000 + offset, START - 300)
            tape.append(before.now_ms, before)
        for offset in (180000, 185000, 190000):
            current = snapshot_at(BEGIN + offset)
            tape.append(current.now_ms, current)
        tape.append(END, None)
        if labels:
            tape.append(
                END + 2000,
                None,
                labels={
                    snap.market.slug: {
                        "condition_id": snap.market.condition_id,
                        "opening": "80000",
                        "final": "80500",
                    }
                },
            )
            tape.append(END + 2500, None)
            for offset in (180000, 185000, 190000):
                later = snapshot_at(END + offset, START + 300)
                tape.append(later.now_ms, later)


def test_historical_entries_are_finite_but_later_recorded_labels_settle_them(tmp_path):
    async def run():
        source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
        source_tape(source)
        variant = Variant("settlement", "control", "Settlement", Config(), exit_policy="settlement")
        with Study(
            source, runtime, Config(), variants=(variant,), start_ms=BEGIN, end_ms=END
        ) as study:
            assert study.manifest["historical"]["source_highwater"] == 13
            assert study.manifest["source_start"] == 1
            while await study.advance(limit=3):
                pass
            runner = study.runners["explore", variant.ident]
            orders = [
                json.loads(r[0]) for r in runner.ledger.db.execute("SELECT data FROM intents")
            ]
            assert len(orders) == 1 and orders[0]["market"]["slug"] == f"btc-updown-5m-{START}"
            assert BEGIN <= orders[0]["created_ms"] < END
            assert runner.ledger.summary(study.now_ms).cash > 100
            assert not runner.ledger.active_positions()
            report = study.report()
            assert report["historical"]["complete"]
            assert report["historical"]["unresolved_variants"] == []
            assert report["phases"][0]["kind"] == "exploratory"
            assert report["phases"][0]["end_ms"] == END
            assert report["forecasts"]["expected_rounds"] == 1
            assert study.auto_freeze() is None
        with pytest.raises(ValueError, match="HISTORICAL_STUDY_IS_EXPLORATORY"):
            freeze(runtime, [variant.ident], test_rounds=12)

    asyncio.run(run())


def test_frozen_archive_end_keeps_unresolved_exposure_and_excludes_appended_labels(tmp_path):
    async def run():
        source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
        source_tape(source, labels=False)
        variant = Variant("settlement", "control", "Settlement", Config(), exit_policy="settlement")
        with Study(
            source, runtime, Config(), variants=(variant,), start_ms=BEGIN, end_ms=END
        ) as study:
            while await study.advance():
                pass
            cap = study.cursor
            assert study.report()["historical"]["unresolved_variants"][0]["ident"] == variant.ident
        with Tape(source) as tape:
            tape.append(
                END + 2000,
                None,
                labels={
                    f"btc-updown-5m-{START}": {
                        "condition_id": "condition",
                        "opening": "80000",
                        "final": "80500",
                    }
                },
            )
            tape.append(END + 2500, None)
        with Study(source, runtime, Config()) as resumed:
            assert await resumed.advance() == 0
            report = resumed.report()
            assert report["source_highwater"] == cap
            assert report["historical"]["source_last_ms"] == END
            assert report["historical"]["complete"]
            assert report["historical"]["unresolved_variants"][0]["open_positions"] == 1
            assert resumed.runners["explore", variant.ident].labels == {}

    asyncio.run(run())


def test_historical_resume_never_parses_labels_appended_after_its_cap(tmp_path):
    source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
    source_tape(source, labels=False)
    variant = Variant("value", "control", "Value", Config())
    with Study(source, runtime, Config(), variants=(variant,), start_ms=BEGIN, end_ms=END):
        pass
    with Tape(source) as tape:
        tape.append(END + 2000, None)
        with tape.db:
            tape.db.execute(
                "INSERT INTO labels VALUES (?,?,?)", (tape.highwater(), "future", "not json")
            )
    with Study(source, runtime, Config()) as study:
        assert study.labels == {}
        assert study.tape.label_cache == {}


def test_archive_ending_before_paper_redemption_reports_claimable_exposure(tmp_path):
    async def run():
        source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
        source_tape(source)
        with sqlite3.connect(source) as db:
            db.execute("DELETE FROM frames WHERE id>9")
        variant = Variant("settlement", "control", "Settlement", Config(), exit_policy="settlement")
        with Study(
            source, runtime, Config(), variants=(variant,), start_ms=BEGIN, end_ms=END
        ) as study:
            while await study.advance():
                pass
            report = study.report()["historical"]
            assert report["complete"]
            exposure = report["unresolved_variants"][0]
            assert exposure["claimable_positions"] == 1
            assert Decimal(exposure["claimable_value"]) > 0

    asyncio.run(run())


def test_tape_label_cap_is_readonly_and_validated(tmp_path):
    source = tmp_path / "capture.sqlite"
    source_tape(source)
    with Tape(source, readonly=True, label_highwater=8) as tape:
        assert tape.label_cache == {}
    for options in (
        {"label_highwater": 0},
        {"readonly": True, "label_highwater": -1},
        {"readonly": True, "label_highwater": 14},
        {"readonly": True, "label_highwater": True},
    ):
        with pytest.raises(ValueError, match="INVALID_TAPE_LABEL_HIGHWATER"):
            Tape(source, **options)


@pytest.mark.parametrize(
    "options",
    [
        {"start_ms": BEGIN},
        {"start_ms": END, "end_ms": BEGIN},
        {"start_ms": BEGIN + 1, "end_ms": END},
        {"start_ms": BEGIN, "end_ms": END + 600000},
        {"start_ms": BEGIN, "end_ms": END, "variant_ids": ("unknown",)},
        {"start_ms": BEGIN, "end_ms": END, "variant_ids": ()},
    ],
)
def test_invalid_historical_request_creates_no_study_manifest(tmp_path, options):
    source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
    source_tape(source)
    with pytest.raises(ValueError):
        Study(source, runtime, Config(), **options)
    assert not (runtime / "study.json").exists()


def test_existing_forward_study_cannot_be_rewritten_as_historical(tmp_path):
    source, runtime = tmp_path / "capture.sqlite", tmp_path / "forward"
    source_tape(source)
    variant = Variant("value", "control", "Value", Config())
    with Study(source, runtime, Config(), variants=(variant,)):
        pass
    before = (runtime / "study.json").read_bytes()
    with pytest.raises(ValueError, match="LAB_TRIALS_CHANGED"):
        Study(source, runtime, Config(), start_ms=BEGIN, end_ms=END)
    assert (runtime / "study.json").read_bytes() == before


def test_original_six_keep_the_supplied_current_strategy_configuration(tmp_path):
    source, runtime = tmp_path / "capture.sqlite", tmp_path / "six"
    source_tape(source)
    base = Config()
    base = replace(
        base,
        risk=replace(
            base.risk,
            allocation_usd=Decimal("600.05"),
            daily_loss_usd=Decimal("150"),
            session_loss_usd=Decimal("90"),
        ),
    )
    with Study(source, runtime, base, suite="original-six", start_ms=BEGIN, end_ms=END) as study:
        asyncio.run(study.advance(limit=1))
        assert len(study.variants) == 6
        assert {v.config.strategy.mode for v in study.variants.values()} == set(STRATEGIES)
        for variant in study.variants.values():
            assert variant.signal == "core"
            assert variant.config.strategy == replace(
                base.strategy, mode=variant.config.strategy.mode
            )
            assert variant.config.execution == base.execution
            allocation = (base.risk.allocation_usd / 6).quantize(
                Decimal(".01"), rounding=ROUND_DOWN
            )
            assert variant.config.risk == replace(
                base.risk,
                allocation_usd=allocation,
                daily_loss_usd=min(base.risk.daily_loss_usd, allocation),
                session_loss_usd=min(base.risk.session_loss_usd, allocation),
            )
            assert study.runners["explore", variant.ident].ledger.summary(BEGIN).cash == allocation


def test_missing_forecasts_finalize_once_across_exit_frames_and_restart(tmp_path):
    async def run():
        source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
        source_tape(source)
        variant = Variant("value", "control", "Value", Config())
        statements = []
        with Study(
            source, runtime, Config(), variants=(variant,), start_ms=BEGIN, end_ms=END
        ) as study:
            study.db.set_trace_callback(statements.append)
            while study.cursor < 8:
                await study.advance(limit=1)
        with Study(source, runtime, Config()) as study:
            study.db.set_trace_callback(statements.append)
            while await study.advance(limit=1):
                pass
        terminal_updates = [
            sql
            for sql in statements
            if sql.startswith("UPDATE forecasts") and "target_ms" not in sql
        ]
        assert len(terminal_updates) == 1

    asyncio.run(run())


def test_historical_end_forecasts_rollback_with_cursor_then_recover(tmp_path):
    async def run():
        source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
        with Tape(source) as tape:
            tape.append(BEGIN + 1000, None)
            tape.append(END, None)
            tape.append(END + 1000, None)
        variant = Variant("value", "control", "Value", Config())
        with Study(
            source, runtime, Config(), variants=(variant,), start_ms=BEGIN, end_ms=END
        ) as study:
            await study.advance(limit=1)
            study.db.execute(
                "CREATE TEMP TRIGGER fail_cursor BEFORE INSERT ON meta WHEN NEW.key='now_ms' BEGIN SELECT RAISE(ABORT,'injected failure'); END"
            )
            with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
                await study.advance(limit=1)
            assert study.cursor == 1
            assert study.forecasts()[0]["status"] == "pending"
        with Study(source, runtime, Config()) as resumed:
            while await resumed.advance():
                pass
            assert resumed.report()["historical"]["complete"]
            assert resumed.forecasts()[0]["status"] == "missing"

    asyncio.run(run())


def test_historical_pending_forecast_tick_does_not_scan_registered_future_rounds(tmp_path):
    async def run():
        source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
        source_tape(source)
        variant = Variant("value", "control", "Value", Config())
        with Study(
            source, runtime, Config(), variants=(variant,), start_ms=BEGIN, end_ms=END
        ) as study:
            # Only Study's forecast database has this budget, not simulator operations.
            with study.db:
                study.db.executemany(
                    "INSERT INTO forecasts VALUES (?,?)",
                    (
                        (
                            f"future-{i}",
                            json.dumps({"status": "pending", "target_ms": END + 1000000}),
                        )
                        for i in range(10000)
                    ),
                )
            study.db.set_progress_handler(lambda: 1, 1000)
            while study.cursor < 6:
                await study.advance(limit=1)
            study.db.set_progress_handler(None, 0)
            assert study.cursor == 6

    asyncio.run(run())


def test_historical_receipt_gap_marks_missed_forecasts_before_completion(tmp_path):
    async def run():
        source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
        with Tape(source) as tape:
            tape.append(BEGIN, None)
            tape.append(BEGIN + 900000, None)
            tape.append(BEGIN + 1200000, None)
        variant = Variant("value", "control", "Value", Config())
        with Study(
            source, runtime, Config(), variants=(variant,), start_ms=BEGIN, end_ms=BEGIN + 1200000
        ) as study:
            await study.advance(limit=2)
            assert [row["status"] for row in study.forecasts()] == [
                "missing",
                "missing",
                "missing",
                "pending",
            ]

    asyncio.run(run())


def test_cli_runs_selected_historical_variant_into_separate_report(tmp_path, capsys):
    from datetime import UTC, datetime

    from btc5m.cli import async_main
    from btc5m.lab import registered_variants

    source, runtime, config = (
        tmp_path / "capture.sqlite",
        tmp_path / "historical",
        tmp_path / "config.toml",
    )
    source_tape(source)
    config.write_text((Path(__file__).resolve().parents[1] / "config/btc5m.toml").read_text())
    ident = registered_variants(load_config(config), "original-six")[1].ident
    args = parse_args(
        [
            "lab",
            "run",
            "--source",
            str(source),
            "--runtime",
            str(runtime),
            "--config",
            str(config),
            "--suite",
            "original-six",
            "--variants",
            ident,
            "--start",
            datetime.fromtimestamp(BEGIN / 1000, UTC).isoformat(),
            "--end",
            datetime.fromtimestamp(END / 1000, UTC).isoformat(),
        ]
    )
    assert asyncio.run(async_main(args)) == 0
    report = json.loads((runtime / "report.json").read_text())
    assert report["status"] == "complete" and report["trial_count"] == 1
    assert report["phases"][0]["variant_ids"] == [ident]
    assert json.loads(capsys.readouterr().out)["kind"] == "lab_stopped"


def test_historical_variant_selection_is_registered_and_fixed(tmp_path):
    from btc5m.lab import registered_variants

    source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
    source_tape(source)
    selected = tuple(v.ident for v in registered_variants(Config(), "original-six")[:2])
    with Study(
        source,
        runtime,
        Config(),
        suite="original-six",
        variant_ids=selected,
        start_ms=BEGIN,
        end_ms=END,
    ) as study:
        assert tuple(study.variants) == selected
    with pytest.raises(ValueError, match="LAB_TRIALS_CHANGED"):
        Study(source, runtime, Config(), variant_ids=selected[::-1])


def test_empty_historical_interval_and_nonempty_runtime_are_rejected(tmp_path):
    source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
    with Tape(source) as tape:
        tape.append(BEGIN - 300000, None)
        tape.append(END, None)
    with pytest.raises(ValueError, match="HISTORICAL_RANGE_HAS_NO_FRAMES"):
        Study(source, runtime, Config(), start_ms=BEGIN, end_ms=END)
    assert not (runtime / "study.json").exists()
    runtime.mkdir(exist_ok=True)
    (runtime / "ledger.sqlite").write_text("existing paper runtime")
    with pytest.raises(ValueError, match="HISTORICAL_REQUIRES_NEW_STUDY_RUNTIME"):
        Study(source, runtime, Config(), start_ms=BEGIN, end_ms=END)


def test_cli_requires_timezone_aware_finite_historical_arguments():
    args = parse_args(
        [
            "lab",
            "run",
            "--source",
            "capture.sqlite",
            "--runtime",
            "new-study",
            "--start",
            "2026-09-08T09:00:00+03:00",
            "--end",
            "2026-09-08T06:05:00Z",
            "--suite",
            "original-six",
        ]
    )
    assert args.end - args.start == 300000
    for tail in [
        ["--start", "2026-09-08T06:00:00", "--end", "2026-09-08T06:05:00Z"],
        ["--start", "2026-09-08T06:00:00Z"],
        ["--start", "2026-09-08T06:00:00Z", "--end", "2026-09-08T06:05:00Z", "--continuous"],
    ]:
        with pytest.raises(SystemExit):
            parse_args(
                ["lab", "run", "--source", "capture.sqlite", "--runtime", "new-study", *tail]
            )


def test_archive_status_does_not_decode_or_scan_payload_history(tmp_path, monkeypatch):
    from btc5m import archive

    source = tmp_path / "capture.sqlite"
    with Tape(source) as tape:
        with tape.db:
            tape.db.executemany(
                "INSERT INTO frames(now_ms,slug,payload,checksum) VALUES (?,NULL,?,?)",
                [(BEGIN + i, b"intentionally not a frame", "not decoded") for i in range(10000)],
            )
    connect = sqlite3.connect

    def bounded(*args, **kwargs):
        db = connect(*args, **kwargs)
        db.set_progress_handler(lambda: 1, 1000)
        return db

    monkeypatch.setattr(archive.sqlite3, "connect", bounded)
    result = archive.archive_status(source)
    assert result["source_highwater"] == 10000
    assert result["receipt_range"] == {"first_ms": BEGIN, "last_ms": BEGIN + 9999}
    assert result["gaps"]["status"] == "not_instrumented"
    assert result["size_bytes"]["total"] > 0


def test_historical_seek_skips_old_payloads_outside_causal_warmup(tmp_path):
    async def run():
        source, runtime = tmp_path / "capture.sqlite", tmp_path / "historical"
        source_tape(source)
        with sqlite3.connect(source) as db:
            db.execute(
                "UPDATE frames SET payload=?,checksum='unread old payload' WHERE id=1",
                (b"not decoded",),
            )
        variant = Variant("value", "control", "Value", Config())
        with Study(
            source, runtime, Config(), variants=(variant,), start_ms=BEGIN, end_ms=END
        ) as study:
            assert study.cursor == 1
            assert study.manifest["historical"]["warmup_first_ms"] == BEGIN - 120000
            assert await study.advance(limit=1) == 1
            assert study.cursor == 2
            assert not study.runners["explore", variant.ident].ledger.unresolved_orders()

    asyncio.run(run())
