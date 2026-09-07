# Progress: repair missing fills, entry sizing and misleading counters

2026-09-07. Work verified on `fix/strategy-execution`, based on `fix/history-resilience`.
The user requested diagnosis of near-zero fills and inactive strategies, then explicitly
removed our arbitrary20-entry daily cap. Single-agent implementation and own review;
no new dependencies or funded operations.

- Corrected passive simulation to compare source and receipt clocks independently and to
  clear obsolete same-price queue depth when qualifying public trades execute through a bid.
  Fills remain limited to observed, deduplicated volume. New records use SOURCE_ORDERED_FLOW_V3;
  prior missing timestamps are not fabricated. Initial queue depth is now retained.
- Replayed55 originally unfilled orders: the baseline reproduced zero fills; the correction
  recovered three, including the0.67 hedge whose omission caused a later simulated stop loss.
  This does not rewrite original cash or establish whole-portfolio returns.
- Optional slippage and SDK share rounding no longer reject affordable0.92/0.93 entries.
  Reduced cash amounts preserve theUSD5 budget and fee reserve. Actual pinned SDK signing
  and controller-to-paper-fill tests cover the corrected boundary for all four directional modes.
- The default daily entry-count cap is disabled (`max_entries_per_day = 0`). Explicit positive
  caps remain supported; zero-fill closures do not consume their slots. Tests cover25 completed
  rounds in one day, restart preservation, partial/unknown orders and a deliberately enabled cap.
- Dashboard distinguishes traded rounds, buy/sell fill records and order attempts. Book rows
  show Up/Down prices, round and source time;99/0 is explicitly a count of price levels.
  Numeric entry-filter reasons and older-simulator warnings explain inactive or historical data.
- Pair variants intentionally share opening logic; value/model_exit intentionally share entries.
  Recorded price-band sensitivity found additional candidates below0.60, but that separate
  strategy change has not been enabled. See [execution and entry audit](research/execution-and-entry-audit.md).
- **541 tests passed in138.15seconds**. Ruff lint/format, mypy (20 sources), locked dependencies,
  JavaScript syntax and whitespace checks passed. Headless Edge verified six cards, explicit
  quote-vs-depth labels (including0.999 precision), separate trade/fill counters, no JavaScript
  errors and no overflow at390px. Paper-cap migration rehearsed against all seven journal
  copies, preserving every session ID and all cash/position/fill/accounting rows.

## Previous history checkpoint

# Progress: recover from brief history gaps

2026-09-07. Branch `fix/history-resilience`, isolated worktree `.worktrees/history-resilience`,
based on merged fork main d26e799 (PR4). The user explicitly requested correcting the overly
strict history rule. Own review, no subagents or new dependencies.

- Replaced the hard largest-gap veto with at least95% point coverage and95% regular-interval
  time coverage. Intervals over12seconds consume the remaining time budget. Both5minute and
  30minute histories must pass. Observed moves across gaps remain in the variance estimate;
  missing endpoints, large outages, stale/future prices and insufficient coverage still reject.
- Separated the15second feed inactivity deadline from the5second current-price freshness limit.
  Delayed feeds can resume on the same subscription while entries remain paused. Genuine
  transport errors and persistent silence still reconnect.
- Dashboard readiness uses the newest sampling check, rather than all historical failures or
  an older strategy's successful sample. Shows coverage and time in long intervals. Historical
  simulator warnings remain visible without overriding current history readiness.
- Recorded-data replay:392 additional long-window checks and112 additional short-window checks
  became usable. All1673 previously valid estimates stayed exactly unchanged. The windows
  overlap; this measures availability, not profit or independent statistical evidence.
  Policy rationale, fingerprinted capture and limitations: [sampling research](research/volatility-sampling.md).
- **516 tests passed in112.67seconds**. Ruff lint/format, mypy, lock, JavaScript syntax and diff
  checks passed. Desktop/mobile browser fixtures verified both current readiness overriding
  historical failures and a new failure overriding an old valid sample, with no JavaScript
  errors or page overflow. The reconnect regression fails against the original consumer and
  passes with the fix.
- Repointed both systemd user services to this checkout and reloaded at02:52:46–02:52:51UTC.
  All seven journal sessions, prior orders, fills and events were preserved. Balances remain
  USD100 each; no retrospective fills were injected and funded execution remains off.
  At02:54:42UTC all six latest history checks reported VALID under BOUNDED_INTERVALS_V1;
  pairing portfolios had resumed order submission (62 attempts each, zero fills at that check).
  Healthy history permits strategy evaluation; it does not guarantee fills or returns.

## Earlier quote and service checkpoints

# Progress: continuous services and corrected quote cancellation

2026-09-07, follow-up to the 0/98 screenshot. The matching fix alone did not repair the
quote controller. It cancelled an owned quote whenever the next preferred quote changed,
including favorable repricing and switching the preferred outcome while the old quote was
still within its limits.

