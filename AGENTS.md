# google-tag-manager-mcp

MCP server for the Google Tag Manager API v2 over stdio, Python 3.14, official
`mcp` SDK 2.x (`MCPServer`). 30 tools cover all 106 API methods; the coverage
is enforced by `tests/test_coverage.py` against the discovery document bundled
in google-api-python-client. This file is the canonical guide for any coding
agent; keep it client-neutral.

## Commands

```bash
uv sync                                   # deps into .venv (uv, never pip)
uv run pytest                             # ~250 offline tests, about 3 s
uv run ruff check && uv run ruff format --check && uv run mypy
uv run pre-commit run --all-files
uv run python scripts/check_discovery_drift.py  # live vs bundled discovery (network)
GTM_MCP_E2E_CONTAINER=accounts/A/containers/C GTM_MCP_E2E_PUBLISH=1 uv run pytest -m e2e tests/e2e
```

The stdio server is the console script `.venv/bin/google-tag-manager-mcp`
(after `uv sync`). Register that absolute path with your MCP client and restart
the client after code changes; tools load at startup. Client-specific notes
live next to this file (for example `CLAUDE.md` for Claude Code).

## Debugging with the MCP Inspector

The `mcp[cli]` extra is not installed and is not needed: `mcp dev` only wraps
the Inspector, and it would show zero tools anyway because tools register in
`run_server()`, not on import. Talk to the console script directly:

```bash
# Web UI on http://localhost:6274, server launched over stdio
npx @modelcontextprotocol/inspector .venv/bin/google-tag-manager-mcp

# Scripted checks (no browser)
npx @modelcontextprotocol/inspector --cli .venv/bin/google-tag-manager-mcp --method tools/list
npx @modelcontextprotocol/inspector --cli .venv/bin/google-tag-manager-mcp \
  --method tools/call --tool-name gtm_describe_schema --tool-arg name=Folder
```

The server only sees the environment the Inspector passes on, so calls that
reach the API need the quota project in a config file (keep it under `tmp/`,
it is machine specific). `-e KEY=VALUE` does not work in `--cli` mode: it
fails with `{"error":{"message":"No servers found in config file"}}`.

```json
{"mcpServers": {"gtm": {"command": ".venv/bin/google-tag-manager-mcp", "args": [],
  "env": {"GOOGLE_CLOUD_QUOTA_PROJECT": "YOUR_PROJECT"}}}}
```

```bash
npx @modelcontextprotocol/inspector --cli --config tmp/inspector.json --server gtm \
  --method tools/call --tool-name gtm_list --tool-arg resource=accounts --tool-arg response_format=json
```

For a quick poke without node, `tests/test_protocol.py` shows the in-process
route: `async with Client(server) as client: await client.call_tool(...)`.

## Architecture

```
src/google_tag_manager_mcp/
├── __init__.py      # main() (lazy import of server), package_version()
├── server.py        # the MCPServer instance, INSTRUCTIONS, register_tools(), run_server()
├── auth.py          # google.auth.default(scopes=ALL) singleton; setup hints; stdin=DEVNULL for gcloud subprocesses
├── client.py        # service(), request(), execute(): lock + sliding-window pacer + retries + HttpError -> ToolError
├── discovery.py     # index over the bundled discovery doc: methods, collections, schemas, describe()
├── paths.py         # API path parsing/validation; nesting rules derived from discovery
├── projection.py    # SLIM_FIELDS, slim_version/slim_status, merge_patch, paginate
├── render.py        # Markdown tables, CallToolResult assembly for response_format
├── registry.py      # @tool(tier=..., methods=...): annotations, read-only mode, coverage ledger
├── examples/        # anonymised example bodies served by gtm_describe_schema
└── tools/
    ├── generic.py     # gtm_list/get/create/update/delete/revert (resource or path dispatch)
    ├── containers.py  # lookup, snippet, combine, move_tag_id, link_destination, reauthorize_environment
    ├── versions.py    # latest header, live, publish, set_latest, undelete; version_result()
    ├── workspaces.py  # status, quick_preview, folder entities, sync, resolve_conflict, bulk_update,
    │                  # built-in variables, move_entities_to_folder, import_from_gallery, create_version
    └── meta.py        # gtm_describe_schema (+ examples), gtm_call_api (opt-in escape hatch)
tests/
├── conftest.py      # RecordingHttp (HTTP-layer fake under the real discovery client), FakeClock, url_parts
├── test_coverage.py # every discovery method claimed exactly once, each pair drives the declared HTTP call
├── test_protocol.py # in-memory and stdio clients: tool count, annotations, 2 KB limits, ToolError text
└── e2e/smoke_test.py  # real API, opt-in via GTM_MCP_E2E_CONTAINER
```

