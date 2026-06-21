# Deployment

## Single-User Personal Server

Single-user mode is the default. One TossInvest credential set is configured
server-wide. ChatGPT and Codex clients share that configured account context.

Anyone who can access `/mcp` can access the configured account data. Public exposure
requires HTTPS and access control.

Live order tools are disabled by default. If you enable them, configure a distinct
tool-level OAuth scope with `--live-order-required-scope`. A single `/mcp` endpoint
can require `tossinvest:read` globally while requiring `tossinvest:trade` only for
`create_order`, `modify_order`, and `cancel_order`.

For local Codex over STDIO, live order tools can instead be enabled with
`--enable-live-orders --allow-stdio-live-orders`. This is a local opt-in and should
not be used as an HTTP access-control substitute.

Configure MCP client approval policies for `create_order`, `modify_order`, and
`cancel_order` before enabling live order tools on a real account.


Recommended controls:

- reverse proxy authentication
- network allowlisting
- private tunnel for development
- optional static bearer-token checks for clients that can send headers
- OAuth resource-server mode for ChatGPT Apps/Connectors

## OAuth Resource Server

OAuth mode validates JWT access tokens from an external authorization server. The app
does not host login, consent, authorization, token, registration, or revocation
endpoints. Configure your authorization server separately, then run:

```bash
uv run tossinvest-mcp-remote serve-http \
  --host 0.0.0.0 \
  --port 8000 \
  --oauth-issuer-url "https://auth.example.com/realms/tossinvest" \
  --oauth-resource-url "https://your-domain.example/mcp" \
  --oauth-jwks-uri "https://auth.example.com/realms/tossinvest/protocol/openid-connect/certs" \
  --oauth-required-scope "tossinvest:read" \
  --live-order-required-scope "tossinvest:trade" \
  --oauth-allowed-email "you@example.com" \
  --enable-live-orders
```

The server rejects missing or invalid bearer tokens, validates issuer and audience,
fetches JWKS with a short cache, and enforces configured scopes. If you need true
multi-user TossInvest access later, add a separate design that maps each authenticated
subject to isolated TossInvest credentials.

## Internal HTTP

Run the app behind infrastructure that handles TLS:

```text
https://your-domain.example/mcp     -> http://app:8000/mcp
https://your-domain.example/healthz -> http://app:8000/healthz
```

For local development, bind to `127.0.0.1`. Use `0.0.0.0` only for containers or
reverse proxy deployments where exposure is intentional.

## Compose Examples

Docker Compose examples live under `examples/compose`:

- `examples/compose/traefik/compose.yaml` for an existing Traefik deployment.
- `examples/compose/nginx/compose.yaml` for a generic Nginx reverse proxy.

Copy the matching proxy-specific env example to `.env`, fill only the values
for the selected reverse proxy, and keep secret files outside version control.
