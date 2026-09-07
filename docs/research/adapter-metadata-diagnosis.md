# Adapter integration metadata disagreement — 2026-09-06

**The 24 historical skips are confirmed, but their exact disagreeing raw field is not recoverable from the log.** Both books agreed on tick `0.01`, minimum `5` and the correct condition throughout. A single later public follow-up directly confirmed `/markets.minimum_tick_size = 0.01` versus `/clob-markets.mts = 0.001` for that same expired contract. This proves that the endpoints can genuinely disagree; it does **not** establish that tick size caused the earlier skips. No parser/comparison bug is demonstrated. The definite adapter defect here is missing diagnostic values on rejected metadata.

## Frozen evidence and duration

Analyzed the first **8,246,985 bytes / 3,986 complete lines** of `work/adapter-integration-probe.jsonl`, ending with a received TWAP event at **17:14:41.494 UTC**. SHA-256 of precisely that prefix:
`0a0bbd34c84970619f76e61152cbf326ed82ecd7b964e41afa284dd1cb678084`.
The live file continues to append; the prefix length/hash make this diagnosis reproducible.

Affected market: `btc-updown-5m-1788714300`, the **17:05–17:10 UTC** round.
Condition: `0xbba438ae06f8f18c14300630fc77e83d71a00fbf618e7e20226c609d027c3fdd`.

| Observation | UTC | Probe log line |
|---|---|---:|
| Last validated old-round metadata and snapshot | 17:09:32.189000 | 1245–1246 |
| First `TRADING_METADATA_CHANGED` outcome | 17:09:33.309093 | 1254 |
| Last of 24 such outcomes | 17:09:59.201462 | 1443 |
| First validated **next-round** snapshot | 17:10:00.398000 | 1452–1453 |

The first-to-last rejected-call span is **25.892369 seconds**; first rejection to first successful next-round snapshot is **27.088907 seconds**. Exact change onset lies between the last successful comparison and the first failure. Recovery is a switch to `btc-updown-5m-1788714600` / condition `0xd76a7274bf0f49ebe4a78bcd6a17375185c8b3545ff4c1c3ef2ae0561b3fba49`, **not evidence that the old contract's inputs reconciled**.

Immediately before failure, line 1245 records agreement: raw `/markets` tick `0.01`, minimum `5`; raw `/clob-markets` `mts=0.01`, `mos=5`, `fd={r:0.07,e:1,to:true}`. All **48 book observations** associated with the 24 failed calls (lines 1251–1441, book records only) retain tick `0.01`, minimum `5` and that same condition. Their source ages at receipt are **923–1,043 ms**. Example first pair: lines 1251–1252; last pair: lines 1440–1441. Both outcomes are already at the extreme end of the book: Up has no bids and best ask `0.01`; Down has best bid `0.99` and no asks. Gamma's received payloads also retain tick `0.01`/minimum `5` (lines 1249 and 1438), but Gamma is not the adapter's mutable trading authority.

## What can and cannot be established

The adapter raises this code either while comparing current raw CLOB tick/minimum fields (including an unsupported tick), or while comparing each book's condition/tick/minimum against that metadata (`src/btc5m/market_data.py:586–591`, `729–735`). A fee-schema, token mapping, active-state or stale-data rejection has a different code. The observed book conditions match the discovered contract, so the historical discrepancy is narrowed to **tick/minimum metadata, including the accepted-tick check**, not a wrong book identity.

However, raw CLOB payloads are emitted only in the later `discovery` / `stage=validated` record (`src/btc5m/market_data.py:630–638`). Every rejected call exits before that record. Its earlier `stage=received` record contains raw Gamma only. Therefore the historical `/markets` and `/clob-markets` values—and which of the two comparison locations rejected—are absent. Do not silently carry line 1245's previous valid fields forward into the failing calls.

One bounded follow-up issued four anonymous GETs for the **same expired condition**, after the historical window:

| Read | Received UTC | HTTP | Actual result |
|---|---|---:|---|
| `/clob-markets/{condition}` | 17:15:48.731332 | 200 | `mts=0.001`, `mos=5`, fee `r=0.07,e=1,to=true`; `ao` absent |
| `/markets/{condition}` | 17:15:48.811874 | 200 | `minimum_tick_size=0.01`, `minimum_order_size=5`, `accepting_orders=true` |
| Both `/book?token_id=...` reads | 17:15:48.752659 / .763390 | 404 | Books no longer available |

Complete responses/URLs/headers are saved in `work/adapter-integration-metadata-followup.json` (tick values at lines **20** and **97**; SHA-256 `44676bc1dc91df7364ed0f82defedb55264321c6992c7e7011d1fa87c979ff16`). Both metadata responses say `CF-Cache-Status: DYNAMIC`; this does not identify whether internal caching, publication lag, endpoint semantics or another backend cause explains their disagreement. Neither the `0.001` tick nor the absent `ao` can be backdated to 17:09. The expired-book 404s are follow-up results, not failures observed during the original probe.

## Smallest future diagnostic change — recommendation only

Keep the existing validation and safe skip. Immediately before either `TRADING_METADATA_CHANGED` raise, emit **one additional public observation per differing field** with:

- existing kind/time conventions, slug and condition;
- public field name on each side and endpoint/token identity;
- the normalized `expected` and `actual` values used in that comparison.

For example, a future observed tick mismatch could record `field="tick_size"`, `expected_field="mts"`, `expected_endpoint="/clob-markets/{condition}"`, `expected="0.001"`, `actual_field="minimum_tick_size"`, `actual_endpoint="/markets/{condition}"`, `actual="0.01"`. This is an illustrative schema using the **later follow-up** values, not a reconstruction of the missing historical record. Book mismatches should similarly distinguish `condition_id`, `tick_size` and `min_order_size`; an unsupported tick should log its actual value and the accepted set. No new data source, second feed, full-payload logging or relaxed check is required.

These skips occurred inside the last 27 seconds, already outside the new-entry windows, but overlapped the configured 20-second exit deadline. The independent held-book path and caller scheduling requirement remain important. No source/test change, suite rerun, credential/account access, funded action or probe interruption was performed. Only this diagnosis and its public follow-up evidence were written.
