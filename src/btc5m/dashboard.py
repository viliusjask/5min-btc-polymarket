"""Local, read-only monitoring of explicitly selected paper journals."""

from __future__ import annotations

import json
import signal
import threading
import time
from collections import Counter
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from btc5m.comparison import MASTER_WALLET
from btc5m.config import STRATEGIES, Config
from btc5m.dashboard_live import LiveDashboardReader
from btc5m.ledger import Ledger, LedgerError
from btc5m.paper import PAPER_MATCHING_MODEL

D = Decimal
ASSETS = Path(__file__).with_name("dashboard_assets")
DESCRIPTIONS = {
    "momentum": "Late directional entry with protected exits",
    "value": "Settlement value after execution costs",
    "fast_value": "Value with aligned Binance information",
    "model_exit": "Value entry with a sale-versus-hold exit",
    "passive_pairs": "Sequential Up/Down limit orders",
    "inventory_pairs": "Pairing with inventory-dependent hedge prices",
}
EXPLANATIONS = {
    "PAPER_TRADE_ID_MISSING": "Opposite-outcome trade volume could not be deduplicated because its transaction identifier was missing.",
    "ENTRY": "The entry screen passed. Confirmation and portfolio risk checks still apply.",
    "ENTRY_WINDOW": "Outside this strategy's scheduled entry interval.",
    "PAIR_WINDOW": "Outside the interval for opening or completing a pair.",
    "MISSING_REFERENCE": "The round's opening reference has not been verified. Joining after the boundary can leave it unavailable.",
    "MISSING_BOOK_SIDE": "At least one required Up/Down bid or ask is empty. The policy requires both complete books.",
    "FAST_STALE": "The exchange tick is too old for the fast-information policy.",
    "FAST_UNALIGNED": "No sufficiently close exchange tick aligns with the Chainlink source time.",
    "FAST_NOT_AHEAD": "The exchange information is not newer than Chainlink.",
    "FAST_MISSING": "No usable exchange history is available.",
    "TRADING_METADATA_CHANGED": "Venue endpoints disagree on the market's trading settings. The adapter waits for agreement.",
    "STALE_DATA": "At least one required observation exceeded its freshness limit.",
    "STREAM_SILENT": "A required feed has stopped supplying fresh messages.",
    "STREAM_WARMUP": "Waiting for initial messages from the required feeds.",
    "NO_SNAPSHOT": "No complete, current market snapshot is available to the execution engine.",
    "MARKET_CHANGED": "Normal book subscription change at a new five-minute round.",
    "FLAT": "The stop request finished with no remaining active exposure.",
    "ENTRY_CONFIRMATION_WAITING": "An eligible signal is waiting for newer confirming information.",
    "PAPER_RESTART_GAP": "Collection resumed after a gap. Saved balances and fills were retained; exposed rounds are marked uncertain.",
    "PAPER_CAPTURE_GAP": "The collector stopped advancing, for example during sleep. Missing executions are not invented on return.",
    "PAIR_COMPLETE_AWAITING_RESOLUTION": "Equal Up/Down quantities are held pending official settlement.",
}


def explain(reason: str, features: dict[str, Any] | None = None) -> tuple[str, str]:
    features = features or {}
    if reason == "INSUFFICIENT_HISTORY":
        statuses = [features.get(f"{label}_sampling_status") for label in ("short", "long")]
        if "EXCESSIVE_GAP" in statuses:
            gap = max(
                float(features.get(f"{label}_max_sample_gap_ms", 0)) for label in ("short", "long")
            )
            return (
                "data",
                f"Price history contains a {gap / 1000:g}s sampled gap. Elapsed warm-up time alone does not clear this guard.",
            )
        if any(
            status in ("MISSING_START", "INSUFFICIENT_SPAN", "INSUFFICIENT_SAMPLES")
            for status in statuses
        ):
            return (
                "warmup",
                "The required historical window does not yet have a complete beginning and span.",
            )
        return (
            "data",
            "Historical sampling failed its end, coverage or quality requirements. Inspect the sampling details.",
        )
    category = (
        "eligible"
        if reason == "ENTRY"
        else "schedule"
        if reason in ("ENTRY_WINDOW", "PAIR_WINDOW")
        else "warmup"
        if reason == "STREAM_WARMUP"
        else "data"
        if any(
            part in reason
            for part in (
                "MISSING",
                "STALE",
                "UNALIGNED",
                "STREAM",
                "METADATA",
                "CONFLICT",
                "BOOK",
                "FUTURE",
            )
        )
        else "strategy"
    )
    return category, EXPLANATIONS.get(reason, reason.replace("_", " ").capitalize() + ".")


