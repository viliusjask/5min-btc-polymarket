import asyncio
import json

from test_historical_replay import BEGIN, END, source_tape

from btc5m.config import Config
from btc5m.lab import Study
from btc5m.lab_tape import Tape
from btc5m.lab_variants import Variant


def test_external_assumptions_are_reported_without_changing_execution(tmp_path):
    async def run():
        original = tmp_path / "original.sqlite"
        imported = tmp_path / "external.sqlite"
        source_tape(original)
        provenance = {
            "provider": "outcometick",
            "limitations": ["MODELED_HISTORICAL_TERMS", "SAMPLED_BOOK_DEPTH"],
            "files": [{"sha256": "a" * 64}],
        }
        with Tape(original, readonly=True) as source, Tape(imported) as destination:
            with destination.db:
                destination.db.execute(
                    "INSERT INTO meta VALUES ('external_history',?)", (json.dumps(provenance),)
                )
            for frame in source.read_after(0):
                destination.append(
                    frame.now_ms,
                    frame.snapshot,
                    labels=frame.labels,
                    research={"external_history": provenance},
                )
        variant = Variant("settlement", "control", "Settlement", Config(), exit_policy="settlement")
        totals = []
        for name, source in (("control", original), ("imported", imported)):
            with Study(
                source, tmp_path / name, Config(), variants=(variant,), start_ms=BEGIN, end_ms=END
            ) as study:
                while await study.advance():
                    pass
                result = study.report()
                row = result["phases"][0]["variants"][0]
                totals.append((row["realized_pnl"], row["completed_rounds"], row["fees"]))
                if name == "imported":
                    assert result["external_history"] == provenance
                    assert row["completed_rounds"] == 1
                    assert row["clean_completed_rounds"] == 0
                    assert row["external_history_rounds"] == 1
                    assert row["external_limitations"] == {
                        "MODELED_HISTORICAL_TERMS": 1,
                        "SAMPLED_BOOK_DEPTH": 1,
                    }
                    assert not study.runners["explore", variant.ident].ledger.active_positions()
        assert totals[0] == totals[1]
        with Study(imported, tmp_path / "imported", Config()) as resumed:
            assert await resumed.advance() == 0
            assert resumed.report()["external_history"] == provenance
            row = resumed.report()["phases"][0]["variants"][0]
            assert row["external_history_rounds"] == 1

    asyncio.run(run())
