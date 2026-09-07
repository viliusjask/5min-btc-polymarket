import asyncio
import json

import pytest
from test_strategy import make_snapshot

from btc5m.config import Config
from btc5m.lab import Study, freeze
from btc5m.lab_tape import Tape
from btc5m.lab_variants import Variant


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
