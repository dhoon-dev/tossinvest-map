"""OAuth resource-server support for HTTP MCP deployments."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWK
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

__all__ = (
    "DEFAULT_CLIENT_ID_CLAIMS",
    "DEFAULT_JWKS_CACHE_TTL",
    "DEFAULT_JWT_LEEWAY",
    "DEFAULT_OAUTH_ALGORITHMS",
    "DEFAULT_SCOPE_CLAIMS",
    "JWTBearerTokenVerifier",
    "MCPResourceServerAuth",
    "OAuthResourceServerConfig",
    "create_auth_settings",
    "create_mcp_resource_server_auth",
)

DEFAULT_OAUTH_ALGORITHMS = ("RS256", "ES256")
DEFAULT_JWKS_CACHE_TTL = 300.0
DEFAULT_JWT_LEEWAY = 30.0
DEFAULT_CLIENT_ID_CLAIMS = ("client_id", "azp", "appid")
DEFAULT_SCOPE_CLAIMS = ("scope", "scp")


@dataclass(frozen=True, slots=True)
class OAuthResourceServerConfig:
    """Settings for validating OAuth access tokens on the MCP endpoint."""

    issuer_url: str
    resource_url: str
    jwks_uri: str
    audiences: tuple[str, ...] = ()
    required_scopes: tuple[str, ...] = ()
    allowed_subjects: tuple[str, ...] = ()
    allowed_emails: tuple[str, ...] = ()
    algorithms: tuple[str, ...] = DEFAULT_OAUTH_ALGORITHMS
    jwks_cache_ttl: float = DEFAULT_JWKS_CACHE_TTL
    leeway: float = DEFAULT_JWT_LEEWAY
    client_id_claims: tuple[str, ...] = DEFAULT_CLIENT_ID_CLAIMS
    scope_claims: tuple[str, ...] = DEFAULT_SCOPE_CLAIMS

    @property
    def accepted_audiences(self) -> tuple[str, ...]:
        """Return configured audiences, defaulting to the MCP resource URL."""
        return self.audiences or (self.resource_url,)

    def auth_settings(self) -> AuthSettings:
        """Build FastMCP auth settings for protected resource metadata."""
        return create_auth_settings(self)


@dataclass(frozen=True, slots=True)
class MCPResourceServerAuth:
    """FastMCP-compatible auth objects for an OAuth-protected MCP server."""

    auth_settings: AuthSettings
    token_verifier: TokenVerifier


def create_auth_settings(config: OAuthResourceServerConfig) -> AuthSettings:
    """Build MCP auth settings for protected resource metadata."""
    return AuthSettings(
        issuer_url=AnyHttpUrl(config.issuer_url),
        resource_server_url=AnyHttpUrl(config.resource_url),
        required_scopes=list(config.required_scopes) or None,
    )


def create_mcp_resource_server_auth(
    config: OAuthResourceServerConfig,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> MCPResourceServerAuth:
    """Build the MCP auth settings and token verifier for one resource server."""
    return MCPResourceServerAuth(
        auth_settings=create_auth_settings(config),
        token_verifier=JWTBearerTokenVerifier(config, http_client=http_client),
    )


class JWTBearerTokenVerifier:
    """Validate JWT bearer tokens from an OAuth authorization server."""

    def __init__(
        self,
        config: OAuthResourceServerConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.jwks_cache = _JWKSetCache(
            config.jwks_uri,
            ttl=config.jwks_cache_ttl,
            http_client=http_client,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify one bearer token and return MCP auth info when valid."""
        try:
            signing_key = await self.jwks_cache.get_signing_key(token, self.config.algorithms)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self.config.algorithms),
                audience=self.config.accepted_audiences,
                issuer=self.config.issuer_url,
                leeway=self.config.leeway,
                options={"require": ["aud", "exp", "iss", "sub"]},
            )
            subject = _string_claim(claims, "sub")
            if subject is None or not _principal_allowed(
                subject,
                _string_claim(claims, "email"),
                allowed_subjects=self.config.allowed_subjects,
                allowed_emails=self.config.allowed_emails,
            ):
                return None
            return AccessToken(
                token=token,
                client_id=_first_string_claim(claims, self.config.client_id_claims) or subject,
                scopes=_extract_scopes(claims, self.config.scope_claims),
                expires_at=_int_claim(claims, "exp"),
                resource=self.config.resource_url,
                subject=subject,
                claims=claims,
            )
        except (httpx.HTTPError, jwt.PyJWTError, TypeError, ValueError):
            return None


