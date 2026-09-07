# Task 1 implementation report

Status: implemented, locally verified; independent task review remains with root.
Base: 16e55a8. Worktree: /home/vilius/projects/5min-btc-polymarket/.worktrees/standalone.
Branch: feat/standalone-btc5m. Commit: 4728b741abc45dedca3541c9da05cb042915bfd9 (`feat: add validated BTC5m strategy and cash sizing core`).

## Requirements addressed

- Immutable Decimal domain inputs, explicit market/reference flags and provenance, sorted validated books, and validated numeric decisions.
- Frozen nested configuration, complete TOML loading with unknown/missing-key rejection, finite numeric/type/range/timing checks, and stable canonical SHA256 fingerprint.
- Pure value and modified-upstream momentum modes; deterministic decisions and reason codes; both outcome books checked, with selected-side spread/depth/price filters.
- Fee numerical vector 5*.07*(.70*.30) = .07350 and independent terminal probability vector sigma=50/sqrt(60), delta=90, tau=120 => about .9405.
- Source-time model horizon, separate wall-clock entry horizon, raw-spot five-second UTC sampling, no duplicate observations/forward-fill, two-second sampling tolerance, seven-second maximum sampled gap, actual source-time denominator, 300s/1800s windows, and larger-sigma 1.25 stress.
- Per-side minimum across central/adverse-reference scenarios and both variance windows plus stress; actual ask-depth cash cost and buy fees, worst-case per-share sell fee reserve, and extra price allowance retained in decision features.
- Fixed signed BUY cash principal rounded down to cents, protected tick-rounded maximum price, conservative minimum shares, exchange minimum checked without rounding the cash budget up, and worst-case buy fee reservation independent of improved asks.
- Missing/stale/future/wrong-kind data, wrong round/rule, missing/conflicting anchor, absent/crossed/token-mismatched books, zero/incomplete variance, insufficient depth and invalid prices all stop entries visibly.
- Exact boundary references are enabled by default per root's updated anonymous-probe ruling. The pure core still rejects a boundary lacking its exact start timestamp; disabling the policy remains supported. Capturing/comparing official values, the USD1e-8 rounding tolerance, cached-null preservation and conflict persistence belong to Task 2.

## Owned files changed

- src/btc5m/__init__.py
- src/btc5m/domain.py
- src/btc5m/config.py
- src/btc5m/strategy.py
- config/btc5m.toml
- tests/test_config.py
- tests/test_strategy.py
- This ignored orchestration report only; no root docs or other worker files modified.

## Verification evidence

Tests were written before implementation. Initial collection found the absent package modules. Minimal importable API scaffolding then gave the meaningful red run:

` .venv/bin/python -m pytest tests/test_config.py tests/test_strategy.py -q --tb=line `

Result: **88 failed, 1 passed in 0.13s**. Failures included independent numerical outputs, invalid configuration accepted, unsafe data accepted, and missing entry/sizing behavior.

The first implementation run gave 87 passed / 2 failed. One test incorrectly demanded a decimal string without its leading zero; it now compares Decimal value. The source-time test initially lacked the earlier 1800-second warm-up when shifting its forecast backwards; the fixture now supplies that earlier observation. Neither correction weakens the associated production assertion.

Additional decision-construction validation was tested red: **1 failed, 73 passed in 0.13s**, because NaN decision cash was accepted. Implemented finite/underreservation checks and reran.

Final scoped checks:

- `.venv/bin/python -m pytest tests/test_config.py tests/test_strategy.py -q` => **98 passed in 0.15s**.
- `.venv/bin/python -m ruff check src/btc5m/__init__.py src/btc5m/domain.py src/btc5m/config.py src/btc5m/strategy.py tests/test_config.py tests/test_strategy.py` => **All checks passed!**
- `.venv/bin/python -m ruff format --check src/btc5m/__init__.py src/btc5m/domain.py src/btc5m/config.py src/btc5m/strategy.py tests/test_config.py tests/test_strategy.py` => **6 files already formatted**.
- `.venv/bin/python -m mypy src/btc5m/__init__.py src/btc5m/domain.py src/btc5m/config.py src/btc5m/strategy.py tests/test_config.py tests/test_strategy.py` => **Success: no issues found in 6 source files**.
- `git diff --check` => exit 0.

## Interface and numerical choices for later tasks

