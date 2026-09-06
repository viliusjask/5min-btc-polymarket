# Task 3 independent review

## Spec compliance

**❌ Issues found.** The durable execution layer substantially implements the brief, but three Important defects prevent task approval: premature receipt accounting under mixed trade statuses, incomplete final non-tick metadata validation, and inconsistent concurrent summaries. Reviewed base `4c9eaa5110c80fce1149dfedffb3d1169aecb09c` through head `1770a1414c06b38bf154bd1e76f55cb809b2aa56`.

**⚠️ Cross-task requirements remain unverified.** Task 4 has not started; the items below must be assigned and resolved by root before the relevant integration gate. They are not evidence that the current source already provides those guarantees.

## Strengths

- `src/btc5m/ledger.py:406`, `:496`, `:551` and `src/btc5m/engine.py:218` preserve reserve → private preparation → SUBMITTING → one POST ordering. `tests/test_ledger.py:397` uses actual SIGKILL at each committed boundary, and `tests/test_broker.py:328` checks one actual SDK transport POST after a lost response. Unknown outcomes retain durable risk and are not replayed.
- `src/btc5m/ledger.py:621` and `tests/test_ledger.py:79` separate gross entry price, fee-inclusive remaining basis, cash movement and realized profit with independent Decimal totals and receipt identity deduplication. Daily/session accounting and resolved noncash inventory have concrete coverage at `tests/test_ledger.py:186` and `:248`.
- `src/btc5m/broker.py:67`, `:152`, `:196` and `src/btc5m/rpc.py:123` implement the pinned no-deploy constructor, bounded unrestricted holdings discovery, account checks and restricted read-only RPC. `tests/test_broker.py:286` runs actual synthetic EOA construction with all network prohibited.
- `src/btc5m/rpc.py:73`, `:233`, `:313` and `tests/test_rpc.py:61`, `:204`, `:241` use independent deployed hash/resolution vectors and reject malformed tracked receipts, wrong chain and unstable payout evidence. Outcome payouts follow token identity rather than label order.
- `src/btc5m/engine.py:163` and `tests/test_engine.py:386`, `:455` implement the fixed original-book watermark, strictly newer spot requirement, fresh economics and cancellation without creating a reservation while waiting. Held-book exits and pre-submit stop/time checks have real core/SDK/SQLite tests at `tests/test_engine.py:97` and `:226`.
- The five production modules have recognizable responsibilities. Tests substitute external transport/receipt data while exercising the actual core, SDK and SQLite. No duplicate strategy framework, runtime dependency addition, funded operation or ordinary signed-payload logging was found in the reviewed source.

## Issues

### Critical

None found.

### Important

**P1 — Do not finalize an entire transaction from one CONFIRMED trade.** `src/btc5m/broker.py:587-603`, `src/btc5m/rpc.py:261-304`, `src/btc5m/ledger.py:587-610`.

When one matching account trade is CONFIRMED, reconciliation loads every receipt log for the tracked order in that transaction and immediately places every decoded fill into `OrderEvidence.fills`. A second same-transaction trade can remain MINED/MATCHED/RETRYING; it is marked pending, but does not prevent those receipt amounts from being booked. `Ledger.apply_evidence` applies fills before considering pending status. The brief explicitly requires matching CONFIRMED account evidence per finalized fill, including mixed fill states.

Focused reproduction with actual SDK parsing, actual receipt decoding and actual SQLite: the account reports 2 shares CONFIRMED and 3 shares MINED in the same transaction; its aggregate owned receipt is 5 shares, principal 3.50, fee .0735. Reconciliation returns `terminal=false` and `pending=["provisional"]`, yet applying it creates 5 shares and cash movement `-3.5735`. The 3 provisional shares have already entered finalized accounting. For SELL, the same path can prematurely recognize realized profit/loss. The pending order still blocks entries, so this is not a claim that the reproduction immediately opened another position.

Fix by establishing which account-confirmed evidence authorizes each receipt amount. If an aggregate log cannot be split reliably, retain the transaction's amounts as provisional until all relevant matching trade evidence is sufficiently confirmed; do not fabricate a prorated fee. Preserve legitimate multiple IDs referring to the same receipt without double counting. Add BUY and SELL mixed-status same-transaction cases. Existing tests at `tests/test_broker.py:374` and `:420` cover failed/confirmed or entirely provisional evidence, not this combination.

