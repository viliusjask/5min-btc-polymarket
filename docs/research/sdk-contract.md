# Task3 pinned SDK adapter dossier

Verified 2026-09-06 against installed `polymarket-client==0.9.0` in the standalone worktree and official release `polymarket-client-v0.9.0` (`8b4fa35045dfba48014dc3067004fb641ca123cf`). Only synthetic values and anonymous reads were used. No credentials inspected, orders posted, wallet deployed, allowances changed, or project files edited.

## Supported contract and imports

Scope this adapter to Polygon 137, ordinary non-negative-risk CTF market tokens, CLOB V2 signing domain version 2. Reject future position-ID/V3 assets, negative-risk instruments, and unrecognized wallet relationships; do not infer the signing protocol from the market-info field `v:"v1"`.

Verified imports:

```python
from polymarket import AsyncPublicClient, AsyncSecureClient
from polymarket.models.clob import ApiKeyCreds, AssetType
from polymarket.models.clob.orders import SignedOrder
from polymarket.models.clob.account import BalanceAllowance, OpenOrder, ClobTrade
from polymarket.models.clob.order_response import AcceptedOrder, RejectedOrder
from polymarket.models.clob.cancel import CancelOrdersResponse
from polymarket.pagination import AsyncPaginator, Page
from polymarket.errors import (
    RequestRejectedError, RateLimitError, TransportError,
    UnexpectedResponseError, UserInputError, SigningError,
)
from polymarket.environments import PRODUCTION
# Private, pinned adapter boundary only:
from polymarket._internal.environment import get_environment_config
```

`get_environment_config` is NOT exported by `polymarket.environments`. `ApiKeyCreds(key=..., secret=..., passphrase=...)` is valid; this is not the older package's `ApiCreds(api_key=...)`. Model field validation aliases also accept wire `apiKey`. `SignedOrder` and `Page` are frozen dataclasses, **not Pydantic models**: no `model_dump`/`model_validate`. Other response models listed above are Pydantic. Serialize the signed dataclass with a purpose-built safe persistence serializer/`dataclasses.asdict`, never an ordinary log serializer.

Current production environment:

| Role | Value |
|---|---|
| CLOB | `https://clob.polymarket.com` |
| Public Polygon RPC | `https://polygon.drpc.org` |
| Standard CTF V2 exchange | `0xE111180000d2663C0091e4f400237545B87B996B` |
| CTF ERC1155 | `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` |
| Trading collateral pUSD | `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` |
| Negative-risk exchange — reject for this adapter | `0xe2222d279d744050d28e00520010520000310F59` |

Read-only onchain checks performed: chainId=`0x89`; pUSD `decimals()`=6; exchange `getCollateral()`=the pUSD address above. **CTF ERC1155 has no standard decimals method.** Treat outcome balances as six-decimal collateral-derived share units for this explicitly supported protocol; do not call ERC1155 `decimals()` and expect success.

