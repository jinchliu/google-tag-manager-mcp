"""Workspace tools without a generic verb.

Status, sync, preview, versioning, built-in variables, folder contents and
gallery imports.
"""

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

from google_tag_manager_mcp import client, paths, projection, render
from google_tag_manager_mcp.registry import Tier, require_confirm, tool
from google_tag_manager_mcp.tools.versions import version_result

_FOLDER_ENTITY_KINDS = {'tag': 'tags', 'trigger': 'triggers', 'variable': 'variables'}


def status_result(
    full: dict[str, Any], response_format: render.ResponseFormat
) -> CallToolResult:
    """Builds the result for a status-like response (getStatus, sync)."""
    return render.result(
        response_format,
        full=full,
        slim=lambda: projection.slim_status(full),
        markdown=render.status,
    )


@tool(tier=Tier.READ, methods={None: 'accounts.containers.workspaces.getStatus'})
def gtm_get_workspace_status(
    workspace: str, response_format: render.ResponseFormat = 'markdown'
) -> CallToolResult:
    """Shows what a workspace changes against the latest version, and conflicts.

    Args:
        workspace: Path of the form accounts/{id}/containers/{id}/workspaces/{id}.
        response_format: markdown or json list each changed entity as kind,
            path, name and changeStatus; json_full returns the raw entities.
    """
    location = paths.expect(workspace, 'workspaces')
    full = client.execute(
        client.request('accounts.containers.workspaces.getStatus', path=str(location)),
        mutating=False,
    )
    return status_result(full, response_format)


@tool(tier=Tier.READ, methods={None: 'accounts.containers.workspaces.quick_preview'})
def gtm_quick_preview_workspace(
    workspace: str, response_format: render.ResponseFormat = 'markdown'
) -> CallToolResult:
    """Compiles the workspace without creating a version, to catch errors early.

    Args:
        workspace: Path of the form accounts/{id}/containers/{id}/workspaces/{id}.
        response_format: markdown or json summarise the compiled version;
            json_full returns it verbatim.

    Returns:
        compilerError and syncStatus alongside the compiled version summary.
    """
    location = paths.expect(workspace, 'workspaces')
    full = client.execute(
        client.request(
            'accounts.containers.workspaces.quick_preview', path=str(location)
        ),
        mutating=False,
    )
    flags = {
        'compilerError': full.get('compilerError', False),
        'syncStatus': full.get('syncStatus'),
    }
    return version_result(full, response_format, flags)


@tool(
    tier=Tier.READ,
    methods={None: 'accounts.containers.workspaces.folders.entities'},
)
def gtm_list_folder_entities(
    folder: str,
    response_format: render.ResponseFormat = 'markdown',
    page_token: str | None = None,
    max_pages: int = 20,
) -> CallToolResult:
    """Lists the tags, triggers and variables inside one folder.

    Args:
        folder: Path of the form .../workspaces/{id}/folders/{id}.
        response_format: markdown or json give slim rows per kind; json_full
            returns complete configurations.
        page_token: Continue a listing that reported more pages.
        max_pages: Pages to fetch in one call.
    """
    location = paths.expect(folder, 'folders')
    collected: dict[str, list[dict[str, Any]]] = {
        key: [] for key in _FOLDER_ENTITY_KINDS
    }
    token = page_token
    for _ in range(max_pages):
        kwargs: dict[str, Any] = {'path': str(location)}
        if token is not None:
            kwargs['pageToken'] = token
        page = client.execute(
            client.request('accounts.containers.workspaces.folders.entities', **kwargs),
            mutating=False,
        )
        for key in _FOLDER_ENTITY_KINDS:
            collected[key].extend(page.get(key, []))
        token = page.get('nextPageToken') or None
        if token is None:
            break
    full: dict[str, Any] = {
        'folder': str(location),
        **collected,
        'next_page_token': token,
    }

    def summary() -> dict[str, Any]:
        return {
            'folder': str(location),
            **{
                key: [projection.slim(item, kind) for item in collected[key]]
                for key, kind in _FOLDER_ENTITY_KINDS.items()
            },
            'next_page_token': token,
        }

    def markdown(s: dict[str, Any]) -> str:
        parts = [
            render.collection(kind, s[key], projection.SLIM_FIELDS[kind])
            for key, kind in _FOLDER_ENTITY_KINDS.items()
        ]
        if token:
            parts.append(f'More pages remain; continue with page_token={token!r}')
        return '\n\n'.join(parts)

    return render.result(response_format, full=full, slim=summary, markdown=markdown)


@tool(tier=Tier.WRITE, methods={None: 'accounts.containers.workspaces.sync'})
def gtm_sync_workspace(
    workspace: str, response_format: render.ResponseFormat = 'markdown'
) -> CallToolResult:
    """Merges the latest container version into the workspace.

    Needed before a version can be created when the container moved on. The
    result lists merge conflicts; resolve each with
    gtm_resolve_workspace_conflict.

    Args:
        workspace: Path of the form accounts/{id}/containers/{id}/workspaces/{id}.
        response_format: markdown, json or json_full.
    """
    location = paths.expect(workspace, 'workspaces')
    full = client.execute(
        client.request('accounts.containers.workspaces.sync', path=str(location)),
        mutating=True,
    )
    return status_result(full, response_format)


