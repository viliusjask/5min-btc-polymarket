import asyncio
import csv
import gzip
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from btc5m.config import Config
from btc5m.history_import import HistoricalTerms, import_outcometick
from btc5m.lab import Study
from btc5m.lab_tape import Tape
from btc5m.lab_variants import original_six_variants

D = Decimal
START = 1788480000
TERMS = HistoricalTerms(D(".01"), D("5"), D(".07"), 1)


def write_json(path, rows):
    with gzip.open(path, "wt") as out:
        for row in rows:
            out.write(json.dumps(row) + "\n")


def fixture(tmp_path, *, seconds=3, rounds=1):
    paths = {key: tmp_path / (key + ".gz") for key in ("markets", "books", "spot", "twap60")}
    markets, books = [], []
    for n in range(rounds):
        start = START + n * 300
        condition = "0x" + f"{n + 1:064x}"
        up, down = str(n * 2 + 1), str(n * 2 + 2)
        markets.append(
            {
                "slug": f"btc-updown-5m-{start}",
                "asset": "btc",
                "interval_sec": 300,
                "condition_id": condition,
                "token_ids": [up, down],
                "start_sec": start,
                "end_sec": start + 300,
                "resolved": True,
                "outcome_prices": ["1", "0"],
                "strike_value": str((80000 + n * 60) * 10**18),
                "raw": {
                    "slug": f"btc-updown-5m-{start}",
                    "conditionId": condition,
                    "outcomes": '["Up","Down"]',
                    "clobTokenIds": json.dumps([up, down]),
                    "cryptoMarketConfig": {
                        "twapEnabled": True,
                        "twapLookbackSeconds": 60,
                        "asset": "btc",
                    },
                    "resolutionSource": "https://data.chain.link/streams/btc-usd-twap-60s-streams",
                    "active": False,
                    "closed": True,
                    "acceptingOrders": False,
                    "orderPriceMinTickSize": 0.001,
                    "orderMinSize": 1000,
                    "feeSchedule": {"rate": 0.9, "exponent": 2},
                },
            }
        )
        for second in range(min(seconds - n * 300, 300)):
            source = (start + second) * 1000
            for token, bid, ask in ((up, ".79", ".80"), (down, ".19", ".20")):
                books.append(
                    {
                        "slug": f"btc-updown-5m-{start}",
                        "asset_id": token,
                        "event_type": "book",
                        "event_ts_ms": source,
                        "recv_ms": source + 200,
                        "payload": {
                            "asset_id": token,
                            "market": condition,
                            "timestamp": str(source),
                            "event_type": "book",
                            "bids": [{"price": bid, "size": "50"}],
                            "asks": [{"price": ask, "size": "50"}],
                        },
                    }
                )
    write_json(paths["markets"], markets)
    write_json(paths["books"], books)
    for key in ("spot", "twap60"):
        with gzip.open(paths[key], "wt") as out:
            writer = csv.writer(out)
            writer.writerow(
                ["feed_ts_ms", "value", "full_accuracy_value", "server_ts_ms", "recv_ms"]
            )
            for second in range(-1860, seconds + 1):
                source = (START + second) * 1000
                price = D(80000) + D(second % 3) + D(second) / 5
                writer.writerow(
                    [source, str(price), str(int(price * 10**18)), source + 100, source + 300]
                )
    return paths


def run_import(tmp_path, paths, *, seconds=3, terms=TERMS, **options):
    return import_outcometick(
        **paths,
        destination=tmp_path / "imported",
        start_ms=START * 1000,
        end_ms=(START + seconds) * 1000,
        config=Config(),
        terms=terms,
        **options,
    )


def frames(path):
    with Tape(path, readonly=True) as tape:
        return list(tape.read_after(0, limit=100000))


def test_exact_causal_inputs_and_explicit_terms_not_final_market_state(tmp_path):
    paths = fixture(tmp_path)
    report = run_import(tmp_path, paths)
    rows = frames(tmp_path / "imported" / "capture.sqlite")
    snapshots = [f.snapshot for f in rows if f.snapshot]
    assert snapshots
    snap = snapshots[-1]
    assert snap.spot.received_ms <= snap.now_ms
    assert all(p.received_ms <= snap.now_ms for p in snap.history)
    assert snap.market.reference_price == D(80000)
    assert snap.market.reference_status == "boundary"
    assert snap.market.tick_size == D(".01")
    assert snap.market.min_order_size == D(5)
    assert snap.market.fee_rate == D(".07")
    assert snap.market.active and snap.market.accepting_orders
    assert all(f.research["external_history"]["limitations"] for f in rows)
    assert all(not f.labels for f in rows)  # No exact closing boundary for these markets.
    assert report["complete"]
    assert report["sources"]["books"]["rows"] == 6
    assert report["capabilities"]["fast_value"] == "missing_binance"
    assert run_import(tmp_path, paths) == report  # Completed imports are idempotent.


