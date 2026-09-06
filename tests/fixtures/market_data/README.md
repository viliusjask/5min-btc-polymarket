# Anonymous public market-data fixtures

Source: official Polymarket public endpoints and the pinned
`polymarket-client==0.9.0` SDK. No authentication, account records, orders or
wallet initialization were involved.

## Captured wire payloads

The following JSON files are complete public HTTP payloads, pretty-printed without
removing fields. Collected 2026-09-06 at approximately **16:24:01 UTC** for
`btc-updown-5m-1788711600` (16:20–16:25 UTC):

- `gamma-event.json`: `GET https://gamma-api.polymarket.com/events/slug/btc-updown-5m-1788711600?include_chat=false`.
- `clob-market.json`: `GET https://clob.polymarket.com/markets/0x98bb13bcb38388772476b9ded97ae81986a12173e66b5f3ab8924e6f74bdf34d`.
- `clob-fees.json`: `GET https://clob.polymarket.com/clob-markets/0x98bb13bcb38388772476b9ded97ae81986a12173e66b5f3ab8924e6f74bdf34d`.
- `book-up.json`, `book-down.json`: `GET https://clob.polymarket.com/book?token_id=<asset_id>` using each file's complete `asset_id`. Original source book times are retained in these files.

`gamma-event.json` naturally has no `eventMetadata`; its Gamma `startDate` is a
listing date on the prior day. Its `eventStartTime` and event `startTime` are the
actual five-minute opening. CLOB flags and fee parameters are independent live
responses; Gamma's cached fee numbers are not used as trading authority.

`boundary-events.json` contains six complete SDK-normalized BTC events from the
anonymous probe at source times **15:39:59, 15:40:00 and 15:40:01 UTC** (spot and
TWAP60). Origin: the project's ignored
`work/anchor-evidence/boundary-events.json`, copied from the root probe described
in `docs/research/anchor-probe.md`. SDK subscriptions were
`CryptoPricesSpec(topic="prices.crypto.chainlink", symbols=("btc/usd",))` and
`CryptoPricesChainlinkTwapSpec(window_seconds=60, symbols=("btc/usd",))` over
`wss://ws-live-data.polymarket.com`. These are normalized events, not the raw RTDS
wire envelope; the SDK retains full-accuracy TWAP Decimal values.

`official-after-boundary.json` is the complete raw Gamma response from the
same probe's normal SDK `get_event(slug="btc-updown-5m-1788709200",
include_chat=False)` follow-up, received **2026-09-06 15:49:48.009652 UTC**.
Origin: the second row's `http_responses[0].raw` in the ignored
`work/anchor-evidence/metadata_validation.jsonl`. Its published
`priceToBeat=79697.53425227966` independently verifies the exact source-time
TWAP `79697.534252279656349696`, while the neighboring seconds differ materially.

## Explicit synthetic replay transformations

The tests load these complete external payloads into real SDK models and the
adapter's real parsers/state. Only transport and wall/monotonic clocks are
substituted. These transformations are scenario inputs, not additional observed
market facts:

- Shift the three source timestamps from 15:40 to the captured 16:20 market,
  retaining every price and its offset from the boundary. Change book timestamps
  to the replay clock while keeping the full original book payload.
- Reverse both outcomes and token IDs together to test opposite token ordering;
  duplicate a label to test ambiguous mapping.
- Omit the exact TWAP boundary; supply missing, matching, rounded, conflicting,
  or stale-null official metadata; transplant the independently captured official
  metadata only where stated in the test.
- Mutate listing/start/end/slug, rule text, source URL, acceptance/active/risk
  flags and fee schema to test explicit rejection. Remove asks, change timestamp
  units, or introduce stale/future timestamps and wrong token IDs.
- Update authoritative fee/tick/minimum together and separately to distinguish
  a valid current revision from inconsistent reads.
- Supply synthetic 30-minute spot histories with a 65-second source gap,
  unexpected subsecond bursts, source disconnect/resume and delayed labels to
  exercise history bounds, gap preservation, retry/retirement and unavailable
  outcomes. These are not backtest prices, outcomes or PnL.

The test names and immediate transformations document each variation rather than
presenting modified payloads as live captures. `SHA256SUMS` identifies the exact
committed JSON fixture bytes.
