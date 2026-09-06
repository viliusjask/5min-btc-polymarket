"""Real SQLite crash/risk/accounting cases with synthetic confirmed receipts."""

from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_strategy import NOW, make_snapshot

from btc5m.config import Config
from btc5m.domain import Decision, Side
from btc5m.execution_types import (
    ConfirmedFill,
    OrderAck,
    OrderEvidence,
    PreparedOrder,
    ResolutionEvidence,
)
from btc5m.ledger import Ledger, LedgerError, runtime_path

WALLET = "0x1111111111111111111111111111111111111111"
HASH = "0x" + "ab" * 32


def decision():
    return Decision(
        make_snapshot().market.slug,
        Side.UP,
        "ENTRY",
        D(".70"),
        D("3.50"),
        D("3.75"),
        D("5"),
        D("5"),
        D(".0735"),
        0.9,
        0.88,
        D(".1"),
        {},
    )


def opened(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET)
    session = ledger.start_or_resume_session(Config())
    ledger.observe_account(D("100"), {}, (), now_ms=NOW)
    return ledger, session


def reserve(ledger, session, *, market=None, dec=None, now=NOW):
    return ledger.reserve_entry(dec or decision(), market or make_snapshot().market, session, now)


def prepared(intent):
    return PreparedOrder(
        intent.intent_id, HASH, '{"synthetic_signed":"private"}', D("3.75"), D("5")
    )


def submitted(ledger, session):
    intent = reserve(ledger, session)
    ledger.prepare(intent.intent_id, prepared(intent))
    ledger.mark_submitting(intent.intent_id)
    ledger.record_ack(intent.intent_id, OrderAck("accepted", HASH, ("buy",)))
    return ledger.order(intent.intent_id)


def fill(order, *, side="BUY", qty="5", principal="3.50", fee=".0735", tx="0x" + "12" * 32, log=0):
    return ConfirmedFill(
        137, tx, log, HASH, order.token_id, WALLET, side, D(qty), D(principal), D(fee), NOW
    )


def evidence(fills=(), *, terminal=True, cash=None, tokens=None, pending=(), discrepancies=()):
    return OrderEvidence(
        tuple(fills), tuple(pending), terminal, cash, tokens or {}, tuple(discrepancies)
    )


def test_receipt_cash_basis_and_deduplication_survive_restart(tmp_path):
    ledger, session = opened(tmp_path)
    buy = submitted(ledger, session)
    bought = evidence([fill(buy)], cash=D("96.4265"), tokens={"up": D("5")})
    ledger.apply_evidence(buy.intent_id, bought)
    ledger.apply_evidence(buy.intent_id, bought)
    position = ledger.open_position()
    assert position is not None
    assert position.quantity == D("5")
    assert position.cost_basis == D("3.5735")
    assert position.gross_entry_price == D(".70")
    sell = ledger.reserve_exit(position, D("2"), D(".80"), "TIME", session, NOW)
    ledger.prepare(
        sell.intent_id, replace(prepared(sell), reserved_cash=D(0), reserved_quantity=D(2))
    )
    ledger.mark_submitting(sell.intent_id)
    ledger.record_ack(sell.intent_id, OrderAck("accepted", HASH, ("sell",)))
    sold = evidence(
        [fill(sell, side="SELL", qty="2", principal="1.60", fee=".0224", log=1)],
        cash=D("98.0041"),
        tokens={"up": D("3")},
    )
    ledger.apply_evidence(sell.intent_id, sold)
    ledger.close()
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET)
    assert ledger.start_or_resume_session(Config()) == session
    ledger.apply_evidence(sell.intent_id, sold)
    remaining = ledger.open_position()
    assert remaining is not None
    assert remaining.quantity == D("3")
    assert remaining.cost_basis == D("2.1441")
    summary = ledger.summary(NOW)
    assert summary.realized_net_pnl == D(".1482")
    assert summary.cash_movement == D("-1.9959")
    assert summary.fees == D(".0959")
    assert summary.cash == D("98.0041")
    assert summary.risk_reserve == 0
    ledger.close()


