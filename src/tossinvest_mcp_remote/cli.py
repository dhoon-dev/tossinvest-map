"""Command-line interface for the TossInvest MCP remote server."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version

from pydantic import AnyHttpUrl
from tossinvest import __version__ as tossinvest_sdk_version

from ._version import __version__
from .config import (
    DEFAULT_ACCOUNT_CACHE_TTL,
    TossInvestRemoteServerConfig,
)
from .credentials import (
    DEFAULT_CREDENTIAL_HELPER_TIMEOUT,
    resolve_credential,
    resolve_optional_secret,
)
from .errors import CredentialHelperError, TossInvestMCPRemoteConfigError
from .logging import configure_logging
from .oauth import DEFAULT_OAUTH_ALGORITHMS, OAuthResourceServerConfig
from .server_http import HTTPServerConfig, run_http
from .server_stdio import run_stdio


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Run the TossInvest MCP remote server.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    stdio_parser = subparsers.add_parser("stdio", help="Run MCP over STDIO.")
    _add_common_server_args(stdio_parser)
    stdio_parser.add_argument(
        "--allow-stdio-live-orders",
        action="store_true",
        default=_env_flag(os.getenv("TOSSINVEST_MCP_ALLOW_STDIO_LIVE_ORDERS")),
        help=(
            "Allow live order tools over local STDIO without OAuth scope checks. "
            "Use only for a trusted local Codex configuration."
        ),
    )

    http_parser = subparsers.add_parser("serve-http", help="Run MCP over Streamable HTTP.")
    _add_common_server_args(http_parser)
    http_parser.set_defaults(allow_stdio_live_orders=False)
    http_parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host.")
    http_parser.add_argument("--port", default=8000, type=int, help="HTTP bind port.")
    http_parser.add_argument(
        "--trusted-proxy",
        action="append",
        default=[],
        help="Trusted reverse proxy IP or CIDR. May be passed more than once.",
    )
    http_parser.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        help="Allowed Origin for /mcp. May be passed more than once.",
    )
    http_bearer_group = http_parser.add_mutually_exclusive_group()
    http_bearer_group.add_argument(
        "--http-bearer-token",
        help="Static bearer token for HTTP clients that support Authorization headers.",
    )
    http_bearer_group.add_argument(
        "--http-bearer-token-command",
        help="Command that prints the HTTP bearer token to stdout.",
    )
    _add_oauth_args(http_parser)
    http_parser.add_argument("--log-level", default="info", help="uvicorn log level.")

    subparsers.add_parser("version", help="Print package and SDK version information.")
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> TossInvestRemoteServerConfig:
    """Build server configuration from parsed arguments and environment."""
    client_id = resolve_credential(
        args.client_id,
        args.client_id_command,
        label="client ID",
        env_var="TOSSINVEST_CLIENT_ID",
        timeout=args.credential_helper_timeout,
    )
    client_secret = resolve_credential(
        args.client_secret,
        args.client_secret_command,
        label="client secret",
        env_var="TOSSINVEST_CLIENT_SECRET",
        timeout=args.credential_helper_timeout,
    )
    account_seq = args.account_seq or os.getenv("TOSSINVEST_ACCOUNT_SEQ")
    account_number = args.account_number or os.getenv("TOSSINVEST_ACCOUNT_NO")
    if account_seq and account_number:
        raise TossInvestMCPRemoteConfigError(
            "Use either accountSeq or accountNo, not both. "
            "Unset TOSSINVEST_ACCOUNT_SEQ or TOSSINVEST_ACCOUNT_NO if needed."
        )
    return TossInvestRemoteServerConfig(
        client_id=client_id,
        client_secret=client_secret,
        account=account_seq,
        account_number=account_number,
        base_url=args.base_url,
        timeout=args.timeout,
        max_retries=args.max_retries,
        user_agent=args.user_agent,
        account_cache_ttl=args.account_cache_ttl,
        enable_live_orders=args.enable_live_orders,
        live_order_required_scopes=tuple(args.live_order_required_scope),
        allow_stdio_live_orders=args.allow_stdio_live_orders,
        mode=args.mode,
    )


def http_config_from_args(args: argparse.Namespace) -> HTTPServerConfig:
    """Build HTTP transport configuration from parsed arguments and environment."""
    bearer_token = resolve_optional_secret(
        args.http_bearer_token,
        args.http_bearer_token_command,
        label="HTTP bearer token",
        env_var="TOSSINVEST_MCP_BEARER_TOKEN",
        timeout=args.credential_helper_timeout,
    )
    oauth = _oauth_config_from_args(args)
    if bearer_token and oauth is not None:
        raise TossInvestMCPRemoteConfigError(
            "Use either static HTTP bearer-token authentication or OAuth, not both. "
            "Unset TOSSINVEST_MCP_BEARER_TOKEN if needed."
        )
    return HTTPServerConfig(
        host=args.host,
        port=args.port,
        trusted_proxies=tuple(args.trusted_proxy),
        allowed_origins=tuple(args.allowed_origin),
        bearer_token=bearer_token,
        oauth=oauth,
        log_level=args.log_level,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entrypoint."""
    args = parse_args(argv)
    if args.command == "version":
        _print_version()
        return

    configure_logging(getattr(args, "log_level", "INFO"))
    try:
        config = config_from_args(args)
        if args.command == "stdio":
            run_stdio(config)
            return
        if args.command == "serve-http":
            run_http(config, http_config_from_args(args))
            return
    except (CredentialHelperError, TossInvestMCPRemoteConfigError) as exc:
        raise SystemExit(str(exc)) from exc

    raise SystemExit(f"Unsupported command: {args.command}")


