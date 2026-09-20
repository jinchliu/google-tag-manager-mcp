"""The single MCPServer instance, its instructions, and the stdio entry point."""

import logging
import os
import sys

from mcp.server.mcpserver import MCPServer

from google_tag_manager_mcp import package_version

SERVER_NAME = 'google-tag-manager-mcp'
SERVER_TITLE = 'Google Tag Manager'
SERVER_DESCRIPTION = 'A stdio MCP server for Google Tag Manager with full API coverage.'

# Claude Code truncates server instructions at 2KB, so the essentials come first
# and tests/test_protocol.py asserts the limit.
INSTRUCTIONS = """\
Google Tag Manager (GTM) API v2. Every locator argument (parent, path, container,
workspace, version, environment, folder) is the API path string exactly as it
appears in the "path" field of earlier results, for example
accounts/123/containers/456/workspaces/7/tags/8. Never invent ids: discover
them with gtm_list.

Hierarchy: account > container > workspace > (tags, triggers, variables,
folders, templates, built_in_variables, clients, transformations, zones,
gtag_config). Versions and environments belong to a container; user_permissions
belong to an account. Only server containers have clients and transformations.

Typical flow: gtm_list('accounts') > gtm_list('containers', parent) >
gtm_list('workspaces', parent) > edit entities in a workspace >
gtm_get_workspace_status > gtm_create_version (consumes the workspace and
returns newWorkspacePath) > gtm_publish_version. Editing a workspace changes
nothing on the live site until a version is published. Rollback = publish an
older version; gtm_set_latest_version is not a rollback.

Entity bodies are the API's camelCase JSON. Call gtm_describe_schema('Tag') (or
'Trigger', 'Variable', 'Parameter', a method id, ...) for fields, enums and
examples. gtm_update sends a shallow merge patch (null deletes a key, lists are
replaced whole) and handles fingerprints itself. For many edits at once prefer
gtm_bulk_update_workspace, which is a single request.

Quota is 25 requests per 100 seconds per GCP project. The server serialises and
rate-limits calls, so prefer one gtm_list (json_full returns complete configs)
over loops of gtm_get. Built-in triggers (ids starting 21474795) never appear
in trigger lists.

Destructive tools (delete, revert, publish, create_version, set_latest,
bulk_update, combine, move_tag_id, link_destination, reauthorize) require
confirm=true; ask the user before passing it.
"""

server = MCPServer(
    name=SERVER_NAME,
    title=SERVER_TITLE,
    description=SERVER_DESCRIPTION,
    version=package_version(),
    instructions=INSTRUCTIONS,
)


def register_tools() -> None:
    """Imports the tool modules, which registers every tool on ``server``.

    The import happens here rather than at module top because the tool modules
    import ``server`` themselves.
    """
    import google_tag_manager_mcp.tools  # noqa: F401


def run_server() -> None:
    """Configures logging to stderr and serves MCP over stdio.

    stdout carries the protocol, so every log line must go to stderr.
    """
    level = os.environ.get('GTM_MCP_LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format='%(levelname)s %(name)s: %(message)s',
    )
    # googleapiclient logs every 403 it sees; execute() already explains them.
    logging.getLogger('googleapiclient').setLevel(logging.ERROR)
    register_tools()
    server.run(transport='stdio')