@pytest.mark.parametrize("boundary", ["RESERVED", "PREPARED", "SUBMITTING", "UNKNOWN", "ACK"])
def test_restart_boundaries_never_repost_ambiguous_orders(tmp_path, boundary):
    ledger, session = opened(tmp_path)
    intent = reserve(ledger, session)
    if boundary != "RESERVED":
        ledger.prepare(intent.intent_id, prepared(intent))
    if boundary in ("SUBMITTING", "UNKNOWN", "ACK"):
        ledger.mark_submitting(intent.intent_id)
    if boundary in ("UNKNOWN", "ACK"):
        ledger.record_ack(
            intent.intent_id, OrderAck("unknown" if boundary == "UNKNOWN" else "accepted", HASH)
        )
    ledger.close()
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET)
    ledger.start_or_resume_session(Config())
    unresolved = ledger.unresolved_orders()
    if boundary in ("RESERVED", "PREPARED"):
        assert not unresolved
        assert ledger.order(intent.intent_id).reason == "ABANDONED_BEFORE_POST"
    else:
        assert len(unresolved) == 1
        ledger.apply_evidence(intent.intent_id, evidence(terminal=False))
        assert ledger.summary(NOW).risk_reserve == D("3.75")
        with pytest.raises(LedgerError):
            reserve(ledger, session)
    with pytest.raises(LedgerError):
        reserve(ledger, session)
    ledger.close()


def test_partial_opening_replaces_only_consumed_reserve(tmp_path):
    ledger, session = opened(tmp_path)
    buy = submitted(ledger, session)
    ledger.apply_evidence(
        buy.intent_id,
        evidence(
            [fill(buy, qty="2", principal="1.40", fee=".0294")], terminal=False, pending=["later"]
        ),
    )
    assert ledger.summary(NOW).risk_reserve == D("2.25")
    assert ledger.summary(NOW).position_risk == D("1.4294")
    assert ledger.order(buy.intent_id).outstanding_quantity == D("3")
    ledger.close()


def test_wrong_ack_hash_and_actual_reserve_breach_freeze_entries(tmp_path):
    ledger, session = opened(tmp_path)
    buy = submitted(ledger, session)
    ledger.record_ack(buy.intent_id, OrderAck("accepted", "0x" + "cd" * 32))
    assert ledger.order(buy.intent_id).state == "UNKNOWN"
    assert "ACK_HASH_MISMATCH" in ledger.summary(NOW).halts
    ledger.apply_evidence(buy.intent_id, evidence([fill(buy, fee=".50")]))
    assert "RESERVE_BREACH" in ledger.summary(NOW).halts
    ledger.close()


def test_unknown_exposure_forbids_config_change_and_new_session_reset(tmp_path):
    ledger, session = opened(tmp_path)
    submitted(ledger, session)
    changed = replace(Config(), risk=replace(Config().risk, max_entries_per_day=10))
    with pytest.raises(LedgerError):
        ledger.start_or_resume_session(changed)
    with pytest.raises(LedgerError):
        ledger.start_or_resume_session(Config(), new_session=True)
    ledger.close()


def test_midnight_carried_inventory_and_daily_loss_are_not_reset(tmp_path):
    config = replace(Config(), risk=replace(Config().risk, trade_budget_usd=D("10")))
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET)
    session = ledger.start_or_resume_session(config)
    ledger.observe_account(D(100), {}, (), now_ms=NOW)
    market = make_snapshot().market
    dec = replace(
        decision(),
        buy_principal=D("8"),
        max_total_reserved=D("8"),
        expected_shares=D("10"),
        minimum_receive_shares=D("10"),
    )
    buy = reserve(ledger, session, dec=dec)
    ledger.prepare(
        buy.intent_id, replace(prepared(buy), reserved_cash=D(8), reserved_quantity=D(10))
    )
    ledger.mark_submitting(buy.intent_id)
    ledger.apply_evidence(buy.intent_id, evidence([fill(buy, qty="10", principal="8", fee="0")]))
    later_market = replace(
        market, slug=market.slug + "-next", start_s=market.start_s + 300, end_s=market.end_s + 300
    )
    with pytest.raises(LedgerError):
        reserve(
            ledger,
            session,
            market=later_market,
            dec=replace(decision(), slug=later_market.slug, max_total_reserved=D(5)),
            now=NOW + 86400000,
        )
    res = ResolutionEvidence(
        market.condition_id,
        137,
        1,
        "0x" + "ef" * 32,
        1,
        (0, 1),
        ((market.up_token, D(0)), (market.down_token, D(1))),
        "CTF_FINALIZED",
        NOW,
    )
    ledger.apply_resolution(market, res, NOW)
    ledger.apply_resolution(market, res, NOW)
    with pytest.raises(LedgerError, match="LOSS_LIMIT"):
        reserve(
            ledger,
            session,
            market=later_market,
            dec=replace(decision(), slug=later_market.slug, max_total_reserved=D(5)),
        )
    assert ledger.summary(NOW).realized_net_pnl == -8
    session = ledger.start_or_resume_session(config, new_session=True)
    with pytest.raises(LedgerError, match="LOSS_LIMIT"):
        reserve(
            ledger,
            session,
            market=later_market,
            dec=replace(decision(), slug=later_market.slug, max_total_reserved=D(5)),
        )
    ledger.close()


