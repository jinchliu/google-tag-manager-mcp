# Claude Code notes

@AGENTS.md

`AGENTS.md` is the canonical guide for this repository (commands, architecture,
rules for changing code, measured facts); the line above imports it. Everything
below is specific to Claude Code.

## Register the checkout

```bash
claude mcp add --scope user google-tag-manager-mcp \
  -e GOOGLE_CLOUD_QUOTA_PROJECT=YOUR_PROJECT \
  -- <abs path>/.venv/bin/google-tag-manager-mcp
```

Restart Claude Code after code changes; tools load at startup. `/mcp` shows the
connection state, and `claude mcp list` the registrations.

## Tool search and the 2 KB limit

Claude Code defers MCP tool definitions by default (tool search): at session
start only the tool names and the server instructions load, and it truncates
every tool description and the instructions at 2 KB each. That is the reason
behind the 2 KB rule in AGENTS.md and why `INSTRUCTIONS` in `server.py` puts the
locator rule and the workflow first. `ENABLE_TOOL_SEARCH=false claude` loads all
30 tools upfront when comparing behaviour.