class DashboardReader:
    """Incrementally aggregate public events; never load authenticated order payloads."""

    def __init__(self, path: Path, config: Config) -> None:
        self.path, self.config = path.resolve(), config
        self.lock = threading.Lock()
        self.identity: tuple[int, int] | None = None
        self._reset()

    def _reset(self) -> None:
        self.cursor = 0
        self.first_ms: int | None = None
        self.last_ms: int | None = None
        self.observations: Counter[str] = Counter()
        self.decisions: dict[str, Any] = {
            name: {
                "counts": Counter(),
                "categories": Counter(),
                "history_reasons": Counter(),
                "latest": None,
                "sampling": None,
            }
            for name in STRATEGIES
        }
        self.feeds: dict[str, Any] = {}
        self.books: dict[str, Any] = {}
        self.prices: dict[int, dict[str, Any]] = {}
        self.timeline: dict[int, dict[str, Any]] = {}
        self.incidents: dict[str, Any] = {}
        self.anchors: dict[str, Any] = {}
        self.lifecycle: dict[str, Any] = {}
        self.heartbeat: dict[str, Any] = {}
        self.restarts: list[int] = []

    def _consume(self, kind: str, stamp: int, data: dict[str, Any]) -> None:
        self.first_ms = min(self.first_ms, stamp) if self.first_ms is not None else stamp
        self.last_ms = max(self.last_ms or stamp, stamp)
        minute = stamp // 60000 * 60000
        if kind == "STOP_CLEARED":
            self.restarts.append(stamp)
            self.restarts = self.restarts[-100:]
        if kind == "DECISION" and data.get("mode") in STRATEGIES:
            name, decision = data["mode"], data["decision"]
            reason, features = decision["reason"], decision.get("features", {})
            category, explanation = explain(reason, features)
            state = self.decisions[name]
            state["counts"][reason] += 1
            state["categories"][category] += 1
            if reason == "INSUFFICIENT_HISTORY":
                for status in set(
                    features.get(f"{label}_sampling_status") for label in ("short", "long")
                ) - {None, "VALID"}:
                    state["history_reasons"][status] += 1
            state["latest"] = {
                "at_ms": stamp,
                "slug": data.get("slug"),
                "reason": reason,
                "category": category,
                "explanation": explanation,
                "features": features,
                "probability_up": decision.get("probability_up"),
            }
            if "long_sampling_status" in features:
                state["sampling"] = {"at_ms": stamp, "features": features}
            bucket = self.timeline.setdefault(minute, {"at_ms": minute, "strategies": {}})
            counts = bucket["strategies"].setdefault(name, Counter())
            counts[category] += 1
        if kind != "PUBLIC_OBSERVATION":
            return
        label = data.get("kind", "unknown")
        self.observations[label] += 1
        if label in ("spot", "twap60", "exchange_spot"):
            prior = self.feeds.get(label)
            if prior is None or data.get("source_ms", 0) >= prior.get("source_ms", 0):
                self.feeds[label] = {
                    key: data.get(key) for key in ("source_ms", "received_ms", "price", "source")
                }
            bucket = self.prices.setdefault(minute, {"at_ms": minute})
            if data.get("source_ms", 0) >= bucket.get(label + "_source_ms", 0):
                bucket[label] = data.get("price")
                bucket[label + "_source_ms"] = data.get("source_ms", 0)
        elif label == "book":
            self.books[data["token_id"]] = data
            self.books = dict(
                sorted(self.books.items(), key=lambda pair: pair[1]["received_ms"])[-12:]
            )
        elif label == "anchor":
            self.anchors[data["slug"]] = data
            if len(self.anchors) > 600:
                self.anchors.pop(next(iter(self.anchors)))
        elif label == "paper_run":
            self.lifecycle = data
        elif label == "paper_heartbeat":
            self.heartbeat = data
        if label in (
            "stream_unavailable",
            "snapshot_unavailable",
            "metadata_rejected",
            "http_unavailable",
            "book_unavailable",
            "paper_recovery",
            "paper_interruption",
        ):
            code = data.get("code") or label.upper()
            key = ":".join(
                str(data.get(field, ""))
                for field in ("kind", "stream", "code", "compared_field", "expected", "actual")
            )
            if key not in self.incidents:
                self.incidents[key] = {
                    "kind": label,
                    "code": code,
                    "stream": data.get("stream"),
                    "count": 0,
                    "first_ms": stamp,
                    "explanation": explain(code)[1],
                    "field": data.get("compared_field"),
                    "expected": data.get("expected"),
                    "actual": data.get("actual"),
                }
            self.incidents[key].update(last_ms=stamp)
            self.incidents[key]["count"] += 1

    def _master(self) -> tuple[dict[str, Any], int]:
        manifest_path = self.path / "paper.json"
        if manifest_path.stat().st_size > 16384:
            raise LedgerError("INVALID_PAPER_MANIFEST")
        manifest = json.loads(manifest_path.read_text())
        selected = manifest.get("strategies", [])
        if (
            manifest.get("environment") != "paper"
            or manifest.get("version") != 1
            or not selected
            or len(selected) != len(set(selected))
            or any(name not in STRATEGIES for name in selected)
        ):
            raise LedgerError("INVALID_PAPER_MANIFEST")
        path = self.path / "observations.sqlite"
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if identity != self.identity:
            self._reset()
            self.identity = identity
        master = Ledger(path, MASTER_WALLET, readonly=True)
        try:
            if master.environment != "paper":
                raise LedgerError("EXECUTION_ENVIRONMENT_MISMATCH")
            master.db.execute("BEGIN")
            maximum = master.db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
            if maximum < self.cursor:
                self._reset()
            # Strip large depth arrays in SQL; retain their actual presence and best prices.
            query = """SELECT id,kind,at_ms,CASE
                WHEN kind='PUBLIC_OBSERVATION' AND json_extract(data,'$.kind')='book'
                THEN json_object('kind','book','token_id',json_extract(data,'$.token_id'),
                    'condition_id',json_extract(data,'$.condition_id'),
                    'received_ms',at_ms,'source_ms',json_extract(data,'$.source_ms'),
                    'bid_count',json_array_length(data,'$.bids'),'ask_count',json_array_length(data,'$.asks'),
                    'best_bid',json_extract(data,'$.bids[0].price'),'best_ask',json_extract(data,'$.asks[0].price'))
                ELSE data END FROM events WHERE id>? AND id<=? ORDER BY id LIMIT 100000"""
            for ident, kind, stamp, raw in master.db.execute(query, (self.cursor, maximum)):
                self._consume(kind, stamp, json.loads(raw))
                self.cursor = ident
        finally:
            master.close()
        # Charts retain at most 24 hours of minute aggregates; counts remain cumulative.
        cutoff = (self.last_ms or 0) - 86400000
        self.prices = {k: v for k, v in self.prices.items() if k >= cutoff}
        self.timeline = {k: v for k, v in self.timeline.items() if k >= cutoff}
        return manifest, maximum

    def _portfolio(self, name: str, allocation: Decimal) -> dict[str, Any]:
        wallet = "0x" + str(STRATEGIES.index(name) + 1).zfill(40)
        ledger = Ledger(self.path / name / "ledger.sqlite", wallet, readonly=True)
        try:
            if ledger.environment != "paper":
                raise LedgerError("EXECUTION_ENVIRONMENT_MISMATCH")
            ledger.db.execute("BEGIN")
            summary, result = ledger.summary(), ledger.portfolio_results()[name]
            orders = {
                ident: json.loads(raw)
                for ident, raw in ledger.db.execute("SELECT id,data FROM intents")
            }
            execution = {
                key.removeprefix("paper_order:"): json.loads(raw)
                for key, raw in ledger.db.execute(
                    "SELECT key,data FROM measurements WHERE key LIKE 'paper_order:%'"
                )
            }
            legacy_matching_orders = 0
            cancellations = dict(
                ledger.db.execute(
                    "SELECT json_extract(data,'$.identity'),json_extract(data,'$.code') FROM events WHERE kind='PUBLIC_OBSERVATION' AND json_extract(data,'$.kind')='quote_cancel' ORDER BY id"
                )
            )
            for ident, order in orders.items():
                paper = execution.get(ident, {})
                if order["passive"] and paper.get("matching_model") != PAPER_MATCHING_MODEL:
                    legacy_matching_orders += 1
                reason = paper.get("terminal_reason") or order["reason"]
                status = order["state"]
                filled = D(order["confirmed_quantity"])
                if filled >= D(order["quantity"]):
                    status = "FILLED"
                elif paper.get("terminal") or status == "SETTLED":
                    if filled:
                        status = "PARTIALLY_FILLED_CLOSED"
                    elif reason == "PAPER_POST_ONLY_REJECTED":
                        status = "REJECTED_UNFILLED"
                    elif reason.startswith("PAPER_CANCELLED"):
                        status = "CANCELLED_UNFILLED"
                    else:
                        status = "CLOSED_UNFILLED"
                elif order["passive"]:
                    if order.get("cancel_requested_ms") is not None:
                        status = "CANCELLING"
                    elif status == "ACK":
                        status = "RESTING"
                        reason = "WAITING_FOR_MATCHING_TRADES"
                if status in ("CANCELLED_UNFILLED", "PARTIALLY_FILLED_CLOSED", "CANCELLING"):
                    reason = cancellations.get(ident, reason)
                order.update(execution_status=status, execution_reason=reason)
            fills = []
            stamps: dict[str, int] = {}
            for chain, tx, log, intent, raw in ledger.db.execute(
                "SELECT chain,tx,log,intent_id,data FROM fills"
            ):
                row = json.loads(raw)
                stamps[f"{chain}:{tx}:{log}"] = row["timestamp_ms"]
                source = orders[intent]
                fills.append(
                    {
                        "at_ms": row["timestamp_ms"],
                        "side": row["side"],
                        "quantity": row["quantity"],
                        "principal": row["principal"],
                        "fee": row["fee"],
                        "slug": source["market"]["slug"],
                        "outcome": (source.get("decision") or {}).get("side"),
                        "order_id": intent,
                    }
                )
            resolutions: dict[str, int] = {}
            payouts: dict[str, int] = {}
            for stamp, kind, raw in ledger.db.execute(
                "SELECT at_ms,kind,data FROM events WHERE kind IN ('RESOLUTION','PAPER_PAYOUT') ORDER BY id"
            ):
                row = json.loads(raw)
                if kind == "RESOLUTION":
                    resolutions.setdefault(row["condition_id"], stamp)
                else:
                    payouts.setdefault(row["position_id"], stamp)
            movements, untimed = [], 0
            for ident, pnl in ledger.db.execute("SELECT id,pnl FROM accounting"):
                stamp = stamps.get(ident)
                if ident.startswith("resolution:"):
                    source = orders.get(ident.split(":", 1)[1])
                    stamp = resolutions.get(source["market"]["condition_id"]) if source else None
                elif ident.startswith("paper_claim:"):
                    stamp = payouts.get(ident.split(":", 1)[1])
                if stamp is None:
                    untimed += 1
                else:
                    movements.append((stamp, D(pnl)))
            cumulative = D(0)
            curve: list[dict[str, Any]] = []
            for stamp, pnl in sorted(movements):
                cumulative += pnl
                if curve and curve[-1]["at_ms"] == stamp:
                    curve[-1]["pnl"] = cumulative
                else:
                    curve.append({"at_ms": stamp, "pnl": cumulative})
            observations = ledger.db.execute(
                "SELECT data FROM events WHERE kind='PUBLIC_OBSERVATION' AND json_extract(data,'$.kind')='execution_result' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            uncertain = [
                r[0]
                for r in ledger.db.execute(
                    "SELECT DISTINCT json_extract(data,'$.slug') FROM events WHERE kind='PUBLIC_OBSERVATION' AND json_extract(data,'$.kind')='paper_uncertainty'"
                )
            ]
            completed = [
                r
                for slug, r in result["rounds"].items()
                if r["filled"] and not r["unresolved"] and slug not in uncertain
            ]
            return {
                **result,
                "allocation": allocation,
                "cash": summary.cash,
                "risk_reserved": summary.risk_reserve,
                "halts": summary.halts,
                "unresolved_orders": len(summary.unresolved_orders),
                "uncertain_rounds": uncertain,
                "win_rate": sum(r["realized_net_pnl"] > 0 for r in completed) / len(completed)
                if completed
                else None,
                "win_rate_rounds": len(completed),
                "pnl_curve": curve[-5000:],
                "curve_truncated": len(curve) > 5000,
                "untimed_accounting": untimed,
                "last_execution": json.loads(observations[0]) if observations else None,
                "legacy_matching_orders": legacy_matching_orders,
                "recent_fills": sorted(fills, key=lambda r: r["at_ms"], reverse=True)[:100],
                "recent_orders": [
                    {
                        "id": r["intent_id"],
                        "created_ms": r["created_ms"],
                        "side": r["side"],
                        "state": r["state"],
                        "reason": r["reason"],
                        "execution_status": r["execution_status"],
                        "execution_reason": r["execution_reason"],
                        "quantity": r["quantity"],
                        "confirmed_quantity": r["confirmed_quantity"],
                        "price_limit": r["price_limit"],
                        "slug": r["market"]["slug"],
                        "outcome": (r.get("decision") or {}).get("side"),
                    }
                    for r in sorted(
                        orders.values(), key=lambda row: row["created_ms"], reverse=True
                    )[:100]
                ],
                "positions": [
                    {
                        "slug": p.market.slug,
                        "side": p.decision.side.value if p.decision.side else None,
                        "quantity": p.quantity,
                        "cost_basis": p.cost_basis,
                        "status": p.status,
                        "claimable_value": p.claimable_value,
                        "exit_reason": p.exit_reason,
                        "exit_problem": p.exit_problem,
                    }
                    for p in ledger.positions()
                    if p.quantity > 0 and p.status != "WORTHLESS"
                ],
            }
        finally:
            ledger.close()

    def snapshot(self, *, now_ms: int | None = None) -> dict[str, Any]:
        with self.lock:
            now = int(time.time() * 1000) if now_ms is None else now_ms
            manifest, maximum = self._master()
            selected = manifest["strategies"]
            portfolios = {
                name: self._portfolio(name, D(manifest["allocation_per_portfolio"]))
                for name in selected
            }
            heartbeat_age = now - self.heartbeat.get("received_ms", 0)
            if self.lifecycle.get("status") in (
                "stopped",
                "failed",
                "unresolved",
            ) and self.lifecycle.get("received_ms", 0) >= self.heartbeat.get("received_ms", 0):
                status = self.lifecycle["status"]
            elif self.heartbeat and 0 <= heartbeat_age <= 15000:
                status = self.heartbeat.get("status", "running")
            elif self.heartbeat:
                status = "heartbeat_stale"
            elif self.last_ms is not None and 0 <= now - self.last_ms <= 15000:
                status = "receiving_data"
            else:
                status = "historical"
            matches = manifest.get("config_fingerprint") == self.config.fingerprint
            payload = {
                "environment": "paper",
                "generated_ms": now,
                "runtime_name": self.path.name,
                "manifest": manifest,
                "collector": {
                    "status": status,
                    "first_ms": self.first_ms,
                    "last_ms": self.last_ms,
                    "heartbeat_ms": self.heartbeat.get("received_ms"),
                    "caught_up": self.cursor >= maximum,
                    "events_loaded": self.cursor,
                    "events_available": maximum,
                    "restart_times": self.restarts,
                },
                "portfolios": portfolios,
                "descriptions": DESCRIPTIONS,
                "decisions": {name: self.decisions[name] for name in selected},
                "feeds": self.feeds,
                "books": sorted(
                    self.books.values(), key=lambda row: row["received_ms"], reverse=True
                )[:2],
                "prices": [self.prices[k] for k in sorted(self.prices)],
                "timeline": [self.timeline[k] for k in sorted(self.timeline)],
                "observation_counts": self.observations,
                "incidents": sorted(
                    self.incidents.values(), key=lambda r: r["count"], reverse=True
                ),
                "anchors": list(self.anchors.values())[-20:],
                "settings_match_capture": matches,
                "thresholds": {
                    "history_seconds": self.config.strategy.volatility_long_seconds,
                    "max_gap_ms": self.config.data.max_sample_gap_ms,
                    "coverage": self.config.data.min_sample_coverage,
                    "price_age_ms": self.config.data.max_price_age_ms,
                }
                if matches
                else None,
            }
            return json.loads(json.dumps(payload, default=str, allow_nan=False))


