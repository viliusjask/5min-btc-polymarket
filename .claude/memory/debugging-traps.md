# Debugging traps (this project)

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
The narrow integration fix is assigned to Task 4; entry checks remain unchanged.