def _add_common_server_args(parser: argparse.ArgumentParser) -> None:
    client_id_group = parser.add_mutually_exclusive_group()
    client_id_group.add_argument("--client-id", help="TossInvest OpenAPI OAuth client ID.")
    client_id_group.add_argument(
        "--client-id-command",
        help=(
            "Command that prints the TossInvest OpenAPI OAuth client ID to stdout. "
            "The command is parsed with shlex and is not run through a shell."
        ),
    )

    client_secret_group = parser.add_mutually_exclusive_group()
    client_secret_group.add_argument(
        "--client-secret",
        help="TossInvest OpenAPI OAuth client secret.",
    )
    client_secret_group.add_argument(
        "--client-secret-command",
        help=(
            "Command that prints the TossInvest OpenAPI OAuth client secret to stdout. "
            "The command is parsed with shlex and is not run through a shell."
        ),
    )

    parser.add_argument(
        "--credential-helper-timeout",
        default=DEFAULT_CREDENTIAL_HELPER_TIMEOUT,
        type=float,
        help="Credential helper timeout in seconds.",
    )
    account_group = parser.add_mutually_exclusive_group()
    account_group.add_argument(
        "--account",
        dest="account_number",
        help="Default TossInvest accountNo for account-scoped tools.",
    )
    account_group.add_argument(
        "--account-seq",
        help="Default TossInvest accountSeq for account-scoped tools.",
    )
    parser.add_argument(
        "--base-url",
        default="https://openapi.tossinvest.com",
        help="TossInvest OpenAPI base URL.",
    )
    parser.add_argument("--timeout", default=10.0, type=float, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--max-retries",
        default=2,
        type=int,
        help="Maximum retries for idempotent HTTP requests.",
    )
    parser.add_argument(
        "--user-agent",
        default="tossinvest-openapi tossinvest-mcp-remote/0.1.0",
        help="User-Agent header for TossInvest API requests.",
    )
    parser.add_argument(
        "--account-cache-ttl",
        default=DEFAULT_ACCOUNT_CACHE_TTL,
        type=float,
        help="Account list cache TTL in seconds.",
    )
    parser.add_argument(
        "--mode",
        choices=["single_user", "multi_user"],
        default="single_user",
        help="Authentication mode. Multi-user OAuth is reserved for a future milestone.",
    )
    parser.add_argument(
        "--enable-live-orders",
        action="store_true",
        default=_env_flag(os.getenv("TOSSINVEST_MCP_ENABLE_LIVE_ORDERS")),
        help="Register live order creation, modification, and cancellation tools.",
    )
    parser.add_argument(
        "--live-order-required-scope",
        action="append",
        default=_split_env_values(os.getenv("TOSSINVEST_MCP_LIVE_ORDER_REQUIRED_SCOPES")),
        help=(
            "OAuth scope required only for live order tools. May be repeated. "
            "Use with --enable-live-orders for single-endpoint tool-level authorization."
        ),
    )


