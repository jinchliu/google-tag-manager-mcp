"""Version tools: headers, the live version, and publishing."""

from typing import Any

from mcp.types import CallToolResult

from google_tag_manager_mcp import client, paths, projection, render
from google_tag_manager_mcp.registry import Tier, require_confirm, tool


def version_result(
    full: dict[str, Any],
    response_format: render.ResponseFormat,
    flags: dict[str, Any] | None = None,
) -> CallToolResult:
    """Builds the result for a response that carries a ContainerVersion.

    ``flags`` are lifted next to the summary (compilerError, syncStatus,
    newWorkspacePath) so the model sees them without digging.
    """
    version = full.get('containerVersion', full)
    extras = flags or {}

    def summary() -> dict[str, Any]:
        return {**extras, 'containerVersion': projection.slim_version(version)}

    def markdown(s: dict[str, Any]) -> str:
        head = render.key_values(extras)
        body = render.version(s['containerVersion'])
        return f'{head}\n\n{body}' if head else body

    return render.result(response_format, full=full, slim=summary, markdown=markdown)


@tool(tier=Tier.READ, methods={None: 'accounts.containers.version_headers.latest'})
def gtm_get_latest_version_header(container: str) -> dict[str, Any]:
    """Returns the header (id, name, entity counts) of the newest version.

    Args:
        container: Path of the form accounts/{id}/containers/{id}.
    """
    location = paths.expect(container, 'containers')
    return client.execute(
        client.request(
            'accounts.containers.version_headers.latest', parent=str(location)
        ),
        mutating=False,
    )


@tool(tier=Tier.READ, methods={None: 'accounts.containers.versions.live'})
def gtm_get_live_version(
    container: str, response_format: render.ResponseFormat = 'markdown'
) -> CallToolResult:
    """Returns the version currently published on the live site.

    Args:
        container: Path of the form accounts/{id}/containers/{id}.
        response_format: markdown or json summarise every entity list to slim
            rows; json_full returns the complete version, which is large.
    """
    location = paths.expect(container, 'containers')
    full = client.execute(
        client.request('accounts.containers.versions.live', parent=str(location)),
        mutating=False,
    )
    return version_result(full, response_format)


@tool(tier=Tier.DESTRUCTIVE, methods={None: 'accounts.containers.versions.publish'})
def gtm_publish_version(
    version: str,
    confirm: bool = False,
    response_format: render.ResponseFormat = 'markdown',
) -> CallToolResult:
    """Publishes a version to the live site. Requires confirm=true.

    There is no unpublish: to roll back, publish an older version (any
    version works). Check compilerError in the result.

    Args:
        version: Path of the form accounts/{id}/containers/{id}/versions/{id}.
        confirm: Must be true; ask the user first.
        response_format: markdown, json or json_full for the published version.
    """
    location = paths.expect(version, 'versions')
    require_confirm(confirm, f'Publishing {location!s} to the live site')
    full = client.execute(
        client.request('accounts.containers.versions.publish', path=str(location)),
        mutating=True,
    )
    return version_result(
        full, response_format, {'compilerError': full.get('compilerError', False)}
    )


@tool(tier=Tier.DESTRUCTIVE, methods={None: 'accounts.containers.versions.set_latest'})
def gtm_set_latest_version(version: str, confirm: bool = False) -> dict[str, Any]:
    """Makes a version the "latest": the base new workspaces sync from.

    This is not a rollback and does not change what is live; use
    gtm_publish_version for that. Requires confirm=true.

    Args:
        version: Path of the form accounts/{id}/containers/{id}/versions/{id}.
        confirm: Must be true; ask the user first.

    Returns:
        A summary of the version.
    """
    location = paths.expect(version, 'versions')
    require_confirm(confirm, f'Setting {location!s} as the latest version')
    full = client.execute(
        client.request('accounts.containers.versions.set_latest', path=str(location)),
        mutating=True,
    )
    return projection.slim_version(full)


@tool(tier=Tier.WRITE, methods={None: 'accounts.containers.versions.undelete'})
def gtm_undelete_version(version: str) -> dict[str, Any]:
    """Restores a deleted version.

    Args:
        version: Path of the form accounts/{id}/containers/{id}/versions/{id}.

    Returns:
        A summary of the restored version.
    """
    location = paths.expect(version, 'versions')
    full = client.execute(
        client.request('accounts.containers.versions.undelete', path=str(location)),
        mutating=True,
    )
    return projection.slim_version(full)