def test_resolved_dust_remains_owned_and_claimable_is_not_cash(tmp_path):
    ledger, session = opened(tmp_path)
    buy = submitted(ledger, session)
    ledger.apply_evidence(
        buy.intent_id, evidence([fill(buy)], cash=D("96.4265"), tokens={"up": D(5)})
    )
    market = buy.market
    resolution = ResolutionEvidence(
        market.condition_id,
        137,
        1,
        "0x" + "ef" * 32,
        1,
        (1, 0),
        ((market.up_token, D(1)), (market.down_token, D(0))),
        "CTF_FINALIZED",
        NOW,
    )
    ledger.apply_resolution(market, resolution, NOW)
    ledger.apply_resolution(market, resolution, NOW)
    assert ledger.open_position() is None
    assert ledger.known_inventory() == {"up": D(5)}
    assert ledger.summary(NOW).claimable_value == 5
    assert ledger.summary(NOW).cash == D("96.4265")
    assert ledger.summary(NOW).realized_net_pnl == 0
    next_market = replace(
        market,
        slug=market.slug + "next",
        condition_id="next-condition",
        up_token="next-up",
        down_token="next-down",
        start_s=market.start_s + 300,
        end_s=market.end_s + 300,
    )
    next_intent = reserve(
        ledger, session, market=next_market, dec=replace(decision(), slug=next_market.slug)
    )
    assert next_intent.remaining_reserve == D("3.75")
    ledger.observe_account(D("97.4265"), {"up": D(5), "next-up": D(0)}, (), now_ms=NOW)
    assert "CASH_DISCREPANCY" in ledger.summary(NOW).halts
    ledger.close()


def test_resolution_does_not_release_unknown_submit(tmp_path):
    ledger, session = opened(tmp_path)
    buy = submitted(ledger, session)
    ledger.apply_evidence(
        buy.intent_id, evidence([fill(buy, qty="2", principal="1.40", fee=".0294")], terminal=False)
    )
    resolution = ResolutionEvidence(
        buy.market.condition_id,
        137,
        1,
        "0x" + "ef" * 32,
        1,
        (1, 0),
        (("up", D(1)), ("down", D(0))),
        "CTF_FINALIZED",
        NOW,
    )
    with pytest.raises(LedgerError):
        ledger.apply_resolution(buy.market, resolution, NOW)
    assert ledger.open_position() is not None
    ledger.close()


def test_single_owner_readonly_status_stop_and_private_files(tmp_path):
    ledger, session = opened(tmp_path)
    with pytest.raises(LedgerError, match="LOCKED"):
        Ledger(tmp_path / "ledger.sqlite", WALLET.upper())
    reader = Ledger(tmp_path / "ledger.sqlite", WALLET, readonly=True)
    assert reader.summary(NOW).cash == 100
    Ledger.request_stop_at(tmp_path / "ledger.sqlite")
    assert ledger.stop_requested()
    for path in tmp_path.iterdir():
        assert path.stat().st_mode & 0o077 == 0
    assert "synthetic_signed" not in repr(ledger.summary(NOW))
    reader.close()
    ledger.close()


def test_common_root_runtime_identity_matches_worktrees(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path / "repo")], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path / "repo"),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "init",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path / "repo"),
            "worktree",
            "add",
            "-qb",
            "feature",
            str(tmp_path / "tree"),
        ],
        check=True,
    )
    assert runtime_path(tmp_path / "repo", WALLET) == runtime_path(
        tmp_path / "tree", WALLET.upper()
    )


