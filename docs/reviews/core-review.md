# Task 1 review — 16e55a8..4728b741abc45dedca3541c9da05cb042915bfd9

## Spec Compliance

- ❌ Issues found: the required visible rejection of invalid model calculations is incomplete. An accepted finite stress setting can make `evaluate` raise while constructing its `INVALID_MODEL` rejection (`src/btc5m/strategy.py:337`, `src/btc5m/strategy.py:345`, `src/btc5m/strategy.py:359`). See Important 1.
- ✅ Scope and interfaces match Task 1: all seven owned files are present in the diff; the pure domain/configuration/strategy split and the required public names are implemented (`src/btc5m/domain.py:65`, `src/btc5m/domain.py:146`, `src/btc5m/config.py:128`, `src/btc5m/strategy.py:275`). The default captured-boundary policy follows the updated binding design (`config/btc5m.toml:36`, `src/btc5m/strategy.py:108`).
- ⚠️ Cannot verify from this task: Task 2 must validate the full supported contract rules, Up-on-equality semantics, negative-risk exclusion, token mapping and official anchor provenance before constructing `Market`; this core checks the normalized settlement-source string and reference status (`src/btc5m/domain.py:65`, `src/btc5m/strategy.py:85`). Task 2 also owns exact-boundary capture, the USD0.00000001 comparison tolerance, preservation of cached official anchors and persistent conflict state. These are task boundaries, not findings against Task 1.
- ⚠️ Cannot verify from this task: Task 3 must consume allocation/daily/session loss limits and daily entry count (`src/btc5m/config.py:65`), plus stop loss, take profit, exit timing and sell slippage (`src/btc5m/config.py:112`). It must maintain uncertain-order reservations, check fresh venue metadata and current entry timing before POST, compare signed integer amounts with the core decision, and use confirmed receipts for holdings. The core consumes trade budget and buy slippage (`src/btc5m/strategy.py:203`, `src/btc5m/strategy.py:223`) and does not claim account-state enforcement.

## Strengths

- Fee and probability calculations use the specified units: cash fee is shares × rate × [price × (1 − price)]^exponent; volatility is raw USD/√second; the ending-average variance factor is model_tau − 40 (`src/btc5m/strategy.py:33`, `src/btc5m/strategy.py:43`). The independent 0.07350 fee and approximately 0.9405 probability vectors are asserted (`tests/test_strategy.py:65`, `tests/test_strategy.py:85`).
- The sampling implementation builds a five-second UTC source-time grid, selects distinct preceding observations within tolerance, rejects missing samples and excessive gaps, and divides squared raw-price changes by actual elapsed source time (`src/btc5m/strategy.py:142`). Tests cover missing short segments, a 61-second gap, duplicate/future/smoothed observations, actual elapsed time, both variance windows and stress (`tests/test_strategy.py:229`, `tests/test_strategy.py:251`, `tests/test_strategy.py:391`, `tests/test_strategy.py:413`). Strict two-second tolerance matches the current design; its live-feed viability is a separate design question being investigated by root.
- Fixed cash sizing stays independent of improved execution prices. Principal is rounded down to cents; fee reservation uses a conservative rate bound for exponent ≥ 1; depth spends that same principal; the tick-rounded signed maximum must remain within the configured price band; the signed minimum shares are rounded conservatively and checked without increasing the budget (`src/btc5m/strategy.py:203`, `src/btc5m/strategy.py:223`, `src/btc5m/strategy.py:230`). Tests check improved asks, multiple levels, insufficient depth, exchange minimum, and protected-rounding numerical vectors (`tests/test_strategy.py:99`, `tests/test_strategy.py:115`, `tests/test_strategy.py:125`, `tests/test_strategy.py:142`, `tests/test_strategy.py:363`). Actual SDK integer signing remains a Task 3 verification requirement.
- The value calculation uses a per-side minimum over both variance windows, larger-sigma stress and adverse references, then subtracts actual depth cost and separately recorded fee/price allowances. Its label explicitly describes USD/share terminal surplus rather than stopped-policy profit (`src/btc5m/strategy.py:236`, `src/btc5m/strategy.py:348`). Momentum uses its own explicit move/timing/ask settings with shared data and sizing checks (`src/btc5m/strategy.py:293`, `src/btc5m/strategy.py:363`).
- Book, market, reference and freshness failures produce deterministic non-entry reasons before quotation (`src/btc5m/strategy.py:85`). Both books are validated, while spread filtering applies to the selected side; tests exercise those actual decisions rather than source-text assertions (`tests/test_strategy.py:162`, `tests/test_strategy.py:185`, `tests/test_strategy.py:205`, `tests/test_strategy.py:281`). Configuration is frozen and rejects unknown/missing keys and invalid types (`src/btc5m/config.py:155`, `src/btc5m/config.py:167`).

## Issues

### Critical (Must Fix)

- None found in this task-scoped diff.

### Important (Should Fix)

1. **Do not attach nonfinite model diagnostics before returning a rejection.** `src/btc5m/strategy.py:337`, `src/btc5m/strategy.py:345`, `src/btc5m/strategy.py:359`; related validation at `src/btc5m/config.py:49` and `src/btc5m/domain.py:188`.

   `StrategyConfig` accepts any finite Decimal stress multiplier ≥ 1. With `Decimal('1e309')`, float conversion yields infinity. The central probability still computes, so infinity is stored in `features['stress_sigma']`; a subsequent scenario correctly raises `ValueError`. The exception handler then calls `_skip` with the contaminated features, and `Decision.__post_init__` raises `ValueError: decision features must be finite`. A malformed configuration therefore escapes the promised deterministic non-entry path instead of yielding `INVALID_MODEL`. The existing tests cover literal NaN settings and directly invalid Decisions, but not failure through `evaluate` with an accepted finite setting (`tests/test_config.py:47`, `tests/test_strategy.py:444`).

   Reject stress settings that cannot be represented as finite floats, and validate calculated stress before adding it to features. Ensure every model-failure branch can construct a finite rejection Decision. Add one behavioral regression for this accepted-input overflow path; do not weaken Decision's finite-value validation.

### Minor (Nice to Have)

- None identified that merits expanding this task.

## Checks and Evidence

- Read the supplied brief, complete implementation report, updated `docs/design.md`, and the complete review diff. Used only targeted line mapping within the supplied diff for citations; no changed source file was independently reread and no broader repository crawl or git mutation occurred.
- Existing reported verification is complete and clean: 98 scoped tests passed; ruff lint and formatting passed; mypy passed; diff check exited zero. These results were reviewed as reported evidence and were not rerun.
- Named risk checked: finite Decimal configuration overflowing float volatility math and breaking `evaluate`'s rejection handling. One scratch invocation imported the existing synthetic snapshot helper without running tests, replaced only `volatility_stress_multiplier` with `Decimal('1e309')`, and called real `evaluate`. Result: `ValueError: decision features must be finite`, confirming Important 1. The first invocation could not import the package without the pytest path configuration; rerunning this same focused check with `PYTHONPATH=src` produced the result above. No scratch/source/test file was written.
- Review is read-only except this explicitly requested ignored review artifact. No existing test suite, network probe or funded action was run.

## Assessment

**Task quality: Needs fixes.**

The domain separation, model units, source-grid logic, scenario screening and protected cash sizing fit the design and have meaningful behavioral tests. Fix the demonstrated rejection-path exception before approving Task 1; downstream adapter/account checks listed above remain for their assigned tasks.
