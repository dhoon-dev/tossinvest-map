# ChatGPT Apps and Connectors

Milestone 1 is a data-only MCP app for personal single-user deployments. It exposes
MCP tools only. It does not serve an iframe UI, widget resources, or custom UI
components.

## Endpoint

ChatGPT must be able to reach a public HTTPS URL that includes the MCP path:

```text
https://your-domain.example/mcp
```

The app itself may listen on internal HTTP. Terminate HTTPS and enforce public access
control in infrastructure:

```text
https://your-domain.example/mcp     -> http://app:8000/mcp
https://your-domain.example/healthz -> http://app:8000/healthz
```

## Setup

1. Enable developer mode if required by the current ChatGPT UI.
2. Open Settings -> Apps & Connectors or Settings -> Connectors.
3. Create a connector or app.
4. Enter a user-facing name.
5. Enter a short description.
6. Enter the public HTTPS `/mcp` endpoint.
7. Select OAuth authentication when your deployment uses the built-in resource-server
   mode.
8. Create the connector.
9. Verify that the expected read-only tool list appears.
10. Refresh metadata after changing tools or descriptions.

## Authentication Notes

ChatGPT Apps/Connectors should use OAuth 2.1 authorization-code flow with PKCE. This
server acts as an OAuth resource server only: it validates access tokens issued by an
external authorization server and exposes protected-resource metadata at:

```text
https://your-domain.example/.well-known/oauth-protected-resource/mcp
```

Example server options:

```bash
--oauth-issuer-url "https://auth.example.com/realms/tossinvest"
--oauth-resource-url "https://your-domain.example/mcp"
--oauth-jwks-uri "https://auth.example.com/realms/tossinvest/protocol/openid-connect/certs"
--oauth-audience "https://your-domain.example/mcp"
--oauth-required-scope "tossinvest:read"
--oauth-allowed-email "you@example.com"
```

The issuer URL must match the token `iss` claim exactly. The audience defaults to the
resource URL when `--oauth-audience` is omitted.

Do not claim static bearer-token authentication works with ChatGPT unless you verify it
against the current ChatGPT Apps/Connectors UI and documentation. For public exposure,
use HTTPS and access control.

OAuth authenticates the ChatGPT caller but does not create per-user TossInvest
credentials. Personal deployments should restrict the authorization server or use
`--oauth-allowed-subject` / `--oauth-allowed-email` so only the intended user can
access the server.

## Safety Notes

The server exposes financial account and market data. It does not provide investment
advice and does not include live order tools in milestone 1.
