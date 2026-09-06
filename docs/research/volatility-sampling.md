Review date: 6 September 2026. Scope: a read-only viability check of volatility sampling against recorded anonymous public feeds. No repository code, configuration, market orders, or research objectives were changed.

**Recommendation: adopt the proposed sparse-grid policy as a documented operational hypothesis.** Retain the two-second source-age tolerance for each historical grid selection, permit isolated unavailable grid points, require at least 95% requested-point coverage, require actual accepted span within two seconds of the target span, and cap the interval between accepted source observations at 12 seconds. Keep the estimator based on actual source-price differences and actual elapsed time. Keep entry-price/order-book freshness and exact opening-anchor rules separate and unchanged. The evidence supports this bounded handling of sparse historical observations; it does not establish that 95% or 12 seconds is statistically optimal.

The simpler proposal of three-second tolerance plus an eight-second accepted-sample gap repairs the earlier capture but does not repair the current capture's failure. The present failure includes a real seven-second source gap, not only a grid alignment error.

I inspected `_sample_window` at `src/btc5m/strategy.py:142` in the standalone worktree, the initial `work/volatility-availability-interim.json`, and both raw capture files. The old sampler chooses the latest source observation at or before every UTC five-second grid, requires every selection, disallows duplicate/nonincreasing source observations, checks gaps, and computes `sqrt(sum(delta_price²)/elapsed_seconds)`. The current defaults were two-second tolerance and seven-second accepted-sample gap. I replayed the stated selection/variance rules, with the proposed sparse policy differing only in coverage/gap handling. No interpolation or substitute prices were generated.

The current capture is still being appended to. To make the numbers reproducible, the main replay uses only the first **536,215 complete bytes** of `/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/work/volatility-probe.jsonl`, SHA-256 `1f6c82d4f0a14f269b75f8c20b64334d642dc2e81d7f1b6a78f8012b4bb65015`. Its 949 distinct spot observations span **15:54:14–16:10:50 UTC**, or 996 seconds. The earlier capture is `/mnt/c/Users/Vilius.DESKTOP-TL3K4H5/Documents/Codex/2026-09-06/hey/work/anchor-probe/prices.jsonl`, 469,460 bytes, SHA-256 `48d5457021128ea8500fa2cb0eb9f18e6552af4817997294d806e65765ca3184`. Its 813 distinct spot observations span **15:30:09–15:44:06 UTC**, or 837 seconds. They are two separate captures; their histories were not joined across the intervening outage.

An eligible window here ends on a five-second UTC grid and has the nominal 300-second interval available since capture start. Windows overlap heavily. Counts measure availability within these captures, not independent statistical experiments.

| Policy | Current capture: valid / eligible 300-second windows | Earlier capture: valid / eligible 300-second windows |
|---|---:|---:|
| Existing: two-second tolerance, seven-second sample gap, every grid required | 98 / 140 (70.0%) | 86 / 108 (79.6%) |
| Three-second tolerance, eight-second sample gap, every grid required | 98 / 140 (70.0%) | 108 / 108 (100%) |
| Proposed: two-second tolerance, 12-second sample gap, at least 95% grid coverage, span within two seconds | 139 / 140 (99.3%) | 107 / 108 (99.1%) |

The earlier interim file's 44 valid out of 86 eligible windows covered only 727 source seconds. It is consistent with the later result: all 42 current-capture strict failures are attributable to the same historical missing grid, and additional later windows become valid once that grid moves outside the five-minute window. The fraction is therefore not a stationary estimate of future availability.

In the current fixed prefix, consecutive raw source intervals were 909 of one second, 35 of two seconds, two of three seconds, one of four seconds, and one of seven seconds. The seven-second interval was **15:57:35 to 15:57:42 UTC**. At the 15:57:40 grid, the latest available source price was still from 15:57:35, five seconds old. Raising tolerance to three seconds cannot accept it. Raising tolerance to five seconds alone would reuse the same observation already selected at the prior grid; that would violate the no-duplicate rule and is not recommended.

The sparse policy instead omits that unavailable grid and computes the next return between actual accepted source observations. The rescued current windows contain one missing point out of 61, giving **98.36% coverage**, with a maximum accepted-source interval of **nine seconds**. It rescues 41 windows. The remaining rejected window ends at 16:02:40: the omitted grid sits at the nominal window start, leaving only **296 seconds** of actual accepted span. Keeping that rejection is correct under the proposed endpoint requirement.

In the earlier capture, raw intervals were 791 of one second, 18 of two seconds, two of three seconds and one of four seconds. A gap from **15:31:52 to 15:31:56 UTC** makes the 15:31:55 grid's latest observation three seconds old. Three-second tolerance accepts that observation, but also requires an eight-second catch-up interval; changing only tolerance while retaining a seven-second sample-gap cap does not help. The proposed sparse rule skips the unavailable grid, rescues 21 windows at **98.36% coverage**, and has a maximum accepted-source interval of **ten seconds**. Its one remaining rejection ends at 15:36:55, with only **295 seconds** of accepted span because the missing point is at the start boundary.

**Every previously valid window has exactly the same selected prices and computed sigma under the sparse policy.** Thus the correction does not lower existing volatility estimates. It makes additional estimates available. The median sigma over all accepted current windows changes from approximately 2.6323 to 1.9244 dollars per square-root second because the newly included historical segment had lower observed variation, not because existing windows were recalculated downward. Comparing only those aggregate medians would confuse sample selection with an estimator change. In the earlier capture, the sparse estimate differs by at most about **0.204%** from the three-second/eight-second alternative on windows both alternatives accept; both remain uncalibrated volatility estimates.