class _JWKSetCache:
    """Small async JWKS cache keyed by kid/alg."""

    def __init__(
        self,
        jwks_uri: str,
        *,
        ttl: float,
        http_client: httpx.AsyncClient | None,
    ) -> None:
        self.jwks_uri = jwks_uri
        self.ttl = ttl
        self.http_client = http_client
        self._jwks: dict[str, Any] | None = None
        self._expires_at = 0.0

    async def get_signing_key(self, token: str, algorithms: tuple[str, ...]) -> PyJWK:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if not isinstance(algorithm, str) or algorithm not in algorithms:
            raise ValueError("Unsupported JWT signing algorithm.")
        kid = header.get("kid")
        if kid is not None and not isinstance(kid, str):
            raise ValueError("Invalid JWT key ID.")

        jwk = await self._find_jwk(kid, algorithm)
        if jwk is None:
            jwk = await self._find_jwk(kid, algorithm, force_refresh=True)
        if jwk is None:
            raise ValueError("No matching JWK found.")
        return PyJWK.from_dict(jwk, algorithm=algorithm)

    async def _find_jwk(
        self,
        kid: str | None,
        algorithm: str,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        jwks = await self._get_jwks(force_refresh=force_refresh)
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            raise ValueError("JWKS response does not contain keys.")
        for jwk in keys:
            if isinstance(jwk, dict) and _jwk_matches(jwk, kid, algorithm):
                return jwk
        return None

    async def _get_jwks(self, *, force_refresh: bool) -> dict[str, Any]:
        now = time.monotonic()
        if self._jwks is not None and not force_refresh and now < self._expires_at:
            return self._jwks

        if self.http_client is None:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self.jwks_uri)
        else:
            response = await self.http_client.get(self.jwks_uri)
        response.raise_for_status()
        jwks = response.json()
        if not isinstance(jwks, dict):
            raise ValueError("JWKS response is not a JSON object.")

        self._jwks = jwks
        self._expires_at = now + self.ttl
        return jwks


def _jwk_matches(jwk: dict[str, Any], kid: str | None, algorithm: str) -> bool:
    if kid is not None and jwk.get("kid") != kid:
        return False
    jwk_algorithm = jwk.get("alg")
    return not isinstance(jwk_algorithm, str) or jwk_algorithm == algorithm


def _principal_allowed(
    subject: str,
    email: str | None,
    *,
    allowed_subjects: tuple[str, ...],
    allowed_emails: tuple[str, ...],
) -> bool:
    if not allowed_subjects and not allowed_emails:
        return True
    return subject in allowed_subjects or (
        email is not None and email.casefold() in {allowed.casefold() for allowed in allowed_emails}
    )


def _extract_scopes(claims: dict[str, Any], scope_claims: Iterable[str]) -> list[str]:
    for claim_name in scope_claims:
        value = claims.get(claim_name)
        if isinstance(value, str):
            return [scope for scope in value.split() if scope]
        if isinstance(value, list) and all(isinstance(scope, str) for scope in value):
            return value
    return []


def _first_string_claim(claims: dict[str, Any], claim_names: Iterable[str]) -> str | None:
    for claim_name in claim_names:
        value = _string_claim(claims, claim_name)
        if value is not None:
            return value
    return None


def _string_claim(claims: dict[str, Any], claim_name: str) -> str | None:
    value = claims.get(claim_name)
    if isinstance(value, str) and value:
        return value
    return None


def _int_claim(claims: dict[str, Any], claim_name: str) -> int | None:
    value = claims.get(claim_name)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
