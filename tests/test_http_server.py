from __future__ import annotations

import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pytest_httpx import HTTPXMock
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from tossinvest_mcp_remote.config import TossInvestRemoteServerConfig
from tossinvest_mcp_remote.oauth import (
    JWTBearerTokenVerifier,
    OAuthResourceServerConfig,
    create_mcp_resource_server_auth,
)
from tossinvest_mcp_remote.server_http import (
    HTTPServerConfig,
    TrustedForwardedHeadersMiddleware,
    create_http_app,
)

ISSUER_URL = "https://auth.example.com"
JWKS_URI = f"{ISSUER_URL}/.well-known/jwks.json"
RESOURCE_URL = "https://mcp.example.com/mcp"
KEY_ID = "test-key"


def test_http_bearer_token_protects_mcp_route() -> None:
    app = create_http_app(
        TossInvestRemoteServerConfig("client-id", "client-secret"),
        HTTPServerConfig(bearer_token="secret"),
    )

    with TestClient(app) as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_http_bearer_token_does_not_protect_healthz() -> None:
    app = create_http_app(
        TossInvestRemoteServerConfig("client-id", "client-secret"),
        HTTPServerConfig(bearer_token="secret"),
    )

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200


def test_mcp_route_reaches_fastmcp_app_when_unprotected() -> None:
    app = create_http_app(
        TossInvestRemoteServerConfig("client-id", "client-secret"),
        HTTPServerConfig(),
    )

    with TestClient(app, follow_redirects=False) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert response.status_code != 404


def test_oauth_protected_resource_metadata_is_exposed() -> None:
    app = create_http_app(
        TossInvestRemoteServerConfig("client-id", "client-secret"),
        HTTPServerConfig(
            oauth=OAuthResourceServerConfig(
                issuer_url=ISSUER_URL,
                resource_url=RESOURCE_URL,
                jwks_uri=JWKS_URI,
                required_scopes=("tossinvest:read",),
            )
        ),
    )

    with TestClient(app) as client:
        response = client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    assert response.json() == {
        "resource": RESOURCE_URL,
        "authorization_servers": [f"{ISSUER_URL}/"],
        "scopes_supported": ["tossinvest:read"],
        "bearer_methods_supported": ["header"],
    }


def test_create_mcp_resource_server_auth_returns_fastmcp_inputs() -> None:
    config = OAuthResourceServerConfig(
        issuer_url=ISSUER_URL,
        resource_url=RESOURCE_URL,
        jwks_uri=JWKS_URI,
        required_scopes=("tossinvest:read",),
    )

    mcp_auth = create_mcp_resource_server_auth(config)

    assert mcp_auth.auth_settings == config.auth_settings()
    assert isinstance(mcp_auth.token_verifier, JWTBearerTokenVerifier)


def test_oauth_protects_mcp_route() -> None:
    app = create_http_app(
        TossInvestRemoteServerConfig("client-id", "client-secret"),
        HTTPServerConfig(
            oauth=OAuthResourceServerConfig(
                issuer_url=ISSUER_URL,
                resource_url=RESOURCE_URL,
                jwks_uri=JWKS_URI,
                required_scopes=("tossinvest:read",),
            )
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    assert (
        'resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"'
        in response.headers["www-authenticate"]
    )


def test_oauth_rejects_insufficient_scope(httpx_mock: HTTPXMock) -> None:
    private_key = _rsa_private_key()
    httpx_mock.add_response(method="GET", url=JWKS_URI, json=_jwks(private_key))
    app = create_http_app(
        TossInvestRemoteServerConfig("client-id", "client-secret"),
        HTTPServerConfig(
            oauth=OAuthResourceServerConfig(
                issuer_url=ISSUER_URL,
                resource_url=RESOURCE_URL,
                jwks_uri=JWKS_URI,
                required_scopes=("tossinvest:read",),
            )
        ),
    )

    token = _jwt(private_key, scope="profile")
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {token}",
            },
        )

    assert response.status_code == 403
    assert response.json()["error"] == "insufficient_scope"


