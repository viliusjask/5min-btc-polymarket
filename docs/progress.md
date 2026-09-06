# Progress: standalone BTC five-minute repair

2026-09-06. Branch `feat/standalone-btc5m`, worktree `.worktrees/standalone`.
Source implementation checkpoint `3f49231b4a57cf6e00934dd86316317e3e275d19`.

## Development and review

- Upstream audit, scientific research, community evidence and current SDK/protocol review complete.
- Feature worktree, Python3.12 environment, pinned official SDK0.9.0, lock and project instructions established.
- Design independently reviewed; six execution and five strategy findings incorporated.
- Task1 independently approved;122 tests at its gate. Task2 independently approved at05c808e;182 combined tests.
- Task3 independently approved atfbe3e9e after its receipt, preparation and summary fixes;144 execution tests.
- Task4 independently approved at2e83025 after provider consumption stopped inventing calibration receipts;124 covering tests.
- Fresh full-system review found three integration defects: immediate conflict invalidation, shutdown cleanup bounds, and final-label conflict reporting.
- One combined fix wave committed at3f49231. Final full suite **412 passed in28.79s**; Ruff lint/format, mypy, lock consistency and diff checks pass. No source changes followed these checks.
- Scoped final re-review independently approved I1/I2/I3 at3f49231; no introduced defect found. Development, research, final checks and handoff are complete. Funded validation remains a separate operator stage.

## Public evidence

The initial boundary probe passed two discriminating official comparisons. A32-minute raw-feed
capture supported the reviewed sparse-history rule:24/24 eligible long windows passed versus0/24
under complete-grid sampling. No interpolation was introduced.

The earlier35-minute adapter/core capture had1,702 snapshots, seven opening anchors, six official
comparisons and five final labels. Its sole value-eligible screen exposed older underlying
information, motivating the explicitly experimental information confirmation rule.

The final actual CLI35-minute run completed19:57:05UTC, exit0 and empty stderr:23,675 observations,
2,989 snapshots,5,978 raw paired screens, and zero entry-eligible screens in either mode. Six opening
boundaries were captured; four later official matches agreed within USD1e-8. Five final references
arrived. Seven calibration-time snapshots included only one model prediction, whose final label
had not arrived. [Complete evidence and limits](research/cli-public-capture.md).

Final public checks on3f49231 also passed: locked sync, CLI help,15-second anonymous doctor, and
retrospective report read. The completed no-conflict capture report is byte-identical after the
reporting fix. Doctor saw spot/TWAP/books but was in normal warm-up; this does not certify account
or trading readiness. All root public-probe processes exited.

## Additional article and choices

The full user article and nine additional screenshots were reviewed. Public profiles and venue
PnL support the existence of the named profitable accounts; private algorithm attribution and the
claimed10M-execution dataset remain unverified. A332-pair/642-direction public quote comparison
found identical complementary/direct closing proceeds under current V2 cash fees, before merge
costs. The8-page scientific/community research PDF is complete, cited and visually checked.

The [inventory ruling](research/inventory-strategy-ruling.md) keeps two candidate modes and one
selected execution mode, with a staged six-policy research menu. Faster information is the next
research priority. Passive orders, automatic merging, an LLM loop and six funded portfolios were
not added. [All autonomous rulings and their costs](reviews/decision-register.md) are retained.

## Remaining operating boundaries

No real account was initialized and no funded order, allowance, transfer or redemption was sent.
Actual venue acceptance/fills and the user's account readiness remain unverified. Probability,
entry/exit parameters and confirmation remain hypotheses. A bounded funded experiment can use the
existing journal; constructing a separate paper platform is not required. Preserve the dedicated
wallet/journal and resolve discrepancies before further entries. Manual claiming remains external.
Branches and worktrees stay preserved; no upstream push or merge is part of this development run.