- `Config()` constructs validated defaults. `load_config(Path)` requires every key in the checked-in TOML; overrides can use `dataclasses.replace`, which reruns validation. `Config.fingerprint` is SHA256 over canonical configuration values.
- Domain/Decision names match the Task 1 brief exactly. `Market.token(Side)` rejects an unknown side. A non-entry decision has `side=None`, zero actionable principal/reservation/share fields, a reason, and any available model diagnostics.
- `terminal_probability_up(spot, reference, sigma, tau)` exposes the independent pure model calculation. `probability_up` is the short-window central probability; `central_probability_down` is its complement. `scenario_floor` is the selected/evaluated side's minimum, not a confidence interval.
- `terminal_surplus_proxy` is **USD/share**, never total realized profit or expected return under the stop/time/profit exit policy. Its components are recorded separately in `features`.
- `strategy` settings are all consumed by evaluate/model/sizing. `data` settings are consumed by freshness, reference and source-grid checks. `risk.trade_budget_usd` and `execution.buy_slippage` are consumed by entry sizing. **Task 3 must consume** risk allocation/daily/session loss/max entries and execution stop_loss_per_share/take_profit_bid/exit_seconds/sell_slippage. They are validated here but not represented as already enforced account state.
- Pinned SDK 0.9.0 BUY amount uses cents. Protected minimum shares use ROUND_CEILING at SDK tick-specific amount precision: tick .1 => 3 decimals; .01 => 4; .005/.001 => 5; .0025/.0001 => 6. Then amounts map exactly to six-decimal base units. Independent SDK-confirmed vector: principal4.90 at max_price.92 yields minimum5.3261. Actual signed integer fields must be compared by Task 3 before POST.
- No SDK dependency is imported by the pure core. The supported rounding table was checked against installed polymarket 0.9.0 `_internal/actions/orders/context.py` and protected calculation in `market.py`.
- Principal = floor_to_cents(trade_budget/(1+fee_rate)); reserved_buy_fee=principal*fee_rate. For exponent>=1, fee per dollar = rate*p**(e-1)*(1-p)**e <= rate, so this is deliberately conservative for every valid improved execution price. Default principal4.67 reserves4.9969. Future fee-rate changes require Task 3 invalidation/re-evaluation; this does not claim an exchange match-time fee cap.
- The adapter must sign **buy_principal directly**, without SDK max_spend fee adjustment or converting expected shares back to cash. expected_shares is only a depth estimate; minimum_receive_shares is the protected signed minimum; receipts determine inventory.
- Lowest/highest ask band checks include the rounded signed buy maximum. Expected depth consumes the same principal over sorted asks. Better asks increase estimated shares while principal/reservation stay unchanged.

## Concerns / remaining external work

No known Task 1 blocker. Scientific calibration and discrete TWAP construction remain model uncertainty; the screen is not proven profitable. The account-state protections, venue signing verification and funded checks are downstream work. No credentials, funded orders, approvals, transfers, pushes, branch deletion or history rewriting occurred.

## Review fix round 1 — Important 1

Base: e7345d0. Commit: a6b8bd82dad16177117c33c791e86b8f2cfa76ae (`fix: reject overflowing volatility models safely`).

Reproduced the reviewer finding through real configuration/strategy calls. A finite Decimal `1e309` previously passed config validation while converting to infinity; a representable multiplier `1e308` also overflowed when multiplied by finite estimated sigma, contaminating diagnostics and preventing the `INVALID_MODEL` Decision itself from being constructed.

The configuration now requires a finite float representation for the stress multiplier. The strategy checks calculated stress before attaching it to diagnostics. Decision finite-value validation is unchanged. Regression scenarios also cover overflow when applying the horizon factor and when squaring finite price changes; both produce finite, non-actionable `INVALID_MODEL` decisions.

Changed only src/btc5m/config.py, src/btc5m/strategy.py, tests/test_config.py, tests/test_strategy.py.

Exact checks:

- `.venv/bin/python -m pytest tests/test_config.py tests/test_strategy.py -q -k 'finite_float_representation or overflows_model_float or model_overflow' --tb=short` before the fix => **3 failed, 2 passed, 98 deselected in 0.27s**; errors reproduced accepted invalid config and failed rejection construction.
- Same focused selection after fix => **5 passed, 98 deselected in 0.04s**.
- `.venv/bin/python -m pytest tests/test_config.py tests/test_strategy.py -q` => **103 passed in 0.18s**.
- `.venv/bin/python -m ruff check src/btc5m/config.py src/btc5m/strategy.py tests/test_config.py tests/test_strategy.py` => **All checks passed!**
- `.venv/bin/python -m ruff format --check src/btc5m/config.py src/btc5m/strategy.py tests/test_config.py tests/test_strategy.py` => **4 files already formatted**.
- `.venv/bin/python -m mypy src/btc5m/config.py src/btc5m/strategy.py tests/test_config.py tests/test_strategy.py` => **Success: no issues found in 4 source files**.
- `git diff --check` and `git diff --cached --check` => exit 0.

