"""Narrow anonymous Polygon reads for cash, canonical fills and binary resolution.

Every eth_call has a fixed contract/function allowlist. This adapter contains no
transaction submission, redemption, signing key, approval or general RPC escape.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
from eth_abi import decode, encode
from eth_account.messages import encode_typed_data
from eth_utils import keccak
from polymarket.models.clob.orders import SignedOrder

from btc5m.domain import Market
from btc5m.execution_types import ConfirmedFill, Intent, ResolutionEvidence

EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
USDCE = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
RPC_URL = "https://polygon.drpc.org"
FILL_TOPIC = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
SCALE = Decimal(1_000_000)
HASH_RE = re.compile(r"0x[0-9a-fA-F]{64}\Z")
ORDER_FIELDS = (
    ("salt", "uint256"),
    ("maker", "address"),
    ("signer", "address"),
    ("tokenId", "uint256"),
    ("makerAmount", "uint256"),
    ("takerAmount", "uint256"),
    ("side", "uint8"),
    ("signatureType", "uint8"),
    ("timestamp", "uint256"),
    ("metadata", "bytes32"),
    ("builder", "bytes32"),
)
CALLS = {
    PUSD.lower(): {"balanceOf(address)", "allowance(address,address)", "decimals()"},
    CTF.lower(): {
        "balanceOf(address,uint256)",
        "isApprovedForAll(address,address)",
        "getOutcomeSlotCount(bytes32)",
        "payoutDenominator(bytes32)",
        "payoutNumerators(bytes32,uint256)",
        "getCollectionId(bytes32,bytes32,uint256)",
        "getPositionId(address,bytes32)",
    },
    EXCHANGE.lower(): {
        "getCollateral()",
        "getMaxFeeRate()",
        "hashOrder((uint256,address,address,uint256,uint256,uint256,uint8,uint8,uint256,bytes32,bytes32,bytes))",
    },
}
SELECTORS = {
    target: {"0x" + keccak(text=sig)[:4].hex() for sig in signatures}
    for target, signatures in CALLS.items()
}


class RPCError(Exception):
    """Safe reason code; upstream exception text is never exposed."""


def canonical_order_hash(order: SignedOrder) -> str:
    if order.side not in ("BUY", "SELL") or order.signature_type not in (0, 1, 2, 3):
        raise RPCError("UNSUPPORTED_SIGNATURE")
    message = dict(
        salt=order.salt,
        maker=order.maker,
        signer=order.signer,
        tokenId=int(order.token_id),
        makerAmount=order.maker_amount,
        takerAmount=order.taker_amount,
        side=0 if order.side == "BUY" else 1,
        signatureType=order.signature_type,
        timestamp=order.timestamp,
        metadata=order.metadata,
        builder=order.builder,
    )
    data = encode_typed_data(
        domain_data=dict(
            name="Polymarket CTF Exchange", version="2", chainId=137, verifyingContract=EXCHANGE
        ),
        message_types={"Order": [{"name": name, "type": kind} for name, kind in ORDER_FIELDS]},
        message_data=message,
    )
    return "0x" + keccak(b"\x19" + data.version + data.header + data.body).hex()


def _hex_int(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value):
        raise RPCError("INVALID_RPC_INTEGER")
    return int(value, 16)


def _hash(value: Any) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise RPCError("INVALID_RPC_HASH")
    return value.lower()


class ReadOnlyRPC:
    def __init__(
        self, *, http: httpx.AsyncClient | None = None, clock: Callable[[], float] = time.time
    ) -> None:
        self.http = http or httpx.AsyncClient(timeout=5)
        self.clock = clock
        self.last_resolution_reason: str | None = None
        self._id = 0

    async def close(self) -> None:
        await self.http.aclose()

    async def request(self, method: str, params: list[Any]) -> Any:
        if method not in {
            "eth_chainId",
            "eth_getCode",
            "eth_call",
            "eth_getTransactionReceipt",
            "eth_getBlockByNumber",
        }:
            raise RPCError("RPC_METHOD_FORBIDDEN")
        if method == "eth_call":
            if len(params) != 2 or not isinstance(params[0], dict):
                raise RPCError("RPC_CALL_FORBIDDEN")
            call = params[0]
            if (
                set(call) != {"to", "data"}
                or not isinstance(call["data"], str)
                or call["data"][:10] not in SELECTORS.get(str(call["to"]).lower(), set())
            ):
                raise RPCError("RPC_CALL_FORBIDDEN")
        self._id += 1
        try:
            response = await self.http.post(
                RPC_URL,
                json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params},
                timeout=5,
            )
            response.raise_for_status()
            result = response.json()
            if (
                result.get("id") != self._id
                or result.get("jsonrpc") != "2.0"
                or "error" in result
                or "result" not in result
            ):
                raise RPCError("RPC_RESPONSE_INVALID")
            return result["result"]
        except RPCError:
            raise
        except Exception:
            raise RPCError("RPC_READ_FAILED") from None

    async def chain(self) -> None:
        if await self.request("eth_chainId", []) != "0x89":
            raise RPCError("WRONG_CHAIN")

    async def call(
        self,
        target: str,
        signature: str,
        types: list[str],
        values: list[Any],
        returns: str = "uint256",
        block: str = "latest",
    ) -> Any:
        data = "0x" + (keccak(text=signature)[:4] + encode(types, values)).hex()
        raw = await self.request("eth_call", [{"to": target, "data": data}, block])
        try:
            return decode([returns], bytes.fromhex(raw[2:]))[0]
        except Exception:
            raise RPCError("RPC_ABI_INVALID") from None

    async def balances(
        self, wallet: str, tokens: set[str]
    ) -> tuple[Decimal, Decimal, bool, dict[str, Decimal]]:
        async with asyncio.timeout(20):
            await self.chain()
            if (
                await self.call(PUSD, "decimals()", [], []) != 6
                or str(
                    await self.call(EXCHANGE, "getCollateral()", [], [], returns="address")
                ).lower()
                != PUSD.lower()
            ):
                raise RPCError("UNSUPPORTED_COLLATERAL")
            cash = (
                Decimal(await self.call(PUSD, "balanceOf(address)", ["address"], [wallet])) / SCALE
            )
            allowance = (
                Decimal(
                    await self.call(
                        PUSD,
                        "allowance(address,address)",
                        ["address", "address"],
                        [wallet, EXCHANGE],
                    )
                )
                / SCALE
            )
            approved = await self.call(
                CTF,
                "isApprovedForAll(address,address)",
                ["address", "address"],
                [wallet, EXCHANGE],
                returns="bool",
            )
            inventory = {}
            for token in sorted(tokens):
                inventory[token] = (
                    Decimal(
                        await self.call(
                            CTF,
                            "balanceOf(address,uint256)",
                            ["address", "uint256"],
                            [wallet, int(token)],
                        )
                    )
                    / SCALE
                )
            return cash, allowance, approved, inventory

    async def confirmed_fills(
        self, order: Intent, transaction_hash: str, timestamp_ms: int
    ) -> tuple[ConfirmedFill, ...]:
        """Caller must first establish CONFIRMED account trade status for this order."""
        try:
            async with asyncio.timeout(15):
                await self.chain()
                tx = _hash(transaction_hash)
                receipt = await self.request("eth_getTransactionReceipt", [tx])
                if (
                    not isinstance(receipt, dict)
                    or receipt.get("status") != "0x1"
                    or _hash(receipt.get("transactionHash")) != tx
                ):
                    raise RPCError("RECEIPT_UNCONFIRMED")
                block_number = _hex_int(receipt["blockNumber"])
                block_hash = _hash(receipt["blockHash"])
                block = await self.request("eth_getBlockByNumber", [hex(block_number), False])
                if (
                    not isinstance(block, dict)
                    or _hash(block.get("hash")) != block_hash
                    or _hex_int(block.get("number")) != block_number
                ):
                    raise RPCError("NONCANONICAL_RECEIPT")
                stamp = _hex_int(block["timestamp"]) * 1000
                if not isinstance(receipt.get("logs"), list):
                    raise RPCError("INVALID_RECEIPT_LOGS")
                fills = []
                for log in receipt["logs"]:
                    topics = log.get("topics", []) if isinstance(log, dict) else []
                    if len(topics) < 2 or str(topics[1]).lower() != order.order_hash:
                        continue
                    if (
                        str(log.get("address")).lower() != EXCHANGE.lower()
                        or len(topics) != 4
                        or str(topics[0]).lower() != FILL_TOPIC
                        or _hash(topics[2])[2:] != "0" * 24 + order.wallet[2:].lower()
                        or log.get("removed") is not False
                        or _hash(log.get("transactionHash")) != tx
                        or _hash(log.get("blockHash")) != block_hash
                        or _hex_int(log.get("blockNumber")) != block_number
                    ):
                        raise RPCError("FILL_IDENTITY_MISMATCH")
                    side, token, maker, taker, fee, _, _ = decode(
                        ["uint8", "uint256", "uint256", "uint256", "uint256", "bytes32", "bytes32"],
                        bytes.fromhex(log["data"][2:]),
                    )
                    if (
                        str(token) != order.token_id
                        or side != (0 if order.side == "BUY" else 1)
                        or maker <= 0
                        or taker <= 0
                        or (side == 1 and fee > taker)
                    ):
                        raise RPCError("INVALID_OWNED_FILL")
                    fills.append(
                        ConfirmedFill(
                            137,
                            tx,
                            _hex_int(log["logIndex"]),
                            order.order_hash or "",
                            order.token_id,
                            order.wallet,
                            order.side,
                            Decimal(taker if side == 0 else maker) / SCALE,
                            Decimal(maker if side == 0 else taker) / SCALE,
                            Decimal(fee) / SCALE,
                            stamp,
                            block_number,
                            block_hash,
                        )
                    )
                if not fills:
                    raise RPCError("OWNED_FILL_MISSING")
                return tuple(fills)
        except RPCError:
            raise
        except Exception:
            raise RPCError("RECEIPT_EVIDENCE_INVALID") from None

    async def resolve(self, market: Market) -> ResolutionEvidence | None:
        self.last_resolution_reason = None
        try:
            async with asyncio.timeout(20):
                await self.chain()
                condition = bytes.fromhex(_hash(market.condition_id)[2:])
                block = await self.request("eth_getBlockByNumber", ["finalized", False])
                if not isinstance(block, dict):
                    raise RPCError("FINALIZED_BLOCK_UNAVAILABLE")
                number, block_hash = _hex_int(block.get("number")), _hash(block.get("hash"))
                explicit = hex(number)
                slots = await self.call(
                    CTF, "getOutcomeSlotCount(bytes32)", ["bytes32"], [condition], block=explicit
                )
                denominator = await self.call(
                    CTF, "payoutDenominator(bytes32)", ["bytes32"], [condition], block=explicit
                )
                if slots != 2 or denominator <= 0:
                    raise RPCError("UNRESOLVED_OR_NONBINARY")
                numerators = tuple(
                    [
                        await self.call(
                            CTF,
                            "payoutNumerators(bytes32,uint256)",
                            ["bytes32", "uint256"],
                            [condition, i],
                            block=explicit,
                        )
                        for i in range(2)
                    ]
                )
                if numerators not in ((denominator, 0), (0, denominator)):
                    raise RPCError("FRACTIONAL_PAYOUT_UNSUPPORTED")
                tokens = []
                for indexset in (1, 2):
                    collection = await self.call(
                        CTF,
                        "getCollectionId(bytes32,bytes32,uint256)",
                        ["bytes32", "bytes32", "uint256"],
                        [bytes(32), condition, indexset],
                        returns="bytes32",
                        block=explicit,
                    )
                    token = await self.call(
                        CTF,
                        "getPositionId(address,bytes32)",
                        ["address", "bytes32"],
                        [USDCE, collection],
                        block=explicit,
                    )
                    tokens.append(str(token))
                if len(set(tokens)) != 2 or set(tokens) != {market.up_token, market.down_token}:
                    raise RPCError("RESOLUTION_TOKEN_MISMATCH")
                checked = await self.request("eth_getBlockByNumber", [explicit, False])
                if (
                    not isinstance(checked, dict)
                    or _hash(checked.get("hash")) != block_hash
                    or _hex_int(checked.get("number")) != number
                ):
                    raise RPCError("FINALIZED_BLOCK_CHANGED")
                return ResolutionEvidence(
                    market.condition_id,
                    137,
                    number,
                    block_hash,
                    denominator,
                    (numerators[0], numerators[1]),
                    tuple(
                        (t, Decimal(n) / denominator)
                        for t, n in zip(tokens, numerators, strict=True)
                    ),
                    "CTF_FINALIZED",
                    int(self.clock() * 1000),
                )
        except RPCError as exc:
            self.last_resolution_reason = str(exc)
        except Exception:
            self.last_resolution_reason = "RESOLUTION_READ_FAILED"
        return None
