"""Descriptive strategy comparisons from existing paper accounting, never trade signals."""

from __future__ import annotations

import json
import random
import re
import statistics
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from btc5m.ledger import Ledger

D = Decimal
ROUND_MS = 300000
REPS = 2000


@dataclass
class RoundResult:
    slug: str
    start_ms: int
    net: Decimal
    fees: Decimal
    used: bool
    complete: bool
    observed: bool
    uncertain: bool
    traded_shares: Decimal = D(0)
    entry_price: Decimal | None = None
    entry_seconds: float | None = None
    direction: str | None = None
    exit_reason: str | None = None


def performance(rows: list[RoundResult]) -> dict[str, Any]:
    values = [r.net for r in rows]
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    n, net = len(rows), sum(values, D(0))
    fees = sum((r.fees for r in rows), D(0))
    shares = sum((r.traded_shares for r in rows), D(0))
    positive = sorted(wins, reverse=True)

    def removed(k: int) -> Decimal | None:
        count = min(k, len(positive))
        return net - sum(positive[:count], D(0)) if n > count else None

    return {
        "rounds": n,
        "flagged_rounds": sum(r.uncertain for r in rows),
        "net": net,
        "fees": fees,
        "before_fees": net + fees,
        "mean": net / n if n else None,
        "median": statistics.median(values) if n else None,
        "wins": len(wins),
        "losses": len(losses),
        "flat": n - len(wins) - len(losses),
        "win_rate": len(wins) / n if n else None,
        "average_win": sum(wins, D(0)) / len(wins) if wins else None,
        "average_loss": sum(losses, D(0)) / len(losses) if losses else None,
        "profit_factor": sum(wins, D(0)) / -sum(losses, D(0)) if losses else None,
        "best": max(values) if n else None,
        "worst": min(values) if n else None,
        "best_win_share": positive[0] / sum(positive, D(0)) if positive else None,
        "without_best_1": removed(1),
        "without_best_3": removed(3),
        "cost_headroom_per_share": net / shares if shares and net > 0 else None,
        "cost_stress": [
            {"extra_per_share": extra, "extra_cost": shares * extra, "net": net - shares * extra}
            for extra in map(D, ("0", ".0025", ".005", ".01"))
        ],
    }


def usable(row: RoundResult, cohort: str) -> bool:
    return row.observed and row.complete and (cohort == "all" or not row.uncertain)


