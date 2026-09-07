# Task 2 re-review 1

## Spec Compliance

- ✅ **Spec compliant for the reviewed fix scope.** Both P1 findings are **ADDRESSED**. The original Task 2 interface and fail-closed requirements are preserved.
- ✅ **P1 freshness: ADDRESSED.** `src/btc5m/market_data.py:594` now always reads the injected UTC clock after network work. The supplied `now_ms` chooses the initial round; it no longer freezes the returned snapshot time, final price/book freshness checks or round-boundary check. The four cases at `tests/test_market_data.py:838` cover a successful advancing timestamp, a price becoming stale, a book becoming stale and crossing the next round. Their delayed metadata response waits until both SDK book reads finish, so these tests exercise the actual awaited-work failure from the original review.
- ✅ **P1 incompatible delayed rules: ADDRESSED.** After matching the official event's slug and condition, `src/btc5m/market_data.py:520` persistently sets the retained round's conflict flag when either the event or its market reports an unsupported description/source. The existing reference conversion exposes that conflict and the actual core blocks entry. Four variants at `tests/test_market_data.py:886` cover event/market descriptions and source URLs while raw discovery remains cached and supported. They assert `REFERENCE_CONFLICT`, restore supported copies, exercise another delayed SDK poll, and verify both persistence and continued held-token book access. The two controls at `tests/test_market_data.py:931` confirm that ordinary network errors and missing optional anchor metadata leave captured anchors usable and retryable.
- ✅ **P3 assertion: ADDRESSED; original gate-order rationale withdrawn.** `tests/test_market_data.py:405` now asserts `MISSING_BOOK_SIDE` explicitly. The fix report correctly identifies my earlier gate-order explanation as wrong: `evaluate` calls `_safety_reason` at `src/btc5m/strategy.py:322`, and `_safety_reason` checks missing sides at `src/btc5m/strategy.py:135`; the entry-window gate follows at `src/btc5m/strategy.py:330`. The original empty-ask snapshot therefore reached `MISSING_BOOK_SIDE`, not `ENTRY_WINDOW`. The stronger reason assertion is useful, but neither a fixture-clock change nor a production strategy fix was needed for P3.
- ⚠️ **Cannot verify from this fix diff:** later CLI persistence/polling and independent exit scheduling, complete configuration consumption across Tasks 3/4, or funded execution. Those integration obligations remain as recorded in the first review. The fixes do not establish a new live boundary capture, full adapter warm-up, fills, or profitability.

## Strengths

- The implementation changes are limited to one final-clock correction and one persistent state transition (`src/btc5m/market_data.py:520`, `src/btc5m/market_data.py:594`). They reuse the existing injected clock, conflict representation and core rejection path without extending interfaces or adding configuration.
- The new tests reproduce the original failures through transport fixtures, real SDK models and the real adapter, with controls distinguishing incompatible official evidence from transient missing data (`tests/test_market_data.py:807`, `tests/test_market_data.py:838`, `tests/test_market_data.py:886`, `tests/test_market_data.py:931`).

## Issues

- **Critical:** None in the fix diff.
- **Important:** None remaining from the reviewed P1 findings; no new breakage found in the fix diff.
- **Minor:** None remaining from the reviewed P3 finding. The incorrect reasoning in the first review is explicitly corrected above.

## Evidence and scope

- Read the original task brief, first review, appended fix report and `.superpowers/sdd/standalone/review-2e5cd84..05c808e.diff`, covering base `2e5cd8429b6c66942e4cf5828103b62f460a4c85` through fix `05c808e38890f1457058d53be6b8776b4a510a20`. Root's intervening `fefdc75` research/progress changes are separate context; this is not a new review of those research claims or the whole branch.
- Read the retained `work/task2/fix-1-red.txt` ending: **8 failed, 2 passed, 50 deselected**. The eight failures name the four explicit-time variants and four delayed-rule variants; the two retryable controls passed before the changes.
- The appended report records **11 targeted passed / 49 deselected**, **60 adapter passed**, **182 combined passed**, clean lint/format/mypy and whitespace checks. The ten added parametrized cases and strengthened P3 assertion in the diff agree with those counts and claimed coverage. These checks were not rerun.
- The sole unchanged-code inspection was the specifically requested gate-order check in `_safety_reason` and `evaluate`, with the supporting lines cited above. No changed source file was separately reread, no git command or test/smoke was run, and no source/index/branch edits or subagents were used. Only this requested review report was written.

## Assessment

**Spec compliance: Approved. Task quality: Approved.**

Both demonstrated P1 failures are corrected with targeted regression coverage. The P3 assertion is strengthened, and the implementer's correction of my original gate-order reasoning is accepted.
