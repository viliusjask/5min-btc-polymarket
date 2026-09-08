"""Causal paper replay with one atomic journal/cursor checkpoint per input frame."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from btc5m.config import PAIR_STRATEGIES, Config
from btc5m.domain import Decision, Market, Side, Snapshot
from btc5m.engine import Engine
from btc5m.execution_types import Intent, PendingCandidate, Position
from btc5m.flow_signals import flow_side, observe_flow
from btc5m.lab_tape import Frame, book_from, encode
from btc5m.lab_variants import Valuations, Variant, evaluate_variant
from btc5m.ledger import Ledger, LedgerError
from btc5m.pairing import pair_decision
from btc5m.paper import PaperBroker
from btc5m.strategy import _quote, _safety_reason, _skip, fee_for
from btc5m.streams import PublicStreams, PublicTrade

D = Decimal


class NestedConnection(sqlite3.Connection):
    """Paper-only connection; existing inner journal contexts become savepoints.

    Never used for live execution, whose pre-submit commits must reach disk before POST.
    The outer frame has no external effects: PaperBroker only changes this same database.
    """

    depth = 0

    def __enter__(self) -> NestedConnection:
        self.execute(f"SAVEPOINT lab_transaction_{self.depth}")
        self.depth += 1
        return self

    def __exit__(self, kind: Any, value: Any, traceback: Any) -> Literal[False]:
        self.depth -= 1
        name = f"lab_transaction_{self.depth}"
        if kind is not None:
            self.execute(f"ROLLBACK TO {name}")
        self.execute(f"RELEASE {name}")
        return False


class LabEngine(Engine):
    variant: Variant
    cache: Valuations | None = None
    entry_start_ms: int = 0
    entry_end_ms: int | None = None
    flow: dict[str, Any]
    signal_state: dict[str, Any]

    def _evaluate(self, snapshot: Snapshot, config: Config) -> Decision:
        if (
            snapshot.now_ms < self.entry_start_ms
            or snapshot.market.start_s * 1000 < self.entry_start_ms
            or (
                self.entry_end_ms is not None
                and max(snapshot.now_ms, snapshot.market.start_s * 1000) >= self.entry_end_ms
            )
        ):
            return _skip(snapshot, "STUDY_ENTRY_WINDOW", {})
        if config.strategy.mode in PAIR_STRATEGIES:
            return self._pair_decision(snapshot, config, self.ledger.active_positions())
        if self.variant.signal in (
            "absorption",
            "flow_continuation",
            "pressure_confirm",
            "confirmation_control",
        ):
            value = (self.cache or Valuations(snapshot)).get(self.variant)
            safety = _safety_reason(snapshot, config)
            if safety:
                return _skip(snapshot, safety, value.features)
            tau = (snapshot.market.end_s * 1000 - snapshot.now_ms) / 1000
            if (
                not config.strategy.momentum_min_seconds
                <= tau
                <= config.strategy.momentum_max_seconds
            ):
                return _skip(snapshot, "ENTRY_WINDOW", value.features)
            if value.reason != "VALID":
                return _skip(snapshot, value.reason, value.features)
            side, reason, details = flow_side(snapshot, self.variant, self.flow, self.signal_state)
            features = {**value.features, **details}
            if side is None:
                return _skip(snapshot, reason, features, value.probability_up)
            assert value.probability_up is not None
            return _quote(
                snapshot,
                config,
                side,
                snapshot.up_book if side is Side.UP else snapshot.down_book,
                value.probability_up,
                value.floors[side],
                features,
            )
        return evaluate_variant(snapshot, self.variant, self.cache)

    def _pair_decision(
        self, snapshot: Snapshot, config: Config, positions: tuple[Position, ...]
    ) -> Decision:
        if self.variant.signal != "pressure_pair" or positions:
            return pair_decision(snapshot, config, positions)
        side, reason, details = flow_side(snapshot, self.variant, self.flow, self.signal_state)
        if side is None:
            return _skip(snapshot, reason, details)
        decision = pair_decision(snapshot, config, positions, preferred_side=side)
        return replace(decision, features={**decision.features, **details})

    def _resting_cancel_reason(
        self, order: Intent, snapshot: Snapshot | None, now_ms: int
    ) -> str | None:
        reason = super()._resting_cancel_reason(order, snapshot, now_ms)
        if (
            reason
            or self.variant.signal != "pressure_pair"
            or snapshot is None
            or order.decision is None
            or order.decision.features.get("pair_role") != "OPEN"
        ):
            return reason
        side, _, _ = flow_side(snapshot, self.variant, self.flow, self.signal_state)
        return None if side is order.decision.side else "OPENING_PRESSURE_LOST"

    def _exit_enabled(self, trigger: str) -> bool:
        policy = self.variant.exit_policy
        return not (
            policy == "settlement"
            or policy == "time_only"
            and trigger != "TIME"
            or policy == "no_stop"
            and trigger == "STOP"
        )

    def _model_exit_enabled(self, position: Position) -> bool:
        return self.variant.exit_policy == "model" or (
            self.variant.exit_policy == "baseline" and super()._model_exit_enabled(position)
        )


class Replay:
    def __init__(
        self,
        path: Path,
        variant: Variant,
        tape_identity: str,
        start_ms: int,
        end_ms: int | None = None,
    ) -> None:
        self.variant = variant
        self.ledger = Ledger(path, "0x" + variant.ident.zfill(40), environment="paper")
        try:
            # The regular Ledger acquires and retains the process lock. Only this paper
            # replay connection uses nested contexts; baseline/live ledgers are unchanged.
            self.ledger.db.close()
            self.ledger.db = sqlite3.connect(path, timeout=5, factory=NestedConnection)
            # This journal is a reproducible cache of a FULL-synchronized input tape.
            # NORMAL preserves transaction atomicity; a power loss may discard a suffix
            # of cache frames, whose surviving cursor then replays them from the tape.
            # It avoids 84 independent disk synchronizations at every capture. Live and
            # baseline paper journals retain FULL; this connection never posts externally.
            self.ledger.db.execute("PRAGMA synchronous=NORMAL")
            self.ledger.db.executescript("""
                CREATE TABLE IF NOT EXISTS lab_rounds(slug TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lab_equity(bucket INTEGER PRIMARY KEY, at_ms INTEGER NOT NULL, equity TEXT, cash TEXT, basis TEXT NOT NULL);
            """)
            identity = encode(
                {
                    "variant": variant.ident,
                    "tape": tape_identity,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                }
            )
            old = self.ledger._meta("lab_identity")
            if old is not None and old != identity:
                raise LedgerError("LAB_REPLAY_IDENTITY_CHANGED")
            with self.ledger.db:
                self.ledger._set("lab_identity", identity)
            self.session = self.ledger.start_or_resume_session(variant.config)
            self.cursor = int(self.ledger._meta("lab_cursor") or 0)
            self.now_ms = int(self.ledger._meta("lab_now_ms") or 0)
            self.labels: dict[str, Any] = json.loads(self.ledger._meta("lab_labels") or "{}")
            self.broker = PaperBroker(
                self.ledger,
                variant.config,
                clock=lambda: self.now_ms / 1000,
                final_reference=self.final_reference,
                streams=PublicStreams(variant.config, clock=lambda: self.now_ms / 1000)
                if variant.config.strategy.mode in PAIR_STRATEGIES
                else None,
            )
            # Replay has the exact intervening input sequence after a process restart.
            # A live source-session change still invalidates passive queue continuity.
            self.broker.submission_session = "replay:" + tape_identity
            engine_type = LabEngine
            if variant.signal == "split_sell":
                from btc5m.split_engine import SplitEngine

                engine_type = SplitEngine
            self.engine = engine_type(
                self.broker,
                self.ledger,
                variant.config,
                self.session,
                read_exit_book=self.broker.book,
                record_screens=False,
            )
            self.engine.variant = variant
            self.engine.flow = {}
            self.engine.signal_state = {}
            self.engine.entry_start_ms, self.engine.entry_end_ms = start_ms, end_ms
            self._restore_pending()
        except BaseException:
            self.ledger.close()
            raise

    def _restore_pending(self) -> None:
        raw = json.loads(self.ledger._meta("lab_pending") or "null")
        if raw:
            raw["side"] = Side(raw["side"])
            raw["reference_price"] = (
                D(raw["reference_price"]) if raw["reference_price"] is not None else None
            )
        self.engine.pending_candidate = PendingCandidate(**raw) if raw else None
        self.engine.signal_state = json.loads(self.ledger._meta("lab_signal_state") or "{}")
        saved = json.loads(self.ledger._meta("lab_streams") or "null")
        if saved:
            self._streams(saved, restore=True)

    def _streams(self, raw: dict[str, Any] | None, *, restore: bool = False) -> None:
        streams = self.broker.streams
        if streams is None:
            return
        if raw is None:
            streams.invalidate_market("LAB_TRADE_RECORDING_MISSING")
            streams.trades.clear()
            return
        if (
            restore
            or streams.session_id != raw["session_id"]
            or streams.generation != raw["generation"]
        ):
            streams.trades.clear()
        streams.session_id, streams.generation = raw["session_id"], raw["generation"]
        streams.books = {token: book_from(book) for token, book in raw["books"].items()}
        streams.pending_books = raw["pending_books"].copy()
        for row in raw["trades"]:
            streams.trades.append(
                PublicTrade(**{**row, "price": D(row["price"]), "quantity": D(row["quantity"])})
            )
        while streams.trades and streams.trades[0].received_ms < self.now_ms - 15000:
            streams.trades.popleft()

    def final_reference(self, market: Market) -> tuple[Decimal, Decimal] | None:
        label = self.labels.get(market.slug)
        if (
            not label
            or label["condition_id"] != market.condition_id
            or self.now_ms < market.end_s * 1000
        ):
            return None
        return D(label["opening"]), D(label["final"])

    def checkpoint(self, frame: Frame) -> None:
        self.ledger._set("lab_cursor", str(frame.ident))
        self.ledger._set("lab_now_ms", str(frame.now_ms))
        self.ledger._set(
            "lab_pending",
            encode(asdict(self.engine.pending_candidate))
            if self.engine.pending_candidate
            else "null",
        )
        if frame.labels:
            self.ledger._set("lab_labels", encode(self.labels))
        self.ledger._set("lab_signal_state", encode(self.engine.signal_state))
        if self.broker.streams:
            streams = self.broker.streams
            self.ledger._set(
                "lab_streams",
                encode(
                    {
                        "session_id": streams.session_id,
                        "generation": streams.generation,
                        "books": {k: asdict(v) for k, v in streams.books.items()},
                        "pending_books": streams.pending_books,
                        "trades": [asdict(t) for t in streams.trades],
                    }
                ),
            )

    def _round(self, slug: str) -> dict[str, Any]:
        row = self.ledger.db.execute("SELECT data FROM lab_rounds WHERE slug=?", (slug,)).fetchone()
        return (
            json.loads(row[0])
            if row
            else {
                "slug": slug,
                "screens": 0,
                "eligible": 0,
                "reasons": {},
                "execution": {},
                "uncertain": False,
            }
        )

    def _save_round(self, row: dict[str, Any]) -> None:
        self.ledger.db.execute(
            "INSERT OR REPLACE INTO lab_rounds VALUES (?,?)", (row["slug"], encode(row))
        )

    async def apply(self, frame: Frame, cache: Valuations | None) -> bool:
        if frame.ident <= self.cursor:
            return False
        if self.cursor and frame.ident != self.cursor + 1:
            raise LedgerError("LAB_INPUT_SEQUENCE_GAP")
        if frame.now_ms < self.now_ms:
            raise LedgerError("LAB_INPUT_CLOCK_REVERSED")
        prior_ms, prior_labels = self.now_ms, self.labels.copy()
        self.now_ms = frame.now_ms
        self.labels.update(frame.labels)
        self.engine.cache = cache
        snap = frame.snapshot
        try:
            with self.ledger.db:
                event_watermark = self.ledger.db.execute(
                    "SELECT COALESCE(MAX(id),0) FROM events"
                ).fetchone()[0]
                research = frame.research or {}
                self.engine.flow = research.get("flow", {})
                observe_flow(snap, self.variant, self.engine.flow, self.engine.signal_state)
                self._streams(research.get("streams"))
                gap = bool(
                    prior_ms and frame.now_ms - prior_ms > self.variant.config.data.max_price_age_ms
                )
                affected = {
                    p.market.slug
                    for p in self.ledger.active_positions()
                    if self.variant.exit_policy != "settlement"
                    and p.market.end_s * 1000 > (prior_ms or frame.now_ms)
                }
                affected.update(o.market.slug for o in self.ledger.unresolved_orders())
                if self.engine.pending_candidate:
                    affected.add(self.engine.pending_candidate.slug)
                if gap or snap is None:
                    if affected:
                        self.broker.observation_gap(frame.now_ms, "LAB_CAPTURE_GAP")
                    self.engine._cancel_pending("LAB_CAPTURE_GAP", None, frame.now_ms)
                    # Before any market data, there is no claim about the missing round.
                    for slug in affected:
                        row = self._round(slug)
                        row["uncertain"] = True
                        self._save_round(row)
                self.broker.update(snap)
                raw = self.engine._evaluate(snap, self.variant.config) if snap else None
                result = await self.engine.step(snap, None, frame.now_ms)
                if snap and raw and raw.reason != "STUDY_ENTRY_WINDOW":
                    row = self._round(snap.market.slug)
                    row["screens"] += 1
                    row["eligible"] += int(raw.reason == "ENTRY")
                    row["reasons"][raw.reason] = row["reasons"].get(raw.reason, 0) + 1
                    row["execution"][result.reason] = row["execution"].get(result.reason, 0) + 1
                    row["last_ms"], row["last_reason"] = frame.now_ms, result.reason
                    self._save_round(row)
                # Transport/queue uncertainty can occur between otherwise timely
                # capture frames. Propagate the broker's evidence to study quality.
                for (raw_event,) in self.ledger.db.execute(
                    "SELECT data FROM events WHERE id>? AND kind='PUBLIC_OBSERVATION' AND json_extract(data,'$.kind')='paper_uncertainty'",
                    (event_watermark,),
                ).fetchall():
                    slug = json.loads(raw_event).get("slug")
                    if isinstance(slug, str):
                        row = self._round(slug)
                        row["uncertain"] = True
                        self._save_round(row)
                # Conflicting later official metadata invalidates interpretation, while
                # preserving cash entries that were legitimately recorded earlier.
                for slug, label in frame.labels.items():
                    if label is None and slug in prior_labels and prior_labels[slug] is not None:
                        row = self._round(slug)
                        row["uncertain"] = True
                        self._save_round(row)
                self._record_equity(frame.now_ms)
                self.checkpoint(frame)
            self.cursor = frame.ident
        except BaseException:
            self.now_ms, self.labels = prior_ms, prior_labels
            self._restore_pending()
            self.broker.books.clear()
            raise
        return True

    def _record_equity(self, now_ms: int) -> None:
        # Record five-second marks, retaining the worst observable mark in the bucket.
        cash = self.ledger.summary(now_ms).cash
        equity = cash
        basis = D(0)
        for pos in self.ledger.positions():
            basis += pos.cost_basis
            if pos.quantity == 0 or pos.status == "WORTHLESS":
                continue
            if pos.status == "CLAIMABLE":
                if equity is not None:
                    equity += pos.claimable_value
                continue
            book = self.broker._book(pos.token_id, now_ms)
            remaining, proceeds = pos.quantity, D(0)
            if book:
                for level in book.bids:
                    q = min(remaining, level.size)
                    proceeds += q * level.price - fee_for(
                        q, level.price, pos.market.fee_rate, pos.market.fee_exponent
                    )
                    remaining -= q
                    if remaining == 0:
                        break
            if remaining:
                equity = None
            elif equity is not None:
                equity += proceeds
        bucket = now_ms // 5000
        old = self.ledger.db.execute(
            "SELECT equity FROM lab_equity WHERE bucket=?", (bucket,)
        ).fetchone()
        if old and (old[0] is None or equity is not None and D(old[0]) <= equity):
            return
        self.ledger.db.execute(
            "INSERT OR REPLACE INTO lab_equity VALUES (?,?,?,?,?)",
            (
                bucket,
                now_ms,
                str(equity) if equity is not None else None,
                str(cash) if cash is not None else None,
                str(basis),
            ),
        )

    def close(self) -> None:
        self.ledger.close()
