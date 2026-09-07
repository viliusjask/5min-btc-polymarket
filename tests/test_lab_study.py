import asyncio
import json

import pytest
from test_strategy import make_snapshot

from btc5m.config import Config
from btc5m.lab import Study, freeze
from btc5m.lab_tape import Tape
from btc5m.lab_variants import Variant


def test_flow_study_starts_at_research_capture_and_resumes_all_seventeen_wallets(tmp_path):
    async def run():
        source, runtime = tmp_path / "capture.sqlite", tmp_path / "flow-lab"
        snap = make_snapshot()
        with Tape(source) as tape:
            tape.append(snap.now_ms - 1000, None)
            tape.append(snap.now_ms, snap, research={"flow": {"status": "FLOW_WARMUP"}})
        with Study(source, runtime, Config(), suite="order-flow") as study:
            assert len(study.runners) == 17
            assert study.cursor == 1
            await study.advance()
            assert study.cursor == 2
            for runner in study.runners.values():
                assert runner.ledger.summary().cash == 100
                assert runner.ledger.db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0
            report = study.report()
            assert report["suite"] == "order-flow"
            assert report["research"]["flow"]["status"] == "FLOW_WARMUP"
        with Study(source, runtime, Config(), suite="order-flow") as study:
            assert study.cursor == 2
            assert len(study.runners) == 17
            await study.advance()
            assert study.cursor == 2
        with pytest.raises(ValueError, match="LAB_TRIALS_CHANGED"):
            Study(source, runtime, Config(), suite="directional")

    asyncio.run(run())


def test_study_records_fixed_forecasts_resumes_and_freezes_only_future_rounds(tmp_path):
    async def run():
        snap = make_snapshot()
        source, runtime = tmp_path / "capture.sqlite", tmp_path / "lab"
        variants = (Variant("v", "control", "Value", Config()),)
        with Tape(source) as tape:
            tape.append(snap.now_ms, snap)
        with Study(source, runtime, Config(), variants=variants) as study:
            await study.advance()
            report = study.report()
            assert report["forecasts"]["expected_rounds"] == 1
            assert report["forecasts"]["statuses"]["observed"] == 1
            assert report["trial_count"] == 1
            cursor = study.cursor
        with Study(source, runtime, Config(), variants=variants) as study:
            await study.advance()
            assert study.cursor == cursor
        frozen = freeze(runtime, [variants[0].ident], now_ms=snap.now_ms + 2000, test_rounds=12)
        assert frozen["start_ms"] > snap.now_ms + 2000
        assert frozen["source_highwater"] == 1
        assert frozen["variant_ids"] == [variants[0].ident]
        assert frozen["end_ms"] - frozen["start_ms"] == 12 * 300000
        with pytest.raises(ValueError, match="UNKNOWN_VARIANT"):
            freeze(runtime, ["made-up"], now_ms=snap.now_ms + 2000, test_rounds=12)
        with Study(source, runtime, Config(), variants=variants) as study:
            assert len(study.phases) == 2
            assert study.report()["phases"][1]["kind"] == "holdout"

    asyncio.run(run())


def test_registry_refuses_changed_code_config_or_tape_identity(tmp_path):
    source, runtime = tmp_path / "capture.sqlite", tmp_path / "lab"
    with Tape(source):
        pass
    with Study(source, runtime, Config(), variants=(Variant("v", "control", "Value", Config()),)):
        pass
    registry = json.loads((runtime / "study.json").read_text())
    registry["implementation"] = "different"
    (runtime / "study.json").write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="IMPLEMENTATION"):
        Study(source, runtime, Config())


