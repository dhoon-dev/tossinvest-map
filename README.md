# tossinvest-mcp-remote

Remote MCP server for the unofficial TossInvest OpenAPI Python SDK.

This project is not affiliated with, endorsed by, or maintained by Toss Securities.
Verify all behavior against the official API documentation before using this server in
production. The server exposes read-only tools by default. The server does not provide
investment advice. Live order tools are not included in milestone 1.

## Purpose

`tossinvest-openapi` provides the SDK and a local STDIO MCP server. This repository
exists separately to provide a production-oriented remote MCP layer for ChatGPT
Apps/Connectors and Codex, including Streamable HTTP at `/mcp`, while keeping a
STDIO entrypoint for local Codex usage.

This repository does not vendor or reimplement the SDK. It depends on
`tossinvest-openapi[mcp]` and calls public APIs such as `TossInvestClient`.

## Installation

Development currently uses the public HTTPS Git dependency:

```toml
dependencies = [
  "tossinvest-openapi[mcp] @ git+https://github.com/dhoon-dev/tossinvest-openapi.git@main",
]
```

When a matching package release is available, deployments can use PyPI:

```toml
dependencies = [
  "tossinvest-openapi[mcp]>=1.0.1",
]
```

## STDIO

```bash
uv run tossinvest-mcp-remote stdio \
  --client-id-command "/usr/bin/security find-generic-password -s tossinvest-api-key -w" \
  --client-secret-command "/usr/bin/security find-generic-password -s tossinvest-secret-key -w" \
  --account "12345678901"
```

Environment-variable launch is also supported by the CLI layer:

```bash
TOSSINVEST_CLIENT_ID="..." \
TOSSINVEST_CLIENT_SECRET="..." \
TOSSINVEST_ACCOUNT_NO="12345678901" \
uv run tossinvest-mcp-remote stdio
```

STDIO mode writes MCP protocol messages to stdout only. Diagnostics go to stderr.

## HTTP

Local development binds to localhost by default:

```bash
uv run tossinvest-mcp-remote serve-http \
  --host 127.0.0.1 \
  --port 8000 \
  --client-id-command "/usr/bin/security find-generic-password -s tossinvest-api-key -w" \
  --client-secret-command "/usr/bin/security find-generic-password -s tossinvest-secret-key -w" \
  --account "12345678901"
```

Behind a reverse proxy or in a container, bind explicitly:

```bash
uv run tossinvest-mcp-remote serve-http \
  --host 0.0.0.0 \
  --port 8000 \
  --trusted-proxy "10.0.0.0/8" \
  --client-id-command "/usr/bin/security find-generic-password -s tossinvest-api-key -w" \
  --client-secret-command "/usr/bin/security find-generic-password -s tossinvest-secret-key -w" \
  --account "12345678901"
```

The app serves internal HTTP. Public HTTPS, TLS certificates, mTLS, IP allowlisting,
and product-specific bot controls belong at the reverse proxy or load balancer.

```text
https://your-domain.example/mcp     -> http://app:8000/mcp
https://your-domain.example/healthz -> http://app:8000/healthz
```

## Access Control

Milestone 1 is single-user personal server mode. One TossInvest credential set is
configured server-wide, so ChatGPT and Codex share the same account context. Anyone
who can access the MCP endpoint may access the configured account data.

For public HTTP deployments, use HTTPS plus access control:

- reverse proxy authentication
- network allowlisting
- private tunnel for development
- optional static bearer-token check for clients that can send `Authorization`
- OAuth 2.1 resource-server mode for ChatGPT Apps/Connectors

For ChatGPT Apps/Connectors, prefer OAuth resource-server mode with an external
authorization server such as Keycloak, Zitadel, Auth0, or Ory Hydra:

```bash
uv run tossinvest-mcp-remote serve-http \
  --host 0.0.0.0 \
  --port 8000 \
  --trusted-proxy "10.0.0.0/8" \
  --client-id-command "cat /run/secrets/tossinvest_client_id" \
  --client-secret-command "cat /run/secrets/tossinvest_client_secret" \
  --account "12345678901" \
  --oauth-issuer-url "https://auth.example.com/realms/tossinvest" \
  --oauth-resource-url "https://your-domain.example/mcp" \
  --oauth-jwks-uri "https://auth.example.com/realms/tossinvest/protocol/openid-connect/certs" \
  --oauth-audience "https://your-domain.example/mcp" \
  --oauth-required-scope "tossinvest:read" \
  --oauth-allowed-email "you@example.com"
```

This server verifies OAuth access tokens on every `/mcp` request but does not issue
tokens itself. Keep using one server instance per TossInvest credential set unless you
also add a separate per-user TossInvest credential mapping layer.

## Accounts

`--account` accepts the official account number (`accountNo`) and resolves it lazily
to `accountSeq` when an account-scoped tool first needs it. `--account-seq` accepts
the official `accountSeq` directly and avoids account discovery. Account list results
are cached briefly with a 1-second default TTL to avoid unnecessary ACCOUNT rate-limit
usage.

Do not pass `accountNo` into account-scoped tools. Tool overrides use `account_seq`.

## Credential Helpers

Credential helper commands are parsed with `shlex` and run without a shell. The
trimmed stdout value becomes the credential. The server does not log helper stdout,
stderr, API keys, client secrets, authorization headers, cookies, or bearer tokens.

macOS Keychain:

```bash
/usr/bin/security add-generic-password -U -a "$USER" -s tossinvest-api-key -w
/usr/bin/security add-generic-password -U -a "$USER" -s tossinvest-secret-key -w
```

Ubuntu `pass`:

```bash
pass insert tossinvest/api-key
pass insert tossinvest/secret-key
```

Command-line arguments and environment variables can be visible to local tools or
process managers. Prefer credential helper commands for personal deployments.

## ChatGPT

Expose a public HTTPS URL ending in `/mcp`, then create an Apps/Connectors entry with
that URL. Milestone 1 provides MCP tools only: no iframe UI, widget resources, or
custom UI components. See [docs/chatgpt.md](docs/chatgpt.md).

## Codex

Codex can use either a local STDIO server or a Streamable HTTP URL. Prefer editing
`~/.codex/config.toml` because it supports explicit URLs, bearer token environment
variables, headers, timeout settings, tool allow/deny lists, and approval settings.
See [docs/codex.md](docs/codex.md).

## Tools

The default tool list is read-only:

- account lookup: `list_accounts`, `find_account_by_number`
- stock information: `get_stock`, `get_stocks`, `get_stock_warnings`
- market data: `get_orderbook`, `get_price`, `get_prices`, `get_trades`,
  `get_price_limit`, `get_candles`
- market information: `get_exchange_rate`, `get_kr_market_calendar`,
  `get_us_market_calendar`
- account data: `get_holdings`, `list_orders`, `get_order`, `get_buying_power`,
  `get_sellable_quantity`, `get_commissions`

Live order creation, modification, and cancellation are deliberately excluded from
milestone 1. If added later, they must require explicit opt-in and separate warnings.

## Development

```bash
uv lock
uv sync --locked --all-extras
uv run ruff format .
uv run ruff check .
uv run ty check
uv run pytest
```

Normal tests use mocked SDK or HTTP behavior and do not require real TossInvest
credentials or network access.
