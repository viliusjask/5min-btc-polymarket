# Unified experiment monitoring and collection recovery

**Goal:** Make every paper portfolio and registered experiment discoverable in one comparison view with useful individual detail, and repair the collection failures found during the September 8 results audit.

**Authority:** The user explicitly requested independent agents for each identified issue, root review, then a separate integration/review agent. The user's unified list/detail vision is the approved design; proceed without repeated human design checkpoints. Existing feature/worktree discipline and unfunded development restrictions apply.

**Architecture:** Preserve the collector tape and every existing account/study journal. Extend the existing Python read-only dashboard and plain JavaScript assets; reuse Ledger, ResearchReader, existing report metrics and charts. No new runtime dependency, no strategy retuning, no capital reset, and no implicit funded API calls.

## User-facing design

The Paper view opens one long list covering the six original portfolios and every phase/variant in both experiment suites. Source, phase and strategy version remain identifiable without separate top-level screens. Search/filter by family, source, evidence quality and activity; sort by net profit, return on initial allocation, profit per completed traded round, win rate, completed count, largest win and drawdown where the existing data can support it. Unknown values sort consistently and display as unavailable rather than zero. All/unflagged views must not silently select different denominators or remove lost capital from account returns.

One comparison chart overlays individual cumulative net/return curves on a common chronological axis. Do not sum overlapping simulated profits. Keep legends/selection usable with 107+ lines; a visible selection/limit is preferable to hiding sources. Clicking any row opens a detail view with clear name, configuration and timeframe, net/return and drawdown graphs, sample sizes, uncertainty, costs, winner concentration, relevant risk-budget blocking, and chronological filled trades/order outcomes. Preserve the existing depth of research and paper diagnostics through the detail flow, including the real-account view. Real account access stays lazy and read-only.

## Independent assignments

- [ ] **Discovery recovery** (`fix/discovery-recovery`): Diagnose repeated Gamma discovery timeouts in the long-lived process while a fresh anonymous request succeeds. Own HTTP request/client lifecycle portions of `market_data.py` and focused tests. Reproduce root cause or bounded failure mode before correcting it; ensure cancellation-safe cleanup and no unbounded retry/rate storm. Coordinate with held-data owner on shared-file changes. No service restart by worker.
- [ ] **Held-position input gaps** (`fix/held-data-gaps`): Investigate post-repair gaps while meaningful inventory exists: 25 metadata-expiry, eight stale-spot and two missing-round-state occurrences over 35 variant-trades/eight markets. Own snapshot scheduling/cache/stream collection fixes and focused tests. Distinguish overly broad invalidation from real missing input. Preserve required freshness, rule validity, actual gaps and historical flags; never manufacture fills. Coordinate changes to `market_data.py` with discovery owner. No study rewrites or service restart by worker.
- [ ] **Unified experiment browser** (`feat/experiment-browser`): Implement the complete list/overlay/detail flow above, owning `dashboard.py`, `dashboard_assets/`, any necessary read-only comparison module and focused dashboard/research tests. Reuse accounting utilities; isolate heavy per-ledger reads to bounded detail requests/cache. Preserve legacy API contracts unless a change is strictly needed for the approved new flow. Test mixed sources/phases, missing/zero-fill/flagged rows, financial metric denominators, bounded reads and real/paper separation. No collector restart by worker.
- [ ] **Root review:** Review each commit, test evidence and remaining uncertainty; check user-facing metric semantics against the frozen audit and confirm that all configurations remain visible. Maintain this plan/progress and the results explanation.
- [ ] **Independent integration review:** A new agent reviews all three changes, integrates them into `feat/unified-research`, resolves conflicts, and verifies interaction tests. Findings return to the relevant owner or an explicitly assigned fixer. Root then runs final repo checks, anonymous multi-round source probe and browser smoke checks before deploying the authorized local paper/dashboard fixes.

## Acceptance evidence

Use meaningful regression tests for failure/recovery behavior and financial presentation, followed by the existing pytest, ruff and mypy gates on the integrated branch. Browser verification must exercise the long list, numeric sorting/filtering, overlay selection and both baseline/experiment details at a desktop and narrow viewport. Verify no real API call is made while browsing Paper.

For collector changes, record an anonymous multi-round probe with exact source commit, valid/missing counts and failures; compare against the pre-fix behavior where practical. Test disconnect/cancellation/shutdown recovery and avoid mistaking heartbeat continuity for usable snapshot continuity. A finite probe is evidence for its interval, not a claim of permanent reliability.

Deploy only after the combined tests/review; preserve account session identities, financial rows, tape history and study registrations. Do not change the pinned strategy implementations used by existing studies. Record the exact deployment boundary and gap. The user merges PRs; never merge/push main or delete branches. Root opens a reviewable PR once the work is complete.

## Starting evidence

Base commit: `8d12573` (PR13 remains open as of September 8). Running source is the separate `metadata-refresh` worktree. Current runtime: `/home/vilius/.local/share/btc5m/paper-six-100-each`. Frozen audit: `/home/vilius/projects/5min-btc-polymarket/.worktrees/metadata-refresh/work/results-audit/report.md` and its companion JSON/CSV files. No credentials are needed.

The six-wallet LOSS_LIMIT rule is behaving as implemented; it is a visibility/research-design issue, not authorization to remove budget protection. Likewise, a losing strategy is not by itself a code bug. Keep model-performance findings and future parameter tests in the results explanation instead of changing strategies during these fixes.