Sources: [pinned environments](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/environments.py), [pinned client](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/clients/async_secure.py), [official contract addresses](https://docs.polymarket.com/resources/contracts).

## Exact no-mutation constructor and metadata refresh

```python
client = await AsyncSecureClient._create(
    private_key=explicit_private_key,
    wallet=explicit_funder,
    credentials=ApiKeyCreds(key=existing_key, secret=existing_secret,
                            passphrase=existing_passphrase),
    validate_credentials=False,
    api_key=None,
)
```

Require all arguments before this call, guard installed version exactly 0.9.0, and isolate the private entrypoint. With explicit wallet and existing credentials plus `validate_credentials=False`, `_create` locally classifies signer/wallet and constructs transports; it skips wallet readiness/deployment and credential creation/repair. A synthetic EOA invocation under a patched `httpx.AsyncClient.send` that rejected **every** network operation completed successfully and closed (`NO_NETWORK_CONSTRUCTOR=PASS EOA`). This is an actual constructor check, not a copied SDK implementation.

Then use explicit authenticated GETs to validate account access; invalid credentials remain a visible error. Public `create()` must not be substituted: it invokes `_ensure_wallet_ready()` and can deploy. Even private `_create(validate_credentials=True)` can replace invalid credentials via `create_or_derive_api_key`. Omitted wallet can trigger automatic wallet discovery. Preflight RPC chain and deployed-code checks do not make these fallback paths safe.

Before EVERY order preparation, under the broker preparation lock:

```python
ctx = client._ctx
fresh = await ctx.order_metadata.fetch_current_market(ctx, token_id=asset_id)
```

Verified `fresh` type is internal `MarketInfo` with `fee_info.rate:Decimal`, `fee_info.exponent:Decimal`, `neg_risk:bool`, `tick_size:Decimal`, `token_ids:frozenset[ClobAssetId]` and alias `asset_ids`. This forced fetch replaces the SDK's ten-minute cache. It does not include min size/acceptance: obtain those from current CLOB metadata/book. Compare metadata with the approved decision/reservation before signing. Changed entry inputs require re-evaluation/skip, not quiet resizing.

The only necessary private hooks are no-deploy `_create`, environment configuration, and forced cache refresh, each tested against the exact pin. No dependency patching, cache-dictionary mutation, or copied SDK client is needed. [Constructor implementation](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/clients/async_secure.py), [cache implementation](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/cache.py).

## Order preparation and exact units

Verified combined signature:

```python
await client.create_market_order(
    asset_id: str, side: Literal['BUY', 'SELL'],
    amount: Decimal | None = None, shares: Decimal | None = None,
    max_spend: Decimal | None = None, max_price: Decimal | None = None,
    min_price: Decimal | None = None, order_type: Literal['FAK','FOK']='FAK',
    builder_code: str | None = None,
) -> SignedOrder
await client.post_order(signed_order: SignedOrder) -> AcceptedOrder | RejectedOrder
```

The annotation above narrows accepted numeric inputs deliberately; SDK also accepts int/float/str. BUY uses `amount` in human cash units, `max_price` and optionally estimated all-in `max_spend`; never pass `shares`/`min_price`. SELL uses human `shares` and `min_price`; never pass `amount`/`max_price`/`max_spend`. Initial entry BUY FOK; exits SELL FAK. Omit builder_code to avoid third-party attribution/fee configuration. `create_market_order` signs but does not post.

Protected prices must already lie exactly on the live tick grid within `[tick_size, 1-tick_size]`. BUY upper-price rounding must not increase the authorized limit; SELL lower-price rounding must not lower the authorized floor. The SDK validates, rather than silently fixing, an off-grid explicit protected price.

**Critical rounding:** raw maker amount is floored to **two decimal places** for both cash BUY and quantity SELL. Taker amount is computed from the protected price, then rounded upward if needed to preserve price protection, using tick-dependent amount precision. Finally both are encoded to six-decimal integers. Verified direct SDK helper vectors:

| side, input amount/shares, price, tick | signed maker_amount | signed taker_amount |
|---|---:|---:|
| BUY 3.50, .70, .01 | 3500000 | 5000000 |
| BUY 4.90, .92, .01 | 4900000 | 5326100 |
| SELL 3.257891, .73, .01 | 3250000 | 2372500 |
| SELL 3.257891, .735, .001 | 3250000 | 2388750 |

Tick `(price decimals, amount decimals)` values: `.1:(1,3)`, `.01:(2,4)`, `.005:(3,5)`, `.0025:(4,6)`, `.001:(3,5)`, `.0001:(4,6)`; size decimals always 2. Verify minimum receive/market min size **after** signing-rounding. Do not repeatedly create residual exits that round to zero or are below accepted minimum size; persist explicit dust/unexitable inventory. Actual fill quantity can exceed the BUY minimum at improved prices.

`max_spend` is estimated fee-adjusted spend: the SDK may reduce principal using cached/fresh fee parameters, then round. It is NOT a final all-in onchain cap. Independently verify signed maker principal plus reserved fee allowance fits the approved reservation. Full current metadata and reserve checks must agree before POST.

`SignedOrder` exact fields:

```text
builder:str, expiration:int, maker:str, maker_amount:int, metadata:str,
order_type:'GTC'|'GTD'|'FAK'|'FOK', salt:int, side:'BUY'|'SELL',
signature:str, signature_type:int, signer:str, taker_amount:int,
timestamp:int, token_id:str, post_only:bool=False
```

Market orders set expiration=0, order_type as requested, post_only=False; generated salt and millisecond timestamp contribute to identity. Metadata/builder default to zero bytes32. Signature types: EOA=0, proxy=1, Safe=2, POLY1271 deposit wallet=3. For type3, the SDK sets **signed `signer` to the wallet**, not the underlying EOA; calculate the hash from returned signed fields, never reconstruct that field from the private key's address.

POST wire field names differ from the dataclass: `makerAmount`, `takerAmount`, `tokenId`, `signatureType`; numeric amounts/timestamp/expiration are stringified except salt. Envelope adds `orderType`, owner API key and `deferExec:false`. Let SDK `post_order` handle that wire formatting/authentication.

Sources: [market amount arithmetic](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/market.py), [rounding rules](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/context.py), [signed-field construction](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/orders.py), [POST formatter](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/post.py).

## Independent canonical order-hash vector — verified against deployed contract

Domain: name=`Polymarket CTF Exchange`, version=`2`, chainId=137, verifyingContract=`0xE111180000d2663C0091e4f400237545B87B996B`.

Ordered EIP712 Order fields: `salt:uint256,maker:address,signer:address,tokenId:uint256,makerAmount:uint256,takerAmount:uint256,side:uint8,signatureType:uint8,timestamp:uint256,metadata:bytes32,builder:bytes32`.

Expected hash: **`0xf356f5e9c8b3c25ebd7e8734cf4c2925120f12bb9df8ff1c55847f6fbb99b22b`**.

Reproducible pure computation (uses existing dependencies, no keys):

```python
from eth_account.messages import encode_typed_data
from eth_abi import encode
from eth_utils import keccak

exchange = '0xE111180000d2663C0091e4f400237545B87B996B'
fields = [
    ('salt','uint256'), ('maker','address'), ('signer','address'),
    ('tokenId','uint256'), ('makerAmount','uint256'), ('takerAmount','uint256'),
    ('side','uint8'), ('signatureType','uint8'), ('timestamp','uint256'),
    ('metadata','bytes32'), ('builder','bytes32'),
]
message = dict(
    salt=1,
    maker='0x1111111111111111111111111111111111111111',
    signer='0x2222222222222222222222222222222222222222',
    tokenId=123456789, makerAmount=3500000, takerAmount=5000000,
    side=0, signatureType=0, timestamp=1788708000000,
    metadata='0x'+'00'*32, builder='0x'+'00'*32,
)
domain = dict(name='Polymarket CTF Exchange', version='2',
              chainId=137, verifyingContract=exchange)
signable = encode_typed_data(
    domain_data=domain,
    message_types={'Order':[{'name':n,'type':t} for n,t in fields]},
    message_data=message,
)
result = '0x'+keccak(b'\x19'+signable.version+signable.header+signable.body).hex()
assert result == '0xf356f5e9c8b3c25ebd7e8734cf4c2925120f12bb9df8ff1c55847f6fbb99b22b'
```

Independent onchain check performed with this calldata construction:

```python
tuple_type = '('+','.join(t for _,t in fields)+',bytes)'
selector = keccak(text='hashOrder('+tuple_type+')')[:4]
values = tuple(bytes.fromhex(message[n][2:]) if t=='bytes32' else message[n]
               for n,t in fields) + (b'',)  # arbitrary signature, ignored by hash
calldata = '0x'+(selector+encode([tuple_type],[values])).hex()
rpc_request = {'jsonrpc':'2.0','id':1,'method':'eth_call',
               'params':[{'to':exchange,'data':calldata},'latest']}
```

POST that JSON to the public RPC as a read-only call. Observed response:

```json
{"id":1,"jsonrpc":"2.0","result":"0xf356f5e9c8b3c25ebd7e8734cf4c2925120f12bb9df8ff1c55847f6fbb99b22b"}
```

Additional independent expected values: selector `0x3d861a4d`; domain separator `0x3264e159346253e26a64e00b69032db0e7d32f94628de3e6eecb50304d7af3d2`; struct hash `0x677ea20aa541943f516d7de889eb03325d439e78f7bf678e450708e5776569c4`.

Do not include expiration, order_type, post_only, owner API key or signature in the order hash. For type3 use the same underlying standard exchange-domain Order hash with actual returned signature_type/signer fields; do not hash its nested signature wrapper. [Authoritative hash contract](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Hashing.sol), [authoritative struct](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/libraries/Structs.sol).

## Account reads, pagination, state and units

Verified methods (all call expressions below except list_* are awaited):

```python
get_balance_allowance(*, asset_type: AssetType, asset_id: str | None=None)
    -> BalanceAllowance
get_order(*, order_id: str) -> OpenOrder
list_open_orders(*, asset_id: str | None=None, id: str | None=None,
                 market: str | None=None) -> AsyncPaginator[OpenOrder]
list_account_trades(*, asset_id: str | None=None, id: str | None=None,
                    market: str | None=None, maker_address: str | None=None,
                    after: str | None=None, before: str | None=None)
    -> AsyncPaginator[ClobTrade]
cancel_order(*, order_id: str) -> CancelOrdersResponse
```

`market` means condition ID, not slug/Gamma ID. `after`/`before` are Unix-seconds strings. Account endpoints are `/data/order/{order_id}`, `/data/orders`, `/data/trades`, `/balance-allowance`. The SDK supplies signature_type and uses `token_id` wire parameter for balance allowance even when Python argument is asset_id.

Correct iteration, including every page:

```python
async for page in client.list_account_trades(asset_id=token, after=str(start_s)):
    for trade in page.items:
        ...
# Equivalent item iterator:
async for trade in client.list_account_trades(asset_id=token).iter_items():
    ...
```

Do not `await list_account_trades()` itself. `Page` fields: items tuple, has_more bool, next_cursor str|None, total_count int|None. `first_page()` is awaited but is insufficient for recovery. The paginator errors if has_more=True lacks a cursor. Add an overall deadline and repeated-cursor guard at the adapter boundary; incomplete pagination leaves account state unresolved. Overlap trade time ranges across polls and deduplicate IDs, rather than assuming equal timestamps imply identical fills.

| Object | Fields used by adapter |
|---|---|
| BalanceAllowance | `balance:int`, `allowances:dict[str,int]`, both raw units. Case-insensitive verified exchange key lookup; absent spender means zero. |
| OpenOrder | `id`, `condition_id`, `asset_id`, `owner`, `maker_address`, `side`, `price:Decimal`, `original_size:Decimal`, `size_matched:Decimal`, `status:str`, `order_type`, `associate_trades:tuple[str,...]`, created_at/expires_at datetimes |
| ClobTrade | `id`, `condition_id`, `asset_id`, `taker_order_id`, `side`, `trader_side:'TAKER'|'MAKER'`, price/size/fee_rate_bps Decimals, status, transaction_hash, bucket_index, matched_at/updated_at datetimes, maker_orders tuple |
| MakerOrder | order_id, asset_id, maker_address, owner, side, price, matched_amount, outcome, optional fee_rate_bps |
| AcceptedOrder | `ok=True`, order_id, status=`live|matched|delayed`, making_amount/taking_amount Decimals, trade_ids tuple, transactions_hashes tuple |
| RejectedOrder | `ok=False`, code and message; no accepted-order fields |
| CancelOrdersResponse | canceled tuple, not_canceled dict of ID→reason; do not assume whole request succeeded |

`original_size`, `size_matched`, trade size and acknowledgement making/taking amounts are already **human Decimal units**; do NOT divide those by 1e6. Signed amount integers, balance integers and receipt amount integers ARE base units and need scaling exactly once. Do not finalize inventory/cash from acknowledgements.

Trade status normalization strips the wire prefix `TRADE_STATUS_`. Full supported set: MATCHED, **MATCHED_NOT_BROADCASTED**, MINED, RETRYING (provisional), CONFIRMED (successful terminal), FAILED (failed terminal). Unknown/unparseable account shapes leave reconciliation incomplete. No new entries while UNKNOWN submit or incomplete account state exists. `size_matched` proves matching, not final settlement. Maker reconciliation uses its `maker_orders` entries; even though the intended strategy is taker-only, do not attribute another trader's size accidentally.

Accepted status does not prove completion. `wait_for_order_fill_settlement(order, timeout_s=30)` returns successful transaction hashes, can return immediately if trade_ids is empty, and does not fail an order merely because SOME fills failed. Do not use it as the sole inventory/state machine.

`RequestRejectedError` exposes status/code/retry_after/restriction; `RateLimitError` is a separate class. HTTP request timeouts and other httpx errors are wrapped as **TransportError**, not necessarily SDK TimeoutError. Treat transport/parse errors during POST as UNKNOWN, never retry automatically. Treat a single get-order 404 as absent evidence, not proof of no exposure. Allow explicit recognized venue rejection states to reject; generic 5xx remains ambiguous. Sanitize error classes rather than logging request/auth bodies.

Sources: [account requests/parsers](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/account.py), [models](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/models/clob/account.py), [pagination](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/pagination.py), [transport](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/clients/_transport.py).

## Read-only RPC and receipt contract

Allowlist needed methods only: eth_chainId, eth_getCode, eth_call, eth_getTransactionReceipt (plus specifically implemented block/finality reads). Reject eth_sendTransaction/eth_sendRawTransaction and arbitrary user-supplied methods. Use existing `httpx`, `eth_abi`, `eth_utils` dependencies. For eth_call, also restrict target contracts/functions to the inspected wallet/CTF/pUSD/exchange methods; read-only HTTP POST is permitted, transaction broadcast is not.

Onchain balance calls:

- pUSD `balanceOf(address)` and `allowance(address,address)` return uint256. `decimals()` returned 6.
- CTF `balanceOf(address,uint256)` returns uint256; `isApprovedForAll(address,address)` returns bool.
- Non-EOA wallet `eth_getCode`; chainId 137 checked before trusting responses.

Use the **funder** address for balances, not necessarily the signer. Reconcile raw onchain inventory against confirmed ledger inventory; CLOB balance caches and public Data API positions are secondary views. Account doctor performs these reads without approvals.

V2 `OrderFilled` event:

```text
OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)
topic0 = 0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee
topic1 = orderHash (bytes32)
topic2 = maker (32-byte ABI-padded address)
topic3 = taker (32-byte ABI-padded address)
data = abi.decode(['uint8','uint256','uint256','uint256','uint256','bytes32','bytes32'])
       -> side,tokenId,makerAmountFilled,takerAmountFilled,fee,builder,metadata
```

For the bot's order the event maker is the funder, even when it was economically the taker. `taker` may be the exchange itself for aggregated taker execution; do not require taker==wallet. Filter emitter==verified standard exchange, topic0, tracked orderHash, maker=funder, token ID and side. Ignore unrelated batched logs; fail on malformed data claiming tracked identity. Do not also count `OrdersMatched` as a fill. Idempotency key `(chain_id,txHash,logIndex)` handles multiple account trade IDs referring to the same receipt event.

Require associated CONFIRMED account trade evidence plus successful canonical receipt (`status=0x1`) under the initial policy. A mined receipt alone is not final. Missing receipt/hash or provisional status retains reserve. Store blockHash/blockNumber for auditing; conflicting evidence or balance mismatch blocks entries.

BUY: shares=takerAmountFilled/1e6; debit=(makerAmountFilled+fee)/1e6.
SELL: shares=makerAmountFilled/1e6; credit=(takerAmountFilled-fee)/1e6.
Fees are collateral; fee_rate_bps is not the actual receipt fee. Preserve all confirmed partial events and their fees.

**Fee cap observation:** exchange `getMaxFeeRate()` returned **0** in a read-only call. Official Fees.sol treats 0 as **no enforced cap**, not zero fees. Never use the source's default 500bps as an assumed deployed limit. The configured $5 target/reservation is a normal-operation budget with breach handling, not an immutable protocol all-in ceiling; the separate wallet allocation is the outer capital limit.

Sources: [event ABI](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/interfaces/ITrading.sol), [actual emitted fields](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Events.sol), [transfer/fee arithmetic](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Trading.sol), [fee cap zero behavior](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Fees.sol).

## Bounded acceptance fixtures for Task3

Use the independent deployed-hash vector above; test type3 signer-field handling separately from wrapper signature bytes. Test no-network no-deploy construction, exact version guard, invalid existing credential failure without creation, forced stale-cache replacement, and SDK rounding vectors. Account fixtures must cover pagination beyond page1, repeated cursors, prefixed/new provisional statuses, unknown POST plus get-order404, partial/failing fills and duplicate batched receipt delivery. Verify RPC method/target allowlists, wrong chain/emitter/maker/token/topic, unrelated logs, missing receipt and actual fee math. Test fractional residual share rounding and minimum-size impossibility explicitly. Funded acknowledgement/signature validation and actual order round-trip remain live-unverified; the anonymous hashOrder agreement already gives independent signing-hash evidence.

## Small SELL FAK and residual inventory — September 6 followup

**Evidence:** the official order-construction guide defines CLOB book `min_order_size` as a share minimum. Its market-order section reuses limit-order construction, accepts SELL quantity in shares, and explicitly checks a BUY producing 19.2308 shares against the example five-share minimum. Neither that guide nor the published size-rejection error documents an exemption for FAK, closing existing positions, or selling one's entire balance. [Place orders](https://docs.polymarket.com/trading/place-orders), [error codes](https://docs.polymarket.com/resources/error-codes).

**Documentation conflict:** the market-details page describes Gamma `orderMinSize` and normalized `minimum_order_size` as minimum USDC notional. That contradicts the order-construction page's share definition; the OpenAPI descriptions merely say minimum order size. Preserve provenance and do not silently interchange those fields/units. For this experiment, use the book's share interpretation as the conservative entry and exit eligibility assumption, explicitly labeled as an assumption pending venue verification. [Market details](https://docs.polymarket.com/market-data/market-details), [CLOB OpenAPI](https://docs.polymarket.com/api-spec/clob-openapi.yaml).

**SDK evidence and remaining unknown:** pinned 0.9.0 validates a positive SELL share quantity and rounds its maker quantity down to two decimals, but does not enforce `min_order_size` inside the market-order builder. Thus successful signing of 3.25 shares demonstrates construction only. It does not demonstrate CLOB acceptance or an exception to five shares. Whether the current venue accepts subminimum protected SELL FAK for existing holdings remains **live-unverified**; do not state that it either certainly accepts or certainly rejects. Onchain transfer/redemption ability is separate from order-book matching. [Pinned market-order implementation](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/orders/market.py).

Minimal ledger policy:

- Sell only eligible rounded quantities; preserve every actual confirmed fill. A remaining quantity below the assumed share minimum, or below the SDK's 0.01-share precision, stays owned. Record why no compliant exit is currently available; do not repeatedly submit it or buy extra shares merely to satisfy a minimum.
- Until verified official resolution, that residual remains directional exposure with its outstanding cost/risk reservation. It can block later entries under the single-active-position rule. Mere end time, `closed=true`, or a displayed price of 0/1 does not prove a final outcome: the official status definition allows a closed market that has not resolved.
- Once the outcome is verified as resolved and related orders/trades have no remaining ambiguity, transition the residual out of the active directional position. Winning tokens remain owned **claimable inventory**, separately valued at the verified payout and never counted as spendable pUSD. Subsequent rounds may use independently reconciled available cash. Losing tokens remain an auditable quantity with zero value; realize the outstanding losing cost basis exactly once. Retain winning cost basis/claim accounting so later redemption cannot double-count profit.
- A later manual redemption becomes cash only after confirmed redemption and balance reconciliation. No automatic redemption or new implementation route is required here. Official guidance says resolved winning tokens redeem for 1 pUSD each and losing tokens for zero. [Position management](https://docs.polymarket.com/trading/positions/manage).

Bounded fixtures: partial close leaving 4.99 shares; 3.257891 shares signed as 3.25 with 0.007891 retained; resolved winning dust permits a new round but cannot fund it; resolved losing dust writes off basis once; unresolved/ambiguous residual continues blocking. Actual minimum SELL acceptance can be tested later within the authorized small live trial; it is not a prerequisite for implementing this honest conservative behavior.

## Verified read-only CTF resolution and outcome identity

**Yes: standard CTF payout reads establish resolution independently of Gamma/CLOB flags.** Polymarket's CTF source exposes the public payout mappings, forbids setting a previously nonzero denominator again, and uses that denominator to gate redemption. The payout for singleton outcome index `i` is `payoutNumerators(conditionId,i) / payoutDenominator(conditionId)`. Query at a finalized Polygon block; finality of the block remains necessary even though the contract's reported payout cannot subsequently be overwritten. [Pinned CTF source](https://github.com/Polymarket/conditional-tokens-contracts/blob/a927b5a52cf9ace712bf1b5fe1d92bf76399e692/contracts/ConditionalTokens.sol).

All calls below target CTF `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` on chain 137. Exact ABI signatures and deployed-call selectors:

| Function signature | Selector | Return ABI |
|---|---|---|
| `getOutcomeSlotCount(bytes32)` | `0xd42dc0c2` | `uint256` |
| `payoutDenominator(bytes32)` | `0xdd34de67` | `uint256` |
| `payoutNumerators(bytes32,uint256)` | `0x0504c814` | `uint256` |
| `getCollectionId(bytes32,bytes32,uint256)` | `0x856296f7` | `bytes32` |
| `getPositionId(address,bytes32)` | `0x39dd7530` | `uint256` |

`getCollectionId` arguments are parent collection (32 zero bytes), condition ID, index set. For binary singleton index `i`, index set is `1 << i`, thus 1 and 2. `getPositionId` takes **underlying USDC.e** `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` and that collection ID. This is distinct from wallet cash pUSD. The current adapter derives standard CTF positions from its USDCE field and wraps redeemed collateral into pUSD; its pUSD-facing function argument does not redefine the underlying CTF IDs. [Pinned adapter source](https://github.com/Polymarket/ctf-exchange-v2/blob/ccc0596074f4dfd62c944fbca4de252893b82b4b/src/adapters/CtfCollateralAdapter.sol).

Anonymous query evidence, September 6, 2026:

- Gamma `GET /events?slug=btc-updown-5m-1788631200&include_chat=false` identifies a standard (`negRisk=false`) BTC market ending September 5 at 18:05 UTC; `umaResolutionStatus=resolved`, labels `[Up,Down]`, prices `[0,1]`, anchor `80065.42201137073`, final `80036.77431728777`. These metadata corroborate the onchain outcome; they are not its finality proof. [Public event payload](https://gamma-api.polymarket.com/events?slug=btc-updown-5m-1788631200&include_chat=false).
- Condition: `0x36734a624c2b5aeee164162536fe811bb82677ad927050b50cc46838fe67d494`.
- RPC `https://polygon.drpc.org` returned chain ID `0x89`. `eth_getBlockByNumber("finalized",false)` returned block **93338017**, hex `0x59039a1`, timestamp `2026-09-06T16:27:39Z`, hash `0x800b15e3c168c04eb194dd3cd8892b96b5fc742470d68001ce71664f83cdaba8`. Every subsequent call used that explicit block number, and a later block-by-number read returned the same hash.
- At that block: outcome slot count **2**, denominator **1**, numerator index 0 **0**, numerator index 1 **1**.

Exact identity vectors from deployed `eth_call`, also matching both Gamma `clobTokenIds`:

| CTF index / index set | Collection ID | USDC.e-derived token ID | Matched label / payout |
|---|---|---|---|
| 0 / 1 | `0x473b89f4c4a2a8702819d50cc597500f9cddc34a375bafcff9352b4a60956396` | `93464131606378261331338471789927052245553593563803080458303202347805601920785` | Up / 0 |
| 1 / 2 | `0x4c7f1253b450efe9b852240a245ead472fc24c4cf96a83bf55c6d1bbc6eef597` | `54587822891934720131108562415940344642217988714969692821005775518682216077925` | Down / 1 |

Negative control: pUSD-derived index-set-1 token was `18167158608228514079914336201797985869660722887513875858583226140523299196062`, which does **not** match the traded Up token. This catches accidental reuse of the exchange cash address for CTF identity.

Reproduction encoding: calldata is `keccak(text=signature)[:4] + eth_abi.encode(argument_types, arguments)`; decode the result according to the return ABI above. For example, the denominator request is:

```json
{"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":"0x4D97DCd97eC945f40cF65F87097ACe5EA0476045","data":"0xdd34de6736734a624c2b5aeee164162536fe811bb82677ad927050b50cc46838fe67d494"},"0x59039a1"]}
```

Expected result: `0x0000000000000000000000000000000000000000000000000000000000000001`. Numerator arguments append one uint256 ABI word for index 0 or 1; collection and position arguments follow the table. No signer, account, balance, relayer, or transaction broadcast is involved.

Minimal runtime contract: require standard CTF/non-negative-risk, slot count 2, distinct derived IDs matching the saved market's **set of token IDs**, and a tracked held token matching exactly one derived ID. Assign payouts to that token ID; only afterward associate the saved human label. Never infer CTF index from list position or assume Up means index 0. Require denominator `d>0` and vector exactly `(d,0)` or `(0,d)`, allowing any positive normalization d while accepting only economic payouts 0 or 1. Denominator zero, fractional payout, unprepared/nonbinary condition, mapping mismatch, RPC failure, unavailable finalized block, or conflicting evidence remains visibly unresolved under the initial policy. This conservatively leaves fractional-but-onchain-resolved conditions unsupported rather than inventing a binary winner.

Read all related state at one explicit finalized block number, retain block hash/number and raw vector, and verify the block hash remains consistent before committing the ledger transition. Add only these CTF selectors and `eth_getBlockByNumber` to the existing read allowlist. Resolution releases directional exposure only after outstanding order/trade ambiguity is cleared; winning residual becomes claimable noncash inventory and losing basis is realized once, as above. This operation performs no redemption.

SDK 0.9.0 has no equivalent payout-mapping/collection/position-ID getter: an exhaustive source search found none of the five names. Its position helper consumes API token IDs and its `redeem_positions` method submits a wallet transaction, so it must not be used as a resolution probe. Existing httpx/eth_abi/eth_utils suffice. [Pinned position helper](https://github.com/Polymarket/py-sdk/blob/polymarket-client-v0.9.0/src/polymarket/_internal/actions/relayer/positions.py).

Fixtures: this full vector, reversed metadata outcome ordering, pUSD-derived mismatch, denominator zero, fractional `[1,1]/2`, nonbinary slot count, changed finalized block hash, and successful resolution with an unresolved submit still blocking transition. The anonymous RPC evidence verifies this resolution path without a funded trial.

Root additionally inspected pinned `AsyncSecureClient.post_order` and `AsyncTransport._request`:
the path formats one payload, calls one HTTP request and parses the response. No automatic retry loop
is present in this pinned path. HTTP transport failures become TransportError. The broker's own
no-retry/UNKNOWN policy therefore need not disable a hidden SDK retry mechanism. Preserve that
property with a transport-count fixture when testing timeout-after-acceptance. SDK transport logging
can include an exception's text, so do not enable its request-failure logger on authenticated paths;
the application reports sanitized error classes/reason codes instead.
