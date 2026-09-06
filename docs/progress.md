# Progress: standalone BTC five-minute repair

2026-09-06. Branch feat/standalone-btc5m in .worktrees/standalone.

- Completed read-only upstream audit and scientific, trader-experience and execution/API research.
- Established feature branch/worktree, Python3.12 environment, pinned official SDK0.9.0 and uv lock.
- Design independently reviewed; six execution and five strategy findings incorporated.
- Anonymous boundary probe passed two comparisons, including exact second vs neighboring seconds.
- Task1 complete and independently approved;122tests,lint/format/mypy pass.
- Task2 implemented at2e5cd84;50 adapter tests and172 combined tests pass, with two bounded anonymous feed/book smokes. Independent task review is running; tasks3..4 pending. No real orders or account actions.

Decisions: default experimental value filter plus modified upstream momentum comparison; no fitted drift,
no passive market-making, no micro-hedge. Exact captured TWAP60 opening anchors enabled on probe evidence; missing boundaries still skip.
Terminal surplus is a valuation proxy, distinct from stopped-policy profit. Full simulator deferred.
All parameters remain hypotheses. Actual funded validation remains a later explicit user step.

Observed feed gaps prompted a reviewed sparse-history policy:>=95% grid coverage,<=12s accepted
source gaps, unchanged2s sampling tolerance and5s currentquote freshness. Completed32minute feed capture:24/24 eligible1800second windows pass revisedsampler; strictpolicy0/24.
