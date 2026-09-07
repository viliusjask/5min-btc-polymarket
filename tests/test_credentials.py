"""Synthetic signing only: authentication never invokes account or order actions."""

import asyncio
import json

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from polymarket._internal.l1_auth import build_api_key_auth_typed_data

from btc5m.credentials import CredentialError, trading_credentials

KEY = "0x" + "01" * 32
RESPONSE = {"apiKey": "synthetic-api", "secret": "synthetic-secret", "passphrase": "synthetic-pass"}


def test_derive_signs_correct_auth_domain_and_only_calls_official_auth():
    def handler(request):
        assert str(request.url) == "https://clob.polymarket.com/auth/derive-api-key"
        assert request.method == "GET"
        typed = build_api_key_auth_typed_data(
            address=Account.from_key(KEY).address, chain_id=137, timestamp=1800000000, nonce=0
        )
        recovered = Account.recover_message(
            encode_typed_data(full_message=typed), signature=request.headers["POLY_SIGNATURE"]
        )
        assert recovered == Account.from_key(KEY).address
        assert KEY not in str(request.headers)
        assert "POLY_API_KEY" not in request.headers
        return httpx.Response(200, json=RESPONSE)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            creds = await trading_credentials(KEY, create=False, http=client, timestamp=1800000000)
            assert creds.key == RESPONSE["apiKey"]

    asyncio.run(scenario())


def test_explicit_create_derives_on_sdk_existing_key_response():
    paths = []

    def handler(request):
        paths.append((request.method, request.url.path))
        return (
            httpx.Response(400, json={"error": "exists"})
            if len(paths) == 1
            else httpx.Response(200, json=RESPONSE)
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await trading_credentials(KEY, create=True, http=client)

    asyncio.run(scenario())
    assert paths == [("POST", "/auth/api-key"), ("GET", "/auth/derive-api-key")]


@pytest.mark.parametrize("failure", ["timeout", "redirect", "rejected", "malformed", "newline"])
def test_errors_are_sanitized_and_no_retry_after_uncertain_create(failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("SECRET_RESPONSE", request=request)
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.com"})
        if failure == "rejected":
            return httpx.Response(401, text="SECRET_RESPONSE")
        if failure == "newline":
            return httpx.Response(200, json={**RESPONSE, "secret": "secret\nEVIL=x"})
        return httpx.Response(200, text="SECRET_RESPONSE")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(CredentialError) as caught:
                await trading_credentials(KEY, create=True, http=client)
            assert "SECRET_RESPONSE" not in str(caught.value)

    asyncio.run(scenario())
    assert len(calls) == 1


def test_cli_replaces_trading_fields_atomically_without_printing_keys(
    tmp_path, monkeypatch, capsys
):
    from polymarket.models.clob import ApiKeyCreds

    from btc5m import cli

    file = tmp_path / ".env"
    original = f"# user comment\nPOLYMARKET_PRIVATE_KEY={KEY}\nPOLYMARKET_FUNDER=0x{'02' * 20}\nPOLYMARKET_API_KEY=builder\nPOLYMARKET_API_SECRET=\nPOLYMARKET_API_PASSPHRASE=\n"
    file.write_text(original)

    async def fake(private_key, *, create, **kwargs):
        assert private_key == KEY and create
        return ApiKeyCreds.parse_response(RESPONSE)

    monkeypatch.setattr("btc5m.credentials.trading_credentials", fake)
    assert cli.main(["credentials", "--env-file", str(file), "--create"]) == 0
    result = file.read_text()
    assert "# user comment" in result and f"POLYMARKET_PRIVATE_KEY={KEY}" in result
    assert "POLYMARKET_API_KEY=synthetic-api" in result
    assert file.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr()
    assert KEY not in output.out and RESPONSE["secret"] not in output.out
    assert json.loads(output.out)["trades_placed"] is False
    assert not list(tmp_path.glob("*.tmp"))


def test_cli_auth_failure_leaves_env_unchanged(tmp_path, monkeypatch, capsys):
    from btc5m import cli

    file = tmp_path / ".env"
    original = f"POLYMARKET_PRIVATE_KEY={KEY}\nPOLYMARKET_FUNDER=0x{'02' * 20}\n"
    file.write_text(original)

    async def fake(*args, **kwargs):
        raise CredentialError("AUTH_UNCERTAIN_DERIVE_BEFORE_RETRY")

    monkeypatch.setattr("btc5m.credentials.trading_credentials", fake)
    assert cli.main(["credentials", "--env-file", str(file), "--create"]) == 2
    assert file.read_text() == original
    assert "AUTH_UNCERTAIN_DERIVE_BEFORE_RETRY" in capsys.readouterr().err