@tool(
    tier=Tier.WRITE,
    methods={None: 'accounts.containers.workspaces.resolve_conflict'},
)
def gtm_resolve_workspace_conflict(
    workspace: str, entity: dict[str, Any], fingerprint: str | None = None
) -> dict[str, Any]:
    """Marks one merge conflict as resolved with the given entity state.

    Args:
        workspace: Path of the form accounts/{id}/containers/{id}/workspaces/{id}.
        entity: An Entity object as reported by gtm_get_workspace_status with
            json_full: {"changeStatus": "...", "tag": {...}} (or trigger,
            variable, folder, ...), holding the state to keep.
        fingerprint: Optional fingerprint of the workspace entity; when given
            it must match the current one.
    """
    location = paths.expect(workspace, 'workspaces')
    kwargs: dict[str, Any] = {'path': str(location), 'body': entity}
    if fingerprint is not None:
        kwargs['fingerprint'] = fingerprint
    client.execute(
        client.request('accounts.containers.workspaces.resolve_conflict', **kwargs),
        mutating=True,
    )
    return {'resolved': projection.slim_entity(entity)}


@tool(
    tier=Tier.DESTRUCTIVE,
    methods={None: 'accounts.containers.workspaces.bulk_update'},
)
def gtm_bulk_update_workspace(
    workspace: str, changes: list[dict[str, Any]], confirm: bool = False
) -> dict[str, Any]:
    """Applies many entity changes to a workspace in one request.

    Each change is an Entity: {"changeStatus": "added" | "updated" |
    "deleted", "tag": {...}} (or trigger, variable, folder, client,
    transformation, zone, gtagConfig, customTemplate, builtInVariable).
    Updated and deleted entities need their ids. This is the efficient way to
    make many edits under the 25 requests / 100 s quota. Requires
    confirm=true because a single call can delete entities.

    Args:
        workspace: Path of the form accounts/{id}/containers/{id}/workspaces/{id}.
        changes: The Entity objects to apply.
        confirm: Must be true; ask the user first.

    Returns:
        The added and updated entities, as slim rows with their paths.
    """
    location = paths.expect(workspace, 'workspaces')
    require_confirm(confirm, f'Bulk-updating {len(changes)} entities in {location!s}')
    response = client.execute(
        client.request(
            'accounts.containers.workspaces.bulk_update',
            path=str(location),
            body={'changes': changes},
        ),
        mutating=True,
    )
    applied = response.get('changes', [])
    return {
        'count': len(applied),
        'changes': [projection.slim_entity(change) for change in applied],
    }


@tool(
    tier=Tier.WRITE,
    methods={None: 'accounts.containers.workspaces.built_in_variables.create'},
)
def gtm_enable_built_in_variables(workspace: str, types: list[str]) -> dict[str, Any]:
    """Enables built-in variables (pageUrl, clickClasses, eventName, ...).

    Call gtm_describe_schema('BuiltInVariable') for the full list of types.

    Args:
        workspace: Path of the form accounts/{id}/containers/{id}/workspaces/{id}.
        types: Built-in variable types to enable.
    """
    location = paths.expect(workspace, 'workspaces')
    response = client.execute(
        client.request(
            'accounts.containers.workspaces.built_in_variables.create',
            parent=str(location),
            type=types,
        ),
        mutating=True,
    )
    return {
        'enabled': [
            projection.slim(item, 'built_in_variables')
            for item in response.get('builtInVariable', [])
        ]
    }


@tool(
    tier=Tier.WRITE,
    methods={None: 'accounts.containers.workspaces.built_in_variables.delete'},
)
def gtm_disable_built_in_variables(workspace: str, types: list[str]) -> dict[str, Any]:
    """Disables built-in variables in the workspace draft (re-enable to undo).

    Args:
        workspace: Path of the form accounts/{id}/containers/{id}/workspaces/{id}.
        types: Built-in variable types to disable.
    """
    location = paths.expect(workspace, 'workspaces')
    client.execute(
        client.request(
            'accounts.containers.workspaces.built_in_variables.delete',
            path=f'{location!s}/built_in_variables',
            type=types,
        ),
        mutating=True,
    )
    return {'disabled': types}


