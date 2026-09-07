# Independent execution review of standalone design and plan

Reviewed 2026-09-06: `/home/vilius/projects/5min-btc-polymarket/.worktrees/standalone/docs/design.md` and `docs/plans/standalone.md`, plus official `polymarket-client-v0.9.0` source. No repository changes, wallet interactions or funded tests were made.

**Spec viability: FAIL as an execution-ready specification until findings 1–4 are resolved. The architecture is feasible.** No paid data service or large framework is required. Task1's pure core can proceed after the entry-quantity contract below is made explicit; Task2 needs an exit-quote interface. The planned Task3 brief may resolve the remaining execution details before its dispatch. Funded validation is a later evidence stage, not a prerequisite for writing implementation.

## 1. [P1] Public authenticated client construction can mutate wallet and API credentials

Location: `docs/design.md:109`, `docs/plans/standalone.md:173`.

Forbidding `place_*` does not make account doctor/reconcile read-only. In SDK0.9.0, `AsyncSecureClient.create()` calls `_ensure_wallet_ready()`, which can deploy an undeployed deposit wallet. Also, `_bootstrap_credentials()` calls `create_or_derive_api_key()` when supplied credentials fail its validation. A public-factory call with an explicit funder and credentials can therefore still perform a mutation before preflight reports a problem.

**Least invasive correction:** isolate a small, version-checked adapter helper around:

```python
await AsyncSecureClient._create(
    private_key=private_key,
    wallet=explicit_funder,
    credentials=existing_credentials,
    validate_credentials=False,
    api_key=None,
)
```

Require all existing credentials and the explicit wallet before calling it. Never allow `None` fallbacks. With those arguments, the inspected method locally resolves/classifies the account and constructs transports; it skips both public-factory wallet deployment and API-key creation/repair. Then validate credentials through an explicit authenticated **GET**, e.g. balance/allowance or account orders; 401/403 must remain an error, not a fallback to key creation. Keep this one private SDK entrypoint in the broker adapter, guard the exact package version and document why it exists. Do not copy SDK implementation or patch site-packages.

Validate chain 137 and recognized signer/funder relationship. For a non-EOA funder, a read-only RPC `eth_getCode` check should require deployed code. An EOA whose funder equals signer follows its supported EOA path. Unsupported wallet relationships fail closed. RPC precheck before the **public** constructor alone is weaker: its relayer deployment view can disagree, and credential validation can still create keys. The private no-deploy/no-key-refresh constructor is the clearer invariant.

**Required fixture checks:** deployed funder, undeployed funder, wrong signer/funder, missing/invalid credentials. Record transport calls and prove doctor/account and read-only reconcile make no relayer mutation, CLOB auth-key POST, approval, or order POST. JSON-RPC uses HTTP POST for reads, so allowlist RPC method names rather than asserting “no HTTP POST anywhere.”

Source: [pinned async client `_create`, `create`, `_bootstrap_credentials`, `_ensure_wallet_ready`](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/clients/async_secure.py).

## 2. [P1] Fresh feed metadata does not refresh the SDK's signing cache

Location: `docs/design.md:34`, `docs/plans/standalone.md:140`, `:174`.

The SDK's separate order-metadata cache uses `_METADATA_TTL_S = 10 * 60`, longer than a complete round. A fresh public snapshot containing changed fee/tick data does not update the secure client's order-building cache. `create_market_order(max_spend=...)` can calculate its signed amounts using old fees, and accepted old tick grids need not trigger its error-driven refresh.

**Correction:** keep one async client but serialize order preparations. Isolate a second narrowly scoped pinned SDK helper that calls:

```python
fresh = await client._ctx.order_metadata.fetch_current_market(
    client._ctx, token_id=asset_id
)
```

This is the SDK's implemented forced-refresh method; it replaces cached market data before `create_market_order` consumes it. Compare its tick, fee parameters, asset mapping and negative-risk flag with the decision's approved inputs and reservation. Changed entry inputs cause re-evaluation or a visible skip, never implicit extra spending. Refresh full current CLOB metadata/book for minimum size and acceptance too: the SDK's `MarketInfo` object does not expose all those fields. Keep post-sign verification of signed principal, price and reserved fee bound.