def test_strict_without_assumed_terms_retains_evidence_but_cannot_trade(tmp_path):
    report = run_import(tmp_path, fixture(tmp_path), terms=None)
    rows = frames(tmp_path / "imported" / "capture.sqlite")
    assert rows and all(f.snapshot is None for f in rows)
    assert report["snapshot_causes"]["UNKNOWN_HISTORICAL_TERMS"]


@pytest.mark.parametrize("change", ["wrong_token", "future_payload", "duplicate_level", "nan"])
def test_malformed_input_never_publishes_complete_tape(tmp_path, change):
    paths = fixture(tmp_path)
    with gzip.open(paths["books"], "rt") as source:
        rows = [json.loads(line) for line in source]
    if change == "wrong_token":
        rows[0]["payload"]["asset_id"] = "999999"
    elif change == "future_payload":
        rows[0]["payload"]["timestamp"] = str(START * 1000 + 5000)
    elif change == "duplicate_level":
        rows[0]["payload"]["asks"] *= 2
    else:
        rows[0]["payload"]["asks"][0]["size"] = "NaN"
    write_json(paths["books"], rows)
    with pytest.raises(ValueError):
        run_import(tmp_path, paths)
    assert not (tmp_path / "imported" / "capture.sqlite").exists()
    assert json.loads((tmp_path / "imported" / "import.json").read_text())["status"] == "failed"


def test_truncated_gzip_and_changed_inputs_fail_visibly(tmp_path):
    paths = fixture(tmp_path)
    run_import(tmp_path, paths)
    paths["spot"].write_bytes(paths["spot"].read_bytes()[:-8])
    with pytest.raises(ValueError, match="IDENTITY_CHANGED"):
        run_import(tmp_path, paths)


@pytest.mark.parametrize("modeled", [False, True])
def test_current_six_evaluate_multiple_rounds_through_existing_study(tmp_path, modeled):
    seconds = 601
    paths = fixture(tmp_path, seconds=seconds, rounds=3)
    options = {}
    if modeled:
        exchange = tmp_path / "exchange.zip"
        binance_fixture(exchange, seconds)
        tradefile = tmp_path / "trades.gz"
        trades = []
        for second in range(seconds):
            n = second // 300
            start = START + n * 300
            for token, price in ((str(n * 2 + 1), ".79"), (str(n * 2 + 2), ".17")):
                at = (START + second) * 1000 + 350
                trades.append(
                    {
                        "slug": f"btc-updown-5m-{start}",
                        "asset_id": token,
                        "event_type": "last_trade_price",
                        "event_ts_ms": at,
                        "recv_ms": at + 50,
                        "payload": {
                            "asset_id": token,
                            "market": "0x" + f"{n + 1:064x}",
                            "timestamp": str(at),
                            "event_type": "last_trade_price",
                            "price": price,
                            "size": "1000",
                            "side": "SELL",
                            "transaction_hash": "0x" + f"{second * 2 + int(token):064x}",
                        },
                    }
                )
        write_json(tradefile, trades)
        options = {"binance": exchange, "binance_latency_ms": 75, "trades": tradefile}
    run_import(tmp_path, paths, seconds=seconds, **options)
    config = Config()
    config = replace(config, risk=replace(config.risk, allocation_usd=D(600)))
    variants = original_six_variants(config)

    async def replay():
        with Study(
            tmp_path / "imported" / "capture.sqlite",
            tmp_path / "study",
            config,
            variants=variants,
            start_ms=START * 1000,
            end_ms=(START + 600) * 1000,
        ) as study:
            while await study.advance(limit=128):
                pass
            evaluations = {}
            for runner in study.runners.values():
                rows = [
                    json.loads(r[0])
                    for r in runner.ledger.db.execute("SELECT data FROM lab_rounds")
                ]
                evaluations[runner.variant.config.strategy.mode] = rows
            assert set(evaluations) == {
                "momentum",
                "value",
                "fast_value",
                "model_exit",
                "passive_pairs",
                "inventory_pairs",
            }
            assert all(
                len(rows) >= 2 and sum(r["screens"] for r in rows) > 0
                for rows in evaluations.values()
            )
            assert sum(r["eligible"] for r in evaluations["momentum"]) > 0
            if not modeled:
                assert any(
                    reason == "FAST_MISSING"
                    for row in evaluations["fast_value"]
                    for reason in row["reasons"]
                )
            else:
                assert sum(r["eligible"] for r in evaluations["fast_value"]) > 0
                assert all(
                    runner.ledger.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0] > 0
                    for runner in study.runners.values()
                )
            assert study.report()["historical"]["complete"]
            for runner in study.runners.values():
                if runner.variant.config.strategy.mode in ("momentum", "value", "model_exit"):
                    sides = {
                        r[0]
                        for r in runner.ledger.db.execute(
                            "SELECT json_extract(data,'$.side') FROM fills"
                        )
                    }
                    assert sides == {"BUY", "SELL"}

    asyncio.run(replay())


