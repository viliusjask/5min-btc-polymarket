"""Independent deployed ABI vectors and synthetic canonical receipts."""

import asyncio
import json
from dataclasses import replace
from decimal import Decimal as D

import httpx
import pytest
from eth_abi import decode, encode
from polymarket.models.clob.orders import SignedOrder
from test_ledger import HASH, NOW, WALLET, opened, submitted
from test_strategy import make_snapshot

from btc5m.rpc import ReadOnlyRPC, RPCError, canonical_order_hash

EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDCE = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
CONDITION = "0x36734a624c2b5aeee164162536fe811bb82677ad927050b50cc46838fe67d494"
TOKENS = (
    "93464131606378261331338471789927052245553593563803080458303202347805601920785",
    "54587822891934720131108562415940344642217988714969692821005775518682216077925",
)
COLLECTIONS = (
    "0x473b89f4c4a2a8702819d50cc597500f9cddc34a375bafcff9352b4a60956396",
    "0x4c7f1253b450efe9b852240a245ead472fc24c4cf96a83bf55c6d1bbc6eef597",
)
BLOCK = {
    "number": "0x59039a1",
    "hash": "0x800b15e3c168c04eb194dd3cd8892b96b5fc742470d68001ce71664f83cdaba8",
    "timestamp": "0x6a9c572b",
}
TX = "0x" + "12" * 32
TOPIC = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"


def signed(**changes):
    data = dict(
        builder="0x" + "00" * 32,
        expiration=0,
        maker=WALLET,
        maker_amount=3500000,
        metadata="0x" + "00" * 32,
        order_type="FOK",
        salt=1,
        side="BUY",
        signature="0x1234",
        signature_type=0,
        signer="0x2222222222222222222222222222222222222222",
        taker_amount=5000000,
        timestamp=1788708000000,
        token_id="123456789",
        post_only=False,
    )
    return SignedOrder(**(data | changes))


def test_independent_deployed_hash_and_signature_wrapper_independence():
    assert (
        canonical_order_hash(signed())
        == "0xf356f5e9c8b3c25ebd7e8734cf4c2925120f12bb9df8ff1c55847f6fbb99b22b"
    )
    assert canonical_order_hash(signed(signature="0xabcdef")) == canonical_order_hash(signed())
    assert canonical_order_hash(signed(signature_type=3, signer=WALLET)) != canonical_order_hash(
        signed(signature_type=3)
    )
    assert canonical_order_hash(
        signed(signature_type=3, signer=WALLET, signature="0xabcdef")
    ) == canonical_order_hash(signed(signature_type=3, signer=WALLET))


def receipt(token="123456789", side=0, maker=3500000, taker=5000000, fee=73500):
    return {
        "transactionHash": TX,
        "status": "0x1",
        "blockNumber": BLOCK["number"],
        "blockHash": BLOCK["hash"],
        "logs": [
            {
                "address": EXCHANGE,
                "topics": [
                    TOPIC,
                    HASH,
                    "0x" + "00" * 12 + WALLET[2:],
                    "0x" + "00" * 12 + EXCHANGE[2:].lower(),
                ],
                "data": "0x"
                + encode(
                    ["uint8", "uint256", "uint256", "uint256", "uint256", "bytes32", "bytes32"],
                    [side, int(token), maker, taker, fee, bytes(32), bytes(32)],
                ).hex(),
                "logIndex": "0x0",
                "transactionHash": TX,
                "blockNumber": BLOCK["number"],
                "blockHash": BLOCK["hash"],
                "removed": False,
            }
        ],
    }


class RPCFixture:
    def __init__(self):
        self.receipt = receipt()
        self.chain = "0x89"
        self.denominator = 1
        self.numerators = (0, 1)
        self.slots = 2
        self.changed_hash = False
        self.pusd_identity = False
        self.calls = []

    def __call__(self, request):
        body = json.loads(request.content)
        method, params = body["method"], body["params"]
        self.calls.append((method, params))
        if method == "eth_chainId":
            result = self.chain
        elif method == "eth_getTransactionReceipt":
            assert params == [TX]
            result = self.receipt
        elif method == "eth_getBlockByNumber":
            assert params[0] in ("finalized", BLOCK["number"])
            result = BLOCK | (
                {"hash": "0x" + "aa" * 32} if self.changed_hash and params[0] != "finalized" else {}
            )
        elif method == "eth_call":
            assert params[0]["to"].lower() == CTF.lower()
            assert params[1] == BLOCK["number"]
            data = params[0]["data"]
            selector = data[:10]
            args = bytes.fromhex(data[10:])
            if selector == "0xd42dc0c2":
                result = self.slots
            elif selector == "0xdd34de67":
                result = self.denominator
            elif selector == "0x0504c814":
                result = self.numerators[decode(["bytes32", "uint256"], args)[1]]
            elif selector == "0x856296f7":
                parent, condition, index = decode(["bytes32", "bytes32", "uint256"], args)
                assert parent == bytes(32) and condition.hex() == CONDITION[2:]
                result = COLLECTIONS[index - 1]
            elif selector == "0x39dd7530":
                collateral, collection = decode(["address", "bytes32"], args)
                assert collateral.lower() == USDCE.lower()
                result = int(TOKENS[COLLECTIONS.index("0x" + collection.hex())])
                if self.pusd_identity:
                    result = 18167158608228514079914336201797985869660722887513875858583226140523299196062
            else:
                raise AssertionError(selector)
            if isinstance(result, int):
                result = "0x" + encode(["uint256"], [result]).hex()
        else:
            raise AssertionError(method)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}, request=request
        )


def rpc_fixture(fixture):
    return ReadOnlyRPC(
        http=httpx.AsyncClient(transport=httpx.MockTransport(fixture)), clock=lambda: NOW / 1000
    )


def test_canonical_receipt_actual_fee_and_unrelated_batched_log(tmp_path):
    async def run():
        ledger, session = opened(tmp_path)
        order = replace(submitted(ledger, session), token_id="123456789")
        fixture = RPCFixture()
        unrelated = dict(fixture.receipt["logs"][0], topics=[TOPIC, "0x" + "bb" * 32])
        fixture.receipt["logs"].append(unrelated)
        rpc = rpc_fixture(fixture)
        fills = await rpc.confirmed_fills(order, TX, NOW)
        assert len(fills) == 1 and fills[0].quantity == 5
        assert fills[0].principal == D("3.5") and fills[0].fee == D(".0735")
        assert fills[0].block_hash == BLOCK["hash"]
        await rpc.close()
        ledger.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad",
    [
        "chain",
        "receipt_failed",
        "receipt_hash",
        "block_hash",
        "emitter",
        "topic",
        "wallet",
        "token",
        "side",
        "malformed",
        "removed",
    ],
)
def test_claimed_order_identity_or_noncanonical_receipt_blocks_finality(tmp_path, bad):
    async def run():
        ledger, session = opened(tmp_path)
        order = replace(submitted(ledger, session), token_id="123456789")
        fixture = RPCFixture()
        log = fixture.receipt["logs"][0]
        if bad == "chain":
            fixture.chain = "0x1"
        elif bad == "receipt_failed":
            fixture.receipt["status"] = "0x0"
        elif bad == "receipt_hash":
            fixture.receipt["transactionHash"] = "0x" + "ab" * 32
        elif bad == "block_hash":
            fixture.receipt["blockHash"] = "0x" + "ab" * 32
        elif bad == "emitter":
            log["address"] = CTF
        elif bad == "topic":
            log["topics"][0] = "0x" + "ab" * 32
        elif bad == "wallet":
            log["topics"][2] = "0x" + "00" * 32
        elif bad == "token":
            fixture.receipt = receipt(token="42")
        elif bad == "side":
            fixture.receipt = receipt(side=1)
        elif bad == "malformed":
            log["data"] = "0x00"
        elif bad == "removed":
            log["removed"] = True
        rpc = rpc_fixture(fixture)
        with pytest.raises(RPCError):
            await rpc.confirmed_fills(order, TX, NOW)
        await rpc.close()
        ledger.close()

    asyncio.run(run())


def test_finalized_resolution_deployed_vector_reversed_labels():
    async def run():
        fixture = RPCFixture()
        rpc = rpc_fixture(fixture)
        market = replace(
            make_snapshot().market, condition_id=CONDITION, up_token=TOKENS[1], down_token=TOKENS[0]
        )
        evidence = await rpc.resolve(market)
        assert evidence is not None
        assert dict(evidence.token_payouts) == {TOKENS[0]: D(0), TOKENS[1]: D(1)}
        assert evidence.block_number == 93338017 and evidence.block_hash == BLOCK["hash"]
        await rpc.close()

    asyncio.run(run())


@pytest.mark.parametrize("bad", ["zero", "fractional", "slots", "identity", "changed_hash"])
def test_unsupported_or_unstable_resolution_retains_uncertainty(bad):
    async def run():
        fixture = RPCFixture()
        if bad == "zero":
            fixture.denominator = 0
        elif bad == "fractional":
            fixture.denominator = 2
            fixture.numerators = (1, 1)
        elif bad == "slots":
            fixture.slots = 3
        elif bad == "identity":
            fixture.pusd_identity = True
        else:
            fixture.changed_hash = True
        rpc = rpc_fixture(fixture)
        market = replace(
            make_snapshot().market, condition_id=CONDITION, up_token=TOKENS[0], down_token=TOKENS[1]
        )
        assert await rpc.resolve(market) is None
        assert rpc.last_resolution_reason
        await rpc.close()

    asyncio.run(run())


def test_rpc_allowlist_rejects_mutations_and_arbitrary_calls_before_transport():
    async def run():
        def forbidden(request):
            raise AssertionError("network must not be reached")

        rpc = rpc_fixture(forbidden)
        for method, params in [
            ("eth_sendRawTransaction", ["0x00"]),
            ("eth_call", [{"to": CTF, "data": "0x095ea7b3"}, "latest"]),
            ("eth_call", [{"to": WALLET, "data": "0x313ce567"}, "latest"]),
        ]:
            with pytest.raises(RPCError):
                await rpc.request(method, params)
        await rpc.close()

    asyncio.run(run())
