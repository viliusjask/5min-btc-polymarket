# Protected exits across a tick refinement — SDK 0.9.0

**Decision:** when the fresh held-book and SDK ticks agree on a supported grid, permit an existing-position protected SELL FAK without requiring equality with the historical entry tick. When those current sources disagree, permit only a supported finer/dividing SDK tick, notably book `0.01` / SDK `0.001`, with compatible protected prices and all non-tick checks intact. The original entry-snapshot equality policy is superseded for collection by the September 8 rule below; funded BUY preparation remains strict.

## Official behavior and the observed disagreement

Polymarket's current market-WebSocket specification describes tick updates as prices approach limits and illustrates old tick `0.01`, new tick `0.001`. Its official agent-skills reference specifies the extreme-price region as price above `0.96` or below `0.04`. Thus refinement near `0.99` is documented behavior. These references do not promise exact update timing, endpoint synchronization, or a tick change on every threshold crossing. [Current WebSocket specification](https://docs.polymarket.com/api-reference/wss/market), [official WebSocket reference](https://github.com/Polymarket/agent-skills/blob/main/websocket.md).

The local diagnosis establishes a later `/clob-markets.mts=0.001` versus `/markets.minimum_tick_size=0.01` disagreement for the same expired condition. It does not establish the raw disagreeing field or change timestamp during the earlier 24 skips. Treat the documented refinement as a plausible explanation, not a reconstructed historical fact. Diagnosis: `/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/work/adapter-integration-metadata-diagnosis.md`.

## Exact signing authority

For `create_market_order(side="SELL", shares=..., min_price=..., order_type="FAK")`, `_prepare_protected_market_order_draft` obtains `MarketInfo` from `ctx.order_metadata.resolve_market`. Its loader fetches **`GET /clob-markets/{condition_id}`**, taking tick from **`mts`**, token membership from `t[*].t`, and negative-risk/fee data from the same response. This protected path does not choose its grid from a saved `Market`, `/markets`, `/book`, or `/tick-size`. [Protected builder](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/market.py), [metadata parser](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/market_data.py).

The cache is normally valid for 600 seconds. The SDK retries metadata once if the protected price fails grid validation, but a coarse price such as `.99` remains valid on both grids and therefore cannot trigger that refresh. **Force `await ctx.order_metadata.fetch_current_market(ctx, token_id=held_token)` immediately before constructing each new order**, under the existing serialization rule. It updates the market cache and checks token membership. Preserve the existing exact-pin/no-deploy constructor; never edit dependency caches or guess a tick from the BTC price. [Pinned cache](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/cache.py).

Grid validation requires `tick <= min_price <= 1-tick`, decimal precision no greater than the tick, and `min_price % tick == 0`. The builder truncates SELL shares to two decimals, then rounds the requested cash upward when protected rounding is needed. Recheck actual constructed integers: `maker_amount > 0`, `maker_amount/1e6 <= confirmed_available_shares`, and `taker_amount/maker_amount >= min_price`. This is a **gross price floor**; fees remain separately checked/accounted. [Validation and supported grids](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/context.py).

## Bounded exit acceptance rule

1. Read a fresh executable held-token book independently of current-round discovery/reference-feed health. Require the correct saved condition, held token and standard/non-negative-risk identity, usable timestamp, and actual eligible bids.
2. Force fresh SDK metadata. Require its exact token set/held-token membership, exchange identity, non-negative-risk result, and existing fee checks to pass. Continue checking minimum order size from raw metadata/book: **SDK `MarketInfo` does not retain `mos` or accepting-order state**, so signing metadata alone cannot replace those checks. A missing accepting field is not a new permission to trade.
3. **Separate historical context from current disagreement.** If the fresh held-book tick and fresh SDK tick agree on an already-supported value, permit SELL regardless of a different saved-entry tick; the saved tick is historical context and does not participate in current-grid acceptance. If the two **current** sources disagree, allow only a supported finer SDK grid: `0 < sdk_tick < book_tick` and `book_tick % sdk_tick == 0`. A current coarse book header may lag while its observed prices remain valid multiples of the finer authoritative grid. Log all three tick values separately.
4. Validate the SELL floor and all bid levels used for the execution estimate against the **fresh SDK grid**, using Decimal arithmetic. Do not lower the selected minimum price to fit the grid or infer absent liquidity. Preserve existing quantity/minimum-size, fee, balance, reservation, signed-hash/write-ahead intent and UNKNOWN-submit reconciliation rules. A finer grid preserves all previously valid coarse prices; it does not itself weaken the price floor.
5. Other disagreements, an unsupported tick, an SDK tick coarser than or nondividing the **current book's** tick, invalid current-grid prices, missing book, stale evidence, or insufficient eligible size remain visible failures under this narrow exception. A jointly confirmed supported coarser tick is allowed when only the historical entry tick differs. Refresh on the next scheduled exit attempt only when no unresolved earlier submit remains. No FAK auto-resubmit is introduced.