def test_transient_reconciliation_error_clears_after_complete_evidence(tmp_path):
    ledger, session = opened(tmp_path)
    buy = submitted(ledger, session)
    ledger.apply_evidence(
        buy.intent_id, evidence(terminal=False, discrepancies=("ACCOUNT_READ_FAILED",))
    )
    assert "ACCOUNT_READ_FAILED" in ledger.summary(NOW).halts
    ledger.apply_evidence(
        buy.intent_id, evidence([fill(buy)], cash=D("96.4265"), tokens={"up": D(5)})
    )
    assert "ACCOUNT_READ_FAILED" not in ledger.summary(NOW).halts
    ledger.close()


def test_provisional_balance_difference_cannot_become_profit_and_clears_when_explained(tmp_path):
    ledger, session = opened(tmp_path)
    buy = submitted(ledger, session)
    ledger.apply_evidence(
        buy.intent_id,
        evidence(terminal=False, cash=D("96.4265"), tokens={"up": D(5)}, pending=("buy",)),
    )
    assert ledger.summary(NOW).cash == 100 and ledger.summary(NOW).realized_net_pnl == 0
    ledger.apply_evidence(
        buy.intent_id, evidence([fill(buy)], cash=D("96.4265"), tokens={"up": D(5)})
    )
    assert not ledger.summary(NOW).halts
    ledger.close()


@pytest.mark.parametrize("boundary", ["RESERVED", "PREPARED", "SUBMITTING", "UNKNOWN", "ACK"])
def test_sigkill_after_each_committed_boundary_retains_exact_risk(tmp_path, boundary):
    import subprocess
    import sys

    script = """
import os, signal, sys
from pathlib import Path
sys.path.insert(0, 'tests')
from test_ledger import opened,reserve,prepared,HASH
from btc5m.execution_types import OrderAck
ledger,session=opened(Path(sys.argv[1]))
intent=reserve(ledger,session)
if sys.argv[2]!='RESERVED': ledger.prepare(intent.intent_id,prepared(intent))
if sys.argv[2] in ('SUBMITTING','UNKNOWN','ACK'): ledger.mark_submitting(intent.intent_id)
if sys.argv[2] in ('UNKNOWN','ACK'): ledger.record_ack(intent.intent_id,OrderAck('unknown' if sys.argv[2]=='UNKNOWN' else 'accepted',HASH))
os.kill(os.getpid(),signal.SIGKILL)
"""
    killed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), boundary], capture_output=True, text=True
    )
    assert killed.returncode == -9, killed.stderr
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET)
    ledger.start_or_resume_session(Config())
    summary = ledger.summary(NOW)
    assert summary.risk_reserve == (
        D("3.75") if boundary in ("SUBMITTING", "UNKNOWN", "ACK") else 0
    )
    assert summary.daily_entries == 1 and summary.cash == 100
    ledger.close()


def test_batch_fill_identity_error_rolls_back_every_cash_and_position_change(tmp_path):
    ledger, session = opened(tmp_path)
    buy = submitted(ledger, session)
    with pytest.raises(LedgerError):
        ledger.apply_evidence(
            buy.intent_id, evidence([fill(buy), replace(fill(buy, log=1), chain_id=1)])
        )
    assert ledger.open_position() is None
    assert ledger.summary(NOW).cash == 100 and ledger.summary(NOW).risk_reserve == D("3.75")
    ledger.close()


def test_daily_entry_count_and_cash_gate_are_independent_of_realized_profit(tmp_path):
    config = replace(Config(), risk=replace(Config().risk, max_entries_per_day=1))
    ledger = Ledger(tmp_path / "ledger.sqlite", WALLET)
    session = ledger.start_or_resume_session(config)
    ledger.observe_account(D(2), {}, (), now_ms=NOW)
    with pytest.raises(LedgerError, match="INSUFFICIENT_CASH"):
        reserve(ledger, session)
    ledger.close()
    ledger, session = opened(tmp_path / "second")
    session = ledger.start_or_resume_session(config)
    intent = reserve(ledger, session)
    ledger.abandon(intent.intent_id, "SYNTHETIC_LOCAL_ABORT")
    other = replace(intent.market, slug=intent.market.slug + "next")
    with pytest.raises(LedgerError, match="DAILY_ENTRY_LIMIT"):
        reserve(ledger, session, market=other, dec=replace(decision(), slug=other.slug))
    ledger.close()