@pytest.mark.asyncio
async def test_jwt_bearer_token_verifier_accepts_allowed_email(httpx_mock: HTTPXMock) -> None:
    private_key = _rsa_private_key()
    httpx_mock.add_response(method="GET", url=JWKS_URI, json=_jwks(private_key))
    verifier = JWTBearerTokenVerifier(
        OAuthResourceServerConfig(
            issuer_url=ISSUER_URL,
            resource_url=RESOURCE_URL,
            jwks_uri=JWKS_URI,
            required_scopes=("tossinvest:read",),
            allowed_emails=("owner@example.com",),
        )
    )

    access_token = await verifier.verify_token(
        _jwt(private_key, scope="profile tossinvest:read", email="owner@example.com")
    )

    assert access_token is not None
    assert access_token.client_id == "chatgpt"
    assert access_token.scopes == ["profile", "tossinvest:read"]
    assert access_token.subject == "owner"


@pytest.mark.asyncio
async def test_jwt_bearer_token_verifier_matches_allowed_email_case_insensitively(
    httpx_mock: HTTPXMock,
) -> None:
    private_key = _rsa_private_key()
    httpx_mock.add_response(method="GET", url=JWKS_URI, json=_jwks(private_key))
    verifier = JWTBearerTokenVerifier(
        OAuthResourceServerConfig(
            issuer_url=ISSUER_URL,
            resource_url=RESOURCE_URL,
            jwks_uri=JWKS_URI,
            required_scopes=("tossinvest:read",),
            allowed_emails=("owner@example.com",),
        )
    )

    access_token = await verifier.verify_token(
        _jwt(private_key, scope="profile tossinvest:read", email="Owner@Example.com")
    )

    assert access_token is not None
    assert access_token.subject == "owner"


@pytest.mark.asyncio
async def test_jwt_bearer_token_verifier_uses_provided_http_client() -> None:
    private_key = _rsa_private_key()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_jwks(private_key))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        verifier = JWTBearerTokenVerifier(
            OAuthResourceServerConfig(
                issuer_url=ISSUER_URL,
                resource_url=RESOURCE_URL,
                jwks_uri=JWKS_URI,
                required_scopes=("tossinvest:read",),
            ),
            http_client=http_client,
        )

        access_token = await verifier.verify_token(_jwt(private_key))

    assert access_token is not None
    assert [request.url for request in requests] == [httpx.URL(JWKS_URI)]


def test_origin_validation_rejects_untrusted_origin() -> None:
    app = create_http_app(
        TossInvestRemoteServerConfig("client-id", "client-secret"),
        HTTPServerConfig(allowed_origins=("https://trusted.example",)),
    )

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "https://evil.example"},
        )

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden_origin"}


def test_forwarded_headers_apply_only_for_trusted_proxy() -> None:
    async def endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"scheme": request.url.scheme, "host": request.url.hostname})

    app = Starlette(routes=[Route("/", endpoint)])
    wrapped = TrustedForwardedHeadersMiddleware(app, trusted_proxies=("10.0.0.0/8",))

    with TestClient(wrapped) as client:
        response = client.get(
            "/",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "public.example",
            },
        )

    assert response.json() == {"scheme": "http", "host": "testserver"}


def test_forwarded_headers_apply_for_trusted_proxy() -> None:
    async def endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"scheme": request.url.scheme, "host": request.url.hostname})

    app = Starlette(routes=[Route("/", endpoint)])
    wrapped = TrustedForwardedHeadersMiddleware(app, trusted_proxies=("10.0.0.0/8",))

    with TestClient(wrapped, client=("10.1.2.3", 50000)) as client:
        response = client.get(
            "/",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "public.example",
            },
        )

    assert response.json() == {"scheme": "https", "host": "public.example"}


def _rsa_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(private_key: rsa.RSAPrivateKey) -> dict[str, object]:
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": KEY_ID, "alg": "RS256"})
    return {"keys": [public_jwk]}


def _jwt(
    private_key: rsa.RSAPrivateKey,
    *,
    scope: str = "tossinvest:read",
    email: str = "owner@example.com",
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ISSUER_URL,
            "aud": RESOURCE_URL,
            "sub": "owner",
            "azp": "chatgpt",
            "email": email,
            "scope": scope,
            "iat": now,
            "exp": now + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )
