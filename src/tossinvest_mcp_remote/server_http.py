"""Streamable HTTP MCP transport entrypoint."""

from __future__ import annotations

import contextlib
import ipaddress
import secrets
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import TossInvestRemoteServerConfig
from .health import healthz
from .oauth import OAuthResourceServerConfig, create_mcp_resource_server_auth
from .server import create_server


@dataclass(frozen=True, slots=True)
class HTTPServerConfig:
    """HTTP transport settings."""

    host: str = "127.0.0.1"
    port: int = 8000
    trusted_proxies: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()
    bearer_token: str | None = field(default=None, repr=False)
    oauth: OAuthResourceServerConfig | None = field(default=None, repr=False)
    log_level: str = "info"


def create_http_app(
    config: TossInvestRemoteServerConfig,
    http_config: HTTPServerConfig | None = None,
) -> Starlette:
    """Create a Starlette app exposing `/mcp` and `/healthz`."""
    resolved_http_config = http_config or HTTPServerConfig()
    mcp_auth = (
        create_mcp_resource_server_auth(resolved_http_config.oauth)
        if resolved_http_config.oauth is not None
        else None
    )
    mcp_server = create_server(
        config,
        auth=mcp_auth.auth_settings if mcp_auth is not None else None,
        token_verifier=mcp_auth.token_verifier if mcp_auth is not None else None,
    )
    mcp_app = mcp_server.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            yield

    middleware = [
        Middleware(
            TrustedForwardedHeadersMiddleware,
            trusted_proxies=resolved_http_config.trusted_proxies,
        ),
        Middleware(
            OriginValidationMiddleware,
            allowed_origins=resolved_http_config.allowed_origins,
        ),
        Middleware(
            BearerTokenMiddleware,
            bearer_token=(
                None
                if resolved_http_config.oauth is not None
                else resolved_http_config.bearer_token
            ),
        ),
    ]
    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
        middleware=middleware,
        lifespan=lifespan,
    )


def run_http(config: TossInvestRemoteServerConfig, http_config: HTTPServerConfig) -> None:
    """Run the Streamable HTTP server with uvicorn."""
    import uvicorn

    app = create_http_app(config, http_config)
    uvicorn.run(app, host=http_config.host, port=http_config.port, log_level=http_config.log_level)


class BearerTokenMiddleware:
    """Optional static bearer-token gate for HTTP clients that support headers."""

    def __init__(self, app: ASGIApp, bearer_token: str | None = None) -> None:
        self.app = app
        self.bearer_token = bearer_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI request."""
        if not self.bearer_token or scope["type"] != "http" or not _is_mcp_path(scope):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        expected = f"Bearer {self.bearer_token}"
        supplied = headers.get("authorization", "")
        if secrets.compare_digest(supplied, expected):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"error": "unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)


class OriginValidationMiddleware:
    """Validate Origin for configured HTTP deployments."""

    def __init__(self, app: ASGIApp, allowed_origins: Sequence[str] = ()) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI request."""
        if scope["type"] != "http" or not self.allowed_origins or not _is_mcp_path(scope):
            await self.app(scope, receive, send)
            return
        origin = Headers(scope=scope).get("origin")
        if origin is None or origin in self.allowed_origins:
            await self.app(scope, receive, send)
            return
        response = JSONResponse({"error": "forbidden_origin"}, status_code=403)
        await response(scope, receive, send)


class TrustedForwardedHeadersMiddleware:
    """Apply X-Forwarded-* headers only from explicitly trusted proxies."""

    def __init__(self, app: ASGIApp, trusted_proxies: Sequence[str] = ()) -> None:
        self.app = app
        self.trusted_networks = tuple(
            ipaddress.ip_network(proxy, strict=False) for proxy in trusted_proxies
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI request."""
        if scope["type"] != "http" or not self.trusted_networks or not self._is_trusted(scope):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        forwarded_scope = dict(scope)
        proto = _first_header_value(headers.get("x-forwarded-proto"))
        if proto in {"http", "https"}:
            forwarded_scope["scheme"] = proto

        host = _first_header_value(headers.get("x-forwarded-host"))
        port = _first_header_value(headers.get("x-forwarded-port"))
        if host is not None:
            forwarded_scope["server"] = _server_from_forwarded_host(host, port)
            forwarded_scope["headers"] = _replace_host_header(scope, host)

        await self.app(forwarded_scope, receive, send)

    def _is_trusted(self, scope: Scope) -> bool:
        client = scope.get("client")
        if client is None:
            return False
        try:
            client_ip = ipaddress.ip_address(client[0])
        except ValueError:
            return False
        return any(client_ip in network for network in self.trusted_networks)


def _is_mcp_path(scope: Scope) -> bool:
    path = str(scope.get("path", ""))
    return path == "/mcp" or path.startswith("/mcp/")


def _first_header_value(value: str | None) -> str | None:
    if value is None:
        return None
    first = value.split(",", maxsplit=1)[0].strip()
    return first or None


def _server_from_forwarded_host(host: str, port: str | None) -> tuple[str, int | None]:
    if ":" in host:
        hostname, raw_port = host.rsplit(":", maxsplit=1)
        try:
            return hostname, int(raw_port)
        except ValueError:
            return hostname, None
    if port is None:
        return host, None
    try:
        return host, int(port)
    except ValueError:
        return host, None


def _replace_host_header(scope: Scope, host: str) -> list[tuple[bytes, bytes]]:
    headers = [(key, value) for key, value in scope.get("headers", []) if key.lower() != b"host"]
    headers.append((b"host", host.encode("latin-1")))
    return headers