**P1 — Preserve the current non-tick metadata contract during final preparation.** `src/btc5m/broker.py:301-336`, especially `:312` and `:320-333`.

The final fee check accepts any `fd` object containing `r` and `e`, ignoring `to` and extra schema keys. It also compares minimum size only between the saved Market, book and `/clob-markets.mos`; `/markets.minimum_order_size` is never checked. The approved upstream parser rejects those conditions at `src/btc5m/market_data.py:720-735`: exact `fd={r,e,to}`, `to=true`, and raw minimum agreement. These values can change during awaited preparation after the approved snapshot. The researched SELL exception relaxes only tick agreement, while retaining fee/minimum checks.

Three focused actual-SDK fixtures each reached one synthetic POST and returned an accepted classification: (a) `/markets.minimum_order_size=6` while the book and `mos` remain 5, (b) `fd.to=false`, and (c) an added unknown fee-rule key. No real order was sent. Current tests alter `mos` but do not cover the other minimum authority or fee-schema drift (`tests/test_broker.py:598`).

Fix the final raw metadata validation to enforce the established non-tick minimum and exact supported fee schema across these reads. Retain the narrowly authorized SELL tick-refinement behavior. Add regression cases that prove rejection before POST, including changes introduced after a previously eligible snapshot.

**P1 — Read one consistent SQLite snapshot for the public summary.** `src/btc5m/ledger.py:294-336`, especially `:297` and `:301`.

`summary()` issues several independent SELECTs without starting a read transaction. In SQLite's current connection mode, those reads can observe different committed versions. A readonly status/report call can read accounting and positions before a BUY settlement, then unresolved orders after that same atomic settlement. It consequently combines the old cash/no-position view with the new absence of pending orders and falsely reports no exposure.

Focused deterministic interleaving used two real Ledger connections and one actual `apply_evidence` transaction. Settlement was committed after the reader fetched `positions()` but before its `unresolved_orders()` query. The returned summary was `cash=100, inventory=(), unresolved_orders=(), position_risk=0, risk_reserve=0`, while the writer held 5 shares and cash `96.4265`. The existing concurrent reader test at `tests/test_ledger.py:314` opens both connections but does not overlap a settlement with a multi-query report.

Make the public summary select all related fields under one SQLite read snapshot, respecting an existing caller transaction. A connection context manager alone does not begin a read transaction for these SELECTs. Keep status/report free of the trading-owner lock, and add this deterministic interleaving regression. This is a Task 3 accessor defect; a future CLI should not have to query private SQLite state to repair it.

### Minor

None promoted from speculative or cosmetic concerns.

## Cannot verify / root integration decisions

