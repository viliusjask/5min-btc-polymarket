# Held-position input gaps after the metadata repair

September 8, 2026. Investigated on `fix/held-data-gaps`, based on `8d12573`.
The frozen directional audit identifies 35 completed variant-trades over eight
markets after deployment at `1788822513082`: 25 first failed metadata-age checks,
eight first failed spot-age checks and two first failed round-state checks while
meaningful inventory remained. Variants share the same tape, so these are not
35 independent outages. Missing strategy input does not establish impossible
endpoint fills. Existing flags and financial rows remain unchanged.

## Confirmed active-round retirement defect

In the original `observations.sqlite`, event `1928307` retires
`btc-updown-5m-1788827100` at `1788827281296`. The round ends at
`1788827400000`, and its metadata was validated at `1788827279675`.
The capture at `1788827281744` then reports `ROUND_STATE_MISSING` with
metadata age 2,026 ms. This is explicit local removal of current evidence.

`Tape.retained_markets` rotates six recovery slots. `MarketData.retain_markets`
can consequently insert old rounds after the current round. `_retire_rounds`
previously applied its count limit in dictionary insertion order, allowing it
to delete the current round before reaching expired restored rounds later in
that order. It could also discard a current reference conflict, allowing a later
rediscovery to lose that contradiction.

Retirement now visits rounds in chronological market order. Existing expiry,
count limits and retained-market exceptions remain identical. Old recovery
entries leave first, keeping current reference evidence and sticky conflicts.
Three regression cases failed with `ROUND_STATE_MISSING` before the fix and pass
after it: expired recovery rotation, the same rotation with a current reference
conflict, and restoring recent rounds out of chronological order at the count
limit. They exercise real retained-market calls and snapshot assembly without
refreshing cached timestamps.

## Metadata expiry and spot staleness

Two bounded original log windows show metadata validations separated by more
than five seconds without a recorded endpoint failure:

| First expired capture | Prior validation | Next Gamma response | Next validation |
|---|---|---|---|
| 1788823339318 | 1788823334178 | 1788823339719 | 1788823340978 |
| 1788825468438 | 1788825462837 | 1788825466466 | 1788825469102 |

These are consistent with delayed refresh work, not evidence that the last
validated settings became contradictory. The independent collector investigation
owns the synchronous journal work that may delay HTTP, stream handling and
refresh scheduling together. This patch does not change scheduling or extend
the five-second metadata lifetime.

For each distinct first stale-spot instant, original observations were read from
30 seconds before through six seconds after the instant:

| Failed capture | Points | Adjacent source intervals | Source-to-receipt lag |
|---|---:|---|---|
| 1788827853010 | 35 | 1 or 2 seconds | 2,981–4,445 ms |
| 1788837140225 | 35 | 1 second | 2,951–4,728 ms |
| 1788827302258 | 34 | 1 or 2 seconds | 2,633–4,797 ms |

At the first two instants, the next one-second-newer source point was recorded
156 ms and 283 ms later. These windows show mostly one-second source cadence;
they do not establish how much delivery latency originated upstream versus in
local event processing. The five-second freshness requirement was actually
exceeded at the rejected samples.

The official RTDS documentation distinguishes message timestamps from price
payload timestamps and specifies a five-second connection heartbeat. Its crypto
price section does not promise a maximum delivery delay or specify five seconds
as an appropriate trading freshness threshold. A connection heartbeat is not a
fresh price observation. [Official real-time data documentation](https://docs.polymarket.com/market-data/realtime-data#crypto-prices).

Recommendation: retain the current source/receipt-age checks and remeasure delay
after the collector performance fix. Raising the threshold would admit older
information into entry/model decisions and requires a separately specified
research comparison; availability alone would not justify it. No timestamp
renewal, missing-point interpolation or stream reconnect tuning is included.

## Strategy-specific replay limits

`Replay.apply` marks missing complete snapshots uncertain when non-settlement
inventory, unresolved orders or a pending candidate are exposed. Settlement-only
holdings are already exempt when there is no outstanding execution or candidate.
`Engine._exit` can evaluate ordinary stop/profit/time exits from a fresh held-token
book without spot/TWAP input; model exits require the model snapshot too.

However, directional replay currently updates its books only from complete
snapshots. Its broker does not consume independently recorded research-stream
books, as pair replay does. Therefore an unrelated price-feed failure still
withholds new held-book observations from that replay. Clearing the uncertainty
flag based only on the failed component would hide an actual input limitation.

A future separately versioned replay could consume validated held-token books
independently and assess uncertainty against each policy's actual exit and
pending-order requirements. That requires identity, synchronization, source-age,
receipt-age and model-input tests; it cannot be a retrospective flag change for
the registered studies. This repair leaves all study implementations untouched.

## Verification and evidence boundaries

117 tests passed across round retention, market refresh, market data, tick
compatibility and lab replay. The existing cases retain real expiry, stale-price,
book-disconnect, tick-invalidation, background-reference and shutdown behavior.
The change is in-memory ordering only: no schema, dependency, public interface,
configuration, accounting or deployment change.

Frozen audit: `.worktrees/metadata-refresh/work/results-audit/directional-audit.json`
and its Markdown companion. Original journal:
`~/.local/share/btc5m/paper-six-100-each/observations.sqlite`. Journal reads used
SQLite read-only mode, binary searches by event primary key to find the target
time windows, then bounded primary-key slices. No historical rows were modified.
An integrated multi-round probe and deployment belong to the parent task; these
unit tests do not establish future uptime or trading returns.
