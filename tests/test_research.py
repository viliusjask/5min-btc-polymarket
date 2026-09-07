import asyncio
import json
import threading
from decimal import Decimal as D
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
from test_strategy import make_snapshot

from btc5m.config import Config
from btc5m.dashboard import make_server
from btc5m.lab_replay import Replay
from btc5m.lab_tape import Frame
from btc5m.lab_variants import Valuations, Variant
from btc5m.research import (
    ResearchReader,
    RoundResult,
    block_sensitivity,
    compare_rounds,
    performance,
    read_rounds,
    summarize,
)


def row(i, pnl="0", *, used=True, uncertain=False, complete=True, observed=True, **kwargs):
    return RoundResult(
        slug=f"btc-updown-5m-{1800000000 + i * 300}",
        start_ms=(1800000000 + i * 300) * 1000,
        net=D(pnl),
        fees=D(".2") if used else D(0),
        used=used,
        complete=complete,
        observed=observed,
        uncertain=uncertain,
        traded_shares=D(20) if used else D(0),
        entry_price=D(".5") if used else None,
        entry_seconds=120 if used else None,
        direction="UP" if used else None,
        exit_reason="PROFIT" if used else None,
        **kwargs,
    )


def test_profit_distribution_outlier_removal_and_fixed_fill_costs():
    result = performance([row(0, "100"), row(1, "-5"), row(2, "-5"), row(3, "2")])
    assert result["net"] == D(92)
    assert result["before_fees"] == D("92.8")
    assert result["mean"] == D(23) and result["median"] == D("-1.5")
    assert result["win_rate"] == 0.5
    assert result["profit_factor"] == D("10.2")
    assert result["without_best_1"] == D(-8)
    assert result["without_best_3"] == D(-10)  # remove only available profitable rounds
    assert result["cost_stress"][-1]["net"] == D("91.20")
    assert result["cost_headroom_per_share"] == D("1.15")


def test_undefined_metrics_are_not_fabricated_as_zero_or_infinity():
    empty = performance([])
    assert empty["mean"] is None and empty["win_rate"] is None
    one = performance([row(0, "5")])
    assert one["profit_factor"] is None and one["losses"] == 0
    assert one["without_best_1"] is None
    all_losses = performance([row(0, "-3"), row(1, "-2")])
    assert all_losses["without_best_1"] == D(-5)
    assert all_losses["cost_headroom_per_share"] is None


def test_incomplete_rounds_and_excluded_winners_do_not_become_break_even_observations():
    rows = [
        row(0, "100", uncertain=True),
        row(1, "-2"),
        row(2, "-1", complete=False),
        row(3, used=False),
    ]
    result = summarize(rows, cohort="unflagged")
    assert result["stats"]["rounds"] == 1 and result["stats"]["net"] == D(-2)
    assert result["counts"]["flagged_used"] == 1 and result["counts"]["incomplete_used"] == 1
    assert len(result["rounds"]) == 1
    assert result["hourly"][0]["used_rounds"] == 1
    assert summarize(rows, cohort="all")["stats"]["net"] == D(98)


def test_matched_calendar_comparison_counts_flat_missing_and_incomplete_separately():
    a = [
        row(0, "10"),
        row(1, "4"),
        row(2, used=False),
        row(3, used=False),
        row(4, "-1", complete=False),
        row(5, "8", observed=False),
    ]
    b = [row(0, "3"), row(1, used=False), row(2, "-2"), row(3, used=False), row(4, "2")]
    result = compare_rounds(a, b, cohort="all")
    assert result["matched_rounds"] == 4
    assert result["excluded_rounds"] == 2
    assert result["difference"] == D(13)
    assert result["both_used"] == 1 and result["both_flat"] == 1
    assert result["selected_only"] == 1 and result["comparison_only"] == 1
    assert result["selected_net"] == D(14) and result["comparison_net"] == D(1)
    assert result["common_used_fraction"] == pytest.approx(1 / 3)
    assert compare_rounds(a, a, cohort="all")["difference"] == 0


def test_parameter_groups_are_fixed_and_conserve_profit_and_count():
    rows = [row(0, "1"), row(1, "-2"), row(2, "3")]
    rows[0].entry_price = D(".04")
    rows[1].entry_seconds = 50
    rows[2].entry_price = None
    groups = summarize(rows, cohort="all")["groups"]
    for dimension in ["entry_price", "entry_time", "exit_reason", "direction"]:
        assert sum(g["rounds"] for g in groups[dimension]) == 3
        assert sum(g["net"] for g in groups[dimension]) == 2
    assert any(g["label"] == "Unknown / conversion" for g in groups["entry_price"])
    assert groups["entry_price"][0]["label"] == "Below 10¢"


def test_block_sensitivity_never_stitches_across_a_missing_round():
    # UTC aligned six-round blocks, one poisoned block, six complete blocks.
    values = {r.start_ms: float(r.net) for r in [row(i, "2") for i in range(42)]}
    del values[row(7).start_ms]
    result = block_sensitivity(values, block_rounds=6)
    assert result["complete_blocks"] == 6 and result["included_rounds"] == 36
    assert result["mean_per_round"] == 2
    assert result["interval95"] == [2, 2]
    assert block_sensitivity({row(0).start_ms: 1}, block_rounds=6)["interval95"] is None


