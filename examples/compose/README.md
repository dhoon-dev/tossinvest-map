# Docker Compose examples

These examples run `tossinvest-mcp-remote` behind a reverse proxy. Copy the
`.env.example` next to the proxy example you use to `.env`, then run that
compose file explicitly.

Traefik:

```bash
cp examples/compose/traefik/.env.example .env
docker compose --env-file .env -f examples/compose/traefik/compose.yaml up -d
```

Nginx:

```bash
cp examples/compose/nginx/.env.example .env
docker compose --env-file .env -f examples/compose/nginx/compose.yaml up -d
```

The Nginx example binds to `127.0.0.1` by default. Change
`NGINX_BIND_ADDRESS` only when a public listener is intentional and TLS/access
control are handled outside this compose file.

Both compose examples are read-only by default. To register live order tools, set
`TOSSINVEST_MCP_ENABLE_LIVE_ORDERS=true` and configure
`TOSSINVEST_MCP_LIVE_ORDER_REQUIRED_SCOPES`, for example `tossinvest:trade`.
The OAuth provider must issue that scope to callers allowed to place, modify, or
cancel orders.