- Existing quotes now keep priority while their own constraints hold, up to the original
  five-second lifetime. Remaining opening quantity still needs its model surplus after a
  partial fill. Hedge reservations, risk limits, model thresholds and fill evidence are unchanged.
- New decisions carry `KEEP_VALID_V1`, best bid/ask and distance below the bid. Cancellation
  triggers are durable and correlated to order identity. Dashboard outcomes distinguish
  Resting, Cancelling and Cancelled unfilled and display the trigger when it was recorded.
- Replayed 25 original V2 orders independently with recorded public prices/books/trades and
  original queue estimates. Seventeen stayed active longer; one filled five shares at 0.70
  versus its original zero. The other 24 remained unfilled. This is a bounded controller
  replay, not a portfolio backtest. Details and limitations: [diagnosis](research/paper-fill-diagnosis.md).
- Full suite: **509 passed in 177.41 seconds**. A subsequent nine-test targeted run also passed,
  including an added partial-fill risk regression. Ruff lint/format, mypy, locked dependency,
  JavaScript syntax and diff checks passed. Own review; no subagents or new dependencies.
- Services reloaded at **02:26:47–02:26:52 UTC**. All seven journals retained their sessions,
  prior order IDs, fill counts and event history. Collector/dashboard are active with no
  automatic restarts. New public decisions report `KEEP_VALID_V1`.
- Live state after reload: USD100 each, 116 historical order attempts, zero fills. New entries
  are currently paused by a 15-second sampled history gap; raw spot records contain separate
  nine- and ten-second gaps around 02:16 and 02:22 UTC, accompanied by stream timeouts. This
  reload does not repair missing observations or certify the six-strategy experiment healthy.
  No retrospective fills were credited and no real orders were sent.

## Earlier service and matching checkpoint

2026-09-07. Branch `feat/paper-service`, worktree `.worktrees/paper-service`, based on fork main
`ab54847` after PR #3. Single-agent implementation, own review, no new runtime dependencies.

- Replaced the two-hour deadline with explicit `paper --continuous`. Installed systemd user
  collector/dashboard services, readiness/heartbeat supervision, retry after failure, bounded
  shutdown and Windows task `BTC5m-WSL`. The task keeps Ubuntu available while Windows is logged
  in and restarts its client after exit. No sleep-policy changes, funded orders or account setup.
- Preserved all seven original databases byte-identically during migration to
  `~/.local/share/btc5m/paper-six-100-each`. Original capture remains untouched in the dashboard
  worktree. Six USD100 balances, sessions, configuration, orders and risk limits were retained.
  Report/manifest publishing is atomic and synced. Low-disk checks do not delete evidence.
- Tested real child-process SIGKILL both before and after accounting application: committed
  fills recover exactly once and uncommitted writes roll back. A supervised synthetic collector
  restarted after SIGKILL, retained seven sessions/journals, recorded a seven-second process pause,
  and stopped gracefully. A separate test terminated only the Windows launcher's keepalive child;
  it was recreated without changing either application service PID. WSL itself was never killed.
- Fixed incomplete-order recovery before queue activation and rejection of an immediate order
  that would otherwise fill from a fresh book after a long observation gap. Exposed rounds are
  marked uncertain; price history retains actual timestamps and gaps after restoration.
- The user's 0/64 screenshot exposed a simulator omission: BUY Up can match BUY Down at the
  complementary price. Added this matching path, transaction-aware mirror deduplication and
  uncertainty for missing opposite-flow identity. An exact recorded-order replay recovered and
  hash-verified 18 public messages and filled five shares at 0.48 versus the old zero. This is
  execution evidence, not a full backtest or profit claim.
- Dashboard now shows filled/cancelled/rejected execution outcomes instead of calling every
  reconciled order "Settled / Entry". The 66 historical passive orders remain labelled as results
  from the old matching model. No counterfactual fills or cash were injected into live collection.
  New starts/orders record `COMPLEMENTARY_FLOW_V2`. Entry/cancellation strategy thresholds remain
  unchanged; rapid quote replacement is still a research concern.

Verification: **501 tests passed in 118.61 seconds**. Ruff lint/format (40 files including the
installer), mypy (20 source files), locked dependencies, JavaScript syntax and diff checks passed.
Public feed disconnect/reconnect, cancellation races on both matching routes, mirror suppression,
missing trade identity, service socket isolation and dashboard outcomes have regression coverage.
Browser verification on desktop and 390-pixel mobile widths showed all six cards, corrected
order outcomes and the historical-model warning, with no JavaScript errors or page overflow.
The installed units are active with no supervisor restarts; paper collection uses public data only.

During installation, systemd 249's user verifier replaced the manager control socket. The installer
now verifies inside a temporary runtime, with regression coverage. A temporary session bus restored
control without restarting other user work; recovery units were then removed. The cutover gap is
recorded and can delay the next valid 30-minute source window. [Operating guide](paper-service.md),
[matching diagnosis](research/paper-fill-diagnosis.md).

---

# Historical record: paper and real account monitoring

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
