# Debugging traps (this project)

## 2026-09-07: A completed capture concealed an unready experiment

Zero orders were summarized without a causal breakdown of the rejection counts. The 38-minute
capture included development restarts: the 23:29 restart left a 23-second source gap, exceeding
the 12-second limit inside the 30-minute history window. Later valid short windows still failed
the long-window gate. Inspect `short_sampling_status`, `long_sampling_status`, actual gaps and
restart times before presenting zero-trade captures as useful strategy experiments. Show these
causes in operator-facing monitoring; JSON totals alone do not explain whether the bot is ready.

Format per entry: **Symptom → root cause → how to spot it faster next time → fix.**
Cross-project traps belong in ~/.claude/memory/debugging-traps.md instead.

## 2026-09-06: Optional snapshot time froze freshness across I/O

A snapshot accepted a seven-second-old spot under a five-second limit when the caller supplied
now_ms. The adapter reused that initial instant after awaited metadata work. Reproduce freshness
checks with every supported clock path, block a final response, and advance both injected clocks.
Use the supplied instant only for initial discovery; reread UTC for final age and round checks.
The fixture also covers crossing a round boundary and books aging during the same wait.

## 2026-09-06: An older cached rule overrode newer incompatible evidence

Delayed official metadata reported unsupported settlement rules, but subsequent cached discovery
still yielded a tradable captured anchor. The adapter treated incompatible authoritative evidence
like a retryable transport error. Replay a matching contract with changed rules followed by its
older supported payload. Keep that round conflicted; transient network failure or absent optional
metadata can remain retryable. Independent held-token book reads must still work for exits.

## 2026-09-06: A large apparent advantage used older underlying information

The public run's sole eligible value screen priced Up at 61c against a 96.8% central model
probability. Its book source time was about 2.2 seconds ahead of the model's BTC point. Later
arrivals for times before the decision showed an approximately USD 18 fall, and the next screen
rejected the trade. Compare source times and replay receive order before treating a large model
disagreement as value. This supports an information-lag explanation, not a proven quote cause
or counterfactual trading loss. The experimental confirmation rule and remaining source gap are
documented in docs/research/information-alignment-review.md.

## 2026-09-06: A rejection code could not identify the rejected field

The adapter's TRADING_METADATA_CHANGED records did not include compared values, preventing
reconstruction of 24 end-round skips. A later anonymous read found disagreeing tick sizes,
but could not prove that was the earlier cause. Record normalized compared fields and public
identities at the rejecting branch. Do not infer historical payloads from a later endpoint read.
Task4 completed the narrow producer-to-ledger diagnostic fix; the final public CLI capture
retained169 tick comparisons with expected0.001 versus actual0.01. Entry checks remain unchanged.

## 2026-09-06: One confirmed trade authorized provisional receipt amounts

A transaction containing two confirmed shares and three provisional shares credited its full
five-share aggregate receipt to final accounting. Grouping by transaction/hash was insufficient:
one CONFIRMED account row authorized every decoded owned amount in that transaction. Test BUY
and SELL with mixed statuses sharing a receipt, then advance status without changing the receipt.
When an aggregate cannot be reliably split, retain it as provisional until matching confirmed
account evidence supports the whole amount; never invent a prorated fee. Execution review fix
round 1 adds the regression and preserves receipt identity deduplication.

## 2026-09-06: Final preparation weakened approved metadata checks

A freshly changed raw minimum, an unsupported fee flag or an unknown fee-object field still
reached a synthetic POST despite the public snapshot parser rejecting those conditions. Compare
the final preparer's authorities with the approved snapshot parser, including values that change
after the snapshot. The authorized SELL tick exception does not relax minimum or fee schema checks.

## 2026-09-06: Concurrent SELECTs fabricated a flat financial summary

A readonly report combined old cash/no position with a newly settled absence of pending orders.
The writer actually held five shares. Multiple SELECTs without an explicit read transaction can
observe different committed SQLite versions; a connection context manager alone does not start
the needed read snapshot. Deterministically commit settlement between the reader's queries and
require a coherent before-or-after result. Use a nested-safe read transaction without acquiring
the trading-owner lock. Execution review fix round 1 covers the interleaving.

## 2026-09-06: Slow reconciliation aged every pre-fetched exit book

A frozen Book passed into Engine.step was checked only after awaited account work. If every
account pass exceeded the five-second book age limit, refreshing a separate CLI cache could
never rescue that already-passed object. Fetch the held token's book after reconciliation under
the engine's serialized ownership, then refresh real time and preserve all guards. A latest-input
invalidation generation also retains gaps or identity excursions overwritten while the engine
awaits. Ordinary same-identity valid updates must not invalidate every preparation. Task 4's
focused provider tests cover the six-second/five-second case and interrupted preparation.


## 2026-09-06: Cached consumption invented a new calibration receipt

