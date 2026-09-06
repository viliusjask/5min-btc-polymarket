# Progress: standalone BTC five-minute repair

2026-09-06. Branch feat/standalone-btc5m in .worktrees/standalone.

- Completed read-only upstream audit and scientific, trader-experience and execution/API research.
- Established feature branch/worktree, Python3.12 environment, pinned official SDK0.9.0 and uv lock.
- Design independently reviewed; six execution and five strategy findings incorporated.
- Anonymous boundary probe passed two comparisons, including exact second vs neighboring seconds.
- Task1 complete and independently approved;122tests,lint/format/mypy pass.
- Task2 complete and independently approved at05c808e. Two review findings fixed with targeted regressions;60 adapter tests and182 combined tests pass, lint/format/mypy clean. Two bounded anonymous feed/book smokes are recorded.
- Task 3 implementation is committed at c05efcb; 301 combined tests pass under the patched pytest 9.0.3 runner, with static checks clean. Independent review against 1770a14 reproduced three accounting/metadata/concurrent-report defects; the original implementer is fixing them with regressions, alongside the clarified persistent-close policy. Task 4 CLI/integration follows the gate. No real orders or account actions.
- The 35-minute anonymous adapter/core run completed at 17:42 UTC: 1,702 snapshots, seven opening anchors, six official comparisons and five final labels. Its one eligible value screen exposed delayed underlying information; an independently reviewed confirmation experiment is being implemented. Rejected-field diagnostics and the researched SELL tick-update policy are recorded for integration.

Decisions: default experimental value filter plus modified upstream momentum comparison; no fitted drift,
no passive market-making, no micro-hedge. Exact captured TWAP60 opening anchors enabled on probe evidence; missing boundaries still skip.
Terminal surplus is a valuation proxy, distinct from stopped-policy profit. Full simulator deferred.
All parameters remain hypotheses. Actual funded validation remains a later explicit user step.

Observed feed gaps prompted a reviewed sparse-history policy:>=95% grid coverage,<=12s accepted
source gaps, unchanged2s sampling tolerance and5s currentquote freshness. Completed32minute feed capture:24/24 eligible1800second windows pass revisedsampler; strictpolicy0/24.
