# google-tag-manager-mcp

A stdio [MCP](https://modelcontextprotocol.io/) server for
[Google Tag Manager](https://developers.google.com/tag-platform/tag-manager/api/v2)
with full API coverage. 🚀🚀🚀 Empower your AI agent with the whole workflow:
audit, edit, version, publish.

## ✨ Highlights

- **Full API coverage, small tool surface.** Six verb tools and 23 dedicated ones
  reach all 106 API methods, and a test holds them to it.
- **Built for context windows.** Lists render as Markdown tables, with `json` and
  `json_full` one argument away.
- **Safe writes.** Merge patches carrying the entity's fingerprint, and
  `confirm=true` on all 11 destructive tools.
- **Quota aware.** Calls are serialised and paced under the API's 25 per 100
  seconds, and errors say what to fix.
- **Runs as you.** Your own OAuth client through Application Default Credentials.

## 🧰 Tools

| Tier | Tools |
|---|---|
| Read (10) | `gtm_list`, `gtm_get`, `gtm_lookup_container`, `gtm_get_container_snippet`, `gtm_get_latest_version_header`, `gtm_get_live_version`, `gtm_get_workspace_status`, `gtm_quick_preview_workspace`, `gtm_list_folder_entities`, `gtm_describe_schema` |
| Write (9) | `gtm_create`, `gtm_update`, `gtm_sync_workspace`, `gtm_resolve_workspace_conflict`, `gtm_enable_built_in_variables`, `gtm_disable_built_in_variables`, `gtm_move_entities_to_folder`, `gtm_import_template_from_gallery`, `gtm_undelete_version` |
| Destructive (11), `confirm=true` required | `gtm_delete`, `gtm_revert`, `gtm_revert_built_in_variable`, `gtm_publish_version`, `gtm_set_latest_version`, `gtm_create_version`, `gtm_bulk_update_workspace`, `gtm_combine_containers`, `gtm_move_tag_id`, `gtm_link_destination`, `gtm_reauthorize_environment` |

## 🔑 Setup

You need a Google Cloud project and the
[gcloud CLI](https://cloud.google.com/sdk/docs/install).

1. Enable the API on the project that will carry the quota:

   ```bash
   gcloud services enable tagmanager.googleapis.com --project=YOUR_PROJECT
   ```

2. Create a **Desktop app** OAuth client in that project
   ([Manage OAuth Clients](https://support.google.com/cloud/answer/15549257)) and
   download its JSON. Publish the consent screen to production, otherwise refresh
   tokens expire after seven days; an app for your own use needs no verification.

3. Log in. Drop any scope you do not want. The matching tools will fail with a
   clear message instead of silently doing less:

   ```bash
   gcloud auth application-default login \
     --client-id-file=YOUR_DESKTOP_CLIENT.json \
     --scopes=https://www.googleapis.com/auth/tagmanager.readonly,\
   https://www.googleapis.com/auth/tagmanager.edit.containers,\
   https://www.googleapis.com/auth/tagmanager.delete.containers,\
   https://www.googleapis.com/auth/tagmanager.edit.containerversions,\
   https://www.googleapis.com/auth/tagmanager.publish,\
   https://www.googleapis.com/auth/tagmanager.manage.users,\
   https://www.googleapis.com/auth/tagmanager.manage.accounts,\
   https://www.googleapis.com/auth/cloud-platform
   ```

   | Scope | Unlocks |
   |---|---|
   | `tagmanager.readonly` | reading accounts, containers, workspaces, versions and the entities in them |
   | `tagmanager.edit.containers` | workspace edits, containers, environments, `gtm_set_latest_version` |
   | `tagmanager.delete.containers` | deleting workspaces and containers |
   | `tagmanager.edit.containerversions` | `gtm_create_version`, `gtm_quick_preview_workspace`, version update / delete / undelete |
   | `tagmanager.publish` | `gtm_publish_version`, `gtm_reauthorize_environment` |
   | `tagmanager.manage.users` | user permissions |
   | `tagmanager.manage.accounts` | updating an account |
   | `cloud-platform` | nothing in GTM; needed when you point the quota at another project |

   Already using Google's
   [analytics-mcp](https://github.com/googleanalytics/google-analytics-mcp)?
   Reuse its OAuth client and add the `tagmanager` scopes to the
   `analytics.readonly` scope in one login.

4. Check that it works (expects a JSON list of accounts):

   ```bash
   curl -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
     https://tagmanager.googleapis.com/tagmanager/v2/accounts
   ```

   A `SERVICE_DISABLED` error names the project the quota goes to; either enable the
   API there or point `GOOGLE_CLOUD_QUOTA_PROJECT` at a project that has it.

## 🔌 Connect an MCP client

Install it:

```bash
uv tool install google-tag-manager-mcp
```

`pipx install google-tag-manager-mcp` does the same. Either one puts a
`google-tag-manager-mcp` executable on your PATH.

Which project the API calls count against, first match wins:

1. `GOOGLE_CLOUD_QUOTA_PROJECT`, as set in the client configs below.
2. `quota_project_id` in your ADC file, written by `gcloud auth
   application-default set-quota-project`. Any later `application-default
   login` rewrites that file and drops it.
3. Neither: the project that owns the OAuth client you logged in with.

Setting it in the client config pins it whatever `gcloud` does elsewhere.

### Claude

Claude Code:

```bash
claude mcp add --scope user google-tag-manager-mcp \
  -e GOOGLE_CLOUD_QUOTA_PROJECT=YOUR_PROJECT \
  -- google-tag-manager-mcp
```

Claude Desktop reads a config file instead. Open Settings > Developer > Edit
Config and add the absolute path printed by `which google-tag-manager-mcp`,
since the app does not inherit your shell PATH:

```json
{
  "mcpServers": {
    "google-tag-manager-mcp": {
      "command": "/absolute/path/to/google-tag-manager-mcp",
      "env": { "GOOGLE_CLOUD_QUOTA_PROJECT": "YOUR_PROJECT" }
    }
  }
}
```

### ChatGPT

The ChatGPT desktop app, Codex CLI and the Codex IDE extension share one config
file, so a single command covers all three:

```bash
codex mcp add google-tag-manager-mcp \
  --env GOOGLE_CLOUD_QUOTA_PROJECT=YOUR_PROJECT \
  -- google-tag-manager-mcp
```

The entry lands in `~/.codex/config.toml`, or in `.codex/config.toml` to scope it
to one project; `codex mcp list` shows what is configured.

The desktop app can do the same without the CLI:

1. Open Settings > MCP servers > Add server.
2. Choose **STDIO** and give it the command `google-tag-manager-mcp`.
3. Save, then select Restart.

ChatGPT on the web takes remote servers only, so it cannot reach this one.

## ⚙️ Configuration

| Variable | Default | Effect |
|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | unset | Standard ADC variable: an authorized_user or service_account JSON file, used before the gcloud ADC file |
| `GOOGLE_CLOUD_QUOTA_PROJECT` | unset | Standard variable: the project the calls count against, overriding the ADC file |
| `GTM_MCP_REQUESTS_PER_WINDOW` | 20 | Requests allowed per 100 s sliding window (the API allows 25 per project) |
| `GTM_MCP_READ_ONLY` | 0 | `1` registers the read tools only |
| `GTM_MCP_ENABLE_RAW_API` | 0 | `1` registers `gtm_call_api`, an escape hatch that calls any API method by id |
| `GTM_MCP_LOG_LEVEL` | INFO | Log level; logs go to stderr |

Service accounts work too: add the account's email as a user in GTM and point
`GOOGLE_APPLICATION_CREDENTIALS` at its key. Version history then shows the
service account, not you.

## 🛡️ Safety model

- Editing and going live are separate: `gtm_create`, `gtm_update`, `gtm_delete`
  and `gtm_revert` touch the workspace draft; only `gtm_publish_version` changes
  the live site. Rollback means publishing an older version.
- `gtm_update` reads the entity, applies a shallow merge patch (null deletes a key,
  lists are replaced whole) and writes back with the fingerprint, so concurrent
  edits fail instead of being clobbered.
- Destructive tools require `confirm=true`; the model is told to ask you first.
- Rate limits are retried; 5xx responses are retried for reads only, because the
  API has no idempotency key and a retried write could duplicate.
- stdout carries the protocol, logging goes to stderr, and nothing is written
  anywhere on your machine.

## Development

```bash
uv sync                      # dependencies into .venv
uv run pytest                # offline tests (an HTTP-layer fake under the real discovery client)
uv run ruff check && uv run ruff format --check && uv run mypy
uv run pre-commit run --files $(git ls-files)
uv run python scripts/check_discovery_drift.py   # live vs bundled discovery document
```

The real-API smoke test needs a throwaway container and the `delete.containers`
scope for its cleanup:

```bash
GTM_MCP_E2E_CONTAINER=accounts/ACCOUNT/containers/CONTAINER \
GTM_MCP_E2E_PUBLISH=1 uv run pytest -m e2e tests/e2e
```

## License

MIT, see [LICENSE](LICENSE).