def test_unthrottled_top_invalidates_depth_until_new_snapshot(tmp_path):
    paths = fixture(tmp_path)
    top = tmp_path / "top.gz"
    write_json(
        top,
        [
            {
                "slug": f"btc-updown-5m-{START}",
                "asset_id": "1",
                "event_type": "best_bid_ask",
                "event_ts_ms": START * 1000 + 600,
                "recv_ms": START * 1000 + 610,
                "payload": {
                    "asset_id": "1",
                    "market": "0x" + f"{1:064x}",
                    "timestamp": str(START * 1000 + 600),
                    "event_type": "best_bid_ask",
                    "best_bid": ".81",
                    "best_ask": ".82",
                },
            }
        ],
    )
    run_import(tmp_path, paths, best_bid_ask=top)
    rows = frames(tmp_path / "imported" / "capture.sqlite")
    invalid = next(f for f in rows if f.code == "HISTORICAL_DEPTH_INVALIDATED_BY_TOP")
    assert invalid.snapshot is None and invalid.research["streams"]["pending_books"]["1"]
    assert any(f.snapshot is not None and f.now_ms > invalid.now_ms for f in rows)


def test_invalid_oracle_keeps_independent_exit_books_without_trade_file(tmp_path):
    paths = fixture(tmp_path, seconds=10)
    with gzip.open(paths["spot"], "rt") as source:
        rows = list(csv.reader(source))
    rows = rows[:1] + [r for r in rows[1:] if int(r[0]) <= START * 1000]
    with gzip.open(paths["spot"], "wt") as output:
        csv.writer(output).writerows(rows)
    run_import(tmp_path, paths, seconds=10)
    frame = next(
        f
        for f in frames(tmp_path / "imported" / "capture.sqlite")
        if f.now_ms == START * 1000 + 6300
    )
    assert frame.snapshot is None and frame.code == "STALE_DATA"
    streams = frame.research["streams"]
    assert streams["books"]["1"]["received_ms"] == START * 1000 + 6200
    assert streams["books"]["2"]["received_ms"] == START * 1000 + 6200
    assert streams["trades"] == []


def test_boundary_book_does_not_reuse_old_executable_depth(tmp_path):
    paths = fixture(tmp_path)
    with gzip.open(paths["books"], "rt") as source:
        rows = [json.loads(line) for line in source]
    rows[2]["payload"]["bids"][0]["price"] = "0"
    write_json(paths["books"], rows)
    report = run_import(tmp_path, paths)
    rows = frames(tmp_path / "imported" / "capture.sqlite")
    assert any(f.snapshot is None and f.now_ms == START * 1000 + 1300 for f in rows)
    assert report["normalization"]["non_executable_books"] == 1


def test_real_boundary_trade_is_counted_without_fabricating_passive_volume(tmp_path):
    paths = fixture(tmp_path)
    tradefile = tmp_path / "trades.gz"
    at = START * 1000 + 400
    write_json(
        tradefile,
        [
            {
                "slug": f"btc-updown-5m-{START}",
                "asset_id": "1",
                "event_type": "last_trade_price",
                "event_ts_ms": at,
                "recv_ms": at + 20,
                "payload": {
                    "asset_id": "1",
                    "market": "0x" + f"{1:064x}",
                    "timestamp": str(at),
                    "event_type": "last_trade_price",
                    "side": "SELL",
                    "size": "5",
                    "price": "1",
                    "transaction_hash": "0x" + f"{1:064x}",
                },
            }
        ],
    )
    report = run_import(tmp_path, paths, trades=tradefile)
    assert report["normalization"]["non_executable_trades"] == 1
    assert all(
        not f.research["streams"]["trades"]
        for f in frames(tmp_path / "imported" / "capture.sqlite")
    )


