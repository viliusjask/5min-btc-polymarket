# Progress: standalone BTC five-minute repair

2026-09-06. Branch feat/standalone-btc5m in .worktrees/standalone.

- Completed read-only upstream audit and scientific, trader-experience and execution/API research.
- Established feature branch/worktree, Python3.12 environment, pinned official SDK0.9.0 and uv lock.
- Design and implementation plan drafted; independent design critique pending.
- Anonymous boundary probe in progress: compare exact TWAP source timestamps to later official anchors.
- Implementation tasks1..4 pending; no real orders or account actions.

Decisions: default experimental value filter plus original momentum comparison; no fitted drift,
no passive market-making, no micro-hedge. Captured opening-anchor permission depends on probe evidence.
Terminal surplus is a valuation proxy, distinct from stopped-policy profit. Full simulator deferred.
All parameters remain hypotheses. Actual funded validation remains a later explicit user step.
