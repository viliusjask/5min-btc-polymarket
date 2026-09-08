"""The browser combines evidence, never simulated wallet balances."""

import json
import sqlite3
import threading
from decimal import Decimal as D
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_research import row
from test_research import study as create_study


@pytest.fixture
def study(tmp_path):
    yield from create_study.__wrapped__(tmp_path)


def paper_snapshot():
    return {
        "environment": "paper",
        "generated_ms": 1800000000000,
        "collector": {"status": "running", "caught_up": True, "first_ms": 1799999900000},
        "manifest": {"config_fingerprint": "current", "strategies": ["value"]},
        "portfolios": {
            "value": {
                "allocation": "100",
                "realized_net_pnl": "-8",
                "fees": ".4",
                "rounds": {
                    row(0).slug: {
                        "filled": True,
                        "unresolved": False,
                        "realized_net_pnl": "2",
                        "fees": ".2",
                    },
                    row(1).slug: {
                        "filled": True,
                        "unresolved": False,
                        "realized_net_pnl": "-10",
                        "fees": ".2",
                    },
                },
                "uncertain_rounds": [row(1).slug],
                "halts": [],
                "recent_fills": [],
                "recent_orders": [],
                "positions": [],
            }
        },
        "feeds": {"spot": {"source_ms": 1799999000000}},
        "decisions": {},
    }


def test_financial_cohorts_do_not_reset_capital_or_use_unfinished_pnl_as_mean():
    from btc5m.experiment_browser import experiment_metrics

    samples = [row(0, "2"), row(1, "-10", uncertain=True), row(2, "1", complete=False)]
    metrics = experiment_metrics(samples, allocation=D(100), realized=D(-7), drawdown=None)
    assert metrics["all"]["net"] == D(-7)
    assert metrics["all"]["completed_net"] == D(-8)
    assert metrics["all"]["mean"] == D(-4)
    assert metrics["unflagged"]["net"] == D(2)
    assert metrics["unflagged"]["return"] == metrics["all"]["return"] == D("-.07")
    assert metrics["unflagged"]["win_rate"] == 1
    assert metrics["all"]["drawdown"] is None
    empty = experiment_metrics([], allocation=D(100), realized=D(0), drawdown=None)
    assert empty["all"]["completed"] == 0
    assert empty["all"]["win_rate"] is None
    assert empty["all"]["mean"] is None and empty["all"]["best"] is None
    missing = experiment_metrics(None, allocation=None, realized=None, drawdown=None)
    assert missing["all"]["completed"] is None and missing["all"]["net"] is None


def test_one_list_includes_both_suites_phases_and_failed_sources(tmp_path, study, monkeypatch):
    monkeypatch.setattr("btc5m.experiment_browser.time.time", lambda: 1800000000)
    from btc5m.experiment_browser import ExperimentBrowser

    other = tmp_path / "order-flow-lab"
    other.mkdir()
    ident = "a" * 20
    (other / "study.json").write_text(
        json.dumps(
            {
                "environment": "paper-lab",
                "start_ms": 0,
                "variants": [{"ident": ident, "label": "Flow", "family": "flow"}],
            }
        )
    )
    (other / "report.json").write_text("broken JSON")
    db = sqlite3.connect(other / "study.sqlite")
    db.execute("CREATE TABLE phases(id TEXT PRIMARY KEY,data TEXT)")
    db.execute(
        "INSERT INTO phases VALUES (?,?)",
        (
            "later",
            json.dumps(
                {"id": "later", "kind": "holdout", "start_ms": 900000, "variant_ids": [ident]}
            ),
        ),
    )
    db.commit()
    db.close()
    reader = ExperimentBrowser(SimpleNamespace(path=tmp_path, snapshot=paper_snapshot))
    result = reader.snapshot()
    keys = {r["key"] for r in result["experiments"]}
    assert {
        "paper:value",
        f"directional:explore:{study.ident}",
        f"order-flow:explore:{ident}",
        f"order-flow:later:{ident}",
    } <= keys
    missing = next(r for r in result["experiments"] if r["key"] == f"order-flow:later:{ident}")
    assert missing["status"] == "unavailable" and missing["metrics"]["all"]["net"] is None
    assert any(e["source"] == "order-flow" for e in result["errors"])
    assert result["capture"]["data_status"] == "stale"
    assert "combined_pnl" not in result