Recreating a no-deploy secure client for each preparation also gives a cold cache, but adds avoidable client/transport churn; the forced refresh is the smaller operational change. Do not mutate the cache dictionaries or monkeypatch SDK methods.

**Required checks:** seed the secure cache with old fee/tick values, advance venue fixtures without advancing ten minutes, and prove forced fetch occurs. Changed fees that invalidate the reservation must result in no POST. Updated tick values must be used for directionally safe price rounding. Locking prevents concurrent preparations from invalidating the check/sign sequence.

Source: [pinned metadata cache](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/cache.py), [protected order construction](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/market.py).

## 3. [P1] The public-data interface cannot independently price a held position

Location: `docs/plans/standalone.md:131–146`; `docs/design.md:89–101`.

The only planned public method returns a complete **current-round** `Snapshot`, requiring current spot, TWAP and history plus two current books. The exit requirement is different: it needs the **held token's** fresh bid depth even if a reference stream is down, warm-up is invalid, discovery switches to the next round, or the held market has expired. Tying exits to `snapshot()`/`DataUnavailable` can suppress stop/time exits precisely during a feed failure.

**Correction:** add a bounded `quote_book(token_id)` or `books_for_market(persisted_market_identity)` method independent of strategy warm-up, anchor and current-round selection. Persist held-market identity and end time in the ledger. The engine's position-management path must run even when new-entry snapshot construction fails. An unavailable held-token book blocks only the price-protected submission; it must not block account reconciliation, time-exit state, risk reservation, reporting or shutdown handling.

**Required checks:** buy round A, advance discovery to round B, and prove all exits still target A. Disconnect spot/TWAP while held-token bids remain available and prove a due time exit proceeds. When bids are unavailable, preserve inventory and continue reconciliation without inventing an execution price.

## 4. [P1] `Decision.shares` has no defined mapping to the SDK's cash-denominated BUY

Location: `docs/plans/standalone.md:89–99`, `:127`, `:174`; `docs/design.md:81–87`.

The strategy sizes/depth-checks `Decision.shares`, but `create_market_order(side="BUY", amount=...)` takes **cash principal**, not shares. If an implementer maps it to `shares * price_limit`, a better market price can buy more shares than were analyzed. If they instead use ask VWAP, the final signed minimum shares at a wider price limit can be below the market minimum. FOK means full eligible order execution; it is not automatically “exactly Decision.shares.” Estimated `max_spend` can also resize signed principal.

**Correction before freezing Task1 types:** explicitly choose spend-based entry. Add `buy_principal`, `max_total_reserved`, and either `expected_shares` plus `minimum_receive_shares`, or clearly rename/document `shares` as an estimate. Strategy depth calculation must consume the same principal amount that the SDK will sign. Broker derives/verifies minimum shares and principal from signed integer maker/taker amounts, respects minimum size, and accepts actual confirmed share quantity as authoritative. Entry cost basis and exit sizes come from receipts, not the decision estimate. Alternatively choose exact-share semantics with a verified supported order construction, but do not leave the conversion implicit.

**Required checks:** ask depth improves below max_price, fee-adjusted principal is rounded, and minimum-share validation occurs after SDK rounding. Assert the submitted cash/reservation matches analyzed inputs and that receipts with a different actual share count reconcile correctly.

Source: [SDK BUY amount and SELL shares overloads](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/clients/async_secure.py), [actual maker/taker amount computation](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/market.py).

## 5. [P2] Source/cache provenance and clock domains need explicit representation

Location: `docs/design.md:38–49`, `:72–77`; `docs/plans/standalone.md:40–47`, `:60–77`.

The latest probe finding—default `get_event` returning older metadata while `include_chat=False` returns newer data—means local receipt time cannot prove origin freshness. Changing a query option is a different cache key, not a general cache-invalidation guarantee. Current Market has no discovery fetch time/provenance or reference verification state; PricePoint/Book have only epoch source/receive times, leaving no monotonic time for connection deadlines.