## Rules for changing code

- Every API call goes through `client.execute(request, mutating=...)`; a bare
  `request.execute()` loses the lock, pacing, retries and error translation.
- Raise `ToolError` (from `mcp.server.mcpserver.exceptions`) for anything the
  model should read. Any other exception reaches the model only as
  "Error executing tool X" (mcp 2.2 behaviour, verified).
- Tools are plain `def`; the SDK runs them on a worker thread. Return
  `dict[str, Any]` for structured output, or a `CallToolResult` when the tool
  offers `response_format` (markdown text only, json/json_full with
  `structured_content`). Never a union return type: the SDK wraps it in
  `{"result": ...}`.
- Register with `@tool(tier=..., methods={resource_or_None: method_id})`. The
  `methods` map is what the coverage test checks; a tool without API calls
  passes no methods.
- All locator parameters are API path strings, validated with `paths.expect`
  / `paths.expect_parent`. Never accept bare ids.
- Destructive tools take `confirm: bool = False`, call `require_confirm` before
  touching the API, and use `Tier.DESTRUCTIVE`. The protocol test asserts that
  exactly the destructive tools have a `confirm` parameter.
- Keep every tool description and the server INSTRUCTIONS under 2 KB (Claude
  Code truncates there); tests assert it.
- Offline tests use `RecordingHttp`; assert on `url_parts(call)` (path plus a
  parsed query dict), never on raw query-string order.
- `SERVER_DESCRIPTION` in `server.py` and `description` in `pyproject.toml` are
  the same sentence by rule; `test_protocol.py` reads the TOML and compares, so
  edit both or neither.
- Comments and docs in English; single quotes; ruff default 88 columns; Google
  style docstrings; mypy strict is the type checker of record. Editors run
  Pylance, which is stricter in one spot: it assumes a
  `contextlib.contextmanager` block may swallow exceptions, so an assignment
  inside such a block does not narrow a type. `auth.py` uses
  `patcher.start()` / `stop()` to keep both happy.

## Hard constraints and measured facts

- GTM quota: 25 requests / 100 s and 10,000 / day per GCP project. Rate
  limiting arrives as 429 in practice; the docs still say 403.
- Which project the calls count against, first match wins (all of it is
  google-auth, nothing of ours): `GOOGLE_CLOUD_QUOTA_PROJECT`, then
  `quota_project_id` in the ADC file, then the project owning the OAuth client.
  The first two send `x-goog-user-project`; with none set the header is absent
  and the server side attributes by client id. An empty string does not clear
  the file's value (`with_quota_project_from_environment` tests truthiness).
  `gcloud auth application-default login --client-id-file=...` deliberately
  writes no quota project, so it wipes whatever `set-quota-project` put there.
  A quota project without the API enabled fails every call with
  `SERVICE_DISABLED`, and the message names the project.
- Scopes are frozen at login. Measured: `workspaces.delete` and
  `containers.delete` need `tagmanager.delete.containers`; `versions.publish`
  and `environments.reauthorize` need `tagmanager.publish` only;
  `create_version`, `quick_preview` and version update/delete/undelete need
  `edit.containerversions`; `set_latest` needs only `edit.containers`.
- The discovery client validates method names, parameter names and enum values
  itself (TypeError); `client.request` turns that into a ToolError.
- `built_in_variables`: create takes `parent` (workspace) and repeated `type`;
  delete takes `path` = `<workspace>/built_in_variables`; revert takes `path` =
  the workspace path (the template appends `/built_in_variables:revert`).
- Entities embedded in a container version carry no `path`; the Markdown
  renderer drops columns that are empty in every row.
- fingerprint mismatch is a 400 whose message contains "fingerprint" (not
  412); classify on `error.reason`, not on the request URI, which contains
  `fingerprint=...` itself.
- `create_version` consumes the workspace. `newWorkspacePath` was absent when
  a non-default workspace was consumed (observed 2026-09-18); treat it as
  optional.
- Free containers allow at most three workspaces; the e2e test creates and
  deletes one per run, so its cleanup needs `delete.containers`.
- Bundled discovery revision 20260826 matched the live document (20260916)
  method for method; `scripts/check_discovery_drift.py` is the check.
- Python floor is 3.14 by decision.