def test_unchanged_results_reuse_round_reads_and_detail_is_readonly(tmp_path, study, monkeypatch):
    import btc5m.experiment_browser as browser

    reads = []
    original = browser.read_rounds

    def tracked(*args):
        reads.append(args[0])
        return original(*args)

    monkeypatch.setattr(browser, "read_rounds", tracked)
    clock = [100.0]
    monkeypatch.setattr(browser.time, "monotonic", lambda: clock[0])
    reader = browser.ExperimentBrowser(SimpleNamespace(path=tmp_path, snapshot=paper_snapshot))
    first = reader.snapshot()
    assert len(reads) == 1
    clock[0] += 31
    reader.snapshot()
    assert len(reads) == 1
    assert first["experiments"][0]["metrics"]["all"]["win_rate"] == 0.5
    before = list(study.runner.ledger.db.iterdump())
    detail = reader.detail(f"directional:explore:{study.ident}", "all")
    assert detail["analysis"]["counts"]["incomplete_used"] == 1
    assert list(study.runner.ledger.db.iterdump()) == before
    with pytest.raises(ValueError, match="UNKNOWN_EXPERIMENT"):
        reader.detail("directional:../../secrets:bad", "all")


def test_browser_http_is_paper_only_and_validates_queries(tmp_path, monkeypatch):
    from test_dashboard import runtime

    from btc5m.config import Config
    from btc5m.dashboard import DashboardReader, make_server

    class NoAccount:
        def snapshot(self):
            pytest.fail("Paper list called the real account")

    reader = DashboardReader(runtime(tmp_path, monkeypatch), Config())
    monkeypatch.setattr(reader, "snapshot", paper_snapshot)
    server = make_server(reader, port=0, live=NoAccount())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/experiments") as response:
            assert json.load(response)["experiments"][0]["key"] == "paper:value"
        with urlopen(base + "/api/experiment?key=paper%3Avalue&cohort=unflagged") as response:
            assert json.load(response)["analysis"]["stats"]["net"] == "2"
        for suffix in (
            "?key=../&cohort=all",
            "?key=paper:value&cohort=winners",
            "?key=paper:value&key=paper:value&cohort=all",
        ):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/experiment" + suffix)
            assert error.value.code == 400
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/api/experiments", data=b"{}", method="POST"))
        assert error.value.code == 405
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    assert reader._worker is not None and not reader._worker.is_alive()


def test_fresh_prices_do_not_hide_missing_usable_snapshot(tmp_path, monkeypatch):
    from btc5m.experiment_browser import ExperimentBrowser

    monkeypatch.setattr("btc5m.experiment_browser.time.time", lambda: 1800000000)
    data = paper_snapshot()
    data["feeds"]["spot"]["source_ms"] = 1800000000000
    db = sqlite3.connect(tmp_path / "capture.sqlite")
    db.execute("CREATE TABLE meta(key TEXT, value TEXT)")
    db.execute(
        "INSERT INTO meta VALUES (?,?)",
        (
            "capture_quality",
            json.dumps(
                {
                    "frames": 3,
                    "last_ms": 1800000000000,
                    "current_unavailable_since_ms": 1799999999000,
                    "latest": {"code": "METADATA_CACHE_EXPIRED"},
                }
            ),
        ),
    )
    db.commit()
    db.close()
    capture = ExperimentBrowser(SimpleNamespace(path=tmp_path, snapshot=lambda: data)).snapshot()[
        "capture"
    ]
    assert capture["data_status"] == "unavailable"
    assert capture["latest"]["code"] == "METADATA_CACHE_EXPIRED"


