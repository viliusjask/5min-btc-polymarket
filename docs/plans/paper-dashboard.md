# Paper monitoring and capture diagnosis

The operator needs to understand why the six policies did not trade and inspect subsequent
paper runs visually. Implement a local, read-only dashboard backed by the existing SQLite
journals. Preserve trading rules and execution state. No credentials or new runtime dependency
are needed for paper monitoring. The operator subsequently requested a Paper/Real switch and
a fresh two-hour paper run with USD100 per strategy (USD600 total).

1. Diagnose the existing capture, separating scheduled waits, history warm-up, actual gaps,
   missing opening references, empty books, and inconsistent metadata. Record exact counts.
2. Add a bounded local HTTP service and static browser UI through `btc5m dashboard --runtime`.
   Reuse ledger accounting. Display independent portfolio results, realized PnL curves, order
   and fill history, observed BTC prices, feed ages, sampling quality, and decision reasons.
3. Distinguish historical capture time from current wall time. A stopped recorder is never
   labelled live. Repeated decision checks are not independent opportunities or trades. Unknown
   returns/timestamps remain missing; cash spent on open holdings is not plotted as realized loss.
4. Test journal accounting, incremental refresh, missing/stale data, environment separation and HTTP
   isolation. Exercise the dashboard on the real saved capture and inspect the rendered UI.
5. Add explicit read-only account monitoring through existing authentication and SDK reads.
   Display cash, indexed holdings, venue orders and recent account trade legs separately from
   the local bot journal. Never expose API owner keys, signed payloads or fabricate account PnL.
6. Run all six with USD100 each in a fresh local runtime, preserving earlier captures. Keep
   the collector independent from dashboard development. No entry threshold is relaxed.
7. Commit, push and open the dashboard PR against the user's fork main. The operator has already
   merged #2 then #1; preserve all branches and let the operator merge this PR too.

The initial dashboard provides monitoring, filtering and export. It does not start/stop trading,
alter parameters, expose secret files, or imply that a strategy has demonstrated profitability.