**Correction:** document `get_event(slug=..., include_chat=False)` as the observed working route, with a bounded retry schedule for missing same-slot metadata. Do not alternate arbitrary query keys to manufacture freshness. Treat absent priceToBeat as unavailable; once a valid same-slot anchor is seen, persist it with endpoint/query provenance and fetch time. A later different value becomes a visible conflict that pauses entries pending reconciliation; an older/null response must not erase the previously verified anchor. Current mutable acceptance/tick/fee values come from current CLOB reads, not Gamma cache age. If response Age/Date headers are available, record them as additional evidence, not as the anchor timestamp.

Add a typed reference status/provenance (official metadata vs verified exact boundary vs missing/conflict), observation timestamp when known, and monotonic receipt/last-seen state at the data adapter boundary. Keep wall-clock UTC for reports and market boundaries. Validate source timestamps against corrected exchange/host time; use monotonic elapsed time for heartbeat/timeouts. A `kind: Literal["spot", "twap60"]` and a reference-status enum avoid accepting unknown strings silently. Market state booleans should be required from the parser rather than defaulting active/accepting to True on missing fields.

**Required checks:** cached null → official anchor → cached null, official conflicting anchor, unsupported schema, and wall-clock jump with unchanged monotonic timer. The independent boundary/latency probe remains the evidence needed to enable captured anchors; it need not block implementing the default official-metadata-only mode.

## 6. [P2] Specify loss-budget semantics and confirmed-trade versus receipt finality in Task3 brief

Location: `docs/design.md:81–87`, `:121–139`; `docs/plans/standalone.md:155–177`.

The design has the right categories, but daily/session loss is not defined as net realized loss, gross losing-trade loss, or realized loss plus worst-case outstanding capital. The reserve wording can be implemented with either double counting or an overshoot: after an $8 realized loss, a new $5 position can take total loss beyond the stated $10 cap. Cash already spent on an open position must remain represented as risk even after its order reservation is consumed. Day rollover and restart must not erase exposure.

**Correction:** choose a precise persisted budget formula and timezone/day boundary. Recommended experimental gate: finalized net loss plus conservative remaining position cost at risk plus unresolved opening reserves must fit the remaining daily/session budget, with each exposure counted once. Transfers/claims/external differences do not become strategy profit. If the intended cap instead only stops *subsequent* entries after a realized threshold is breached, say so and expose the possible one-trade overshoot.

Also specify that receipt `status=1` is not finality by itself. Finalize only when associated account trade status is CONFIRMED and the canonical successful receipt is available, or under an explicitly documented independently verified finality policy. A normal transaction contains other traders' logs: **ignore unrelated logs**, reject malformed/mismatched logs claiming the bot's tracked identity, and never reject an otherwise valid batched receipt simply because unrelated logs are present. Mixed FAILED/CONFIRMED fills remain per-fill accounting, not whole-order success.

**Required checks:** $8 loss/$5 proposed risk/$10 cap, a position carried across midnight/restart, matched-but-unsettled buy, receipt mined while trade remains RETRYING, mixed outcomes, and a valid batched receipt with unrelated orders.

## Explicitly live-unverified after development

The code can be implemented and verified anonymously/synthetically now. Later funded evidence still must establish correct signer/funder behavior for the selected wallet, available pUSD/CTF permissions, acknowledged order hash agreement, min-size/rounding acceptance, actual FOK/FAK matching, per-fill finality and fee/balance reconciliation. The exact boundary-policy and cache-latency evidence is separately being gathered. None of these pending measurements justify blocking implementation or claiming it already passed a live round trip.

Additional acceptance checks requested by root: test that any installed SDK version other than exact `0.9.0` fails before invoking private constructor/cache hooks; missing package and changed private signatures fail clearly. The read-only RPC adapter must allowlist only the necessary methods (`eth_chainId`, `eth_getCode`, `eth_call`, `eth_getTransactionReceipt`, and any explicitly implemented block/finality read), reject `eth_sendTransaction`/`eth_sendRawTransaction` and arbitrary caller-supplied RPC methods, and verify configured chain/address inputs. Account doctor/reconcile fixtures must fail if relayer POST, credential creation, approval, cancellation or order posting is attempted.
