"""Small dashboard read models from real paper journal accounting."""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from typing import Any

from btc5m.lab_replay import Replay

D = Decimal


def replay_report(replay: Replay, *, before_ms: int | None = None) -> dict[str, Any]:
    ledger, variant = replay.ledger, replay.variant
    result = ledger.portfolio_results()[variant.config.strategy.mode]
    rows = {
        slug: json.loads(raw) for slug, raw in ledger.db.execute("SELECT slug,data FROM lab_rounds")
    }

    def in_window(slug: str) -> bool:
        return before_ms is None or int(slug.rsplit("-", 1)[1]) * 1000 < before_ms

    rounds = {slug: row for slug, row in result["rounds"].items() if in_window(slug)}
    screens = [row for slug, row in rows.items() if in_window(slug)]
    completed = {
        slug: row for slug, row in rounds.items() if row["filled"] and not row["unresolved"]
    }
    clean = {
        slug: row
        for slug, row in completed.items()
        if not rows.get(slug, {}).get("uncertain", True)
    }
    events: Counter[str] = Counter()
    for row in screens:
        events.update(row["execution"])
    reasons: Counter[str] = Counter()
    for row in screens:
        reasons.update(row["reasons"])
    orders = []
    outcomes: Counter[str] = Counter()
    for raw, state in ledger.db.execute(
        "SELECT i.data,m.data FROM intents i LEFT JOIN measurements m ON m.key='paper_order:'||i.id ORDER BY json_extract(i.data,'$.created_ms')"
    ):
        order = json.loads(raw)
        if not in_window(order["market"]["slug"]):
            continue
        paper = json.loads(state) if state else {}
        outcome = paper.get("terminal_reason") or order["submission_reason"] or order["reason"]
        outcomes[outcome] += 1
        orders.append(
            {
                "id": order["intent_id"],
                "at_ms": order["created_ms"],
                "slug": order["market"]["slug"],
                "side": order["side"],
                "outcome_side": order["decision"]["side"] if order["decision"] else None,
                "limit": order["price_limit"],
                "principal": order["principal"],
                "filled_principal": order["confirmed_principal"],
                "filled_shares": order["confirmed_quantity"],
                "fee": order["confirmed_fee"],
                "state": order["state"],
                "reason": outcome,
                "exit_trigger": order["reason"] if order["side"] == "SELL" else None,
                "execution_check": paper.get("execution_check"),
            }
        )
    confirmations = {
        slug
        for (slug,) in ledger.db.execute(
            "SELECT DISTINCT json_extract(data,'$.slug') FROM events WHERE kind='PUBLIC_OBSERVATION' AND json_extract(data,'$.kind')='execution_confirmation' AND json_extract(data,'$.status')='confirmed'"
        )
        if slug and in_window(slug)
    }
    marks = [
        (stamp, D(value) if value is not None else None)
        for stamp, value in ledger.db.execute("SELECT at_ms,equity FROM lab_equity ORDER BY bucket")
        if before_ms is None or stamp < before_ms
    ]
    peak, drawdown, missing = variant.config.risk.allocation_usd, D(0), 0
    for _, value in marks:
        if value is None:
            missing += 1
            continue
        peak = max(peak, value)
        drawdown = max(drawdown, peak - value)
    days: dict[str, Decimal] = {}
    for slug, row in clean.items():
        from datetime import UTC, datetime

        day = datetime.fromtimestamp(int(slug.rsplit("-", 1)[1]), UTC).date().isoformat()
        days[day] = days.get(day, D(0)) + row["realized_net_pnl"]
    summary = ledger.summary(replay.now_ms)
    opening = [o for o in orders if o["side"] == "BUY"]
    filled_opening = [o for o in opening if D(o["filled_shares"]) > 0]
    clean_pnl = sum((r["realized_net_pnl"] for r in clean.values()), D(0))
    realized = sum((r["realized_net_pnl"] for r in rounds.values()), D(0))
    stride = max(1, len(marks) // 240)
    series = marks[::stride]
    if marks and series[-1] != marks[-1]:
        series.append(marks[-1])
    return {
        "ident": variant.ident,
        "name": variant.name,
        "label": variant.label,
        "family": variant.family,
        "parameters": {
            "mode": variant.config.strategy.mode,
            "lead_usd": variant.config.strategy.momentum_min_move_usd,
            "entry_min_seconds": variant.config.strategy.momentum_min_seconds
            if variant.config.strategy.mode == "momentum"
            else variant.config.strategy.entry_min_seconds,
            "entry_max_seconds": variant.config.strategy.momentum_max_seconds
            if variant.config.strategy.mode == "momentum"
            else variant.config.strategy.entry_max_seconds,
            "surplus": variant.config.strategy.min_terminal_surplus,
            "signal": variant.signal,
            "signal_threshold": variant.threshold,
            "lookback_seconds": variant.lookback_seconds,
            "exit_policy": variant.exit_policy,
            "stop_per_share": variant.config.execution.stop_loss_per_share,
            "scenario": variant.scenario,
            "adverse_reference_usd": variant.config.strategy.adverse_reference_usd,
            "latency_ms": variant.config.experiments.paper_latency_ms,
        },
        "cursor": replay.cursor,
        "as_of_ms": replay.now_ms,
        "allocation": variant.config.risk.allocation_usd,
        "trade_budget": variant.config.risk.trade_budget_usd,
        "cash": summary.cash,
        "reserved": summary.risk_reserve,
        "open_basis": result["open_cost_basis"],
        "halts": summary.halts,
        "realized_pnl": realized,
        "fees": sum((r["fees"] for r in rounds.values()), D(0)),
        "clean_completed_pnl": clean_pnl,
        "clean_completed_roi": clean_pnl / variant.config.risk.allocation_usd,
        "completed_rounds": len(completed),
        "clean_completed_rounds": len(clean),
        "filled_rounds": sum(r["filled"] for r in rounds.values()),
        "unresolved_rounds": sum(r["unresolved"] for r in rounds.values()),
        "uncertain_rounds": sum(r.get("uncertain", False) for r in screens),
        "observed_rounds": sum(r["screens"] > 0 for r in screens),
        "funnel": {
            "screens": sum(r["screens"] for r in screens),
            "eligible_checks": sum(r["eligible"] for r in screens),
            "eligible_rounds": sum(r["eligible"] > 0 for r in screens),
            "confirmed_rounds": len(confirmations),
            "opening_orders": len(opening),
            "filled_opening_orders": len(filled_opening),
            "sell_orders": len(orders) - len(opening),
            "completed_rounds": len(completed),
        },
        "fill_rate": len(filled_opening) / len(opening) if opening else None,
        "equity": marks[-1][1] if marks else None,
        "observed_drawdown": drawdown if marks else None,
        "missing_equity_marks": missing,
        "equity_series": series,
        "day_pnl": days,
        "reasons": dict(reasons),
        "execution": dict(events),
        "order_outcomes": dict(outcomes),
        "orders": orders[-50:],
        "evidence": "insufficient sample"
        if len(clean) < 30
        else "exploratory; later test required",
    }
