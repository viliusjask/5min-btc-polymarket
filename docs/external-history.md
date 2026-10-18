# External history and the existing six strategies

The OutcomeTick importer converts explicitly supplied local files into the same `Tape`
that `lab run` already reads. The real `Study`, strategy rules, `Engine`, `PaperBroker`
and account journals then run unchanged. This is an exploratory simulation, not evidence
that orders would have filled identically at the venue.

## Required evidence and explicit assumptions

The supported source is BTC five-minute markets under the Chainlink TWAP60 rule. The
market's own `cryptoMarketConfig` and resolution URL select that rule; older spot/TWAP30
markets are recorded as unsupported rather than silently applying today's formula.
Source: [OutcomeTick September 4 public release](https://github.com/Ligengxin96/polymarket-data-samples/releases/tag/samples-2026-09-04)
and [field guide](https://github.com/Ligengxin96/polymarket-data-samples/blob/main/DATA_GUIDE.md).

Required gzip files are market identities/rules, full order-book snapshots, Chainlink spot
CSV and exact Chainlink TWAP60 CSV. Optional files are public trades and unthrottled
best-bid/ask updates. Exact `full_accuracy_value` is divided by 10^18 using Decimal;
the rounded display `value` column is not used. Historical spot is never substituted for
the settlement stream. An opening anchor must be an actually received exact boundary
tick. Missing boundaries, warmup, stale books and missing feed input remain unavailable.

The archived final market record is not a series of historical metadata messages. Its
final closed/accepting-orders flags, tick size, minimum size and fees are **not copied
back into earlier snapshots**. Without `HistoricalTerms`, the strict import writes
unavailable snapshots with `UNKNOWN_HISTORICAL_TERMS`. An explicitly supplied terms
profile enables modeled execution: the declared tick, minimum and fee formula are
assumptions, and acceptance while fresh in-window books exist is an assumption too.
Every external frame and the immutable source metadata carry these limitations.

The importer uses complete snapshots and never applies the vendor's sampled price-change
deltas as if they formed a complete sequence. When an unthrottled top update changes
either best price, the old snapshot depth becomes unavailable until refreshed. A price
touch does not fabricate a fill. The existing paper simulator needs later protected
depth for immediate orders and observed trade volume/transaction identities for passive
orders. Public transaction hashes preserve complementary-outcome mirror deduplication.
Even then, sampled books cannot establish exact queue priority, so passive results remain
assumed execution. Omitting the trade file leaves passive fill evidence unavailable.
Independent books remain available for exits even without a trade file or while an
oracle-dependent forecast is unavailable; lack of trade volume cannot fabricate a fill.
Real resolution-adjacent books/prints sometimes contain prices of zero or one. A book with
such a level or zero-size level becomes wholly unavailable; filtering just that level
could invent a better executable ask. Boundary-price trades are counted but excluded from
ordinary passive fill volume, matching the current live stream adapter's price domain.

FastValue additionally needs native Binance `BTCUSDT-aggTrades-YYYY-MM-DD.zip` from
[Binance's public archive](https://github.com/binance/binance-public-data). The ZIP must
contain exactly its matching CSV format. This source has exchange timestamps, not local
receipt timestamps. `binance_latency_ms` is therefore required when the ZIP is supplied:
each modeled receipt is exchange time plus that explicit delay. Native 2025+ timestamps
are microseconds, floored to the application's millisecond clock. The usual alignment,
freshness and move-size gates still apply. Without Binance, FastValue reports its missing
feed rather than falling back to Value. Test multiple plausible delays before interpreting
a speed advantage.

Official outcome labels are independently checked against exact opening and closing
TWAP boundaries and the archived strike when present. A mismatch fails the import.
Unknown resolution-message receipt times are never represented as actual receipts.
By default verified labels are withheld until the last imported observation. Supplying
`resolution_delay_ms` instead enables modeled availability at the later archived
`umaEndDate`/`closedTime`, plus that explicit delay. Such times must be at or after the
market end. Labels appear only in a subsequent actual received frame. Missing availability
still waits until the final imported observation. This assumption changes cash recycling,
so the report records it and its results need sensitivity checks.

## Safe conversion and replay

`import_outcometick` in `btc5m.history_import` accepts explicit paths, a fresh destination
directory, `start_ms`, `end_ms`, and the existing `Config`. Both receipt endpoints are
inclusive. The importer also reads up to the configured longest volatility window plus
60 seconds before the start to construct causal histories; it does not invent absent
pre-roll. Choose an earlier import start if the replay itself should display those
warmup frames. Include a real suffix after the last entry round for order exits and labels.

The function returns a JSON-compatible summary and publishes `capture.sqlite` together
with `import.json` in that directory. Replay it using the existing bounded `lab run
--start ... --end ...` command and a separate new study directory; see
[historical replay](historical-replay.md). Nothing changes a continuous collector, funded
account, existing study, or supplied source file. The importer makes no network calls.

Files stream through bounded line readers into a disposable indexed SQLite sorting cache.
This handles cross-stream ordering by vendor receive time without loading a full day into
RAM. Each 500ms decision bucket evaluates the state at its last actual received event,
retaining original source/receipt times; it does not refresh stale input timestamps.
This sampling is another execution limitation. Maximum source receipt gaps, snapshot
rejection causes, exact-boundary coverage, input counts and computed SHA-256 hashes appear
in the summary. These hashes attest downloaded bytes; they are not vendor-supplied
checksums. The September 4 source URL is pinned rather than following `latest`.
CSV prices have no embedded asset symbol, so choosing the documented BTC source files
is an explicit acquisition responsibility; the manifest records their paths and hashes.
The importer also fingerprints the strategy, domain, configuration, tape, ledger and
quality modules that affect conversion, so resumption cannot silently change semantics.

The destination must be new. Publication occurs only after complete gzip/ZIP parsing,
identity/field validation and a second source hash comparison. A failed/interrupted import
keeps an explicit incomplete manifest and never publishes a successful tape. Repeating a
completed conversion with exactly the same source/code/config/profile returns its stored
summary. An incomplete conversion requires a new destination; it cannot overwrite an
older good archive or silently resume with changed inputs. The temporary sorting cache is
removed after either success or failure; a failed partial tape and manifest remain for
diagnosis. Supplied source archives and the finished tape remain. The strict no-terms
output is a diagnostic tape, so keep the source files to create a later assumed-terms run.

Only the unpublished derived tape uses SQLite NORMAL synchronization while being built.
Before publication, the importer switches to FULL, requires a complete WAL checkpoint,
flushes the database file explicitly, then publishes and flushes the manifest directory.
An interrupted conversion remains incomplete and requires a fresh destination. The
ordinary `Tape` writer and continuous collector retain FULL synchronization. A bounded
200-frame actual-data benchmark produced identical decoded outputs and final sizes:
FULL took4.06seconds, NORMAL0.69seconds, including durable finalization. This measures
the tested import path under that disk load, not a guaranteed whole-day speedup.

For meaningful comparison, retain all tested variants and compare complete time blocks
under the same terms/latency/availability assumptions. Keep execution assumptions separate
from known collection gaps. More historical hours can broaden a test, but cannot turn
sampled or modeled execution into confirmed venue cash.
