# Historical data availability, checked September 8, 2026

Historical data exists. Continuous self-collection remains valuable because ordinary BTC
prices do not describe the exact Polymarket liquidity, settlement reference and delays
that the application could observe. The useful promise is rapid replay of new strategies
using recorded inputs, with gaps and execution limits preserved.

| Input | Verified source | Coverage and limit |
| --- | --- | --- |
| Binance BTC prices/trades | [Official public archive](https://github.com/binance/binance-public-data) | Free daily/monthly trades, aggregate trades and candles down to1second, with checksums. Spot archive timestamps from2025 use microseconds. BTCUSDT remains an exchange feed, not the settlement reference. |
| Coinbase BTC-USD | [Candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles), [trades](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-trades) | Public candles have1-minute minimum granularity and300/request; intervals can be incomplete. Trade pagination provides executions, not cancelled orders or exact historical queues. |
| Polymarket token prices | [Official prices-history endpoint](https://docs.polymarket.com/api-reference/markets/get-prices-history) | Token/start/end filters, fidelity in integer minutes, default1minute. An anonymous request for the sampled September8 contract returned five roughly minute-spaced observations. This is insufficient for executable bid/ask/depth or intraminute stop simulation. |
| Polymarket executions | [Official trades endpoint](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets) | Market/event/time filters; documented page/offset caps are10,000. Narrow windows are needed for deeper histories. Trades cannot reveal liquidity that was cancelled without executing. |
| Polymarket historical books | [Live market stream](https://docs.polymarket.com/api-reference/wss/market), [PMXT archive v2](https://archive.pmxt.dev/docs/v2-data-overview) | No official historical book replay endpoint was found in the reviewed documentation; this is not proof none will exist. PMXT, a third-party dataset publisher, provides free hourly Parquet book/change/trade/tick events from2026-04-13T19UTC. Its documentation acknowledges coverage gaps and substantial v1 omissions. Test selected tokens before trusting a backfill. |
| Exact settlement reference | [Sample BTC5m rules](https://polymarket.com/event/btc-updown-5m-1788854700), [TWAP documentation](https://docs.polymarket.com/market-data/chainlink-twap) | The sampled current market uses BTC/USD TWAP60s. Retain source/rules per market; do not apply today's rule to older markets or substitute exchange prices. |
| TWAP historical values | [Polymarket RTDS TWAP](https://docs.polymarket.com/market-data/chainlink-twap), [Chainlink historical reports](https://docs.chain.link/data-streams/reference/data-streams-api/interface-api) | Public RTDS explicitly has no snapshot/history/replay after disconnect. Authenticated Chainlink REST offers historical reports, but entitlement and exact feed coverage require separate verification; existing Polymarket credentials do not establish access. |

The sampled Gamma response for `btc-updown-5m-1788854700`, market4325784, named
`https://data.chain.link/streams/btc-usd-twap-60s-streams` as its resolution source.
Direct RTDS wire topics are `crypto_prices_twap_thirty` and `crypto_prices_twap_sixty`;
the averaging window is different from the update frequency. The official documentation
describes signed E18 `full_accuracy_value`, a payload timestamp and `window_s`, plus the
outer publication timestamp. Its calculation details are not public, so our own rolling
average is not an exact replacement. The application's pinned SDK converts the original
E18 value to an exact Decimal. Archiving that normalized value retains its numeric precision,
but not the original wire-field representation; the capture documentation records this limit.

## What the existing application already archives

The source observations and compressed tape are durable, append-only in normal operation,
with no automatic historical deletion. They retain accepted oracle prices, sampled full
Polymarket price-level books, public trades, normalized Binance aggregate trades and
depth20@100ms, normalized market settings, official reference labels, timestamps and gaps.
The flow feed's depth is the top20levels, not full Binance depth. Polymarket snapshots are
not application-truncated, but intermediate book updates previously disappeared between
roughly500ms recordings. The observations journal retains accepted oracle ticks even when
the combined snapshot is invalid; the old replay tape did not always retain those ticks.

The approved extension keeps those independent inputs and intermediate messages in the
same archive, adds producer/rule provenance and exposes selected historical replay. It
does not reinterpret old warnings or certify hypothetical execution. Aggregated books do
not supply individual queue positions; our simulated orders do not create real market impact.
Archive gaps while the PC sleeps or disconnects remain unknown. Committed data can survive
process failure; uncommitted message buffers and disk failure require separate treatment.

No external historical dataset was imported, no paid source was enabled and no credentials
were requested during this check. Backfills should be separate attributed inputs with
coverage checks, never inserted into older frames as though originally observed locally.