CLI publication correctly recorded a snapshot, but Engine changed its timestamp and recorded it
again on consumption. A pre-window observation then became an in-window calibration sample and
raw counts doubled. Keep actual receipt/publication writes with the producer; reevaluate cached
execution input at current time without claiming a new observation. The regression uses a
pre-window publication, no in-window publication, then a genuine-publication control. Direct-call
observation behavior is intentionally preserved. Task4 fix2e83025 is independently approved.

## 2026-09-06: Cleanup errors must not strand journal ownership

Transport close can fail while a CLI command is unwinding. Independent cleanup responsibilities
must still close the ledger and release its owner lock; a single finally block with sequential
awaits can skip later work after the first exception. Exercise both construction and close failure
with the real lock, then prove the next owner can acquire it. AsyncExitStack protects independent
cleanup callbacks. A separate final review checks that asynchronous cleanup also respects deadlines.


## 2026-09-06: A producer conflict did not invalidate the consumer cache

MarketData retained an anchor conflict, but LatestInput only invalidated stream errors. During
awaited polling or order preparation, Engine could still see the old eligible snapshot and post.
Test the real producer emission before the replacement snapshot exists, including a later cached
valid overwrite and unrelated historical-round controls. Definitive current-round rule/reference
invalidity must advance generation immediately; persistent adapter state alone is insufficient.

## 2026-09-06: A conflict flag matters even when its retained number is unchanged

The final-reference producer preserved the original numeric value after a conflicting later price,
then emitted status=conflict. A reducer that compared only numbers incorrectly retained official.
Test actual producer events through a reopened journal/report. Explicit conflict must be sticky;
compatible duplicates and unrelated rounds must remain independent. Do not reconstruct authority
from a retained number while dropping its status/provenance.


## 2026-09-06: A controller timeout did not bound asynchronous cleanup

SHUTDOWN_DEADLINE was persisted, but a cooperative SDK close could keep run_live pending and its
wallet owner locked indefinitely. AsyncExitStack handles exceptions, not an enclosing time budget.
Carry one absolute budget through drain and resource close, including flat early exit; shield the
finalization ownership boundary against repeated caller cancellation. An interrupted submitted
order becomes UNKNOWN before cancellation propagates. Do not release ownership while execution
can survive. Prompt cancellation acknowledgement and local scheduling/I/O remain explicit limits;
noncooperative code requires external termination followed by journal inspection/reconciliation.
# 2026-09-07 extension findings

- A public capture with zero bot orders is observation evidence, not paper performance.
  The operator read flat zero PnL cards as a broken dashboard. Use "Awaiting first trade",
  keep the performance curve empty, and explicitly distinguish public market trades from
  the bot's own simulated fills. Show data gaps separately from elapsed warm-up time.

- Repeated WS book reconnects: an empty ask is reported with best_ask=1, and a single match can
  send a new crossed level before the zero-removal message at the same source timestamp. Keep
  incomplete working depth private; publish only after consistency returns, reconnect after a
  one-second unresolved sequence. Do not reconnect just because an older full snapshot arrives.
- False account discrepancy: Data API returned a four-decimal position size while the ERC1155
  balance kept six decimals. The index is a discovery aid; allow only sub-0.0001-share rounding
  there and retain exact blockchain-versus-journal and foreign-inventory checks.
- Paper BUY under-spent: requested minimum shares are a signed price protection, not the cash
  order's target size. Consume the requested cash principal through subsequent depth, allowing
  more shares at improved prices; test the actual cash amount as well as a nonzero fill.
- Queue recovery: a connection generation counter can repeat after process restart. Persist
  a stream-session identity too; a new session cannot inherit the old simulated queue position.
- Price-history restart: restore original public timestamps and conflicts without setting fresh
  feed receipt state. New spot and TWAP receipts remain mandatory before trading resumes.
<!-- 2026-09-07: additional paper regression during final verification. -->
- Simulated maker volume must be strictly later than the activation book timestamp. A trade
  sharing that timestamp may already be removed from the displayed queue; consuming it again
  invents a fill. Equal-timestamp ordering is unknown, so exclude it conservatively.

- 2026-09-07: Zero passive fills despite many orders was not explained by checking same-token
  SELL flow alone. Polymarket also matches BUY Up with BUY Down at complementary prices. A real
  0.48 bid replay changed from zero to five shares after adding that path. Retain transaction
  hashes, avoid double-counting mirrored outcome messages, and distinguish internal SETTLED
  reconciliation from actual filled/cancelled execution. Investigate the venue's full matching
  model before calling zero fills expected; synthetic tests had omitted the same real pathway.
- 2026-09-07: systemd 249 `systemd-analyze --user verify` against the active XDG_RUNTIME_DIR
  replaced the user's private control socket. Verify in a temporary isolated runtime instead.
  Recovery used a temporary session-bus socket/service and daemon reexecution without stopping
  other user work; temporary recovery units were removed. The installer regression protects the
  existing runtime. Do not test service recovery by killing the user's whole WSL instance.
