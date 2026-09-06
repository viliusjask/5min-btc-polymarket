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
