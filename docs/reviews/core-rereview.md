# Task 1 re-review 1 — e7345d0..3b1c70f35c8292ee9ad135c3010f458c91a608cd

## Spec Compliance

- ✅ Spec compliant for this fix diff. **Important 1 is addressed.** Configuration rejects a finite Decimal stress multiplier whose float representation is nonfinite (`src/btc5m/config.py:50`). Calculated stress is checked before it can enter Decision diagnostics (`src/btc5m/strategy.py:380`). The existing finite-value protection on Decision was not weakened.
- ✅ The explicitly approved sampling correction is implemented within its bounds: five-second UTC grid, unchanged at-most-two-second preceding-source selection age, distinct observations, at least 95% requested-point coverage, at most 12 seconds between accepted source observations, and full endpoint/span requirements (`src/btc5m/strategy.py:153`, `src/btc5m/strategy.py:185`, `src/btc5m/strategy.py:191`, `src/btc5m/strategy.py:193`). These match the updated brief and `docs/design.md:73`.
- ✅ The new default configuration is explicit and may be tightened: coverage is restricted to [.95, 1] and the accepted-source gap to [5000, 12000] milliseconds (`config/btc5m.toml:34`, `src/btc5m/config.py:97`, `src/btc5m/config.py:109`). Current quote freshness and exact opening-anchor rules are unchanged by this diff.
- ⚠️ Cross-task verification remains assigned to the existing Task 2/3 gates: complete venue rule/anchor validation and conflict persistence; current market metadata; actual signed integer amounts; account risk limits, uncertain orders, exit behavior and receipt-based holdings. This re-review does not reopen those implementation boundaries. The private `_SampleWindow` result is consumed by `evaluate` in the fix diff (`src/btc5m/strategy.py:357`); root owns scratch-consumer migration as stated in the dispatch.
- ⚠️ The supplied feed-availability study explicitly lacks eligible 1800-second windows (`docs/research/volatility-sampling.md:39`). This review verifies core conformity and synthetic numerical behavior; it does not convert the study into evidence of live 30-minute warm-up availability or profitability.

## Strengths

- The overflow regression reaches real configuration loading and real `evaluate`, including three distinct paths: multiplication overflow from finite factors, overflow in the model horizon factor, and overflow while squaring finite price changes (`tests/test_config.py:86`, `tests/test_config.py:91`, `tests/test_strategy.py:457`). The tests require a finite non-entry Decision with zero principal/reservation, not merely an exception caught somewhere.
- Sparse sampling retains actual observed endpoint changes and actual elapsed time. The independent omitted-alternating-point vector correctly removes two USD5 changes and inserts the observed zero change across that gap: short variance rate is 1450/300 and long variance rate is 8950/1800 (`src/btc5m/strategy.py:202`, `tests/test_strategy.py:491`). There is no interpolation, fictitious return or assumed five-second denominator.
- Complete histories select the same source points and preserve the original arithmetic (`src/btc5m/strategy.py:153`, `src/btc5m/strategy.py:202`, `tests/test_strategy.py:507`). Requested counts include both endpoints: 61 for 300 seconds and 361 for 1800 seconds. Coverage admission uses the integer count against the Decimal threshold, avoiding an imprecise float boundary decision (`src/btc5m/strategy.py:173`, `src/btc5m/strategy.py:191`).
- Boundary tests exercise exact 12-second acceptance and the minimum 13-second gap caused by two consecutive missing grid points (`tests/test_strategy.py:551`, `tests/test_strategy.py:558`). Separate tests reject below-threshold coverage even when every individual gap is bounded, show that the configured coverage threshold is consumed, reject missing endpoints, and accept exactly the permitted two-second span shortfall (`tests/test_strategy.py:517`, `tests/test_strategy.py:525`, `tests/test_strategy.py:536`, `tests/test_strategy.py:542`). The existing 61-second outage and future-data rejection cases remain.
- Rejection diagnostics preserve measured count, requested count, coverage, span, maximum interval and status for both windows; sigma is included only when calculated successfully (`src/btc5m/strategy.py:143`, `src/btc5m/strategy.py:180`, `src/btc5m/strategy.py:357`). Invalid variance becomes `INVALID_MODEL`; other sampler failures become `INSUFFICIENT_HISTORY` (`src/btc5m/strategy.py:370`). The tests verify finite diagnostics across empty, missing-start, missing-end, excessive-gap and insufficient-coverage cases (`tests/test_strategy.py:575`).

## Issues

### Critical (Must Fix)

- None found in the fix diff.

### Important (Should Fix)

- None outstanding. Previous Important 1 is addressed at `src/btc5m/config.py:50` and `src/btc5m/strategy.py:381`, with behavioral regression coverage at `tests/test_strategy.py:457`.

### Minor (Nice to Have)

- None identified in this scoped re-review.

## Checks and Evidence

- Reviewed the report's two new fix sections, the approved brief amendment, the relevant updated design/research evidence, and the complete supplied diff. The first combined tool response truncated the middle of the diff, so the diff was fetched alone to obtain the missing review context. No changed source file was read independently and no broader core crawl was performed.
- The report supplies clean evidence for the final revision: 122 scoped tests passed in 0.17s; ruff lint and format passed; mypy passed; both diff checks exited zero. Reviewed that evidence without rerunning suites. No further scratch execution was needed because the added behavioral/numerical tests answer the concrete review questions.
- No source, test, index, branch, commit or external state was mutated. The only write is this explicitly requested ignored review artifact.

## Assessment

**Task quality: Approved.**

The previous invalid-model rejection failure is fixed at both conversion and calculated-stress boundaries. The authorized sampler change preserves the estimator's units and complete-history calculations while enforcing bounded omissions and retaining useful finite diagnostics; no new breakage was found in this diff.
