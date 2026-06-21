# Security

## Credential Handling

The package does not automatically read `.env` files. The CLI launch layer can read
environment variables and passes credentials explicitly into server configuration.

Prefer credential helper commands:

```bash
--client-id-command "/usr/bin/security find-generic-password -s tossinvest-api-key -w"
--client-secret-command "/usr/bin/security find-generic-password -s tossinvest-secret-key -w"
```

Helper commands are parsed with `shlex` and run without a shell. Stdout is trimmed and
used as the credential. Stdout, stderr, API keys, client secrets, bearer tokens,
authorization headers, cookies, and helper command output must not be logged.

## Access Control

The Streamable HTTP endpoint exposes user-specific financial data. Public deployments
must not be left unauthenticated. Use HTTPS and one or more access controls such as
reverse proxy auth, network allowlisting, private tunnels, or supported bearer-token
headers.

For ChatGPT Apps/Connectors, use OAuth resource-server mode with an external
authorization server. The server publishes protected-resource metadata, validates
JWT access tokens with JWKS, checks issuer and audience, enforces configured scopes,
and can restrict access to configured subjects or email addresses.

## Origin and Proxy Headers

Configure `--allowed-origin` when you want the app to enforce Origin checks on `/mcp`.
Configure `--trusted-proxy` before trusting `X-Forwarded-*` headers. Forwarded headers
from untrusted clients are ignored.

## OAuth Resource Server

This package does not implement an OAuth authorization server. Run one externally
and configure:

- `--oauth-issuer-url`
- `--oauth-resource-url`
- `--oauth-jwks-uri`
- `--oauth-audience`
- `--oauth-required-scope`
- `--live-order-required-scope`
- `--oauth-allowed-subject` or `--oauth-allowed-email`

OAuth authenticates the MCP caller. It does not automatically create per-user
TossInvest credentials. Do not silently share one server-wide TossInvest credential
set across multiple users. Keep one personal deployment per credential set unless a
separate credential-isolation design is added.

## Financial Scope

This server is a data access layer. It does not provide investment advice, rank
securities, suggest trades, create portfolio allocations, or make buy/sell/hold
recommendations.

Live order tools are disabled by default and are registered only with
`--enable-live-orders`. HTTP deployments also require at least one configured
`--live-order-required-scope`. The server checks those scopes at tool execution time
for `create_order`, `modify_order`, and `cancel_order`, so one `/mcp` endpoint can
serve read tools with a baseline scope such as `tossinvest:read` while live order
tools require an additional scope such as `tossinvest:trade`.

Local STDIO deployments can opt in with `--allow-stdio-live-orders`. That mode is for
a trusted local Codex process only; it does not provide OAuth authorization because
STDIO has no caller access token.

Configure MCP client approval policies for `create_order`, `modify_order`, and
`cancel_order` before exposing live order tools to real accounts.