def test_only_explicit_owner_start_clears_stop_and_later_stop_survives(tmp_path):
    ledger, session = opened(tmp_path)
    ledger.request_stop()
    ledger.start_or_resume_session(Config())
    assert ledger.stop_requested()
    ledger.clear_stop_request()
    assert not ledger.stop_requested()
    Ledger.request_stop_at(ledger.path)
    ledger.start_or_resume_session(Config())
    assert ledger.stop_requested()
    reader = Ledger(ledger.path, WALLET, readonly=True)
    with pytest.raises(LedgerError):
        reader.clear_stop_request()
    reader.close()
    ledger.close()


def test_resolution_waits_for_explained_account_balances(tmp_path):
    ledger, session = opened(tmp_path)
    buy = submitted(ledger, session)
    ledger.apply_evidence(
        buy.intent_id, evidence([fill(buy)], cash=D("96.4265"), tokens={"up": D(5)})
    )
    ledger.observe_account(D("90"), {"up": D(5)}, (), now_ms=NOW)
    resolution = ResolutionEvidence(
        buy.market.condition_id,
        137,
        1,
        "0x" + "ef" * 32,
        1,
        (1, 0),
        (("up", D(1)), ("down", D(0))),
        "CTF_FINALIZED",
        NOW,
    )
    with pytest.raises(LedgerError, match="RESOLUTION_ACCOUNT_UNCERTAINTY"):
        ledger.apply_resolution(buy.market, resolution, NOW)
    assert ledger.open_position() is not None
    ledger.close()


def test_preparation_commits_the_domain_and_keeps_signed_payload_out_of_status(tmp_path):
    import json
    import sqlite3

    ledger, session = opened(tmp_path)
    intent = reserve(ledger, session)
    ledger.prepare(intent.intent_id, prepared(intent))
    external = sqlite3.connect(ledger.path)
    record = json.loads(
        external.execute("SELECT data FROM events WHERE kind='PREPARED'").fetchone()[0]
    )
    assert record["signing_domain"] == {
        "name": "Polymarket CTF Exchange",
        "version": "2",
        "chain_id": 137,
        "exchange": "0xE111180000d2663C0091e4f400237545B87B996B",
    }
    assert (
        external.execute(
            "SELECT signed_payload FROM intents WHERE id=?", (intent.intent_id,)
        ).fetchone()[0]
        == prepared(intent).signed_payload
    )
    assert "synthetic_signed" not in repr(ledger.summary(NOW))
    external.close()
    ledger.close()


def test_exit_cannot_assign_realized_pnl_to_an_unknown_session(tmp_path):
    ledger, session = opened(tmp_path)
    buy = submitted(ledger, session)
    ledger.apply_evidence(buy.intent_id, evidence([fill(buy)]))
    with pytest.raises(LedgerError, match="SESSION_REQUIRED"):
        ledger.reserve_exit(
            ledger.open_position(), D(2), D(".8"), "TIME", "unrecognized-session", NOW
        )
    ledger.close()


def test_readonly_decisions_exposes_paired_screens_without_private_execution_data(tmp_path):
    from dataclasses import asdict

    from test_strategy import make_snapshot

    ledger, session = opened(tmp_path)
    intent = ledger.reserve_entry(decision(), make_snapshot().market, session, NOW)
    ledger.prepare(
        intent.intent_id,
        PreparedOrder(intent.intent_id, HASH, "REPLAYABLE_PRIVATE_PAYLOAD", D("3.75"), D(5)),
    )
    decisions = ledger.record_snapshot(make_snapshot(), Config())
    reader = Ledger(ledger.path, WALLET, readonly=True)
    rows = reader.decisions()
    assert tuple(row["mode"] for row in rows) == ("value", "momentum")
    assert tuple(row["decision"]["reason"] for row in rows) == tuple(d.reason for d in decisions)
    assert all(row["config_fingerprint"] == Config().fingerprint for row in rows)
    assert "REPLAYABLE_PRIVATE_PAYLOAD" not in str(rows)
    assert "signed_payload" not in str(rows) and "signature" not in str(rows)
    assert set(rows[0]["decision"]) == set(asdict(decisions[0]))
    reader.close()
    ledger.close()


