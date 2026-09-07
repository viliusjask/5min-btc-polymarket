# Progress: Momentum and execution policy corrections

2026-09-07. `fix/strategy-policy-audit`, isolated `.worktrees/strategy-policy-audit`.
User-authorized Astra implementation and bounded strategy audits; no cross-model workflow.
[Methods, defects, frozen replay and limitations](research/strategy-policy-audit.md).

- Corrected Momentum to use the recent signed 30-second BTC move relative to five-minute
  observed price variation. It no longer requires a terminal model or half-hour history.
  Preserved price/timing bands, trade budgets, confirmation and exits; retained explicit
  `opening_lead` comparison and unchanged pinned legacy studies.
- Corrected pair completion funding checks, unmatched timeout behind a resting hedge, and
  Model exit input freshness after awaited book/settlement operations. Value/Fast entry
  policies were audited; no unsupported parameter changes were made.
- Frozen 44,752-frame replay: old and explicit legacy policy match exactly. Recent policy
  had 66 candidate rounds versus 18, but only three completed trades, all flagged uncertain.
  The retained loss limit then blocked more orders. This is no profitability result.
- Dashboard describes the current signal and required history, and marks the policy cutover
  so lifetime totals cannot be mistaken for a clean result of the new policy.
- Main lacked the PR11 research dashboard: PR11 was merged into PR10's branch after PR10
  had merged. This feature branch includes that merge so the PR to main preserves it.

Validation: **681 tests passed in 210.19 seconds**. Ruff lint/format, mypy (33 source
files), dependency lock, CLI help and whitespace checks passed. Browser checks covered
all six Paper portfolios, both unchanged registered studies (84 + 17 variants), research
comparisons/export, corrected Momentum sampling and the policy notice, desktop/mobile
layout, no JavaScript errors and no Real-account requests. Service unit verification used
an isolated XDG_RUNTIME_DIR. A seven-journal metadata migration passed on backed-up copies,
preserving sessions/accounting; its final bounded path took 0.699 seconds on those copies.
Deployment confirmation is recorded after the service cutover.

---

# Progress: strategy performance comparisons