Local pure SDK checks (no signing/network/orders) with requested SELL `5.257891` shares:

| Tick | Minimum price | Result |
|---|---|---|
| `.01` | `.99` | maker `5250000`, taker `5197500` |
| `.001` | `.99` | identical maker/taker amounts |
| `.001` | `.995` | maker `5250000`, taker `5223750` |
| `.01` | `.995` | `UserInputError` |

Each successful vector preserves the gross floor; the residual `0.007891` shares remains owned. Add adapter fixtures for agreeing current grids despite a different saved-entry tick (in both directions), successful current book/SDK tick-only refinement, fee/minimum/token mismatch still rejected, current SDK coarser than current book rejected, off-grid price rejected, unchanged entry skip, and a cached `.01` that only the forced fetch replaces. Actual venue acceptance or fills are not proven by pure construction or documentation; a rejection still follows the established rejection/unknown-outcome policy. No funded action or implementation change was performed for this handoff.


## Collection across a compatible refinement — September 8

The original exact-equality policy also removed public research snapshots during refinement.
It is an application restriction: the venue documents a tick field on each endpoint but does
not promise atomic updates across them. The pinned SDK still selects the signing grid from
fresh `/clob-markets.mts`. The public `/book` client reads and preserves the raw header on each
request; this discrepancy is not a local SDK book cache. [CLOB market info](https://docs.polymarket.com/api-reference/markets/get-clob-market-info),
[order-book response](https://docs.polymarket.com/api-reference/market-data/get-order-book).

Collection now uses that freshly validated signing grid and admits a reported flags/book tick
only when equal, or supported and coarser with an exact integer ratio. For example, every
0.01-grid price is also valid on a 0.001 grid. All actual book levels must fit the chosen grid.
A coarser authoritative tick, nondividing grids, unsupported values, changed conditions/tokens,
minimum-size disagreement and invalid fee/accepting state still reject. Original reported
values remain in the observations; accepted refinements are explicitly recorded. This rule
does not infer the tick from a price threshold, invent finer liquidity, or renew timestamps.

Tick events still invalidate cached metadata. Fresh consistent authoritative metadata and
compatible quotes must recover it; a reconnect or older in-flight response cannot clear it.

This change makes public capture and paper evaluation usable under the bounded refinement.
It does not relax the funded broker's BUY preparation check. Such a BUY can still reject a
current book/header disagreement; public capture success is not funded-order validation.
The existing protected SELL rule above is unchanged. The latest actual probe and test evidence
are recorded in [progress](../progress.md).


A new simultaneous anonymous probe on September 7, 23:03:56–23:04:21 UTC corroborated this
transition in 12 samples: `/clob-markets.mts` and both `/tick-size` responses were 0.001,
while `/markets.minimum_tick_size` remained 0.01. Both book headers were initially 0.01
(three samples), then 0.001 (nine samples). Response headers reported `cf-cache-status:
DYNAMIC`; that does not establish the server's internal cache policy. Requests were parallel,
not an atomic exchange snapshot. Raw timestamped bodies/headers remain in the ignored
`work/corroborated-tick-refinement.json`. This confirms the compatibility case, not fills.
