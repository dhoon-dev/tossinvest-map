from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from tossinvest_mcp_remote.cli import config_from_args, http_config_from_args, parse_args
from tossinvest_mcp_remote.config import TossInvestRemoteServerConfig
from tossinvest_mcp_remote.errors import TossInvestMCPRemoteConfigError

from .conftest import BASE_URL, account_payload, add_api_response, add_token_response


def test_config_from_args_preserves_explicit_credentials() -> None:
    args = parse_args(
        [
            "stdio",
            "--client-id",
            "client-id",
            "--client-secret",
            "client-secret",
            "--account",
            "12345678901",
            "--base-url",
            "https://example.test",
            "--timeout",
            "3.5",
            "--max-retries",
            "4",
            "--user-agent",
            "custom-agent",
        ]
    )

    config = config_from_args(args)

    assert config == TossInvestRemoteServerConfig(
        client_id="client-id",
        client_secret="client-secret",
        account_number="12345678901",
        base_url="https://example.test",
        timeout=3.5,
        max_retries=4,
        user_agent="custom-agent",
    )


def test_config_from_args_preserves_account_seq_override() -> None:
    args = parse_args(
        [
            "stdio",
            "--client-id",
            "client-id",
            "--client-secret",
            "client-secret",
            "--account-seq",
            "1",
        ]
    )

    config = config_from_args(args)

    assert config.account == "1"
    assert config.account_number is None


def test_parse_args_rejects_client_id_value_and_command() -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "stdio",
                "--client-id",
                "client-id",
                "--client-id-command",
                "printf client-id",
                "--client-secret",
                "client-secret",
            ]
        )


def test_config_rejects_account_number_and_seq_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOSSINVEST_ACCOUNT_NO", "12345678901")
    monkeypatch.setenv("TOSSINVEST_ACCOUNT_SEQ", "1")
    args = parse_args(["stdio", "--client-id", "client-id", "--client-secret", "client-secret"])

    with pytest.raises(TossInvestMCPRemoteConfigError):
        config_from_args(args)


def test_http_config_from_args_preserves_oauth_settings() -> None:
    args = parse_args(
        [
            "serve-http",
            "--client-id",
            "client-id",
            "--client-secret",
            "client-secret",
            "--oauth-issuer-url",
            "https://auth.example.com",
            "--oauth-resource-url",
            "https://mcp.example.com/mcp",
            "--oauth-jwks-uri",
            "https://auth.example.com/.well-known/jwks.json",
            "--oauth-required-scope",
            "tossinvest:read",
            "--oauth-allowed-email",
            "owner@example.com",
        ]
    )

    http_config = http_config_from_args(args)

    assert http_config.oauth is not None
    assert http_config.oauth.issuer_url == "https://auth.example.com"
    assert http_config.oauth.resource_url == "https://mcp.example.com/mcp"
    assert http_config.oauth.required_scopes == ("tossinvest:read",)
    assert http_config.oauth.allowed_emails == ("owner@example.com",)


def test_http_config_rejects_incomplete_oauth_settings() -> None:
    args = parse_args(
        [
            "serve-http",
            "--client-id",
            "client-id",
            "--client-secret",
            "client-secret",
            "--oauth-issuer-url",
            "https://auth.example.com",
        ]
    )

    with pytest.raises(TossInvestMCPRemoteConfigError):
        http_config_from_args(args)


def test_http_config_rejects_static_bearer_with_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOSSINVEST_MCP_BEARER_TOKEN", "secret")
    args = parse_args(
        [
            "serve-http",
            "--client-id",
            "client-id",
            "--client-secret",
            "client-secret",
            "--oauth-issuer-url",
            "https://auth.example.com",
            "--oauth-resource-url",
            "https://mcp.example.com/mcp",
            "--oauth-jwks-uri",
            "https://auth.example.com/.well-known/jwks.json",
        ]
    )

    with pytest.raises(TossInvestMCPRemoteConfigError):
        http_config_from_args(args)


def test_config_create_client_does_not_resolve_account_number() -> None:
    config = TossInvestRemoteServerConfig(
        client_id="client-id",
        client_secret="client-secret",
        account_number="12345678901",
    )

    with config.create_client() as client:
        assert client.config.default_account is None


def test_config_resolves_account_number_once(httpx_mock: HTTPXMock) -> None:
    add_token_response(httpx_mock)
    add_api_response(
        httpx_mock,
        method="GET",
        url=f"{BASE_URL}/api/v1/accounts",
        result=[account_payload(account_seq=1)],
    )
    config = TossInvestRemoteServerConfig(
        client_id="client-id",
        client_secret="client-secret",
        account_number="12345678901",
    )

    assert config.account_seq_for_tool() == 1
    assert config.account_seq_for_tool() == 1

    account_requests = [
        request
        for request in httpx_mock.get_requests(method="GET")
        if request.url.path == "/api/v1/accounts"
    ]
    assert len(account_requests) == 1


def test_config_refreshes_cached_account_after_ttl(
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = 100.0
    monkeypatch.setattr("tossinvest_mcp_remote.config.time.monotonic", lambda: current_time)
    add_token_response(httpx_mock, token="token-1")
    add_api_response(
        httpx_mock,
        method="GET",
        url=f"{BASE_URL}/api/v1/accounts",
        result=[account_payload(account_seq=1)],
    )
    add_token_response(httpx_mock, token="token-2")
    add_api_response(
        httpx_mock,
        method="GET",
        url=f"{BASE_URL}/api/v1/accounts",
        result=[account_payload(account_seq=2)],
    )
    config = TossInvestRemoteServerConfig(
        client_id="client-id",
        client_secret="client-secret",
        account_number="12345678901",
        account_cache_ttl=60.0,
    )

    assert config.account_seq_for_tool() == 1
    current_time = 160.0
    assert config.account_seq_for_tool() == 2

    account_requests = [
        request
        for request in httpx_mock.get_requests(method="GET")
        if request.url.path == "/api/v1/accounts"
    ]
    assert len(account_requests) == 2