def block_sensitivity(values: dict[int, float], *, block_rounds: int) -> dict[str, Any]:
    """Resample whole, nonoverlapping UTC blocks; never connect across missing slots.

    Percentiles describe the empirical block distribution, assuming blocks represent
    future conditions. Not selection-adjusted inference or a probability of profit.
    """
    width = block_rounds * ROUND_MS
    groups: dict[int, dict[int, float]] = defaultdict(dict)
    for stamp, value in values.items():
        groups[stamp // width * width][stamp] = value
    blocks = [
        sum(group.values())
        for start, group in sorted(groups.items())
        if set(group) == set(range(start, start + width, ROUND_MS))
    ]
    n = len(blocks)
    result: dict[str, Any] = {
        "minutes": block_rounds * 5,
        "complete_blocks": n,
        "included_rounds": n * block_rounds,
        "available_rounds": len(values),
        "interval95": None,
        "mean_per_round": sum(blocks) / (n * block_rounds) if n else None,
        "status": "too_few_blocks",
        "resamples": REPS,
    }
    if n < 6:
        return result
    if all(v == 0 for v in blocks):
        result["status"] = "no_block_variation"
        return result
    rng = random.Random(6027 + block_rounds)
    means = sorted(sum(rng.choices(blocks, k=n)) / (n * block_rounds) for _ in range(REPS))
    result.update(
        interval95=[means[int(0.025 * (REPS - 1))], means[int(0.975 * (REPS - 1))]],
        status="descriptive",
    )
    return result


def _price_group(row: RoundResult) -> str:
    p = row.entry_price
    if p is None:
        return "Unknown / conversion"
    for limit, label in ((".1", "Below 10¢"), (".3", "10–30¢"), (".7", "30–70¢"), (".9", "70–90¢")):
        if p < D(limit):
            return label
    return "90¢ or more"


def _time_group(row: RoundResult) -> str:
    if row.entry_seconds is None:
        return "Unknown / conversion"
    for limit, label in (
        (60, "Below 60s"),
        (90, "60–90s"),
        (120, "90–120s"),
        (150, "120–150s"),
        (180, "150–180s"),
    ):
        if row.entry_seconds < limit:
            return label
    return "180s or more"


def summarize(rows: list[RoundResult], *, cohort: str) -> dict[str, Any]:
    chosen = [r for r in rows if r.used and usable(r, cohort)]
    groups = {}
    group_order = {
        "entry_price": [
            "Below 10¢",
            "10–30¢",
            "30–70¢",
            "70–90¢",
            "90¢ or more",
            "Unknown / conversion",
        ],
        "entry_time": [
            "Below 60s",
            "60–90s",
            "90–120s",
            "120–150s",
            "150–180s",
            "180s or more",
            "Unknown / conversion",
        ],
    }
    for name, group_by in (
        ("entry_price", _price_group),
        ("entry_time", _time_group),
        ("direction", lambda r: r.direction or "Unknown / conversion"),
        ("exit_reason", lambda r: r.exit_reason or "Settlement / merge"),
    ):
        partition: dict[str, list[RoundResult]] = defaultdict(list)
        for row in chosen:
            partition[group_by(row)].append(row)
        labels = group_order.get(name, sorted(partition))
        groups[name] = [
            {"label": label, **performance(partition[label])}
            for label in labels
            if label in partition
        ]
    hours: dict[int, list[RoundResult]] = defaultdict(list)
    for row in rows:
        hours[row.start_ms // 3600000 * 3600000].append(row)
    hourly = []
    cumulative = D(0)
    for stamp, sample in sorted(hours.items()):
        selected = [r for r in sample if r.used and usable(r, cohort)]
        net = sum((r.net for r in selected), D(0))
        cumulative += net
        hourly.append(
            {
                "at_ms": stamp,
                "net": net,
                "cumulative": cumulative,
                "used_rounds": len(selected),
                "excluded_used": sum(r.used for r in sample) - len(selected),
                "observed_slots": sum(r.observed for r in sample),
                "flagged_rounds": sum(r.uncertain for r in selected),
            }
        )
    # Only observable completed/flat rounds enter calendar-time comparisons. Missing
    # and still-held rounds are never treated as flat returns.
    calendar = {r.start_ms: float(r.net) for r in rows if usable(r, cohort)}
    ordered = sorted(chosen, key=lambda r: (-r.net, r.start_ms))
    return {
        "stats": performance(chosen),
        "counts": {
            "observed": sum(r.observed for r in rows),
            "used": sum(r.used for r in rows),
            "flagged_used": sum(r.used and r.uncertain for r in rows),
            "incomplete_used": sum(r.used and not r.complete for r in rows),
            "flat_observed": sum(not r.used and r.observed and r.complete for r in rows),
        },
        "hourly": hourly,
        "groups": groups,
        "block_sensitivity": [block_sensitivity(calendar, block_rounds=b) for b in (6, 12)],
        "best_rounds": [asdict(r) for r in ordered[:5]],
        "worst_rounds": [asdict(r) for r in sorted(chosen, key=lambda r: (r.net, r.start_ms))[:5]],
        "rounds": [asdict(r) for r in chosen],
    }


def compare_rounds(a: list[RoundResult], b: list[RoundResult], *, cohort: str) -> dict[str, Any]:
    left, right = {r.slug: r for r in a}, {r.slug: r for r in b}
    matched = [
        (left[k], right[k])
        for k in sorted(left.keys() & right.keys())
        if usable(left[k], cohort) and usable(right[k], cohort)
    ]
    differences = {x.start_ms: float(x.net - y.net) for x, y in matched}
    active = [(x, y) for x, y in matched if x.used or y.used]
    both = sum(x.used and y.used for x, y in matched)
    xnet, ynet = sum((x.net for x, y in matched), D(0)), sum((y.net for x, y in matched), D(0))
    correlation = None
    if len(active) >= 3:
        xs, ys = [float(x.net) for x, y in active], [float(y.net) for x, y in active]
        if statistics.pvariance(xs) > 0 and statistics.pvariance(ys) > 0:
            correlation = statistics.correlation(xs, ys)
    return {
        "matched_rounds": len(matched),
        "excluded_rounds": len(left.keys() | right.keys()) - len(matched),
        "both_used": both,
        "both_flat": len(matched) - len(active),
        "selected_only": sum(x.used and not y.used for x, y in matched),
        "comparison_only": sum(y.used and not x.used for x, y in matched),
        "selected_net": xnet,
        "comparison_net": ynet,
        "difference": xnet - ynet,
        "common_used_fraction": both / len(active) if active else None,
        "active_round_correlation": correlation,
        "block_sensitivity": [block_sensitivity(differences, block_rounds=k) for k in (6, 12)],
        "series": [
            {
                "at_ms": x.start_ms,
                "selected": x.net,
                "comparison": y.net,
                "difference": x.net - y.net,
            }
            for x, y in matched
        ],
    }


def read_rounds(
    path: Path, ident: str, mode: str, phase: dict[str, Any], tape_id: str
) -> tuple[list[RoundResult], dict[str, int]]:
    ledger = Ledger(path, "0x" + ident.zfill(40), readonly=True, environment="paper")
    try:
        if ledger.environment != "paper":
            raise ValueError("PAPER_RESEARCH_ONLY")
        ledger.db.execute("BEGIN")
        identity = json.loads(ledger._meta("lab_identity") or "{}")
        if identity != {
            "variant": ident,
            "tape": tape_id,
            "start_ms": phase["start_ms"],
            "end_ms": phase.get("end_ms"),
        }:
            raise ValueError("RESEARCH_IDENTITY_MISMATCH")
        stamp = int(ledger._meta("lab_now_ms") or 0)
        cursor = int(ledger._meta("lab_cursor") or 0)
        start, end = phase["start_ms"], min(stamp, phase.get("end_ms") or stamp)
        accounts = ledger.portfolio_results()[mode]["rounds"]
        screens = {
            slug: json.loads(raw)
            for slug, raw in ledger.db.execute("SELECT slug,data FROM lab_rounds")
        }
        orders = {
            ident: json.loads(raw)
            for ident, raw in ledger.db.execute("SELECT id,data FROM intents")
        }
        fills: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
        for order_id, raw in ledger.db.execute("SELECT intent_id,data FROM fills"):
            order, fill = orders[order_id], json.loads(raw)
            fills[order["market"]["slug"]].append((order, fill))
        rows = []
        for slug in sorted(screens.keys() | accounts.keys()):
            t = int(slug.rsplit("-", 1)[1]) * 1000
            if t < start or t + ROUND_MS > end:
                continue  # ended markets only; partial current round cannot skew comparisons
            screen = screens.get(slug, {})
            account = accounts.get(slug, {})
            row = RoundResult(
                slug,
                t,
                account.get("realized_net_pnl", D(0)),
                account.get("fees", D(0)),
                bool(account.get("filled") or account.get("converted")),
                not account.get("unresolved", False),
                bool(screen.get("screens", 0)),
                screen.get("uncertain", True),
            )
            trades = sorted(fills[slug], key=lambda item: item[1]["timestamp_ms"])
            row.traded_shares = sum((D(f["quantity"]) for _, f in trades), D(0))
            buys = [(o, f) for o, f in trades if f["side"] == "BUY"]
            if buys and not account.get("converted"):
                order, fill = buys[0]
                # The first filled BUY is the entry condition, not an average of both
                # sides of an inventory strategy or an unfilled submitted limit.
                row.entry_price = D(fill["principal"]) / D(fill["quantity"])
                row.entry_seconds = (order["market"]["end_s"] * 1000 - fill["timestamp_ms"]) / 1000
                row.direction = "UP" if fill["token_id"] == order["market"]["up_token"] else "DOWN"
            exits = {o["reason"] for o, f in trades if f["side"] == "SELL"}
            row.exit_reason = ", ".join(sorted(exits)) if exits else None
            rows.append(row)
        return rows, {
            "as_of_ms": stamp,
            "cursor": cursor,
            "window_start_ms": start,
            "window_end_ms": end,
        }
    finally:
        ledger.close()


class ResearchReader:
    """Bounded selected-pair cache. No replay/writer, credential or network construction."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _document(path: Path) -> dict[str, Any]:
        with path.open("rb") as file:
            raw = file.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("RESEARCH_DOCUMENT_TOO_LARGE")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("RESEARCH_DOCUMENT_INVALID")
        return data

    def snapshot(
        self, suite: str, phase_id: str, selected: str, comparison: str, cohort: str
    ) -> dict[str, Any]:
        if suite not in ("directional", "order-flow") or cohort not in ("all", "unflagged"):
            raise ValueError("UNKNOWN_RESEARCH_FILTER")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", phase_id) or any(
            not re.fullmatch(r"[0-9a-f]{20}", i) for i in (selected, comparison)
        ):
            raise ValueError("UNKNOWN_RESEARCH_VARIANT")
        key = (suite, phase_id, selected, comparison, cohort)
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < 20:
                return cached[1]
            root = self.path / ("lab" if suite == "directional" else "order-flow-lab")
            report = self._document(root / "report.json")
            registry = self._document(root / "study.json")
            if (
                report.get("environment") != "paper-lab"
                or registry.get("environment") != "paper-lab"
            ):
                raise ValueError("PAPER_RESEARCH_ONLY")
            phases = [p for p in report["phases"] if p["id"] == phase_id]
            if not phases:
                raise ValueError("UNKNOWN_RESEARCH_PHASE")
            phase = phases[0]
            catalog = {v["ident"]: v for v in phase["variants"]}
            registered = {v["ident"] for v in registry["variants"]}
            if any(i not in catalog or i not in registered for i in (selected, comparison)):
                raise ValueError("UNKNOWN_RESEARCH_VARIANT")
            samples, clocks = [], []
            for ident in (selected, comparison):
                journal = root / phase_id / ident / "ledger.sqlite"
                if not journal.resolve().is_relative_to(root.resolve()):
                    raise ValueError("RESEARCH_PATH_OUTSIDE_STUDY")
                rows, clock = read_rounds(
                    journal,
                    ident,
                    catalog[ident]["parameters"]["mode"],
                    phase,
                    registry["tape_identity"],
                )
                samples.append(rows)
                clocks.append(clock)
            end = min(c["window_end_ms"] for c in clocks)
            samples = [[r for r in rows if r.start_ms + ROUND_MS <= end] for rows in samples]
            a, b = (catalog[i] for i in (selected, comparison))
            differences = [
                {
                    "parameter": k,
                    "selected": a["parameters"].get(k),
                    "comparison": b["parameters"].get(k),
                }
                for k in sorted(a["parameters"].keys() | b["parameters"].keys())
                if a["parameters"].get(k) != b["parameters"].get(k)
            ]
            result = {
                "environment": "paper-research",
                "generated_ms": int(time.time() * 1000),
                "suite": suite,
                "phase": phase_id,
                "phase_kind": phase["kind"],
                "cohort": cohort,
                "trial_count": report["trial_count"],
                "clocks": clocks,
                "selected": {
                    "ident": selected,
                    "label": a["label"],
                    **summarize(samples[0], cohort=cohort),
                },
                "comparison": {
                    "ident": comparison,
                    "label": b["label"],
                    **summarize(samples[1], cohort=cohort),
                },
                "matched": compare_rounds(samples[0], samples[1], cohort=cohort),
                "parameter_differences": differences,
            }
            # No non-finite JSON or Decimal loss in financial values.
            result = json.loads(json.dumps(result, default=str, allow_nan=False))
            if len(self._cache) >= 8:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.monotonic(), result)
            return result
