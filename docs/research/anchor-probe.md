# Anonymous BTC 5-minute anchor probe — 2026-09-06

**Result: two published boundary matches confirmed, including one that distinguishes the exact source second from its neighbors.** The initial 16-minute collection confirmed the first boundary; an authorized metadata-only follow-up at 15:49:48 UTC confirmed the second using the existing recorded stream. No orders, credentials, or account activity were used. This is a timestamp/anchor observation, not evidence about strategy calibration or profitability.

## What was collected

- Stream collection: **15:30:09.3–15:44:09.3 UTC**, using the installed official SDK `AsyncPublicClient` and BTC/USD Chainlink spot plus 60-second TWAP subscriptions.
- Source timestamps covered **15:30:08–15:44:06 UTC** for TWAP and **15:30:09–15:44:06 UTC** for spot. Source-time boundaries **15:35:00** and **15:40:00** were captured in both streams.
- Raw RTDS frames: **12,994**. The server supplies additional symbols before SDK filtering; all received frames were retained before SDK event parsing. BTC normalized events: **814 TWAP + 813 spot = 1,627**. Raw BTC event counts match normalized counts.
- Metadata: **164 default SDK snapshots + 162 cache-busted snapshots = 326**. Default calls periodically queried current/previous and previously observed windows. Cache-busted snapshots also retain raw Gamma JSON and HTTP headers. Metadata-only collection continued until **15:46:09 UTC**; its last polling batch completed at **15:45:58.320 UTC**.
- A later bounded follow-up made **two normal SDK `get_event(include_chat=False)` calls** at 15:49:47–15:49:48 UTC. Both required fields were populated on the first attempt. These bring the analyzed metadata total to **328 snapshots**. No stream collection resumed.
- Supplementary one-off cache/parameter comparisons are retained separately.

## Boundary comparisons

TWAP values below use the SDK Decimal decoded from the wire `full_accuracy_value` integer at scale 10^18. The API metadata is a JSON number with lower precision. “Matches” therefore means agreement at the number precision actually published in metadata, not equality of all Decimal digits.

| Boundary source timestamp | Captured 60s TWAP | Captured spot | Official metadata observed |
|---|---:|---:|---|
| 2026-09-06 15:35:00 UTC | 79629.188843035644919808 | 79634.71230020556 | 79629.18884303565 in both prior `finalPrice` and next `priceToBeat`: matches TWAP, differs from spot |
| 2026-09-06 15:40:00 UTC | 79697.534252279656349696 | 79689.625168105 | 79697.53425227966 in both prior `finalPrice` and next `priceToBeat`: matches exact-time TWAP and differs from neighboring seconds and spot |

The first row uses:

