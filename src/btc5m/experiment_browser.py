"""One read-only catalog of independent paper experiments and their evidence.

Saved study reports supply wallet totals. Round statistics reuse research accounting,
with a cache keyed by financial changes, not the collector's ever-changing cursor.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from btc5m.capture_quality import read_quality
from btc5m.config import STRATEGIES
from btc5m.ledger import LedgerError
from btc5m.research import (
    ROUND_MS,
    ResearchReader,
    RoundResult,
    performance,
    read_rounds,
    summarize,
)

if TYPE_CHECKING:
    from btc5m.dashboard import DashboardReader

D = Decimal
READ_ERRORS = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    ArithmeticError,
    sqlite3.Error,
    LedgerError,
)
SOURCES = {"directional": "lab", "order-flow": "order-flow-lab"}


def decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    result = D(str(value))
    if not result.is_finite():
        raise ValueError("NONFINITE_EXPERIMENT_VALUE")
    return result


def experiment_metrics(
    samples: list[RoundResult] | None,
    *,
    allocation: Decimal | None,
    realized: Decimal | None,
    drawdown: Decimal | None,
) -> dict[str, Any]:
    result = {}
    for cohort in ("all", "unflagged"):
        chosen = [
            r
            for r in samples or []
            if r.used and r.complete and r.observed and (cohort == "all" or not r.uncertain)
        ]
        stats = performance(chosen)
        result[cohort] = {
            "net": realized if cohort == "all" else stats["net"] if samples is not None else None,
            # This denominator and numerator deliberately do not change with the cohort.
            "return": realized / allocation if realized is not None and allocation else None,
            "completed_net": stats["net"] if samples is not None else None,
            "completed": stats["rounds"] if samples is not None else None,
            "mean": stats["mean"] if samples is not None else None,
            "win_rate": stats["win_rate"] if samples is not None else None,
            "best": max((r.net for r in chosen if r.net > 0), default=None),
            "drawdown": drawdown,
        }
    return result


def completed_curve(samples: list[RoundResult], cohort: str) -> list[list[Any]]:
    total = D(0)
    points: list[list[Any]] = []
    for row in sorted(samples, key=lambda r: r.start_ms):
        if not (row.used and row.complete and row.observed) or (
            cohort == "unflagged" and row.uncertain
        ):
            continue
        total += row.net
        points.append([row.start_ms + ROUND_MS, total])
    if len(points) <= 1200:
        return points
    # Retain both endpoints and each consecutive group's min/max, including
    # large winning/loss spikes. Sampling never changes financial totals.
    stride = (len(points) - 2 + 598) // 599
    retained = [points[0]]
    for start in range(1, len(points) - 1, stride):
        group = points[start : min(start + stride, len(points) - 1)]
        extreme = sorted(
            {
                min(range(len(group)), key=lambda i: group[i][1]),
                max(range(len(group)), key=lambda i: group[i][1]),
            }
        )
        retained.extend(group[i] for i in extreme)
    return [*retained, points[-1]]


def paper_rounds(portfolio: dict[str, Any]) -> list[RoundResult]:
    """Reuse portfolio_results; missing no-trade calendar slots stay unknown."""
    rows = []
    for slug, raw in portfolio.get("rounds", {}).items():
        match = re.fullmatch(r"btc-updown-5m-(\d+)", slug)
        if not match:
            continue
        row = RoundResult(
            slug,
            int(match[1]) * 1000,
            D(raw["realized_net_pnl"]),
            D(raw["fees"]),
            bool(raw.get("filled") or raw.get("converted")),
            not raw["unresolved"],
            True,
            slug in portfolio.get("uncertain_rounds", []),
        )
        rows.append(row)
    return rows


def public_json(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, allow_nan=False))


class ExperimentBrowser:
    """Thirty-second catalog cache; unchanged financial rows never reread a journal."""

    def __init__(self, paper: DashboardReader) -> None:
        self.paper, self.path = paper, paper.path
        self._lock = threading.RLock()
        self._loaded = -float("inf")
        self._snapshot: dict[str, Any] | None = None
        self._entries: dict[str, dict[str, Any]] = {}
        self._samples: dict[str, tuple[str, list[RoundResult], dict[str, int]]] = {}
        self._details: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    def _studies(self, source: str, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
        root = self.path / SOURCES[source]
        if not root.exists():
            return []
        report: dict[str, Any] = {}
        registry: dict[str, Any] = {}
        for name in ("study", "report"):
            try:
                data = ResearchReader._document(root / (name + ".json"))
                if data.get("environment") != "paper-lab":
                    raise ValueError("PAPER_EXPERIMENTS_ONLY")
                if name == "study":
                    registry = data
                else:
                    report = data
            except READ_ERRORS:
                errors.append({"source": source, "error": name.upper() + "_UNAVAILABLE"})
        registered = {v["ident"]: v for v in registry.get("variants", [])}
        phases = {p["id"]: p for p in report.get("phases", [])}
        # The registration survives a failed/partial report. Preserve all registered
        # later-data phases from the small study catalog, without opening variant journals.
        if registry:
            try:
                catalog = root / "study.sqlite"
                if catalog.exists():
                    with sqlite3.connect(
                        catalog.resolve().as_uri() + "?mode=ro", uri=True, timeout=2
                    ) as db:
                        for (raw,) in db.execute("SELECT data FROM phases LIMIT 256"):
                            if len(raw) > 16 * 1024 * 1024:
                                raise ValueError("PHASE_TOO_LARGE")
                            phase = json.loads(raw)
                            phases.setdefault(phase["id"], phase)
            except READ_ERRORS:
                errors.append({"source": source, "error": "PHASE_CATALOG_UNAVAILABLE"})
            phases.setdefault(
                "explore",
                {
                    "id": "explore",
                    "kind": "exploratory",
                    "start_ms": registry.get("start_ms"),
                    "variant_ids": list(registered),
                },
            )
        entries = []
        for phase_id, phase in phases.items():
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", phase_id):
                raise ValueError("INVALID_EXPERIMENT_PHASE")
            variants = {v["ident"]: v for v in phase.get("variants", [])}
            ids = list(
                dict.fromkeys(
                    [
                        *phase.get("variant_ids", []),
                        *variants,
                        *(registered if phase_id == "explore" else []),
                    ]
                )
            )
            for ident in ids:
                if not re.fullmatch(r"[0-9a-f]{20}", ident):
                    raise ValueError("INVALID_EXPERIMENT_IDENT")
                definition = registered.get(ident, {})
                raw = variants.get(ident)
                if raw is not None:
                    try:
                        for field in ("allocation", "realized_pnl", "fees", "observed_drawdown"):
                            decimal(raw.get(field))
                    except READ_ERRORS:
                        errors.append(
                            {"source": source, "error": "VARIANT_REPORT_INVALID:" + ident}
                        )
                        raw = None
                # A report without its registration can display reported totals, but
                # must not authorize opening an arbitrary journal path.
                entries.append(
                    {
                        "key": f"{source}:{phase_id}:{ident}",
                        "source": source,
                        "ident": ident,
                        "phase": phase_id,
                        "phase_kind": phase.get("kind", "unknown"),
                        "label": (raw or definition).get("label", ident),
                        "family": (raw or definition).get("family", "unknown"),
                        "version": phase.get("implementation")
                        or registry.get("implementation")
                        or report.get("implementation"),
                        "start_ms": phase.get("start_ms"),
                        "end_ms": phase.get("end_ms"),
                        "raw": raw,
                        "definition": definition,
                        "phase_definition": phase,
                        "registry": registry,
                        "report": report,
                    }
                )
        return entries

    def _rounds(self, entry: dict[str, Any]) -> tuple[list[RoundResult], dict[str, int]]:
        raw = entry["raw"]
        if entry["source"] == "paper":
            return paper_rounds(raw), {
                "as_of_ms": entry["as_of_ms"],
                "window_start_ms": entry["start_ms"],
                "window_end_ms": entry["as_of_ms"],
            }
        if not raw or not entry["definition"]:
            raise ValueError("EXPERIMENT_REGISTRATION_OR_REPORT_UNAVAILABLE")
        root = self.path / SOURCES[entry["source"]]
        journal = root / entry["phase"] / entry["ident"] / "ledger.sqlite"
        if not journal.resolve().is_relative_to(root.resolve()):
            raise ValueError("EXPERIMENT_PATH_OUTSIDE_STUDY")
        mode = (
            raw.get("parameters", {}).get("mode")
            or entry["definition"]["config"]["strategy"]["mode"]
        )
        return read_rounds(
            journal,
            entry["ident"],
            mode,
            entry["phase_definition"],
            entry["registry"]["tape_identity"],
        )

    @staticmethod
    def _report_matches(entry: dict[str, Any], samples: list[RoundResult]) -> bool:
        if entry["source"] == "paper":
            return True
        raw = entry["raw"] or {}
        completed = [r for r in samples if r.used and r.complete and r.observed]
        clean = [r for r in completed if not r.uncertain]
        checks = {
            "completed_rounds": len(completed),
            "clean_completed_rounds": len(clean),
            "clean_completed_pnl": sum((r.net for r in clean), D(0)),
        }
        if raw.get("unresolved_rounds") == 0:
            checks["realized_pnl"] = sum((r.net for r in samples if r.used), D(0))
        return all(decimal(raw[k]) == decimal(value) for k, value in checks.items() if k in raw)

    def _statistics(self, entry: dict[str, Any]) -> tuple[list[RoundResult], dict[str, int]]:
        raw = entry["raw"] or {}
        if entry["source"] == "paper":
            return self._rounds(entry)
        fields = (
            "completed_rounds",
            "clean_completed_rounds",
            "clean_completed_pnl",
            "realized_pnl",
            "fees",
            "uncertain_rounds",
            "unresolved_rounds",
            "deployed_rounds",
            "filled_rounds",
        )
        signature = json.dumps(
            [entry["version"], entry["start_ms"], entry["end_ms"], *[raw.get(k) for k in fields]]
        )
        cached = self._samples.get(entry["key"])
        if cached and cached[0] == signature:
            return cached[1], cached[2]
        rows, clock = self._rounds(entry)
        if not self._report_matches(entry, rows):
            raise ValueError("REPORT_JOURNAL_BOUNDARY_MISMATCH")
        self._samples[entry["key"]] = (signature, rows, clock)
        return rows, clock

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._snapshot is not None and time.monotonic() - self._loaded < 30:
                return self._snapshot
            errors: list[dict[str, str]] = []
            paper: dict[str, Any] = {}
            try:
                paper = self.paper.snapshot()
            except READ_ERRORS:
                errors.append({"source": "paper", "error": "PAPER_UNAVAILABLE"})
            manifest = paper.get("manifest", {})
            entries = []
            for name in manifest.get("strategies", STRATEGIES):
                entries.append(
                    {
                        "key": "paper:" + name,
                        "source": "paper",
                        "ident": name,
                        "label": name.replace("_", " ").title(),
                        "family": name,
                        "phase": "original",
                        "phase_kind": "continuous",
                        "version": manifest.get("config_fingerprint"),
                        "policy_change": paper.get("policy_change"),
                        "start_ms": paper.get("collector", {}).get("first_ms"),
                        "end_ms": None,
                        "as_of_ms": paper.get("generated_ms"),
                        "raw": paper.get("portfolios", {}).get(name),
                        "definition": {
                            "config": paper.get("portfolios", {}).get(name, {}).get("configuration")
                            or {}
                        },
                        "paper": paper,
                    }
                )
            for source in SOURCES:
                try:
                    entries.extend(self._studies(source, errors))
                except READ_ERRORS:
                    errors.append({"source": source, "error": "CATALOG_UNAVAILABLE"})
            rows = []
            for entry in entries:
                raw = entry["raw"] or {}
                source = entry["source"]
                samples: list[RoundResult] | None = None
                clock: dict[str, int] = {}
                failure = None
                try:
                    if entry["raw"] is not None:
                        samples, clock = self._statistics(entry)
                except READ_ERRORS as exc:
                    failure = (
                        "REPORT_JOURNAL_BOUNDARY_MISMATCH"
                        if str(exc) == "REPORT_JOURNAL_BOUNDARY_MISMATCH"
                        else "ROUND_STATISTICS_UNAVAILABLE"
                    )
                allocation = decimal(raw.get("allocation"))
                realized = decimal(
                    raw.get("realized_net_pnl" if source == "paper" else "realized_pnl")
                )
                risk = entry["definition"].get("config", {}).get("risk", {})
                execution = raw.get("execution", {})
                if source == "paper":
                    latest = raw.get("last_execution") or {}
                    execution = {**execution, latest.get("code", latest.get("reason", "")): 1}
                metrics = experiment_metrics(
                    samples,
                    allocation=allocation,
                    realized=realized,
                    drawdown=decimal(raw.get("observed_drawdown")),
                )
                row = {
                    k: entry[k]
                    for k in (
                        "key",
                        "source",
                        "ident",
                        "label",
                        "family",
                        "phase",
                        "phase_kind",
                        "version",
                        "start_ms",
                        "end_ms",
                    )
                }
                row.update(
                    status="unavailable"
                    if entry["raw"] is None
                    else "halted"
                    if raw.get("halts")
                    else "no_fills"
                    if not any(r.used for r in samples or []) and samples is not None
                    else "recorded",
                    statistics_error=failure,
                    metrics=metrics,
                    allocation=allocation,
                    fees=raw.get("fees"),
                    cash=raw.get("cash"),
                    equity=raw.get("equity"),
                    held_cost=raw.get("open_cost_basis" if source == "paper" else "open_basis"),
                    unresolved=raw.get(
                        "unresolved_orders" if source == "paper" else "unresolved_rounds"
                    ),
                    flagged_completed=sum(r.used and r.complete and r.uncertain for r in samples)
                    if samples is not None
                    else None,
                    flagged_observed=len(raw.get("uncertain_rounds", []))
                    if source == "paper"
                    else raw.get("uncertain_rounds"),
                    sample_as_of_ms=clock.get("as_of_ms"),
                    as_of_ms=entry.get("as_of_ms") if source == "paper" else raw.get("as_of_ms"),
                    report_generated_ms=paper.get("generated_ms")
                    if source == "paper"
                    else entry["report"].get("generated_ms"),
                    risk_limits=risk,
                    blocked_reasons=list(raw.get("halts", [])),
                    budget_rejections=execution.get("LOSS_LIMIT", 0),
                    latest_execution=raw.get("last_execution"),
                    parameters=raw.get("parameters", {}),
                    missing_equity_marks=raw.get("missing_equity_marks"),
                    policy_note=(
                        "Continuous journal includes earlier policies; current configuration fingerprint does not identify every historical trade."
                        if source == "paper"
                        else "Registered implementation is pinned for this phase; original Momentum controls can differ from current original portfolios."
                    ),
                    curves={
                        c: completed_curve(samples, c) if samples is not None else []
                        for c in ("all", "unflagged")
                    },
                )
                rows.append(row)
            current_keys = {e["key"] for e in entries}
            self._samples = {k: v for k, v in self._samples.items() if k in current_keys}
            self._entries = {e["key"]: e for e in entries}
            feed_times = [
                f.get("source_ms") for f in paper.get("feeds", {}).values() if f.get("source_ms")
            ]
            input_ms = min(feed_times) if feed_times else None
            collector = paper.get("collector", {})
            quality = read_quality(self.path / "capture.sqlite")
            # Capture can advance during the study/journal reads above. Compare
            # its timestamp with the clock after reading it, not the request start.
            now = int(time.time() * 1000)
            data_status = (
                "loading"
                if collector.get("caught_up") is False
                else "unavailable"
                if input_ms is None
                else "stale"
                if not 0 <= now - input_ms <= 15000
                else "recent"
            )
            if quality.get("status") == "available":
                input_ms = quality.get("last_ms")
                data_status = (
                    "stale"
                    if input_ms is None or not 0 <= now - input_ms <= 15000
                    else "recent"
                    if quality.get("latest", {}).get("code") == "CAPTURED"
                    and quality.get("current_unavailable_since_ms") is None
                    else "unavailable"
                )
            elif data_status == "recent":
                data_status = "unavailable"
            result = {
                "environment": "paper-experiments",
                "generated_ms": now,
                "experiments": rows,
                "errors": errors,
                "capture": {
                    **collector,
                    "data_status": data_status,
                    "input_ms": input_ms,
                    "latest": quality.get("latest"),
                    "quality": quality,
                },
                "refresh_seconds": 30,
                "curve_sampling": "At most 1200 curve points per experiment; earliest/latest and each consecutive group's cumulative minimum/maximum are retained. Totals and rankings use the full completed sample.",
                "semantics": "All net is all recorded realized profit. Unflagged net is a completed-round subtotal, not account equity. Realized return always uses all recorded realized profit / original allocation. Mean and win rate use completed capital-used rounds in the selected cohort. Curves show individual completed profit by market end, not a combined wallet or time of cash receipt. Drawdown is observed marked equity when available; original journals have no equivalent marked series.",
            }
            self._snapshot = public_json(result)
            self._loaded = time.monotonic()
            return self._snapshot

    def detail(self, key: str, cohort: str) -> dict[str, Any]:
        if cohort not in ("all", "unflagged") or not re.fullmatch(
            r"(?:paper:[a-z_]+|(?:directional|order-flow):[a-zA-Z0-9_-]{1,64}:[0-9a-f]{20})", key
        ):
            raise ValueError("UNKNOWN_EXPERIMENT_SELECTION")
        with self._lock:
            snapshot = self.snapshot()
            if key not in self._entries:
                raise ValueError("UNKNOWN_EXPERIMENT_SELECTION")
            cache_key = (key, cohort)
            cached = self._details.get(cache_key)
            if cached and time.monotonic() - cached[0] < 30:
                return cached[1]
            entry = self._entries[key]
            raw = entry["raw"] or {}
            samples, clock = self._rounds(entry)
            analysis = summarize(samples, cohort=cohort)
            if entry["source"] == "paper":
                # Baseline report has all accounting rounds, but only a bounded recent
                # fill journal. Never infer lifetime entry/cost sensitivity from it.
                analysis["groups"] = {}
                analysis["block_sensitivity"] = []
                analysis["stats"]["cost_stress"] = []
                analysis["stats"]["cost_headroom_per_share"] = None
            compatible = self._report_matches(entry, samples)
            displayed = dict(next(r for r in snapshot["experiments"] if r["key"] == key))
            if not compatible:
                displayed["fees"] = None
                displayed["metrics"] = experiment_metrics(
                    samples, allocation=decimal(raw.get("allocation")), realized=None, drawdown=None
                )
                displayed["curves"] = {c: completed_curve(samples, c) for c in ("all", "unflagged")}
            result = public_json(
                {
                    "environment": "paper-experiment",
                    "report_matches_analysis": compatible,
                    "generated_ms": int(time.time() * 1000),
                    "experiment": displayed,
                    "cohort": cohort,
                    "clock": clock,
                    "analysis": analysis,
                    "configuration": entry["definition"].get("config") or raw.get("parameters"),
                    "policy_change": entry.get("policy_change"),
                    "wallet": raw,
                    "phase_selection": entry.get("phase_definition", {}).get("selection"),
                    "limitations": entry.get("report", {}).get("limitations", []),
                }
            )
            if len(self._details) >= 8:
                self._details.pop(next(iter(self._details)))
            self._details[cache_key] = (time.monotonic(), result)
            return result