@pytest.mark.parametrize("existing_transaction", [False, True])
def test_summary_observes_one_snapshot_during_concurrent_settlement(
    tmp_path, monkeypatch, existing_transaction
):
    writer, session = opened(tmp_path)
    buy = submitted(writer, session)
    reader = Ledger(writer.path, WALLET, readonly=True)
    if existing_transaction:
        reader.db.execute("BEGIN")
    original_positions = reader.positions
    committed = False

    def positions_then_settle():
        nonlocal committed
        positions = original_positions()
        if not committed:
            writer.apply_evidence(
                buy.intent_id, evidence([fill(buy)], cash=D("96.4265"), tokens={"up": D(5)})
            )
            committed = True
        return positions

    monkeypatch.setattr(reader, "positions", positions_then_settle)
    summary = reader.summary(NOW)
    assert committed and writer.open_position().quantity == 5
    assert summary.cash == 100 and not summary.inventory
    assert len(summary.unresolved_orders) == 1 and summary.risk_reserve == D("3.75")
    assert summary.position_risk == 0 and summary.fees == 0
    assert reader.db.in_transaction is existing_transaction
    if existing_transaction:
        assert reader.summary(NOW) == summary
        reader.db.rollback()
    current = reader.summary(NOW)
    assert current.cash == D("96.4265") and current.inventory[0].quantity == 5
    assert not current.unresolved_orders and current.risk_reserve == 0
    assert current.position_risk == D("3.5735")
    reader.close()
    writer.close()


def test_summary_does_not_commit_callers_uncommitted_write(tmp_path):
    ledger, _ = opened(tmp_path)
    reader = Ledger(ledger.path, WALLET, readonly=True)
    ledger.db.execute("UPDATE meta SET value='101' WHERE key='initial_cash'")
    assert ledger.summary(NOW).cash == 101
    assert ledger.db.in_transaction and reader.summary(NOW).cash == 100
    ledger.db.rollback()
    assert ledger.summary(NOW).cash == 100
    reader.close()
    ledger.close()


def test_initial_close_reason_survives_later_control_and_resolution_problems(tmp_path):
    ledger, session = opened(tmp_path)
    buy = submitted(ledger, session)
    ledger.apply_evidence(buy.intent_id, evidence([fill(buy)]))
    ledger.note_exit(buy.position_id, "STOP", None, NOW)
    ledger.note_exit(buy.position_id, "SHUTDOWN", "NO_EXIT_BOOK", NOW + 1000)
    ledger.note_exit(buy.position_id, "RESOLUTION", "RESOLUTION_UNCONFIRMED", NOW + 2000)
    position = ledger.open_position()
    assert position.exit_reason == "STOP" and position.exit_problem == "RESOLUTION_UNCONFIRMED"
    ledger.close()


def test_metadata_diagnostics_accept_only_normalized_public_comparisons(tmp_path):
    ledger = Ledger(tmp_path / "diagnostic.sqlite", WALLET)
    public = {
        "kind": "metadata_rejected",
        "received_ms": NOW,
        "slug": make_snapshot().market.slug,
        "condition_id": make_snapshot().market.condition_id,
        "token_id": "123456789",
        "endpoint": "https://clob.polymarket.com/book",
        "compared_field": "tick_size",
        "expected": D(".01"),
        "actual": D(".001"),
        "supported_ticks": (D(".01"), D(".001")),
        "signed_payload": "secret",
        "api_key": "secret",
    }
    ledger.record_observation(public)
    row = ledger.observations()[0]
    assert row["expected"] == "0.01" and row["actual"] == "0.001"
    assert row["supported_ticks"] == ["0.01", "0.001"]
    assert "signed_payload" not in row and "api_key" not in row
    with pytest.raises(LedgerError, match="INVALID_PUBLIC_OBSERVATION"):
        ledger.record_observation(public | {"actual": {"arbitrary": "payload"}})
    ledger.record_observation({"kind": "other", "received_ms": NOW, "expected": "unrelated"})
    assert "expected" not in ledger.observations()[-1]
    ledger.close()