def test_bootstrap_is_reproducible_and_matched_differences_are_resampled_together():
    a = [row(i, str((i // 6) % 3 - 1)) for i in range(72)]
    b = [row(i, str((i // 6) % 3 - 2)) for i in range(72)]
    result = compare_rounds(a, b, cohort="all")
    assert result["block_sensitivity"][0]["interval95"] == [1, 1]
    assert result["block_sensitivity"] == compare_rounds(a, b, cohort="all")["block_sensitivity"]


def test_unobserved_accounting_round_is_not_counted_as_observed_hour():
    result = summarize([row(0, "2", observed=False), row(1, used=False)], cohort="all")
    assert result["hourly"][0]["observed_slots"] == 1
    assert result["stats"]["rounds"] == 0


@pytest.fixture
def study(tmp_path):
    variant = Variant("value", "control", "Value", Config(), exit_policy="settlement")
    phase = {
        "id": "explore",
        "kind": "exploratory",
        "start_ms": 0,
        "end_ms": None,
        "variants": [
            {"ident": variant.ident, "label": variant.label, "parameters": {"mode": "value"}}
        ],
    }
    root = tmp_path / "lab"
    path = root / "explore" / variant.ident / "ledger.sqlite"
    path.parent.mkdir(parents=True)
    runner = Replay(path, variant, "tape", 0)
    snap = make_snapshot()

    async def fill():
        for i in range(1, 4):
            current = make_snapshot(now_ms=snap.now_ms + (i - 1) * 5000)
            await runner.apply(
                Frame(i, current.now_ms, current, {}, "CAPTURED"), Valuations(current)
            )
        await runner.apply(Frame(4, snap.market.end_s * 1000 + 1, None, {}, "NO_SNAPSHOT"), None)

    asyncio.run(fill())
    (root / "study.json").write_text(
        json.dumps(
            {
                "environment": "paper-lab",
                "tape_identity": "tape",
                "variants": [{"ident": variant.ident}],
            }
        )
    )
    (root / "report.json").write_text(
        json.dumps(
            {
                "environment": "paper-lab",
                "trial_count": 1,
                "phases": [phase],
            }
        )
    )
    yield SimpleNamespace(
        root=root, path=path, runner=runner, phase=phase, ident=variant.ident, snap=snap
    )
    runner.close()


def test_reader_matches_settled_accounting_without_mutating_journal(study):
    rows, clock = read_rounds(study.path, study.ident, "value", study.phase, "tape")
    assert len(rows) == 1 and rows[0].used and not rows[0].complete
    assert summarize(rows, cohort="all")["stats"]["rounds"] == 0
    assert clock["cursor"] == 4

    async def settle():
        market = study.snap.market
        labels = {
            market.slug: {
                "condition_id": market.condition_id,
                "opening": str(market.reference_price),
                "final": "80500",
            }
        }
        await study.runner.apply(
            Frame(5, market.end_s * 1000 + 2000, None, labels, "NO_SNAPSHOT"), None
        )
        await study.runner.apply(
            Frame(6, market.end_s * 1000 + 2500, None, {}, "NO_SNAPSHOT"), None
        )

    asyncio.run(settle())
    before = list(study.runner.ledger.db.iterdump())
    rows, _ = read_rounds(study.path, study.ident, "value", study.phase, "tape")
    ledger = study.runner.ledger.portfolio_results()["value"]
    assert rows[0].complete and rows[0].net == ledger["realized_net_pnl"] > 0
    assert rows[0].fees == ledger["fees"]
    assert rows[0].entry_price == D(".70") and rows[0].direction == "UP"
    assert rows[0].traded_shares > 0 and rows[0].entry_seconds > 0
    assert list(study.runner.ledger.db.iterdump()) == before
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        read_rounds(study.path, study.ident, "value", {**study.phase, "start_ms": 300000}, "tape")


def test_research_api_validates_selection_and_never_opens_account(tmp_path, study):
    class NoAccount:
        def snapshot(self):
            pytest.fail("research attempted to access Real account")

    server = make_server(SimpleNamespace(path=tmp_path), port=0, live=NoAccount())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    params = dict(
        suite="directional",
        phase="explore",
        selected=study.ident,
        comparison=study.ident,
        cohort="all",
    )
    try:
        with urlopen(base + "/api/research?" + urlencode(params)) as response:
            data = json.load(response)
            assert data["environment"] == "paper-research"
            assert data["selected"]["counts"]["incomplete_used"] == 1
        for query in [
            urlencode({**params, "phase": "../"}),
            urlencode({**params, "selected": "0" * 20}),
            urlencode({**params, "cohort": "wins"}),
            urlencode(params) + "&suite=directional",
            urlencode({**params, "extra": "1"}),
        ]:
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/research?" + query)
            assert error.value.code == 400
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/api/research", data=b"{}", method="POST"))
        assert error.value.code == 405
        with urlopen(base + "/research.js") as response:
            assert response.headers["Content-Type"].startswith("text/javascript")
        (study.root / "report.json").write_text("[]")
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/research?" + urlencode({**params, "cohort": "unflagged"}))
        assert error.value.code == 503
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_reader_rejects_outside_study_symlinks_and_mismatched_environment(tmp_path, study):
    outside = tmp_path / "other.sqlite"
    study.runner.close()
    study.path.rename(outside)
    study.path.symlink_to(outside)
    with pytest.raises(ValueError, match="PATH_OUTSIDE"):
        ResearchReader(tmp_path).snapshot("directional", "explore", study.ident, study.ident, "all")
    # A study may not relabel a live account journal as a paper experiment.
    study.path.unlink()
    outside.rename(study.path)
    registry = json.loads((study.root / "study.json").read_text())
    registry["environment"] = "live"
    (study.root / "study.json").write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="PAPER_RESEARCH_ONLY"):
        ResearchReader(tmp_path).snapshot("directional", "explore", study.ident, study.ident, "all")
