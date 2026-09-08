# Public history archive

The existing paper collector now records additional public history automatically. It still
uses the same anonymous connections and `capture.sqlite`; it does not start another service,
subscribe to account data, or change any strategy, fee calculation, execution rule or
freshness threshold. Existing `observations.sqlite` oracle history is retained as well.

## What is retained from this version onward

| Data | Stored evidence | Limits |
| --- | --- | --- |
| Chainlink BTC/USD spot and TWAP60 | Every accepted exact normalized Decimal tick, original payload source time, local receipt time, event envelope time, symbol, TWAP window, source and connection generation. Conflicting prices and stream failures remain visible. | For TWAP, pinned SDK 0.9.0 converts the E18 `full_accuracy_value` into exact Decimal `value`; it does not expose the original wire field afterward. Precision is preserved, but we do not reconstruct the raw field or claim byte-for-byte RTDS capture. Duplicate or rejected oracle ticks are not additional accepted prices. |
| Polymarket market websocket | Book snapshots, price-change messages, public trade messages and tick changes before consolidation or validation, including book hashes when supplied, token/market identities, source and receipt times, local event order, stream identity and generation, and disconnect markers. | Only the currently subscribed market. Local order is not an exchange sequence guarantee. Public messages do not reveal queue position, hidden liquidity, or individual resting order IDs. Rejected/intermediate messages are evidence rather than executable books. |
| Binance BTCUSDT | Every received aggregate-trade message, retaining trade/event times, aggregate/first/last trade IDs when supplied, price, quantity and aggressor indication, even when multiple messages occupy one 100ms strategy sampling bucket. | BTCUSDT is a different instrument from the settlement BTC/USD oracle. The existing `--capture-flow` mode also retains normalized depth20 updates and their supplied update IDs; that feed supplies receipt-only depth timing. |
| Public market interpretation | Narrow Gamma rule text, resolution source, market IDs, outcome/token mapping, event times and opening/final reference metadata; CLOB fee, tick, minimum-size and state fields; normalized REST books and book hashes, including retained positions. | Fields are archived before interpretation checks where the raw public HTTP dictionary is available. SDK-normalized fields are identified as such. Chat, rewards descriptions and unrelated payloads are excluded. HTTP metadata has local receipt timing, not an invented provider timestamp. |
| Producer identity | A durable capture-session row with public config and fingerprint, source-file hashes, Python/SDK versions, flow mode, previous capture time, next frame ID, and written source/durability semantics. | These identify the running files, not a claim that all prior history used this implementation. Every process has a new capture identity. |

The source code and configuration record is in `capture_sessions(id, started_ms, data)`.
Each prospective compressed frame has an optional `archive` object with `version`,
`session_id`, `events` and `gap`. Each event has a local `sequence`, monotonically increasing
within that capture session. Source websocket session identity is separately present on
wire records. The frame ID and capture-session ID disambiguate records across restarts.

Independent oracle and wire records are retained even when `frame.snapshot` is absent.
A missing snapshot remains missing: archive presence does not repair eligibility, certify
completeness, or clear old uncertainty flags. The existing snapshot/research structures
remain the inputs to current experiment engines.

## Durability and capacity

Additional archive events use the collector's existing compressed frame transaction,
normally every 500ms, with SQLite WAL and `synchronous=FULL`. A graceful stop closes the
transports and commits the final archive batch. Accepted oracle observations also retain
their existing immediate master-journal write.

An abrupt process kill, WSL termination, power loss or unavailable storage can lose the
uncommitted wire-message tail. There is no honest zero-loss guarantee for messages that
have not reached a committed transaction. During sleep or disconnected periods no collector
can observe missing exchange events. Existing capture/stream gaps and new process boundaries
remain visible; this implementation does not invent those events afterward.

The new buffer admits at most 20,000 records and 8 MiB of encoded event bytes per batch
(Python object overhead is additional). Oversized messages or an overfull buffer cause
the remainder of that batch to be omitted with `ARCHIVE_BUFFER_OVERFLOW`, a dropped count,
first/last local sequence and receipt bounds. Recording resumes on the next batch. The
buffer does not grow indefinitely and does not read historical SQLite rows per event.

No archive, tick or historical frame is automatically deleted. The earlier observed combined
runtime footprint was roughly 4.27 GiB over approximately 25–32 hours; the additional raw
book/trade data increases storage and decoder work. That observation is not a future capacity
forecast. Sustained growth and remaining disk space must be measured after deployment.

## Using the data

New readers can inspect `frame.archive` through `Tape.read_after`. Iterate frames and local
event sequences in capture order and use receipt times to decide what was known at a
decision. Source times alone cannot establish that information had arrived. Start a book
reconstruction only from a full snapshot for the same token and stream generation, apply
subsequent deltas in recorded order, and invalidate it across gaps or uncertain sequences.
An archived last trade or a touched price is not proof that our hypothetical order filled.

This makes future tests more flexible, but does not implement a universal raw-event strategy
replayer. Existing decision-snapshot strategies can use the existing replay engine; a new
strategy that requires a previously unrecorded instrument, queue priority, or unavailable
pre-start history still cannot be faithfully evaluated on those missing inputs.

## Compatibility and verification

Tape version and identity stay unchanged. The new table and payload field are additive;
old frames, checksums, labels and experiment manifests are not rewritten. Actual decoders
from both pinned `.worktrees/experiment-lab` and `.worktrees/order-flow` successfully read a
synthetic tape containing an old frame plus new valid and rejected frames. They ignored
the added archive field and preserved their original snapshot/research interpretation.
Scratch evidence: `work/archive-capture/pinned-reader-check.json`.

Regression checks cover oracle precision/provenance without a tradable snapshot, pre-consolidation
and rejected book deltas, buffer byte/count limits, mutable-payload detachment, capture-session
identity, old-frame immutability, future-receipt rejection, selective metadata, shutdown-tail
flush and several Binance trades inside one strategy sample. A synthetic 10,000-small-delta
benchmark measured approximately 0.041s without archiving and 0.096s with it, about 5.5µs
extra per delta. This excludes disk and is not a live throughput guarantee.

The focused market/stream/tape/collector regression selection passed 152 tests. The final
archive-envelope validation refinement passed its 17 archive/tape checks; Ruff lint and
format, mypy and the locked dependency check also pass. Combined integration verification
and live service cutover belong to the parent task; this worktree has not changed services.