- Prior event [`btc-updown-5m-1788708600`](https://gamma-api.polymarket.com/events/slug/btc-updown-5m-1788708600), covering 15:30–15:35. Its `finalPrice=79629.18884303565` was first seen at **15:41:14.673770 UTC**.
- Next event [`btc-updown-5m-1788708900`](https://gamma-api.polymarket.com/events/slug/btc-updown-5m-1788708900), covering 15:35–15:40. Its `priceToBeat=79629.18884303565` was first seen at **15:41:30.168945 UTC**.
- The full-precision TWAP difference from the metadata number is **−0.000000000005080192**. The raw wire's displayed numeric value is exactly the same published number as metadata.

There is an important limitation to this first match: the TWAP at **15:34:59** is identical to the TWAP at **15:35:00**. This boundary alone therefore cannot distinguish selecting the exact source second from an off-by-one selection of the preceding second. The next second, **15:35:01**, differs: **79629.787279779281502208**.

The second boundary is discriminating because the neighboring TWAP values differ:

| Source UTC | 60s TWAP |
|---|---:|
| 15:39:59 | 79697.640602597586894848 |
| **15:40:00** | **79697.534252279656349696** |
| 15:40:01 | 79697.300380131864346624 |

The follow-up found `finalPrice` of [`btc-updown-5m-1788708900`](https://gamma-api.polymarket.com/events/slug/btc-updown-5m-1788708900) and `priceToBeat` of [`btc-updown-5m-1788709200`](https://gamma-api.polymarket.com/events/slug/btc-updown-5m-1788709200) both equal **79697.53425227966**. The exact-time full-precision TWAP differs by only **−0.000000000003650304**, and its wire display number equals the metadata number. The preceding second differs by **+$0.106350317926894848** and the following second by **−$0.233872147795653376**. Exact-time spot differs by **−$7.90908417466**. Therefore the neighboring-second and spot alternatives fail this check at published precision.

Additional continuity observation: the 15:25–15:30 event's `finalPrice` and the 15:30–15:35 event's `priceToBeat` both became **79626.0237292455**. The stream collection started after the 15:30 boundary, so that equality cannot independently validate the source-time anchor.

## Metadata availability and caching

The API description for the observed markets explicitly names the [BTC/USD 60s TWAP stream](https://data.chain.link/streams/btc-usd-twap-60s-streams). Metadata availability is a separate issue:

- The 15:30 event's `priceToBeat` was first seen at **15:35:06.457591 UTC**, after its five-minute trading window had ended.
- The 15:35 event's `priceToBeat` was first seen at **15:41:30.168945 UTC**, over six minutes after its start. Fresh-query polls during its trading window had not returned it.
- `finalPrice` for the 15:30 event was first seen **374.674 seconds after the 15:35 close**. This is observed first availability at the polled endpoint, not proof of the internal publisher's exact write time.
- The 15:35 event's `finalPrice` and the 15:40 event's `priceToBeat` remained absent in fresh snapshots through **15:45:58 UTC**. They were subsequently present in the separate normal-SDK follow-up at **15:49:47.929805** and **15:49:48.009652 UTC**, respectively. The unobserved interval prevents identifying their exact publication time.

Caching is directly evidenced, rather than merely inferred. At approximately **15:38:28 UTC**, paired reads of the 15:30 event returned:

| Request | Metadata | `updatedAt` | Cache evidence |
|---|---|---|---|
| Default query | `null` | 15:31:38.767564 | `CF-Cache-Status: HIT`, `Age: 221` |
| Unique `_anchor_probe` query | `priceToBeat: 79626.0237292455` | 15:37:28.076816 | `CF-Cache-Status: MISS` |

Both advertise **`Cache-Control: public, max-age=300`**. An earlier supported `include_chat=False` variant likewise returned newer metadata than the default `get_event` call. The unique query and optional no-cache header were used only for this read-only probe; no authentication or access controls were bypassed.

Consequently, a later response can be older and less complete than a previously seen response. Even after eliminating the observed edge-cache hits, metadata was too late to provide a timely opening anchor for the tested live windows. The experiment does not isolate all remaining origin/replica/publishing delays.

## Feed completeness and timing

| Measurement | TWAP | Spot |
|---|---:|---:|
| Unique observed source seconds | 814 | 813 |
| Unobserved seconds between first and last source times | 25 | 25 |
| Gaps larger than one second | 21 | 21 |
| Longest gap between adjacent observed source times | 4 seconds | 4 seconds |
| Conflicting values at the same source timestamp | 0 | 0 |
| Median receive time minus source time | 2.454 seconds | 2.343 seconds |
| 95th percentile receive time minus source time | 3.015 seconds | 2.892 seconds |

Both exact boundary ticks were present despite other missing seconds. Absence of other source seconds is also visible in the captured raw BTC frames; the normalized counts show no loss between raw BTC events and the SDK subscription output. This does not establish where upstream gaps originated.

The 15:35:00 TWAP arrived locally at **15:35:02.582165 UTC**. These elapsed times include source publication, relay, delivery, and any local clock offset. They are **not** measured network round-trip latency; local clock synchronization was not independently audited.

## Implications for anchor policy

1. **Use source timestamps.** A first-tick-received-after-the-wall-clock-boundary rule can pick a previous source second. Persist the candidate TWAP tagged with exactly the bucket's start timestamp and preserve its full Decimal value.
2. **Missing exact timestamps require an explicit no-anchor state.** This sample has gaps. Substituting a nearby tick or Chainlink spot is not validated here. The captured exact-time spot values differ materially from TWAP.
3. **Treat Gamma metadata as delayed verification in the observed windows.** It was not a usable live opening source. Preserve already known fields when a stale response returns null, and inspect source `updatedAt`/cache headers rather than trusting local request order.
4. **Keep the validation's scope precise.** Both tested boundaries now match published metadata; the second distinguishes the exact source second from its neighbors. This supports retaining the TWAP tagged with the exact bucket boundary. Two observations do not guarantee that every future boundary arrives, that a rule cannot change, or that a trading strategy has an edge. Later official metadata should still be reconciled against the retained anchor.
5. **Keep resolution-rule eras separate.** The older spot-based trader anecdotes and studies in the earlier sentiment report do not directly quantify today's TWAP strategy behavior. Their execution/accounting lessons remain relevant.

## Artifact map and reproduction

- `collect.py`: bounded public stream/default metadata collector; instantiates only `AsyncPublicClient`.
- `wire.jsonl`: raw parsed-JSON RTDS messages before SDK normalization, with receive UTC and epoch milliseconds. These are JSON frames, not network packet captures.
- `prices.jsonl`: normalized BTC spot/TWAP events with source timestamps and Decimal strings.
- `metadata.jsonl`: default SDK event snapshots.
- `fresh_metadata.py`, `metadata_fresh.jsonl`, `metadata_tail.jsonl`: fresh-query event collector and raw-response/headers evidence.
- `metadata_variants.jsonl`, `cache_comparison.jsonl`: supplementary paired-query observations.
- `validate_metadata.py`, `metadata_validation.jsonl`: bounded follow-up through normal `get_event(include_chat=False)`, preserving normalized events plus raw HTTP responses and available cache headers.
- `health.jsonl`: collection start, counters, and successful finish.
- `analyze.py`, `analysis.json`: reproducible comparisons for exact boundary timestamps and each neighboring second within ±5 seconds; first observed metadata times; source gaps and timing summary.

Re-run only the analysis (no network): `python3 analyze.py` from this directory. Collector scripts intentionally create output files exclusively to avoid silently overwriting the captured evidence. All scripts and data are scratch artifacts in this chat's `work/anchor-probe/`; the project checkout and its files were not modified.

## Metadata-only follow-up record

The second-boundary comparison was completed on the first pair of requests, at **2026-09-06 15:49:47.929805 UTC** for the prior round and **15:49:48.009652 UTC** for the next round. Both were ordinary official-SDK `get_event(slug=..., include_chat=False)` calls. Both HTTP responses returned `CF-Cache-Status: MISS` and `Cache-Control: public, max-age=300`; raw responses and headers are retained in `metadata_validation.jsonl`. No cache-busting query was used in this follow-up. No wait/retry was needed, and the follow-up process exited successfully.

`analysis.json` now includes these two snapshots and exact Decimal comparisons for each neighboring source second. Its two comparisons targeting timestamp **1788709200000**—prior `finalPrice` and next `priceToBeat`—both mark `equals_wire_display_value=true` at offset **0**, and `false` at offsets **−1** and **+1**.