Root subsequently authorized a separate sparse-grid sampling correction based on independent anonymous feed replay; it is intentionally not bundled into this overflow-fix commit.

## Authorized sampling-policy correction

Base: a6b8bd8. Commit: 3b1c70f35c8292ee9ad135c3010f458c91a608cd (`fix: tolerate bounded isolated volatility sample gaps`).

Root explicitly revised the binding design after independent anonymous-feed replay. This section supersedes the original report's strict every-grid-point/seven-second-gap policy; it is a feed-availability correction rather than trading-return threshold selection. Root owns the live-replay evidence in docs/research/volatility-sampling.md; this worker performed the core implementation and synthetic behavioral/numerical verification.

The core keeps five-second UTC grids, last observation at/before each grid, at most two seconds source age, distinct source observations, actual observed price differences and actual elapsed denominator. It now omits unavailable individual grid samples and requires:

- `data.min_sample_coverage = Decimal('.95')`, validated in [.95, 1] so operators may tighten the approved requirement;
- `data.max_sample_gap_ms = 12000`, configurable only from 5000 through 12000;
- both endpoint grid observations and an accepted span no more than two seconds shorter than the requested window.

No interpolation or forward-fill was added. A 12-second accepted source gap may pass; two consecutive missing grid points require a minimum 13-second accepted source gap and reject. The 61-second outage still rejects. Complete-grid sample choices and volatility calculations are unchanged.

The private `_SampleWindow` result replaces the old tuple-or-None return; no compatibility wrapper or dead path remains. Successful and rejected sampling windows retain finite measurements in Decision.features:

- `short_` / `long_` prefixes for `sample_count`, `requested_sample_count`, `sample_coverage`, `span_seconds`, `max_sample_gap_ms`, and `sampling_status`;
- status `VALID`, `INSUFFICIENT_SAMPLES`, `MISSING_START`, `MISSING_END`, `INSUFFICIENT_SPAN`, `INSUFFICIENT_COVERAGE`, `EXCESSIVE_GAP`, or `INVALID_VARIANCE`;
- sigma is attached only when computed and finite. Invalid variance yields `INVALID_MODEL`; other sampling rejection yields `INSUFFICIENT_HISTORY`.

Changed only config/btc5m.toml, src/btc5m/config.py, src/btc5m/strategy.py, tests/test_config.py and tests/test_strategy.py. Root design/plan/research edits were left untouched and unstaged.

Red runs before implementation:

- `.venv/bin/python -m pytest tests/test_strategy.py -q -k 'isolated_missing_grid or complete_grid_keeps or one_missing_grid or grid_discards or coverage_setting' --tb=short` => **5 failed, 82 deselected in 0.12s**; existing strict sampling rejected authorized isolated gaps and omitted coverage measurements.
- `.venv/bin/python -m pytest tests/test_strategy.py -q -k 'rejected_sampling_retains' --tb=short` => **5 failed, 87 deselected in 0.10s**; rejected-window measurements/status were absent.

Final checks:

- `.venv/bin/python -m pytest tests/test_config.py tests/test_strategy.py -q` => **122 passed in 0.17s**.
- `.venv/bin/python -m ruff check src/btc5m/config.py src/btc5m/strategy.py tests/test_config.py tests/test_strategy.py` => **All checks passed!**
- `.venv/bin/python -m ruff format --check src/btc5m/config.py src/btc5m/strategy.py tests/test_config.py tests/test_strategy.py` => **4 files already formatted**.
- `.venv/bin/python -m mypy src/btc5m/config.py src/btc5m/strategy.py tests/test_config.py tests/test_strategy.py` => **Success: no issues found in 4 source files**.
- `git diff --check` and `git diff --cached --check` => exit 0.

No known blocker. Independent fix review remains with root. The availability thresholds and resulting terminal screen remain hypotheses, not claims of scientific optimality or profitability.
