# Two large reversal gains: recorded evidence and remaining uncertainty

2026-09-07. Read-only audit of the existing paper journals and public observations.
No orders, cash, flags, registrations or strategy parameters were changed.

## Finding

The two largest `reversal-60-.5` gains total **USD195.147396**. That is **93.67%** of
its USD208.3285917 realized profit in the saved report at 15:04:20.870 UTC (frame32801).
Both rounds are flagged uncertain. The same two market events also benefited
`reversal-60-1`; those are overlapping evidence, not two independent confirmations.

The four entry/exit prices exist in the captured books, with enough displayed size for
the entire simulated order. Nearby recorded public trades in the same token also have
each of those prices. Independent Decimal arithmetic reproduces principal, fees and net
profit. This audit found no token swap, insufficient displayed size, or accounting error
in these four fills. It **does not establish actual execution or a profitable strategy**.

| Round start UTC | Outcome | Simulated purchase | Simulated sale | Both fees | Net profit |
|---|---|---|---|---|---|
| 07:30 | Down | 93 shares × $0.05 = $4.65 | 93 × $0.99 = $92.07 | $0.373674 | **+$87.046326** |
| 11:55 | Up | 115.5 shares × $0.04 = $4.62 | 115.5 × $0.98 = $113.19 | $0.468930 | **+$108.101070** |

All times in this document are UTC on September7. These are simulated buys/sales,
not settlement winnings or venue-confirmed fills. Profit already deducts entry and exit
fees; do not subtract the dashboard's fee total a second time.

## Checks against the original recorded input

| Fill time | Tape frame | Available size at fill price | Book source age | Local receipt age |
|---|---:|---:|---:|---:|
| 07:32:34.539 buy Down | 346 | 344.46 shares at $0.05 | 670ms | 108ms |
| 07:33:18.447 sell Down | 380 | 3,405.32 at $0.99 | 679ms | 55ms |
| 11:57:58.738 buy Up | 19311 | 151.08 at $0.04 | 946ms | 64ms |
| 11:59:36.885 sell Up | 19419 | 205.59 at $0.98 | 871ms | 55ms |

For each fill the audit checked:

- SHA256 integrity of its compressed frame and every frame between entry and exit.
- Exact round, condition and token identity against its persisted order.
- Book source/receipt times after the order's 250ms activation delay and within the
  configured 5-second freshness bound. No later input was used for this check.
- Actual top-level depth, price protection, venue minimum size and price increment.
  Better purchase prices legitimately buy more shares for the same protected cash amount.
- Equal bought/sold quantities, signed minimum receive shares, cash budget and the recorded
  market fee formula: `quantity × fee_rate × (price × (1 − price))^fee_exponent`.
  Each captured market records fee_rate0.07 and exponent1; these are historical parameters.
- Same-token public trade reports at the same price within two seconds of each fill.
  The counts were1,19,5,3 respectively. Those reports corroborate prices, **not** the
  bot's counterfactual fill or available queue priority. Counts are not deduplicated
  executions and no blockchain receipt audit was performed.

For traceability, the rounds are `btc-updown-5m-1788766200` and
`btc-updown-5m-1788782100`; variant `dd1e0cd9d6e4773780ca` under `lab/explore`.
The four intent ids are `a94dadb2258e4bd297d2e0fc5700ec1f`,
`3a99512f4712494581468a9270342071`, `3d8ea8d33fd44aa6b8617e5b531ca3be`,
and `e4263f058c9d4a6ca2c2d0d4fdd54e47`. The ignored local reconstruction and detailed
results are `work/audit_reversal.py` and `work/reversal-audit.json` in this worktree.

## Why both gains remain excluded from unflagged comparisons

**07:30 round:** 35 frames between purchase and sale,34 with snapshots. The recorder
interval from07:33:01.208 to07:33:12.575 lasted **11.367seconds**; that next frame also
lacked a snapshot. Valid input returned at07:33:17.494. The last bid before the interruption
was7¢ and the first after it was99¢. The independent public journal records HTTP/book
failures during that interval. It does not recover the bot's missing decision sequence.

**11:55 round:** 109 frames between purchase and sale,93 with snapshots. There was
**no recorder interval above the configured5-second limit**. Instead,16 successive frames
had no valid snapshot, from11:58:52.359 through11:59:10.036. Valid input returned at
11:59:10.782; the adjacent valid snapshots were20.370seconds apart. The public journal
records an HTTP failure late in that interval. Because the old current-snapshot path
discarded its precise failure reason, this cannot prove why each of the16 samples failed.
Earlier in the same holding period, eight otherwise valid snapshots had no exit bids.

The registered profit trigger is98¢, not an entry-relative take-profit. The registered
8¢ absolute stop is below zero for these4–5¢ entries, so it cannot protect those purchases.
This is an experimental policy limitation, not evidence that the recorded stop malfunctioned.
The missing intervals could conceal an earlier profit-trigger crossing or other execution
conditions. Endpoint depth and nearby public trades cannot establish the full execution path.

Excluding a flagged round is not a declaration that its profit was impossible. Conversely,
a round without flags is not certified realistic. Missing inputs can depend on volatility,
so the unflagged subset can itself be biased. Keep all results and quality flags together;
do not select a profitable subset or erase inconvenient samples.

## Reporting and instrumentation change

The dashboard now always displays all realized profit, completed unflagged profit and
their exact difference. That **excluded remainder includes flagged rounds and realized
amounts on incomplete rounds**. It is not unrealized profit, and is not necessarily all
profit from completed flagged rounds. Completed counts, incomplete counts and held cost
remain visible. A dash means no supporting observations rather than zero measured profit.

For the15:04 snapshot: all profit+$208.328592 = unflagged completed−$2.523792 + excluded
remainder+$210.852384. Only4 of26 completed rounds were unflagged; one further round was
incomplete. Subsequent live reports will differ as positions close.

New captures store the **first failed snapshot check** and source context. Durable counters
separate rejected snapshots, consecutive rejected spans and intervals between recorder
samples longer than the configured limit. Counters begin at deployment, not at the start
of the old study. Historical unknown causes and exclusion flags are retained unchanged.
The displayed percentage is sample availability, not elapsed-time uptime or missed trades.

A180-second anonymous probe of the new diagnostics produced360checks:341 valid snapshots,
5 initial missing-metadata checks,5 stale-spot checks,3 silent-spot checks,5 expired-metadata
checks and1 normal round rollover. This demonstrates useful diagnosis; it is not a
performance benchmark or a fix for all upstream interruptions.

Both registered study workers remain on their original implementation. Only the collector
and read-only dashboard receive this observability update. A later investigation can use
these exact causes to target avoidable capture failures without weakening validity rules.