def _add_oauth_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--oauth-issuer-url",
        default=os.getenv("TOSSINVEST_MCP_OAUTH_ISSUER_URL"),
        help="OAuth authorization server issuer URL.",
    )
    parser.add_argument(
        "--oauth-resource-url",
        default=os.getenv("TOSSINVEST_MCP_OAUTH_RESOURCE_URL"),
        help="Public MCP resource URL, usually the HTTPS /mcp endpoint.",
    )
    parser.add_argument(
        "--oauth-jwks-uri",
        default=os.getenv("TOSSINVEST_MCP_OAUTH_JWKS_URI"),
        help="Authorization server JWKS URI used to validate access-token signatures.",
    )
    parser.add_argument(
        "--oauth-audience",
        action="append",
        default=_split_env_values(os.getenv("TOSSINVEST_MCP_OAUTH_AUDIENCES")),
        help="Accepted JWT audience. Defaults to --oauth-resource-url. May be repeated.",
    )
    parser.add_argument(
        "--oauth-required-scope",
        action="append",
        default=_split_env_values(os.getenv("TOSSINVEST_MCP_OAUTH_REQUIRED_SCOPES")),
        help="Required OAuth scope for /mcp. May be repeated.",
    )
    parser.add_argument(
        "--oauth-allowed-subject",
        action="append",
        default=_split_env_values(os.getenv("TOSSINVEST_MCP_OAUTH_ALLOWED_SUBJECTS")),
        help="Allowed token subject for personal deployments. May be repeated.",
    )
    parser.add_argument(
        "--oauth-allowed-email",
        action="append",
        default=_split_env_values(os.getenv("TOSSINVEST_MCP_OAUTH_ALLOWED_EMAILS")),
        help="Allowed token email for personal deployments. May be repeated.",
    )
    parser.add_argument(
        "--oauth-algorithm",
        action="append",
        default=_split_env_values(os.getenv("TOSSINVEST_MCP_OAUTH_ALGORITHMS")),
        help="Accepted JWT signing algorithm. Defaults to RS256 and ES256. May be repeated.",
    )
    parser.add_argument(
        "--oauth-jwks-cache-ttl",
        default=float(os.getenv("TOSSINVEST_MCP_OAUTH_JWKS_CACHE_TTL", "300")),
        type=float,
        help="JWKS cache TTL in seconds.",
    )
    parser.add_argument(
        "--oauth-leeway",
        default=float(os.getenv("TOSSINVEST_MCP_OAUTH_LEEWAY", "30")),
        type=float,
        help="JWT time validation leeway in seconds.",
    )


def _oauth_config_from_args(args: argparse.Namespace) -> OAuthResourceServerConfig | None:
    oauth_fields = {
        "issuer URL": args.oauth_issuer_url,
        "resource URL": args.oauth_resource_url,
        "JWKS URI": args.oauth_jwks_uri,
    }
    oauth_requested = any(oauth_fields.values()) or any(
        (
            args.oauth_audience,
            args.oauth_required_scope,
            args.oauth_allowed_subject,
            args.oauth_allowed_email,
            args.oauth_algorithm,
        )
    )
    if not oauth_requested:
        return None
    missing = [label for label, value in oauth_fields.items() if not value]
    if missing:
        raise TossInvestMCPRemoteConfigError(
            "OAuth configuration is incomplete. Missing: " + ", ".join(missing) + "."
        )
    oauth = OAuthResourceServerConfig(
        issuer_url=args.oauth_issuer_url,
        resource_url=args.oauth_resource_url,
        jwks_uri=args.oauth_jwks_uri,
        audiences=tuple(args.oauth_audience),
        required_scopes=tuple(args.oauth_required_scope),
        allowed_subjects=tuple(args.oauth_allowed_subject),
        allowed_emails=tuple(args.oauth_allowed_email),
        algorithms=tuple(args.oauth_algorithm) or DEFAULT_OAUTH_ALGORITHMS,
        jwks_cache_ttl=args.oauth_jwks_cache_ttl,
        leeway=args.oauth_leeway,
    )
    try:
        oauth.auth_settings()
        AnyHttpUrl(oauth.jwks_uri)
    except ValueError as exc:
        raise TossInvestMCPRemoteConfigError(
            "OAuth configuration contains an invalid URL."
        ) from exc
    return oauth


def _split_env_values(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item for item in value.replace(",", " ").split() if item]


def _env_flag(value: str | None) -> bool:
    return value is not None and value.strip().casefold() in {"1", "true", "yes", "on"}


def _print_version() -> None:
    try:
        package_version = version("tossinvest-mcp-remote")
    except PackageNotFoundError:
        package_version = __version__
    sys.stdout.write(f"tossinvest-mcp-remote {package_version}\n")
    sys.stdout.write(f"tossinvest-openapi {tossinvest_sdk_version}\n")