def test_registered_trial_set_and_selection_window_cannot_change_on_resume(tmp_path):
    source, runtime = tmp_path / "capture.sqlite", tmp_path / "lab"
    variants = (Variant("v", "control", "Value", Config()),)
    with Tape(source):
        pass
    with Study(source, runtime, Config(), variants=variants, explore_rounds=12):
        pass
    with Study(source, runtime, Config()):
        pass  # Unspecified options resume the registered experiment unchanged.
    for options in ({"dense": True}, {"explore_rounds": 288}, {"variants": ()}):
        with pytest.raises(ValueError, match="LAB_TRIALS_CHANGED"):
            Study(source, runtime, Config(), **options)


@pytest.mark.parametrize("enough_evidence", [False, True])
def test_auto_selection_freezes_future_configuration_once_after_crash(
    tmp_path, monkeypatch, enough_evidence
):
    from btc5m import lab

    snap = make_snapshot()
    source, runtime = tmp_path / "capture.sqlite", tmp_path / "lab"
    control = Variant("control-value", "control", "Value", Config())
    contender = Variant("candidate", "momentum", "Candidate", Config())
    with Tape(source) as tape:
        tape.append(snap.now_ms, snap)
    with Study(
        source, runtime, Config(), variants=(control, contender), explore_rounds=12
    ) as study:
        cutoff = study.manifest["explore_end_ms"]
        monkeypatch.setattr(lab.time, "time", lambda: cutoff / 1000 + 5)

        def results(runner, *, before_ms):
            assert before_ms == cutoff
            return {
                "ident": runner.variant.ident,
                "clean_completed_rounds": 30 if enough_evidence else 29,
                "clean_completed_pnl": 2 if runner.variant.ident == contender.ident else -1,
                "unresolved_rounds": 0,
            }

        monkeypatch.setattr(lab, "replay_report", results)
        study.now_ms = cutoff - 1
        assert study.auto_freeze() is None
        study.now_ms = cutoff
        phase = study.auto_freeze()
        assert phase["start_ms"] > cutoff + 5000
        assert phase["source_highwater"] == 1
        assert control.ident in phase["variant_ids"]
        assert (contender.ident in phase["variant_ids"]) is enough_evidence
        assert study.auto_freeze() is None
        # Simulate death after the durable phase commit but before the marker commit.
        with study.db:
            study.db.execute("DELETE FROM meta WHERE key='auto_frozen'")
        assert study.auto_freeze() is None
        assert study.db.execute("SELECT COUNT(*) FROM phases").fetchone()[0] == 2
        assert study._meta("auto_frozen") == phase["id"]


def test_lost_derived_cache_suffix_catches_up_without_rescoring_or_duplicate_cash(tmp_path):
    import sqlite3

    async def run():
        source, runtime = tmp_path / "capture.sqlite", tmp_path / "lab"
        a, b = (Variant(name, "control", name, Config()) for name in ("a", "b"))
        snap = make_snapshot()
        with Tape(source) as tape:
            tape.append(snap.market.start_s * 1000 - 1, None)
            for i in range(3):
                current = make_snapshot(now_ms=snap.now_ms + i * 5000)
                tape.append(current.now_ms, current)
        backup = tmp_path / "cache-before-fill.sqlite"
        with Study(source, runtime, Config(), variants=(a, b)) as study:
            await study.advance(limit=2)
            with sqlite3.connect(backup) as db:
                study.runners["explore", a.ident].ledger.db.backup(db)
            await study.advance()
            cash = study.runners["explore", a.ident].ledger.summary().cash
            assert cash < 100
            count = study.db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
        # NORMAL can lose a whole committed suffix after power loss. The FULL study
        # cursor and the other variant can survive farther ahead than this cache.
        with (
            sqlite3.connect(backup) as src,
            sqlite3.connect(runtime / "explore" / a.ident / "ledger.sqlite") as dest,
        ):
            src.backup(dest)
        with Study(source, runtime, Config()) as study:
            assert study.cursor == 4
            assert study.runners["explore", a.ident].cursor == 2
            await study.advance()
            assert study.db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == count
            for runner in study.runners.values():
                assert runner.cursor == 4
                assert runner.ledger.summary().cash == cash
                assert runner.ledger.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1

    asyncio.run(run())
