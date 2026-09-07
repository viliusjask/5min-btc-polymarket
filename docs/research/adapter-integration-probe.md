# Full public adapter and strategy run

2026-09-06, 17:07:13.867756–17:42:13.912243 UTC: **2,100.044 seconds** using the
actual reviewed `MarketData`, `evaluate` and repository configuration. This was an anonymous
observation run. No account client, reservation, order, hypothetical fill or profit was produced.
The later execution-confirmation rule was not implemented during this capture.

| Evidence | Result |
|---|---:|
| Successful snapshots | 1,702 |
| Unavailable snapshots, recorded separately | 139 |
| Raw candidate decisions, both modes per successful snapshot | 3,404 |
| Received spot / TWAP observations | 2,004 / 2,002 |
| Current token book observations | 3,682 |
| Distinct captured opening boundaries | 7 |
| Captured openings subsequently compared with official metadata | 6 |
| Distinct official final reference labels received | 5 |
| Valid-model value / momentum snapshots | 102 / 53 |
| Distinct rounds represented in those valid-model snapshots | 2 |
| Eligible value / momentum snapshots | 1 / 0 |

The two candidates' repeated snapshots are not independent market outcomes. The short fully warmed
part of this run cannot estimate opportunity frequency, calibration quality or trading returns.

The median source age at successful evaluation was **3,016 ms for spot**, **3,088 ms for TWAP**,
and **993 ms for each book**. Maximum accepted ages were 4,914 ms for spot/TWAP and 2,578 ms for
books. These differences include local/source clock effects; they do not identify network-only
latency. The latest books often contained newer information than the underlying model input.

Unavailable results were 116 `TRADING_METADATA_CHANGED`, 13 `STALE_DATA`, seven `STREAM_SILENT`,
two initial `STREAM_WARMUP`, and one `ROUND_CHANGED`. The streams emitted six unavailable events
and recovered. No missing observations were interpolated into the live history. Once warm, the
actual core produced valid 1,800-second estimates; the eligible snapshot had 359/361 accepted
long-window samples, full 1,800-second span and maximum accepted gap 12,000 ms.

The metadata skips exposed a diagnostic gap: the adapter retained the rejection code but omitted
the compared raw values. A later read confirmed that two official endpoints could disagree on
tick size, without proving the precise earlier cause. The planned integration fix adds field-level
diagnostics and keeps entry rejection intact. See [the exact diagnosis](adapter-metadata-diagnosis.md)
and [the researched protected-SELL rule](tick-change-contract.md).

## The eligible candidate and information timing

At 17:38:50.190 UTC, a value screen selected Up for the 17:35–17:40 round. The ask was 0.61,
the central model probability 0.968279, and the scenario floor 0.770603. Its apparent terminal
surplus after the specified allowances was 0.116450 USD/share. The proposed principal was 4.67,
maximum reservation 4.9969 and protected price 0.62. These are screen outputs only.

The selected book was timestamped 17:38:49.189, while the model still used spot source time
17:38:47.000 at BTC 79749.469423. Later arrivals reported source times 17:38:48/49 at
79739.586583/79731.904579. Those source times preceded the original decision. The next snapshot,
17:38:51.329, already failed the value screen. This supports an information-lag explanation for
the temporary apparent advantage; it does not prove the quote's cause or a counterfactual loss.
Actual order preparation and price protection could also have rejected a changing book.

An independent review accepted a prospective confirmation experiment: preserve the original
candidate book timestamp, wait for a strictly newer underlying point to reach it, and require
the same side to remain eligible on the current inputs before reserving. Any observed invalidation
cancels the candidate. The supplied episode would cancel after 1,139 ms, before its original
timestamp could be reached. A generic next-snapshot check also rejects it, so this event does
not establish the chosen rule's superiority. Current book information can still lead at confirmation.
See [the independent review and counterexamples](information-alignment-review.md).

## Reproduction artifacts

The ignored work directory retains `adapter-integration-probe.py`, the complete public JSONL,
its end summary, `analyze-adapter-integration.py`, and `adapter-integration-analysis.json`.
The complete capture is **38,868,929 bytes**, SHA-256
`5d5bf5fe4d0ce294d07f46c8469d0c3cc88bc0fb1539b6aff4d8fac516679da0`.
The exact 60-record event excerpt is `work/information-alignment-event.json`, 169,016 bytes,
SHA-256 `f645644c9015a1cb50dfa43210d944ed0da2e3e75366c2978c5960c7db628100`.
The probe process closed cleanly with exit zero. No public-data process remains from this run.
