# Polymarket experiment lab

Authorized September 7, 2026: implement the five research priorities in the current
BTC five-minute project. Single-agent development; funded execution remains disabled.
The existing six portfolios and their journals are preserved.

## Scope and evidence

1. Score central probability forecasts and a contemporaneous market baseline against
   official outcomes, with missing observations explicit. Inspect conservative scenarios
   separately from calibration.
2. Run registered, comparable parameter variants on common recorded public inputs;
   expose an Experiments dashboard with profit, fills, rounds, drawdown and diagnostics.
3. Compare entry windows, exit/stop/settlement controls and aligned faster prices,
   preserving the candidate-to-confirmation-to-order-to-fill-to-exit funnel.
4. Test volatility/time-normalized lead and recent continuation/reversal hypotheses.
5. Freeze configurations before evaluating later data. Keep unsuccessful trials visible,
   and separate exploratory selection from prospective validation.

Primary research supplies statistical and execution requirements, not profitable parameter
values. Current exchange documentation governs contract mechanics. Existing public journals
provide operating evidence; synthetic tests verify accounting and causality. Report gaps
instead of inventing historical inputs or fills. No new runtime dependency is planned.

## Implementation sequence

- [x] Research scoring, chronological evaluation, correlated trials and execution realism;
      record a source/claim/limitation register and concrete implementation decisions.
- [x] Inspect and reuse existing recording, strategy, simulation and dashboard machinery.
      Define durable experiment identities and restart-safe shared input consumption.
- [x] Implement forecast evaluation and registered variants, with causal execution tests.
- [x] Implement chronological selection/freeze and later-data evaluation, including
      coverage, sample sizes, costs and all attempted variants.
- [x] Add the dashboard views and operator commands, test integration and restart behavior.
- [ ] Verify against recorded public data, deploy alongside preserved portfolios, and
      publish a feature PR with honest evidence and remaining limitations.

Success means the five capabilities work end to end, remain paper-only, persist across
restart, and distinguish observed results from unsupported claims. A profitable strategy
is an empirical outcome of future evidence, not an acceptance criterion code can guarantee.
