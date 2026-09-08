# Unified experiment monitoring and collection recovery

**Goal:** Make every paper portfolio and registered experiment discoverable in one comparison view with useful individual detail, and repair the collection failures found during the September 8 results audit.

**Authority:** The user explicitly requested independent agents for each identified issue, root review, then a separate integration/review agent. The user's unified list/detail vision is the approved design; proceed without repeated human design checkpoints. Existing feature/worktree discipline and unfunded development restrictions apply.

**Architecture:** Preserve the collector tape and every existing account/study journal. Extend the existing Python read-only dashboard and plain JavaScript assets; reuse Ledger, ResearchReader, existing report metrics and charts. No new runtime dependency, no strategy retuning, no capital reset, and no implicit funded API calls.

## User-facing design

The Paper view opens one long list covering the six original portfolios and every phase/variant in both experiment suites. Source, phase and strategy version remain identifiable without separate top-level screens. Search/filter by family, source, evidence quality and activity; sort by net profit, return on initial allocation, profit per completed traded round, win rate, completed count, largest win and drawdown where the existing data can support it. Unknown values sort consistently and display as unavailable rather than zero. All/unflagged views must not silently select different denominators or remove lost capital from account returns.

One comparison chart overlays individual cumulative net/return curves on a common chronological axis. Do not sum overlapping simulated profits. Keep legends/selection usable with 107+ lines; a visible selection/limit is preferable to hiding sources. Clicking any row opens a detail view with clear name, configuration and timeframe, net/return and drawdown graphs, sample sizes, uncertainty, costs, winner concentration, relevant risk-budget blocking, and chronological filled trades/order outcomes. Preserve the existing depth of research and paper diagnostics through the detail flow, including the real-account view. Real account access stays lazy and read-only.

## Independent assignments

- [x] **Discovery recovery** (`fix/discovery-recovery`, `3b62f8f`, root reviewed): Reproduced the timeout as event-loop starvation from full historical measurement scans in `Ledger.record_clock`. A partial index and due-only query replace the scan; 716 tests and static gates pass. No HTTP retry/client changes were warranted. Integrated deployment verification remains below.
- [x] **Held-position input gaps** (`fix/held-data-gaps`, `e439aac`, root reviewed): Fixed chronological retirement so restored old markets cannot evict the active reference or its sticky conflict. Three regression cases and 117 focused tests pass. Spot freshness remains unchanged; remeasure delayed data after the collector fix. Historical study flags remain intact.
- [x] **Unified experiment browser** (`feat/experiment-browser`, `9a0693e`, root reviewed): Implemented the complete list/overlay/detail flow using existing accounting and a bounded financial-change cache. Root-reviewed input validation, read-only boundaries, account-return denominators, report/journal consistency and actual desktop/mobile behavior. Worker recorded 720 passing tests and clean static/lock checks. Preview contains 108 distinct source/phase rows, including the newly registered holdout. No collector restart by worker.
- [x] **Dashboard history catch-up** (`fix/dashboard-catchup`, `47ae0cc`, root reviewed): A server-owned reader now follows bounded 10,000-event batches independently from browser/cache cadence. Five regressions cover autonomous progress, closing, failures without double-counting, truncation and file replacement. Forty focused cases have passing results after a legacy fixture adjustment; static/lock checks pass. The actual 2.366-million-event journal caught up in 41.282 seconds with only initial/final snapshot requests; close took 1 ms. Integration must adapt the new browser HTTP test's incomplete lifecycle double.
- [x] **Root review:** Reviewed all four source commits and their tests/evidence. Desktop/mobile preview, numeric sorts, source/search/minimum-sample filters and cohort/detail behavior pass; no Paper request reaches Real. Confirmed the frozen Momentum candidate's metrics against the new endpoints. The combined branch still requires the independent review and acceptance checks below.
- [x] **Independent integration review:** A new agent reviewed and integrated all four changes into `feat/unified-research`. It reproduced and fixed the HTTP test's lifecycle mismatch and a concurrent-capture clock race discovered during root's browser checks. Final source `ac3d037` passed all 734 tests, Ruff, formatting, mypy, lock and CLI checks. No blocking findings remain; [the review](../research/unified-integration-review.md) records exact evidence. Root retains ownership of the anonymous multi-round probe, final browser checks and preserved local service cutover.

## Acceptance evidence

Use meaningful regression tests for failure/recovery behavior and financial presentation, followed by the existing pytest, ruff and mypy gates on the integrated branch. Browser verification must exercise the long list, numeric sorting/filtering, overlay selection and both baseline/experiment details at a desktop and narrow viewport. Verify no real API call is made while browsing Paper.

For collector changes, record an anonymous multi-round probe with exact source commit, valid/missing counts and failures; compare against the pre-fix behavior where practical. Test disconnect/cancellation/shutdown recovery and avoid mistaking heartbeat continuity for usable snapshot continuity. A finite probe is evidence for its interval, not a claim of permanent reliability.

Deploy only after the combined tests/review; preserve account session identities, financial rows, tape history and study registrations. Do not change the pinned strategy implementations used by existing studies. Record the exact deployment boundary and gap. The user merges PRs; never merge/push main or delete branches. Root opens a reviewable PR once the work is complete.

## Starting evidence

Base commit: `8d12573` (PR13 remains open as of September 8). Running source is the separate `metadata-refresh` worktree. Current runtime: `/home/vilius/.local/share/btc5m/paper-six-100-each`. Frozen audit: `/home/vilius/projects/5min-btc-polymarket/.worktrees/metadata-refresh/work/results-audit/report.md` and its companion JSON/CSV files. No credentials are needed.

The six-wallet LOSS_LIMIT rule is behaving as implemented; it is a visibility/research-design issue, not authorization to remove budget protection. Likewise, a losing strategy is not by itself a code bug. Keep model-performance findings and future parameter tests in the results explanation instead of changing strategies during these fixes.
