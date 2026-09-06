# Progress: standalone BTC five-minute repair

2026-09-06. Branch feat/standalone-btc5m in .worktrees/standalone.

- Completed read-only upstream audit and scientific, trader-experience and execution/API research.
- Established feature branch/worktree, Python3.12 environment, pinned official SDK0.9.0 and uv lock.
- Design independently reviewed; six execution and five strategy findings incorporated.
- Anonymous boundary probe passed two comparisons, including exact second vs neighboring seconds.
- Task1 core/config/strategy implementation running; tasks2..4 pending. No real orders or account actions.

Decisions: default experimental value filter plus modified upstream momentum comparison; no fitted drift,
no passive market-making, no micro-hedge. Exact captured TWAP60 opening anchors enabled on probe evidence; missing boundaries still skip.
Terminal surplus is a valuation proxy, distinct from stopped-policy profit. Full simulator deferred.
All parameters remain hypotheses. Actual funded validation remains a later explicit user step.
