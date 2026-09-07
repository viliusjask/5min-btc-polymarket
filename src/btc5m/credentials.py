"""Explicit CLOB authentication using the pinned SDK's wallet-signature contract.

Only authentication endpoints are used. No wallet deployment, approval, order,
relayer or transfer action is reachable here. Responses/signatures are never logged.
"""

import time

import httpx
from eth_account import Account
from polymarket._internal.actions.auth import build_l1_auth_headers, parse_api_key_creds
from polymarket._internal.l1_auth import sign_api_key_auth
from polymarket.models.clob import ApiKeyCreds


class CredentialError(Exception):
    """Sanitized local or authentication failure."""


async def trading_credentials(
    private_key: str,
    *,
    create: bool,
    http: httpx.AsyncClient | None = None,
    timestamp: int | None = None,
) -> ApiKeyCreds:
    try:
        signature = sign_api_key_auth(
            Account.from_key(private_key),
            chain_id=137,
            timestamp=int(time.time()) if timestamp is None else timestamp,
            nonce=0,
        )
        headers = build_l1_auth_headers(signature)
    except Exception:
        raise CredentialError("AUTH_SIGNING_FAILED") from None
    client = http if http is not None else httpx.AsyncClient(timeout=10)
    try:
        # Match the SDK's explicit create-or-derive behavior. A transport error on
        # POST is ambiguous; never repeat it automatically or expose its payload.
        path = "/auth/api-key" if create else "/auth/derive-api-key"
        response = await client.request(
            "POST" if create else "GET",
            "https://clob.polymarket.com" + path,
            headers=headers,
            follow_redirects=False,
        )
        if create and response.status_code == 400:
            response = await client.get(
                "https://clob.polymarket.com/auth/derive-api-key",
                headers=headers,
                follow_redirects=False,
            )
        if response.status_code != 200:
            raise CredentialError(f"AUTH_HTTP_{response.status_code}")
        try:
            credentials = parse_api_key_creds(response.json())
            for value in (credentials.key, credentials.secret, credentials.passphrase):
                if (
                    not value
                    or len(value) > 4096
                    or not value.isascii()
                    or any(ord(char) < 33 or ord(char) > 126 or char in "\"'" for char in value)
                ):
                    raise ValueError
        except Exception:
            raise CredentialError("AUTH_INVALID_RESPONSE") from None
        return credentials
    except httpx.HTTPError:
        raise CredentialError(
            "AUTH_UNCERTAIN_DERIVE_BEFORE_RETRY" if create else "AUTH_CONNECTION_FAILED"
        ) from None
    finally:
        if http is None:
            await client.aclose()
