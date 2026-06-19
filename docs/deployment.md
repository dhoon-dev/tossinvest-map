# Deployment

## Single-User Personal Server

Single-user mode is the milestone-1 default. One TossInvest credential set is
configured server-wide. ChatGPT and Codex clients share that configured account
context.

Anyone who can access `/mcp` can access the configured account data. Public exposure
requires HTTPS and access control.

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
  --oauth-allowed-email "you@example.com"
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