def make_server(
    reader: DashboardReader, *, port: int = 8765, live: LiveDashboardReader | None = None
) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise LedgerError("INVALID_DASHBOARD_PORT")

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def respond(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self) -> None:
            try:
                hostname = urlsplit("http://" + self.headers.get("Host", "")).hostname
            except ValueError:
                hostname = None
            if hostname not in (
                "localhost",
                "127.0.0.1",
            ):
                self.respond(403, b"Local access only", "text/plain")
                return
            path = urlsplit(self.path).path
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
                "/icon.svg": ("icon.svg", "image/svg+xml"),
            }
            if path in assets:
                file, mime = assets[path]
                self.respond(200, (ASSETS / file).read_bytes(), mime)
            elif path == "/api/state":
                try:
                    payload = json.dumps(reader.snapshot(), allow_nan=False).encode()
                except Exception:
                    self.respond(503, b'{"error":"PAPER_DATA_UNAVAILABLE"}', "application/json")
                    return
                self.respond(200, payload, "application/json")
            elif path == "/api/live":
                live_payload = (
                    live.snapshot()
                    if live
                    else {"environment": "live", "status": "not_configured", "account": None}
                )
                self.respond(
                    200, json.dumps(live_payload, allow_nan=False).encode(), "application/json"
                )
            else:
                self.respond(404, b"Not found", "text/plain")

        def do_POST(self) -> None:
            self.respond(405, b"Read-only dashboard", "text/plain")

        do_PUT = do_POST
        do_DELETE = do_POST
        do_PATCH = do_POST

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        raise LedgerError("DASHBOARD_PORT_UNAVAILABLE") from None
    server.daemon_threads = True
    return server


def serve_dashboard(
    path: Path, config: Config, port: int, live: LiveDashboardReader | None = None
) -> None:
    reader = DashboardReader(path, config)
    reader.snapshot()  # Validate the selected paper runtime before opening a listener.
    server = make_server(reader, port=port, live=live)
    print(
        json.dumps(
            {
                "kind": "dashboard_started",
                "url": f"http://127.0.0.1:{server.server_port}",
                "environment": "paper",
                "read_only": True,
                "real_account_configured": live is not None,
            }
        ),
        flush=True,
    )
    previous = {}

    def interrupted(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    # The CLI runs inside asyncio.run; its default first Ctrl-C only cancels a task,
    # which a synchronous HTTP loop cannot observe. Give this read-only command its own stop.
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, interrupted)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if live is not None:
            live.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