2026-09-07. `feat/research-comparisons`, isolated `.worktrees/research-comparisons`,
based on PR10's `455e17f`. Single-agent implementation and own review. The user requested
research tools for drawing conclusions, beyond operational diagnostics.
[PR11](https://github.com/viliusjask/5min-btc-polymarket/pull/11), implementation `4d58848`.

- Added **Experiments → Strategy research** for both existing registered studies (84+17
  variants). Individual market profit distributions, typical/average outcomes, removal of
  the best one/three wins, fee and added-cost sensitivity, fixed entry/exit-condition groups,
  hourly contributions, same-market comparisons, overlap/correlation, and paired 30/60-minute
  block resampling use existing accounting. [Methods and practical reading guide](research/strategy-comparisons.md).
- Reversal/continuation and absorption/continuation comparisons initially match lookback and
  threshold. Manual comparator, phase and flagged/unflagged selectors are available; JSON
  export retains the exact selected calculations. No strategy parameters, study definitions,
  wallet balances, dependencies or funded execution were changed.
- **642 tests passed in162.67seconds**. After fixed numerical group ordering was added,
  all14research/dashboard tests passed again. Ruff lint/format, mypy33sources, dependency
  lock and whitespace checks passed. New cases include complete/incomplete accounting,
  delayed settlement, dollar conservation, missing rounds/blocks and read-only API boundaries.
- Desktop and390px browser checks exercised84+17variants, opposite/manual comparisons,
  every grouping, cohort filtering, downloads, overview return and six original wallets.
  No JavaScript errors or Real-account requests. Follow-up mobile layout makes the grouping
  control stack below its heading; long hourly tables scroll inside their panel.
- Deployed only the dashboard to this checkout. Collector3917006, original lab3802676 and
  flow lab3850281 retained their process ids; both study manifests and all six portfolio
  sessions matched before/after. Dashboard4022225 serves the research API on8765. The unit
  verifier used an isolated temporary runtime; neither credentials nor study state were changed.
  The complete browser check passed again on live8765, including all research selectors,
  downloads, both studies and the six original wallets. Updated installed-location docs and
  the global operating cheatsheet; preserve all four service-referenced worktrees.

Local ignored verification: `work/browser-check.log`, `work/live-browser-check.log`,
`work/research-probe.json` and `work/cutover/`.

# Previous checkpoint: explain experiment evidence and capture failures

2026-09-07. `fix/research-evidence`, isolated `.worktrees/evidence-audit`, based on
PR9's `de70bf6`. Single-agent implementation and own review. No new dependency, strategy,
parameter change, credential inspection or funded operation.
[PR10](https://github.com/viliusjask/5min-btc-polymarket/pull/10), implementation `d26bf49`.

- Independently audited the two reversal gains totaling **USD195.147396** against original
  frame checksums, timestamps, token identities, depth, protected order amounts, fees and
  nearby public trade reports. Endpoint checks pass; both existing path-uncertainty flags
  remain. [Audit and exact limitations](research/reversal-evidence-audit.md).
- Every variant now shows all realized profit, completed unflagged profit, their exact
  excluded remainder, completion counts and incomplete exposure together. The heatmap's
  denominator follows its selected metric. Forecast comparisons use plain language;
  scanner status polls are distinct from protected price candidates.
- The collector records the first failed snapshot check, separately from recorder delays.
  Sample availability, consecutive unavailable spans and cause counts commit atomically
  with new frames and survive restart. Historical unknown causes are not backfilled.
  The dashboard reads one bounded aggregate without scanning the growing capture.
- **631 tests passed in164.83seconds**. Ruff lint/format, mypy32sources, dependency lock
  and whitespace checks passed. Regression tests cover failed snapshot checks/recovery,
  transactional counter rollback, restart continuity and exact profit decomposition.
- A180-second public probe distinguished stale spot, silent spot, metadata expiry and
  round rollover. Desktop/390px browser checks passed:84+17variants, six original wallets,
  visible profit partitions, metric denominators, conversions and diagnostic failure states.
  No JavaScript errors, mobile page overflow or real-account requests occurred.
- Deployed only collector/dashboard; restart25.444seconds, actual last-old/first-new frame
  interval25.041seconds. The old35,024-frame prefix, seven journal sessions, all prior
  fills/accounting/intents, both study manifests and both study process ids were retained.
  Both workers consumed new diagnostic-bearing frames and reached one-frame lag in the
  subsequent check. The original six remain continuous, and their prior cash/loss history
  was not reset. Live8765 browser checks passed; PR10's implementation CI passed.
- Updated installed-location documentation and the global operating cheatsheet. Both lab
  workers remain pinned to their original code. The generic installer is not appropriate
  for collector-only updates with those studies pinned; preserve its flow-capture argument
  while changing only collector/dashboard checkout paths.

Local ignored verification: `work/reversal-audit.json`, `work/probe-quality.json`,
`work/full-tests.log`, `work/browser-check.log` and `work/cutover/`.

# Previous checkpoint: order-flow and pair experiments

2026-09-07. `feat/order-flow-experiments`, `.worktrees/order-flow`, from merged PR8
(`687ba4a`). Single-agent implementation and own review; [PR9](https://github.com/viliusjask/5min-btc-polymarket/pull/9).
Implementation checkpoint `e75adfd`; no funded transactions, credential inspection or new dependencies.

- Implemented the five authorized research ideas as **17 separate USD100 variants plus a
  quote scanner**. Exact rules, controls and limits are in [order-flow.md](order-flow.md).
  Public aggregate volume, depth and Polymarket trades are recorded with receipt timestamps.
  Passive pair replay, delayed split/merge accounting and early-signal state recover atomically.
- **621 tests passed in164.04seconds**. Ruff lint/format, mypy31sources, dependency-lock and
  whitespace checks passed. Tests include directional symmetry, common early observations,
  incompatible cross-duration contracts, queue uncertainty, delayed splits, two sale fills,
  no-sale cancellation/merge, partial conversion accounting and restart recovery.
- A300-second public probe recorded **583 frames**. Final-code replay produced nine opening
  fills across nine directional variants. Split/sell recorded one passive fill and a taker
  cleanup of the unmatched side. Its realized result was **−USD1.131500**, and a capture gap
  made that round unsuitable for clean comparison. This is functional execution evidence,
  not a performance sample. The scanner made275checks with zero protected quote candidates;
  shared-expiry quotes, unavailable anchors/books and budget/price rejections remained distinct.
- Desktop and390px browser checks passed with no JavaScript errors: original84variants,
  new17variants, original six portfolios, study switching and actual conversion records.
  A second pass used the deployed API. Split conversions and maker-sale fill rates are separate.
- Continuous collection/dashboard switched to `e75adfd` in **12.719seconds**, retaining all
  seven original journal sessions, prior fill/accounting/order rows and **12,623 tape frames**.
  `btc5m-lab.service` stayed on its old process and registered code. Both old and new workers
  caught up with the same extended tape; missing pre-capture volume was not fabricated.
- `btc5m-flow-lab.service` is enabled with the existing WSL supervisor arrangement. An actual
  SIGKILL test restarted it, preserving all17variant journals, cursor12800 and the unchanged
  registration, without restarting the collector. That new study was still in its excluded
  partial round and had no fills yet; synthetic restart tests separately cover filled and
  partially completed conversion lifecycles. The original continuous portfolios remain active.

Local ignored evidence: `work/final-tests.log`, `work/public-flow/capture.sqlite`,
`work/flow-study-release-check/report.json`, `work/browser-check.log`,
`work/live-browser-check.log`, `work/final-cutover.json` and `work/flow-restart.json`.
The operating cheatsheet was updated. Both service-referenced worktrees remain preserved.

# Previous checkpoint: fix unfillable protected cash/share amounts

2026-09-07. `fix/limit-sizing`, isolated `.worktrees/limit-sizing`, based on merged PR6
(`11f80d1`). Single-agent diagnosis/implementation. No new dependencies or funded operations.

- Traced the first Fast value, Value and Model exit orders in the05:10UTC round. At their
  allowed0.32/0.34 execution prices, rounded required shares cost slightly more thanUSD4.67.
  The earlier repair tested the better current ask and missed this later execution boundary.
- Reused the exact cash/share-grid calculation for every BUY whose minimum shares are
  unaffordable at its limit. Reduce cash and recompute costs without relaxing price, fee,
  share-receipt or spending protections. All four directional modes use the correction.
- Original captured-book reconstruction reproduced three unfilled orders; corrected cash
  amounts4.66/4.59/4.59 produced three counterfactual fills. Historical orders/results remain
  untouched. Evidence and reconstruction limits are in [the sizing audit](research/limit-price-sizing.md).
- Ten new regression cases failed on the original source: actual pinned-SDK signing and
  all four directional engines with asks rising to the permitted limit. Corrected cases pass.
  Additional tests retain rejection of worse prices, insufficient depth and malformed minimum
  shares; final pre-post authorization still rejects resized decisions.
- Immediate paper orders now retain execution-time book timestamps, quotes, price limit,
  requested cash/shares, available shares and remaining amount in existing journal measurements.
  TheUSD100 portfolios andUSD5 order budgets are unchanged.
- **562 tests passed in127.11seconds**. Ruff lint/format, mypy20sources, locked dependencies
  and whitespace checks passed. The before-fix ten-case failure log, complete final test log,
  three-order reconstruction and prepared preservation/reload scripts remain in ignored `work/`.
- Applied code commit7a1ae14 to the continuous services at05:46:06–05:46:13UTC. Seven journal
  sessions and all prior orders/fills/accounting rows were retained. No configuration fingerprints
  changed; a dated IMPLEMENTATION_CHANGED event records old/new source commits in each journal.
  Services now run from `.worktrees/limit-sizing`, with zero supervisor restarts. The dashboard
  responds with matching configuration and a caught-up collector. Preservation evidence is in
  `work/sizing-cutover.json` and `work/sizing-reload-result.json`.
- At05:48:41UTC the latest sampling records for all six strategies were from after the reload,
  with valid short/long histories and a largest sampled gap of10seconds. No fresh30-minute
  warm-up was needed. A previously recorded Fast value fill at05:28:13UTC predates this fix and
  is not evidence of corrected prospective execution. The three replay fills remain counterfactual.

## Previous entry-filter checkpoint

# Progress: broaden entry filters and explain one-sided books

2026-09-07. `fix/entry-filters`, isolated `.worktrees/entry-filters`, based on merged PR5
(`c851d83`). Single-agent implementation and own review; public feeds and synthetic execution only.

- Removed the default0.60 ask floor for Value, Fast value and Model exit. Positive executable
  prices, the0.92 ceiling, model-surplus/cost requirements, confirmation and USD5 budget remain.
- Reduced Momentum's minimum lead fromUSD70 toUSD50 for the paper experiment. A fixed-capture
  comparison produced2/23/45 eligible checks atUSD70/50/35, subject to recorded-book limitations.
  None had positive conservative terminal surplus; this broadens observations, not proven returns.
- Traced the original Momentum candidates through the actual execution journal: one expired
  on a widened spread while awaiting source confirmation; another failed minimum sizing.
- Matched the screenshot's0.99 Up bid/0.01 Down ask and99 mirrored levels to recorded books.
  Stable Up/Down order, explicit Buy/Sell quotes and expandable depth details replace ambiguous
  primary counts. Fresh flat portfolios outside their entry window show the schedule; actual
  in-window failures, stale data, held inventory, unresolved orders and halts remain visible.
- Entry-filter changes passed548 tests in187.98seconds, including full confirmation/submission/
  synthetic fill for each directional mode. Dashboard13 tests passed after the schedule change.
  Ruff lint/format, mypy20sources, locked dependencies and JavaScript syntax passed. Edge verified
  desktop/mobile output, all six cards, schedule cases, preserved warnings and depth expansion
  through refreshes. The paper-only migration was rehearsed on seven SQLite backup copies.

- Reloaded the existing services from the entry-filters worktree at05:03:25–05:03:57UTC.
  All seven session IDs and all prior orders, fills and accounting rows survived. Only the two
  requested strategy settings changed, with old/new configuration hashes in dated journal events.
  The manifest, loaded config and latest decision hashes agree. The collector still reports
  SOURCE_ORDERED_FLOW_V3 and BOUNDED_INTERVALS_V1; both services are active with no restarts.
- The cutover's largest raw spot gap was10seconds (05:03:47–05:03:57UTC), measured from captured
  observations rather than the full service-stop interval. Live Edge verified all six cards,
  Buy/Sell quotes, stable ordering and retained depth expansion without JavaScript errors or
  mobile overflow. The paper/dashboard remain unfunded/read-only, respectively. Rehearsal and
  preservation evidence are under ignored `work/entry-filter-migration` and `work/filter-reload-result.json`.
- At05:08:07UTC all six strategies produced fresh, valid short/long sampling checks under the
  new configuration. The sampled15-second interval remained within the coverage allowance.
  Momentum rejected an8.68-dollar lead; the three value variants rejected insufficient modeled
  surplus with `minimum_ask = 0`; both pair engines had new pending orders. The four directional
  portfolios still had no public-data fills. This confirms resumed evaluation, not profitability.

Evidence, limitations and the unchanged absolute-stop behavior at cheap entries are documented
in [entry filters and dashboard](research/entry-filters-and-dashboard.md). Passing fixtures do
not establish profitable public fills; entry readiness still depends on current source history.

## Previous execution checkpoint

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

- Applied the explicit20→0 cap migration and reloaded both existing systemd services at
  04:10:19–04:10:54UTC, retaining all seven session IDs and all original orders, fills and
  accounting rows. Only the current session's configuration fingerprint was advanced, with
  a dated CONFIGURATION_CHANGED event preserving both fingerprints and the exact policy change.
  No loss-session reset or retrospective fill repair occurred. SQLite backup rehearsals,
  applied migration and before/after evidence live under the ignored strategy-execution
  `work/entry-cap-migration` and `work/execution-reload-result.json`.
- Active services confirmed SOURCE_ORDERED_FLOW_V3 and BOUNDED_INTERVALS_V1, zero entry cap,
  matching config/manifest and no supervisor restarts. Live Edge verified six cards and the
  corrected counters without JavaScript errors. Public books now show labeled outcomes and
  actual quotes (at the check, Up0.34/0.35 and Down0.65/0.66). The original four directional
  portfolios still have no recorded fills; passing mechanical tests is not evidence of an edge.
- Prospective check at04:17:22UTC: the next opening reference was captured and the short
  history was valid, but the long history contained92 irregular seconds (22 from an earlier
  interruption and70 from this maintenance reload), exceeding its90-second allowance.
  Therefore new entries remained paused. The earlier gap leaves the30-minute window around
  04:26:15UTC, conditional on no further gaps. This is recorded separately from passing
  execution tests; a running service does not prove current entry readiness.

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

# Current checkpoint: strategy experiment lab

September 7, 2026. `feat/experiment-lab`, source `bbf9e2e`. [PR8](https://github.com/viliusjask/5min-btc-polymarket/pull/8)
implements the five priorities in [the plan](plans/experiment-lab.md). Development followed the
user's single-agent instruction: research, implementation and own review; no cross-model gate.
The [operator guide](experiment-lab.md) describes all 84 trials and their limitations.

- Full suite: **592 passed in 136.58s**, plus Ruff lint/format, mypy (26 modules), locked
  dependencies, both JS syntax checks and whitespace checks. Tests include a real SIGKILL
  mid-replay-frame, loss of a derived cache suffix while other cursors are ahead, exactly-once
  cash/fills, preserved confirmation, future-only freeze and recovery of a partly saved freeze.
- Browser checks: 84 variant rows, 30 Momentum grid cells, 14 exit variants, calibration bins,
  filters and phase selection, exports, empty/error states, 390px layout, and all original six
  portfolio cards. A separate browser pass used the actual deployed API, with no JS errors.
- The input recorder first went live at `5760d5e`; final integration at `bbf9e2e` retained all
  seven original journals, sessions and historical cash/fill rows, plus all **2,375** prior tape
  frames. The prepared collector/dashboard restart took **14.688 seconds**. Funded operation
  stayed off and no credential file was read.
- All three user services run from `.worktrees/experiment-lab`: `btc5m-paper`, `btc5m-dashboard`
  and `btc5m-lab`. The lab is independent of the original six portfolios and retains their
  public input tape under the existing persistent runtime. A real lab service restart retained
  all **84** variant journals, **162** fill rows and the unchanged registration at cursor1520,
  without changing the original collector process. The worker then continued catching up.
- At cursor1648, the actual public-input replay had **98 simulated opening fills across67
  variants** and **three scoreable forecast rounds**. Fills across correlated variants are not
  independent observations or a profitability estimate. Some earlier capture gaps mark affected
  results uncertain; both raw and usable completed profit remain visible.

Evidence is saved locally in the ignored `work/` directory: `final-tests.log`,
`browser-check.log`, `live-browser-check.log`, `final-cutover.json` and `lab-restart.json`.
No additional runtime dependency was installed. Future profitability and the untouched test's
results are still empirical questions; the first automatic selection is after288 full rounds.

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
