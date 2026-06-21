# Codex Configuration

Codex can use this server over STDIO or Streamable HTTP.

## STDIO

Add a local MCP server to `~/.codex/config.toml`:

```toml
[mcp_servers.tossinvest]
command = "uvx"
args = [
  "--from",
  "git+https://github.com/dhoon-dev/tossinvest-mcp-remote.git@main",
  "tossinvest-mcp-remote",
  "stdio",
  "--client-id-command",
  "/usr/bin/security find-generic-password -s tossinvest-api-key -w",
  "--client-secret-command",
  "/usr/bin/security find-generic-password -s tossinvest-secret-key -w",
  "--account",
  "12345678901",
]
startup_timeout_sec = 30
tool_timeout_sec = 60
default_tools_approval_mode = "prompt"
```

Codex passes `args` as literal process arguments. Do not rely on shell expansion inside
the list.

Local STDIO can expose live order tools for a trusted personal Codex setup:

```toml
[mcp_servers.tossinvest]
command = "uvx"
args = [
  "--from",
  "git+https://github.com/dhoon-dev/tossinvest-mcp-remote.git@main",
  "tossinvest-mcp-remote",
  "stdio",
  "--client-id-command",
  "/usr/bin/security find-generic-password -s tossinvest-api-key -w",
  "--client-secret-command",
  "/usr/bin/security find-generic-password -s tossinvest-secret-key -w",
  "--account",
  "12345678901",
  "--enable-live-orders",
  "--allow-stdio-live-orders",
]
startup_timeout_sec = 30
tool_timeout_sec = 60
default_tools_approval_mode = "approve"

[mcp_servers.tossinvest.tools.create_order]
approval_mode = "prompt"

[mcp_servers.tossinvest.tools.modify_order]
approval_mode = "prompt"

[mcp_servers.tossinvest.tools.cancel_order]
approval_mode = "prompt"
```

`--allow-stdio-live-orders` is not OAuth authorization. It is a local opt-in for a
trusted Codex process, so keep credentials isolated to the intended account.
The tool-specific approval settings prompt before each live order tool call.

## Streamable HTTP

Prefer direct `config.toml` registration for HTTP:

```toml
[mcp_servers.tossinvest]
url = "https://your-domain.example/mcp"
startup_timeout_sec = 30
tool_timeout_sec = 60
default_tools_approval_mode = "prompt"
```

With a bearer token for clients that support it:

```toml
[mcp_servers.tossinvest]
url = "https://your-domain.example/mcp"
bearer_token_env_var = "TOSSINVEST_MCP_BEARER_TOKEN"
startup_timeout_sec = 30
tool_timeout_sec = 60
default_tools_approval_mode = "prompt"
```

Do not assume the installed Codex CLI supports `codex mcp add --url`. Check:

```bash
codex mcp --help
```

Use `/mcp` in the Codex TUI to verify active MCP servers.

## OAuth

OAuth resource-server mode is intended for ChatGPT Apps/Connectors. For Codex HTTP
usage, prefer static bearer-token configuration when your installed Codex surface
supports `bearer_token_env_var`.