def test_late_snapshot_cannot_override_a_newer_source_top(tmp_path):
    paths = fixture(tmp_path)
    with gzip.open(paths["books"], "rt") as source:
        books = [json.loads(line) for line in source]
    books[2]["event_ts_ms"] = START * 1000 + 500
    books[2]["payload"]["timestamp"] = str(START * 1000 + 500)
    write_json(paths["books"], books)
    top = tmp_path / "top.gz"
    write_json(
        top,
        [
            {
                "slug": f"btc-updown-5m-{START}",
                "asset_id": "1",
                "event_type": "best_bid_ask",
                "event_ts_ms": START * 1000 + 600,
                "recv_ms": START * 1000 + 610,
                "payload": {
                    "asset_id": "1",
                    "market": "0x" + f"{1:064x}",
                    "timestamp": str(START * 1000 + 600),
                    "event_type": "best_bid_ask",
                    "best_bid": ".81",
                    "best_ask": ".82",
                },
            }
        ],
    )
    run_import(tmp_path, paths, best_bid_ask=top)
    row = next(
        f
        for f in frames(tmp_path / "imported" / "capture.sqlite")
        if f.now_ms == START * 1000 + 1300
    )
    assert row.snapshot is None and row.code == "HISTORICAL_DEPTH_INVALIDATED_BY_TOP"


def binance_fixture(path, seconds):
    with zipfile.ZipFile(path, "w") as archive:
        rows = []
        for n in range(seconds * 10):
            at = START * 1000 + n * 100
            price = D(80000) + D(n // 10 % 3) + D(n) / 50
            rows.append(f"{n + 1},{price},10,{n + 1},{n + 1},{at * 1000},True,True\n")
        archive.writestr("BTCUSDT-aggTrades-2026-09-04.csv", "".join(rows))


def test_explicit_binance_receipt_model_retains_source_time_and_causality(tmp_path):
    paths = fixture(tmp_path)
    binance = tmp_path / "binance.zip"
    binance_fixture(binance, 3)
    with pytest.raises(ValueError, match="EXPLICIT_LATENCY"):
        run_import(tmp_path, paths, binance=binance)
    report = run_import(tmp_path, paths, binance=binance, binance_latency_ms=75)
    snap = next(f.snapshot for f in frames(tmp_path / "imported" / "capture.sqlite") if f.snapshot)
    assert snap.exchange_history
    assert all(
        p.received_ms - p.timestamp_ms == 75 and p.received_ms <= snap.now_ms
        for p in snap.exchange_history
    )
    assert report["capabilities"]["fast_value"] == "modeled_binance_receipts"


def test_labels_only_after_modeled_resolution_and_exact_boundary_validation(tmp_path):
    paths = fixture(tmp_path, seconds=340, rounds=2)
    with gzip.open(paths["markets"], "rt") as source:
        rows = [json.loads(line) for line in source]
    rows[0]["raw"]["umaEndDate"] = datetime.fromtimestamp(START + 310, UTC).isoformat()
    write_json(paths["markets"], rows)
    report = run_import(tmp_path, paths, seconds=340, resolution_delay_ms=20000)
    rows = frames(tmp_path / "imported" / "capture.sqlite")
    labels = [f for f in rows if f.labels]
    assert report["labels"] == 1
    assert labels and labels[0].now_ms >= (START + 330) * 1000
    assert labels[0].now_ms < (START + 331) * 1000
    assert next(iter(labels[0].labels.values()))["availability"] == "modeled_resolution_delay"


def test_raw_precision_is_preserved_beyond_default_decimal_context(tmp_path):
    paths = fixture(tmp_path)
    exact = "80000123456789123456789"
    with gzip.open(paths["spot"], "rt") as source:
        rows = list(csv.reader(source))
    for row in rows[1:]:
        row[2] = exact
    with gzip.open(paths["spot"], "wt") as output:
        csv.writer(output).writerows(rows)
    run_import(tmp_path, paths)
    snap = next(f.snapshot for f in frames(tmp_path / "imported" / "capture.sqlite") if f.snapshot)
    assert snap.spot.price == D("80000.123456789123456789")
