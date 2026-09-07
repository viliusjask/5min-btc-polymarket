# Progress: paper and real account monitoring

2026-09-07. Branch `feat/paper-dashboard`, worktree `.worktrees/dashboard`, based on the user's
fork main `c4d4b9b` after the operator merged PRs #2 then #1. Original upstream and feature
branches remain preserved. This change used the requested single-agent implementation and review.

- Diagnosed the original zero-order capture: the long history had a 25-second sampled gap
  from a development restart, above the 12-second guard. Separated warm-up, schedule, empty-book,
  reference and metadata rejections. [Exact counts](research/paper-capture-diagnosis.md).
- Added local read-only dashboard, six portfolio cards, accounting curves, feed/decision charts,
  sampling details, order/fill/holding tables, filters and selected-view JSON export. No fills
  means "Awaiting first trade" and an empty performance curve, not flat-return evidence.
- Added recorder heartbeat and final lifecycle status. The dashboard and collector run
  independently, so dashboard work does not repeatedly break the source-history window.
- Added Paper/Real view switch. Explicit account mode reuses existing no-deploy authentication,
  Polygon balance reads, public indexed positions, and authenticated order/recent-trade reads.
  It labels outside-bot activity, unavailable sections, old account snapshots and truncated trade
  history. Maker records use our wallet's leg. API-key owner fields and signed payloads are omitted.
  Monitoring cannot start trading, submit/cancel orders, approve, transfer or redeem funds.
- Started a separate two-hour anonymous run with **USD100 per strategy, USD600 total** under
  `work/paper-six-100-each-20260907`, using local `work/paper-100-each.toml`. Per-entry budget stays
  USD5; per-portfolio day/session loss limits stay USD10. Earlier captures are preserved. At
  the integration check all six had USD100 cash and zero fills while accumulating initial history.

Verification: **489 tests passed in 102.76 seconds**. Ruff lint/format (37 files), mypy (19 source
files), locked dependency consistency, JavaScript syntax and diff checks passed. New tests cover
accounting timing, real delayed paper fills, readonly journal access, incremental aggregation,
heartbeat aging, HTTP isolation, account identity, maker attribution, missing sections and
credential redaction. After a final dashboard signal-handling correction, all 15 dashboard tests
passed again in 16.90 seconds, including stopping on the first signal and restoring the handler.
No runtime dependency was added.

The 45-second anonymous recorder smoke completed with 1,452 journal events, explicit stopped
status and empty stderr. Browser checks exercised both views, six USD100 cards, mobile width,
filters, tabs and export without JavaScript errors. Authorized real-account monitoring returned
all four account sections successfully; no funded bot journal existed. This validates reads and
display behaviour, not funded execution, profitability or a completed two-hour experiment.

Account projection follows the pinned SDK0.9.0 models and the official
[trade response contract](https://docs.polymarket.com/trading/clients/l2).
The `owner` field is an API-key identifier, so it is deliberately absent from dashboard JSON.

---

# Historical record: six-strategy extension

2026-09-07. Branch `feat/six-strategies`, worktree `.worktrees/six-strategies`, based on
`60615024f1b7fb4a3cc8afe6d606967b00f51a03`. All six policies are implemented and connected to
the common execution engine. This extension used one agent's implementation, own review and
tests, as requested. The previous multi-agent repair record below is historical.

## Implemented and checked

- Added `fast_value`, `model_exit`, `passive_pairs` and `inventory_pairs` to the two repaired
  baselines. [Exact mechanics, assumptions and limits](six-strategies.md).
- Added anonymous public exchange/book/trade streams, six independent paper accounts, persisted
  reports, delayed simulated execution, queue-volume fills, restart history and settlement polling.
- Added explicit operator credential provisioning. The operator generated the trading tuple;
  subsequent authorized read-only checks verified authentication, wallet association, collateral
  and approvals. An existing external holding remains a dedicated-account entry blocker.
- Corrected measured stream-book sequencing/empty-side cases, index precision comparison,
  full-principal paper BUY execution, queue restart identity, same-price queue accounting and
  activation-timestamp trade double counting. Each accounting/execution correction has a regression.
- Each of the six policies is driven through confirmation, submission and a fill in controlled
  tests. Further tests exercise fair-value math, stale/unaligned feeds, model exits, real pinned-SDK
  resting-order signing/cancellation with intercepted transport, partial fills, cancellation races,
  unmatched timeout, two-leg settlement, report attribution, account checks and restart isolation.

Final suite: **475 passed in 72.33 seconds**. Ruff lint/format, mypy (17 source files), locked
dependency consistency and diff checks passed. Main/paper CLI help also passed. The only later
Python edit clarifies paper shutdown help: its exposure-monitoring deadline does not include
the subsequent transport cleanup. That help and static checks were rechecked.

The public comparison capture spans **23:10:37–23:48:42 UTC on September 6** (38.07 minutes),
across four cleanly stopped runs. It is not an uninterrupted hour despite the local directory
name `work/paper-six-60m`. The last 45-second segment used the final execution source. Together
the runs recorded 19,070 books, 9,997 public trades, 5,517 exchange observations, 2,116 Chainlink
spot observations and three official final references. All four runs exited 0; stderr was empty.
All six portfolios ended with **zero orders, fills, open positions and unresolved orders**.
History/window/reference/book guards rejected candidates; fast mode additionally rejected stale
or unaligned ticks. This verifies public collection, screening, restart and shutdown integration,
not execution on organic signals or strategy returns. Controlled functional tests supply the
entry/fill/exit evidence. Public records remain in the ignored local runtime.

No funded order, approval, transfer, merge or redemption was submitted. Automated tests establish
specified behaviour; they do not establish calibrated probabilities, actual queue priority or ROI.
Live GTC orders can survive process failure, and live redemption remains manual.

---

# Historical record: standalone BTC five-minute repair

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