@pytest.mark.parametrize("future_ms, expected", [(0, "recent"), (1000, "stale")])
def test_quality_freshness_uses_time_after_concurrent_capture_read(
    tmp_path, monkeypatch, future_ms, expected
):
    import btc5m.experiment_browser as browser

    clock = [1800000000.0]
    monkeypatch.setattr(browser.time, "time", lambda: clock[0])

    def advancing_quality(_path):
        # A collector can append while the catalog is reading study statistics.
        clock[0] += 1
        return {
            "status": "available",
            "last_ms": int(clock[0] * 1000) + future_ms,
            "latest": {"code": "CAPTURED"},
            "current_unavailable_since_ms": None,
        }

    monkeypatch.setattr(browser, "read_quality", advancing_quality)
    reader = browser.ExperimentBrowser(SimpleNamespace(path=tmp_path, snapshot=paper_snapshot))
    result = reader.snapshot()
    assert result["capture"]["data_status"] == expected
    assert result["generated_ms"] == int(clock[0] * 1000)


def test_journal_advancing_past_report_does_not_mix_financial_generations(
    tmp_path, study, monkeypatch
):
    import btc5m.experiment_browser as browser

    report = json.loads((study.root / "report.json").read_text())
    report["phases"][0]["variants"][0].update(
        allocation="100",
        realized_pnl="-10",
        completed_rounds=1,
        clean_completed_rounds=0,
        clean_completed_pnl="0",
    )
    (study.root / "report.json").write_text(json.dumps(report))
    monkeypatch.setattr(
        browser,
        "read_rounds",
        lambda *args: (
            [row(0, "-10", uncertain=True), row(1, "20")],
            {"as_of_ms": 1800000600000, "window_start_ms": 0, "window_end_ms": 1800000600000},
        ),
    )
    reader = browser.ExperimentBrowser(SimpleNamespace(path=tmp_path, snapshot=paper_snapshot))
    result = reader.snapshot()
    variant = next(r for r in result["experiments"] if r["source"] == "directional")
    assert variant["metrics"]["all"]["net"] == "-10"
    assert variant["metrics"]["all"]["completed"] is None
    assert variant["curves"]["all"] == []
    assert variant["statistics_error"] == "REPORT_JOURNAL_BOUNDARY_MISMATCH"
    detail = reader.detail(variant["key"], "all")
    assert detail["analysis"]["stats"]["net"] == "10"
    assert detail["report_matches_analysis"] is False
    assert detail["experiment"]["metrics"]["all"]["net"] is None


def test_budget_headroom_keeps_session_losses_and_only_uses_verified_config(tmp_path, monkeypatch):
    from test_dashboard import runtime

    from btc5m.config import Config
    from btc5m.dashboard import DashboardReader

    root = runtime(tmp_path, monkeypatch)
    reader = DashboardReader(root, Config())
    first = reader.snapshot()["portfolios"]["momentum"]
    assert first["risk_budget"]["session_loss_limit"] == "10"
    assert first["risk_budget"]["session_remaining_before_new_order"] == "10"
    db = sqlite3.connect(root / "momentum" / "ledger.sqlite")
    session = db.execute("SELECT value FROM meta WHERE key='session'").fetchone()[0]
    db.execute(
        "INSERT INTO accounting VALUES (?,?,?,?,?,?)",
        ("past-loss", session, "2000-01-01", "-9", "-9", "0"),
    )
    db.commit()
    db.close()
    current = reader.snapshot()["portfolios"]["momentum"]["risk_budget"]
    assert current["session_remaining_before_new_order"] == "1"
    assert current["daily_remaining_before_new_order"] == "10"


def test_long_completed_curves_are_bounded_without_hiding_profit_extremes():
    from btc5m.experiment_browser import completed_curve

    samples = [row(i, "1") for i in range(2000)]
    samples[900].net = D("10000")
    samples[901].net = D("-20000")
    full = []
    total = D(0)
    for sample in samples:
        total += sample.net
        full.append(total)
    curve = completed_curve(samples, "all")
    assert len(curve) <= 1200
    assert curve[0][1] == full[0] and curve[-1][1] == full[-1]
    assert max(p[1] for p in curve) == max(full)
    assert min(p[1] for p in curve) == min(full)
    assert [p[0] for p in curve] == sorted(p[0] for p in curve)
