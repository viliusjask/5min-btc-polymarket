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
    assert ledger.open_position().quantity == D("3")
    assert ledger.open_position().cost_basis == D("2.1441")
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
    ledger.observe_account(D("97.4265"), {"up": D(5)}, (), now_ms=NOW)
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