The 12-second bound has a simple geometric interpretation. With a five-second grid and selected observations up to two seconds before their grids, two adjacent accepted points normally have source intervals between three and seven seconds. One omitted internal grid produces an interval between eight and 12 seconds. Two consecutive omitted internal grids produce at least 13 seconds and are rejected. The cap therefore permits one isolated missing grid while rejecting consecutive missing-grid stretches, without claiming that every raw source gap above a particular smaller duration must fail. Endpoint-span checks also prevent an omitted boundary from silently shortening the requested history.

Coverage should be computed explicitly as `accepted_distinct_points / requested_grid_points`, using 61 requested points for 300 seconds and 361 for 1800 seconds, with both endpoints included. At 95%, this permits at most three missing grid points in a 300-second window and 18 in an 1800-second window. The actual captures exercised only one missing point per rescued window. Therefore the data directly supports the policy's mechanism but does not validate behaviour close to the 95% limit. A 98% minimum would produce the same results on these captures and be a defensible stricter alternative, but there is no measured estimation-quality result requiring it. The proposed 95% bound is acceptable if presented as an availability/coverage choice and retained alongside the gap and span restrictions.

Under the stated zero-drift constant-variance Brownian model and observation times independent of shocks, each observed increment satisfies `E[(delta_price_i)² | delta_time_i]=sigma²*delta_time_i`. Consequently `sum(delta_price_i²)/sum(delta_time_i)` remains an unbiased variance-rate estimator with unequal observation intervals. There is no need to divide by a fictitious five seconds for every return or insert zero returns for missing observations. The square root itself has ordinary finite-sample estimation bias, which this sampling change does not remove.

Unequal intervals reduce precision. A useful diagnostic under those model assumptions is the effective number of increments `n_eff=(sum(delta_time_i))² / sum(delta_time_i²)`. Regular five-second observations over 300 seconds give 60. Rescued current windows have approximately **58.21–58.37** effective increments; rescued earlier windows have approximately **57.84–57.99**. Relative to an ideal regular window, this corresponds to roughly a **1.4–1.9% increase in the variance estimator's standard error**, under the model, rather than a loss of most of the statistical information. Near the full 95% omission allowance, even isolated omissions could have a larger precision effect; log actual coverage and intervals instead of assuming every accepted window has the same information.

Real BTC and oracle observations need not satisfy that Brownian/exogenous-sampling assumption. Missing updates can coincide with high activity, and a price can jump and reverse inside an unobserved interval. End-to-end price differences do not recover such within-interval variation. A 25% sigma stress is a scenario allowance, not proof that this bias is bounded. The change also does not establish that the raw feed or resulting terminal probabilities are well calibrated. Those limitations already exist with five-second sampling; sparse sampling must keep them visible rather than suggest the omitted prices were known.

There are **no eligible 1800-second windows** in either fixed replay dataset. Do not infer a demonstrated successful 30-minute warm-up from the five-minute availability result. One unavailable grid can poison every strict rolling window containing it for up to the entire window length. In this current capture, the bad 15:57:40 grid will remain inside strict 1800-second windows until after 16:27:40, later than a 32-minute capture beginning around 15:54:14 would finish. The proposed policy should remove that particular obstacle if the rest of the eventual 30-minute history satisfies its conditions, but the final full-span replay remains the direct verification.

The implementation consequence is bounded: make the coverage threshold explicit; skip and count unavailable/duplicate historical grid selections; reject inadequate coverage, excessive actual accepted-sample gaps or inadequate endpoint span; calculate variation from the accepted actual observations; and expose coverage, skipped grids, span and largest interval in diagnostics. Preserve raw data for later analysis. Meaningful checks are one missing internal grid accepted, consecutive missing grids rejected by the 12-second cap, a missing endpoint rejected by span, a below-95% history rejected even with separated omissions, and unchanged estimates on complete history. This is a volatility-history viability correction, not permission to trade on stale current quotes or approximate an exact settlement boundary.

## Completed 30-minute availability check

The bounded collector subsequently completed 1,920.3 seconds of anonymous collection. Source history
covers2026-09-06 15:54:14–16:26:13UTC (1,919seconds), with1,835 spot observations and1,835 TWAP events.
The final1,036,785-byte JSONL has SHA256
d0753ea1ba26fbe2bd7b87fd3aea698e44638588e5d093c7a66ce25aaac6eb99.

Root replayed this complete capture through the actual reviewed sampler at commit3b1c70f, using the
new defaults and a strict100%/7second configuration for comparison:

| Requested history | Eligible overlapping windows | Strict valid | Sparse valid |
|---|---:|---:|---:|
|300seconds|324|221|321|
|1800seconds|24|0|24|

The three rejected short windows had missing endpoints. Every one of the221 commonly valid short
windows retained exactly the same sigma. There were no commonly valid long windows, so no unchanged-
estimate claim is made for that comparison. The latest long window has359/361 acceptedpoints
(99.44598% coverage), exactly1,800seconds span and a10second maximum accepted interval. Its estimated
sigma is2.086654694377782 USD/sqrt(second). Both histories now produce operationally usable estimates
in this capture. These overlapping windows are availability checks, not independent trials, probability
calibration or evidence of trading profit.

Reproduction artifacts remain under the active worktree's work/: volatility-probe.py,
volatility-probe.jsonl, analyze-volatility-probe.py and volatility-availability-final.json. The collector
stopped at its bound and made no authenticated/account calls. The earlier prefix-based scientific
review above remains unchanged so its original scope and evidence are auditable.