@tool(
    tier=Tier.DESTRUCTIVE,
    methods={None: 'accounts.containers.workspaces.built_in_variables.revert'},
)
def gtm_revert_built_in_variable(
    workspace: str, type: str, confirm: bool = False
) -> dict[str, Any]:
    """Discards the workspace's change to one built-in variable.

    Args:
        workspace: Path of the form accounts/{id}/containers/{id}/workspaces/{id}.
        type: The built-in variable type, for example pageUrl.
        confirm: Must be true; ask the user first.

    Returns:
        enabled: whether the variable is enabled after the revert.
    """
    location = paths.expect(workspace, 'workspaces')
    require_confirm(confirm, f'Reverting built-in variable {type} in {location!s}')
    # The template appends /built_in_variables:revert to the workspace path
    # itself, unlike delete, whose path already names the collection.
    return client.execute(
        client.request(
            'accounts.containers.workspaces.built_in_variables.revert',
            path=str(location),
            type=type,
        ),
        mutating=True,
    )


@tool(
    tier=Tier.WRITE,
    methods={None: 'accounts.containers.workspaces.folders.move_entities_to_folder'},
)
def gtm_move_entities_to_folder(
    folder: str,
    tag_ids: list[str] | None = None,
    trigger_ids: list[str] | None = None,
    variable_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Moves tags, triggers and variables (by id) into a folder.

    Args:
        folder: Path of the form .../workspaces/{id}/folders/{id}.
        tag_ids: Tag ids (the tagId field) to move.
        trigger_ids: Trigger ids to move.
        variable_ids: Variable ids to move.
    """
    location = paths.expect(folder, 'folders')
    ids = {
        'tagId': tag_ids or [],
        'triggerId': trigger_ids or [],
        'variableId': variable_ids or [],
    }
    if not any(ids.values()):
        raise ToolError('Pass at least one of tag_ids, trigger_ids or variable_ids')
    current = client.execute(
        client.request(
            'accounts.containers.workspaces.folders.get', path=str(location)
        ),
        mutating=False,
    )
    client.execute(
        client.request(
            'accounts.containers.workspaces.folders.move_entities_to_folder',
            path=str(location),
            body=current,
            **{key: value for key, value in ids.items() if value},
        ),
        mutating=True,
    )
    return {'folder': str(location), 'moved': {k: v for k, v in ids.items() if v}}


@tool(
    tier=Tier.WRITE,
    methods={None: 'accounts.containers.workspaces.templates.import_from_gallery'},
)
def gtm_import_template_from_gallery(
    workspace: str,
    gallery_owner: str,
    gallery_repository: str,
    gallery_sha: str | None = None,
    acknowledge_permissions: bool = False,
) -> dict[str, Any]:
    """Imports a Community Template Gallery template into the workspace.

    Args:
        workspace: Path of the form accounts/{id}/containers/{id}/workspaces/{id}.
        gallery_owner: GitHub owner of the template repository.
        gallery_repository: GitHub repository name of the template.
        gallery_sha: Commit to import; the latest when omitted.
        acknowledge_permissions: Must be true to accept the permissions the
            template declares.

    Returns:
        The imported CustomTemplate (templateData omitted; gtm_get reads it).
    """
    location = paths.expect(workspace, 'workspaces')
    kwargs: dict[str, Any] = {
        'parent': str(location),
        'galleryOwner': gallery_owner,
        'galleryRepository': gallery_repository,
        'acknowledgePermissions': acknowledge_permissions,
    }
    if gallery_sha is not None:
        kwargs['gallerySha'] = gallery_sha
    template = client.execute(
        client.request(
            'accounts.containers.workspaces.templates.import_from_gallery', **kwargs
        ),
        mutating=True,
    )
    if 'templateData' in template:
        template = {k: v for k, v in template.items() if k != 'templateData'}
        template['templateData'] = '(omitted; use gtm_get to read it)'
    return template


@tool(
    tier=Tier.DESTRUCTIVE,
    methods={None: 'accounts.containers.workspaces.create_version'},
)
def gtm_create_version(
    workspace: str,
    name: str | None = None,
    notes: str | None = None,
    confirm: bool = False,
    response_format: render.ResponseFormat = 'markdown',
) -> CallToolResult:
    """Turns the workspace into a new container version. Requires confirm=true.

    The workspace is consumed: continue in the workspace named by
    newWorkspacePath. Nothing goes live until gtm_publish_version. If
    syncStatus reports a merge conflict, run gtm_sync_workspace and resolve
    the conflicts first. Free containers allow at most 3 workspaces.

    Args:
        workspace: Path of the form accounts/{id}/containers/{id}/workspaces/{id}.
        name: Version name.
        notes: Version notes.
        confirm: Must be true; ask the user first.
        response_format: markdown, json or json_full for the created version.
    """
    location = paths.expect(workspace, 'workspaces')
    require_confirm(confirm, f'Creating a version from {location!s} (consumes it)')
    body = {key: value for key, value in (('name', name), ('notes', notes)) if value}
    full = client.execute(
        client.request(
            'accounts.containers.workspaces.create_version',
            path=str(location),
            body=body,
        ),
        mutating=True,
    )
    flags = {
        'compilerError': full.get('compilerError', False),
        'newWorkspacePath': full.get('newWorkspacePath'),
        'syncStatus': full.get('syncStatus'),
    }
    return version_result(full, response_format, flags)