- **Independent scheduling and every observed confirmation invalidation:** `src/btc5m/engine.py:56-65`, `:163` receive a particular snapshot/book before awaited reconciliation. Task 4 must keep observations and held books independent of discovery, preserve the fixed calibration interval with `Ledger.record_snapshot`, and ensure missing/invalid intervening observations cancel a pending candidate rather than being overwritten by a later valid latest snapshot. A delayed discovery/slow account fixture must prove a due exit and current-time validation. Source producer concurrency alone does not verify this caller behavior.
- **Readonly and ownership routing:** `src/btc5m/ledger.py:119-175`, `:766`, `:954` provide distinct owner, readonly and stop-write paths. Root clarified during review that venue-readonly `reconcile` must still acquire the owner lock when applying local execution evidence; status/report/account doctor remain readonly; a first account doctor must work through isolated temporary state before a live journal exists. Task 4 must test these routes and clear the old stop once, under the owner lock, before awaited account setup. A new concurrent stop must survive setup and preparation. This clarification does not change the reviewed Task 3 source.
- **Metadata diagnostics must survive the ledger sink:** Task 4 owns new rejected-field observations, but `src/btc5m/ledger.py:777-837` currently allowlists neither field/expected/actual nor their endpoint-field names. Root must authorize the matching safe consumer change or another explicit safe schema, then test a producer → persisted report round trip. Merely emitting richer adapter records will otherwise lose those values.
- **Execution history and safe CLI presentation:** `src/btc5m/ledger.py:855-875` expose public observations, measurements and decisions; `:294` exposes the current summary. Task 4 must demonstrate that its report keeps estimated quotes, cash, actual fees, realized PnL, unknown orders, active inventory and claimable value distinct without serializing `PreparedOrder` or private SQLite columns. Submission/settlement status must remain visible on failure and abrupt termination.
- **Partial price-trigger exit policy needs a root ruling:** `src/btc5m/engine.py:263-345` re-evaluates STOP/PROFIT from the current quote and does not use the saved `Position.exit_reason` to continue a previously triggered close. The real partial-retry test (`tests/test_engine.py:261`) exercises TIME, whose trigger remains true. The brief says the triggers share reliable close handling, but does not explicitly settle whether a STOP/PROFIT close must remain active if the price recovers after a partial fill. Root must rule on that policy and require its behavioral test; this review does not invent a latching requirement or silently approve either policy.
- **Bounded shutdown and live limits:** `src/btc5m/engine.py:363` performs one pass and leaves resource closure/continued monitoring to its caller. Task 4 must prove bounded interruption with persisted unresolved exposure and a non-success result when appropriate. Actual account initialization, venue acceptance/finality, subminimum FAK behavior, non-EOA funded signing and manual claims remain live-unverified. They were not exercised by this review.

## Review evidence and scope

- Read the brief, binding design/SDK/tick/information contracts, prior task handoffs and implementation report. Reviewed the supplied 302 KB diff in bounded passes. New source/test files were inspected through the diff, not reread independently. Already-read contract/report content duplicated in added documentation was not independently re-rendered. No source function required an outside-file truncation read.
- Named outside-diff check 1: **current non-tick metadata guard compatibility**. Inspected `src/btc5m/market_data.py:688-735` plus its construction context `:550-650` to compare the final preparer's authorities with the approved snapshot parser; this supports Important finding 2.
- Named outside-diff check 2: **exit depth and durable numeric reconstruction assumptions**. Inspected `src/btc5m/domain.py:13-167` to establish that Book sorts positive finite Level objects and that Market retains an integer fee exponent; this eliminated an apparent zero-depth division/unsorted-book concern and an exponent-decoding concern without broad codebase exploration.
- Read retained test evidence: `work/pytest-security-upgrade-tests.txt` reports **301 passed in 15.54s**; `work/task3/final-tests.txt` reports **300 passed in 14.31s**. No warnings were present. The implementation report records clean Ruff/format/mypy checks. No suite, static tool or git verification command was rerun.
- Ran one focused Python stdin invocation with `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=src:tests` and `.venv/bin/python -B`. It used ephemeral `/dev/shm` temporary directories, actual core/SDK/SQLite, existing synthetic HTTP fixtures and deterministic interleavings; no production method was replaced by a second broker implementation. External network was intercepted by the fixtures. Results are recorded verbatim below. No retained scratch file, source/index/HEAD/branch change, credential inspection, funded action, approval, transfer, deployment or redemption occurred. The sole retained write is this ignored review report.

```text
mixed_receipt_status {"pending": ["provisional"], "terminal": false, "credited_quantity": "5", "cash_movement": "-3.5735", "confirmed_account_quantity": "2", "provisional_account_quantity": "3"}
metadata_guard {"case": "raw_minimum_disagrees", "posts": 1, "classification": "accepted"}
metadata_guard {"case": "fee_taker_only_false", "posts": 1, "classification": "accepted"}
metadata_guard {"case": "fee_schema_extended", "posts": 1, "classification": "accepted"}
concurrent_summary {"reported_cash": "100", "reported_inventory": 0, "reported_orders": 0, "reported_position_risk": "0", "reported_reserve": "0", "actual_quantity": "5", "actual_cash": "96.4265"}
```

## Assessment

**Task quality: Needs fixes.** The architecture and existing adversarial tests provide a solid execution foundation, but the three reproduced defects affect finalized accounting, final entry authorization and visibility of real exposure. Fix them and resolve the listed root/Task 4 contracts before treating this task gate as complete; broad suite reruns by another reviewer are unnecessary.
