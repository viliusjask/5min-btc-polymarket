# One paper experiment catalog

Paper opens the original portfolios and every registered phase of the directional and order-flow
studies in one table. A repeated control in a later-data test is a separate row and wallet.
Identity includes source, phase and variant identifier; names alone are not unique. The current
catalog can grow when a worker registers a later-data phase. Nothing in the browser starts,
resets, retunes or funds a study.

Search includes names, families, identifiers, displayed parameters and implementation versions.
Source/family/phase, evidence, activity and minimum completed-round filters combine. Numeric
headers sort in either direction; unavailable values always sort last. The minimum sample filter
starts at zero, so one-win experiments are visible rather than silently suppressed. Historical
LOSS_LIMIT rejections are labelled historical; an aggregate count does not prove a current halt.

The catalog appears before the comparison chart. Use **Compare curves** to jump to the chart.
All filtered experiments appear as grey context curves by default, with up to eight chosen
experiments highlighted and named in the removable legend. Highlights survive search/filter and
refresh changes. Disable context to inspect only the highlights. Each line is an individual
completed-profit history on a shared UTC axis. Overlapping simulated profits are never summed.

## Financial meanings

| Display | Meaning |
| --- | --- |
| All realized net | All recorded realized profit after fees, including any realized amounts on unfinished markets |
| Unflagged completed net | A subtotal of completed capital-used markets without recorded execution flags; not account equity or restored capital |
| All realized return | All recorded realized net divided by the original allocation; deliberately unchanged by the cohort filter |
| Net per completed round | Selected completed net divided by selected completed capital-used market count; several fills/orders remain one round |
| Win rate | Positive-net completed markets divided by selected completed markets, including flat results in the denominator |
| Largest win | Largest strictly positive completed result; unavailable if there are no wins |
| Observed equity drawdown | Reported peak-to-trough decline in bid-marked equity for studies; unavailable for originals without comparable marked history |
| Comparison return curve | Completed-profit subtotal divided by original allocation, not an account equity return |

No-fill experiments retain their known wallet balance/net, but do not acquire a zero win rate or
profit-per-round estimate. Missing reports or statistics remain unavailable, not zero. Curve
points are assigned to market end, not the time of accounting or cash receipt, and stop at the last
completed result. Long curves retain at most 1,200 points, keeping endpoints and each consecutive
group's cumulative minimum/maximum; rankings use the complete sample. Missing marked equity breaks
a drawdown line and can conceal deeper losses.

Detail shows chronological completed markets and the source's bounded latest order journal
(100 original orders or 50 study orders). Costs, hourly consistency, winner concentration and
entry-condition research reuse the existing research calculations. Original portfolio exports
contain only recent individual fills, so lifetime entry-condition and per-share cost-sensitivity
analyses are unavailable rather than estimated from a partial journal. Same-market comparisons
and existing collection/scanner/calibration diagnostics remain accessible from study detail.

The original continuous journals can span policy changes. Their current configuration is shown
only when the actual journal session fingerprint matches it. The same match is required before
showing daily/session risk-budget headroom. Realized session losses persist across a new day;
held position risk and order reservations also consume the limit before a proposed new order.
Available loss budget is not a promise that a quoted order can fill. Pinned study Momentum controls
may implement a different rule from the current original Momentum portfolio.

## Read boundaries and freshness

`GET /api/experiments` provides the catalog. `GET /api/experiment?key=...&cohort=all|unflagged`
loads a selected experiment. Both remain localhost-only, read-only and independent of Real account
initialization. Existing state, lab and research routes keep their contracts.

The catalog is cached for 30 seconds. Financial statistics reuse `read_rounds` and `performance`;
unchanged reported net/counts/fees/flags reuse cached samples instead of reopening every journal
on each page poll. Detail reads are bounded to the requested journal, with an eight-entry,
30-second response cache. The saved report and small study registry supply catalog coverage;
registered rows remain visible if a report fails, including registered later-data phases.

If a journal advances beyond the saved report's completed counts or profit, the list temporarily
withholds inconsistent round statistics. Detail can show its newer analysis but explicitly removes
incompatible account net/return totals and identifies the separate times. No journal is rewritten
to align it with a report.

Capture status reads the small existing capture-quality aggregate. A fresh recorder heartbeat or
fresh Bitcoin price alone does not establish a usable market snapshot: current snapshot code,
recorded time and data gaps remain visible. Study timestamps and phase boundaries appear separately.
Paper browsing never requests `/api/live`; the Real switch retains lazy read-only account access.
