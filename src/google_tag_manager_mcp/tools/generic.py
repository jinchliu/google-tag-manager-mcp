"""The generic verb tools: one tool per verb, dispatching on resource or path.

``gtm_list`` and ``gtm_create`` take a ``resource`` name plus the parent path;
``gtm_get``, ``gtm_update``, ``gtm_delete`` and ``gtm_revert`` infer the
resource from the last collection in the path. Together they cover every
list / get / create / update / delete / revert method of the API.
"""

from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

from google_tag_manager_mcp import client, discovery, paths, projection, render
from google_tag_manager_mcp.registry import Tier, require_confirm, tool

ListResource = Literal[
    'accounts',
    'containers',
    'destinations',
    'environments',
    'version_headers',
    'workspaces',
    'built_in_variables',
    'clients',
    'folders',
    'gtag_config',
    'tags',
    'templates',
    'transformations',
    'triggers',
    'variables',
    'zones',
    'user_permissions',
]


# Built-in variables are keyed by type, not id, so their create / delete /
# revert methods live in dedicated tools instead of the generic verbs.
_SPECIAL_COLLECTIONS = frozenset({'built_in_variables'})


def _method_ids(verb: str) -> dict[str | None, str]:
    """Maps every collection that has ``<verb>`` to that method's id."""
    found: dict[str | None, str] = {}
    for collection in discovery.collections():
        if collection in _SPECIAL_COLLECTIONS and verb != 'list':
            continue
        spec = discovery.find_method(collection, verb)
        if spec is not None:
            found[collection] = spec.id
    return found


def _require_verb(parsed: paths.ResourcePath, verb: str) -> discovery.Method:
    """Returns the ``<collection>.<verb>`` method for a parsed path or explains."""
    spec = discovery.find_method(parsed.collection, verb)
    if spec is None or parsed.id is None:
        supported = ', '.join(sorted(str(name) for name in _method_ids(verb)))
        raise ToolError(
            f'{verb} is not available for {parsed.collection} at {parsed!s};'
            f' it works for: {supported}'
        )
    return spec


@tool(tier=Tier.READ, methods=_method_ids('list'))
def gtm_list(
    resource: ListResource,
    parent: str | None = None,
    response_format: render.ResponseFormat = 'markdown',
    include_deleted: bool = False,
    include_google_tags: bool = False,
    page_token: str | None = None,
    max_pages: int = 20,
) -> CallToolResult:
    """Lists resources of one kind under a parent path.

    Parents: accounts need none; containers and user_permissions take
    accounts/{id}; destinations, environments, version_headers and workspaces
    take accounts/{id}/containers/{id}; everything else (tags, triggers,
    variables, folders, templates, built_in_variables, clients,
    transformations, zones, gtag_config) takes .../workspaces/{id}.

    Args:
        resource: The collection to list.
        parent: Path of the enclosing resource, copied from earlier results.
        response_format: markdown (default, compact table), json (same slim
            fields as structured data) or json_full (complete configurations,
            the way to read many tags without one gtm_get per tag).
        include_deleted: version_headers only; include deleted versions.
        include_google_tags: accounts only; include Google tag accounts.
        page_token: Continue a listing that reported more pages.
        max_pages: Pages to fetch in one call (each page is one API request).
    """
    if resource == 'accounts':
        location = ''
    else:
        if parent is None:
            raise ToolError(
                f'{resource} need a parent of the form'
                f' {paths.shape(discovery.parent_collection(resource) or "")}'
            )
        location = str(paths.expect_parent(parent, resource))
    if include_deleted and resource != 'version_headers':
        raise ToolError('include_deleted only applies to version_headers')
    if include_google_tags and resource != 'accounts':
        raise ToolError('include_google_tags only applies to accounts')
    spec = discovery.method(_method_ids('list')[resource])
    extra: dict[str, Any] = {}
    if location:
        extra['parent'] = location
    if include_deleted:
        extra['includeDeleted'] = True
    if include_google_tags:
        extra['includeGoogleTags'] = True

    def fetch(token: str | None) -> dict[str, Any]:
        kwargs = dict(extra)
        if token is not None:
            kwargs['pageToken'] = token
        return client.execute(client.request(spec.id, **kwargs), mutating=False)

    items, next_token = projection.paginate(
        fetch,
        discovery.list_items_key(resource),
        page_token=page_token,
        max_pages=max_pages,
    )
    title = f'{resource} under {location}' if location else resource
    columns = projection.SLIM_FIELDS[resource]

    def summary() -> dict[str, Any]:
        return {
            'resource': resource,
            'parent': location or None,
            'count': len(items),
            'items': [projection.slim(item, resource) for item in items],
            'next_page_token': next_token,
        }

    return render.result(
        response_format,
        full={
            'resource': resource,
            'parent': location or None,
            'count': len(items),
            'items': items,
            'next_page_token': next_token,
        },
        slim=summary,
        markdown=lambda s: render.collection(
            title, s['items'], columns, next_page_token=next_token
        ),
    )


@tool(tier=Tier.READ, methods=_method_ids('get'))
def gtm_get(path: str, response_format: render.JsonFormat = 'json') -> CallToolResult:
    """Fetches one resource by its full path.

    Works for accounts, containers, destinations, environments, versions,
    workspaces, user_permissions and every workspace entity (tags, triggers,
    variables, folders, templates, clients, transformations, zones,
    gtag_config). The result is the complete configuration; edit it and send
    the changed keys back with gtm_update.

    Args:
        path: Full path such as accounts/1/containers/2/workspaces/3/tags/4.
        response_format: json (default) returns the entity as is, except for
            container versions, which are summarised (entity lists reduced to
            slim rows); json_full returns a version verbatim, which can run to
            hundreds of KB.
    """
    parsed = paths.parse(path)
    spec = _require_verb(parsed, 'get')
    full = client.execute(client.request(spec.id, path=str(parsed)), mutating=False)
    if parsed.collection == 'versions' and response_format == 'json':
        return render.json_result(projection.slim_version(full))
    return render.json_result(full)


CreateResource = Literal[
    'containers',
    'environments',
    'workspaces',
    'clients',
    'folders',
    'gtag_config',
    'tags',
    'templates',
    'transformations',
    'triggers',
    'variables',
    'zones',
    'user_permissions',
]

# versions.update only changes these; sending the embedded entity lists back
# would PUT the whole container for a rename.
_VERSION_PATCHABLE = ('name', 'description')


def _without_template_data(entity: dict[str, Any]) -> dict[str, Any]:
    """Drops templateData (often tens of KB) from an echoed CustomTemplate."""
    if 'templateData' in entity:
        entity = {k: v for k, v in entity.items() if k != 'templateData'}
        entity['templateData'] = '(omitted; use gtm_get to read it)'
    return entity


@tool(tier=Tier.WRITE, methods=_method_ids('create'))
def gtm_create(
    resource: CreateResource, parent: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Creates one resource under a parent path.

    Bodies use the API's camelCase JSON; call gtm_describe_schema('Tag') (or
    Trigger, Variable, Folder, Client, Transformation, Zone, GtagConfig,
    CustomTemplate, Container, Workspace, Environment, UserPermission) for the
    fields and example bodies. Workspace entities take .../workspaces/{id} as
    parent, containers and user_permissions take accounts/{id}, environments
    and workspaces take accounts/{id}/containers/{id}. Changes stay in the
    workspace draft until a version is created and published.

    Args:
        resource: The collection to create in.
        parent: Path of the enclosing resource.
        body: The entity, for example {"name": "...", "type": "gaawe", ...}.

    Returns:
        The created entity with its path and fingerprint (templateData is
        omitted for templates).
    """
    location = paths.expect_parent(parent, resource)
    spec = discovery.method(_method_ids('create')[resource])
    created = client.execute(
        client.request(spec.id, parent=str(location), body=body), mutating=True
    )
    return _without_template_data(created)


@tool(tier=Tier.WRITE, methods=_method_ids('update'))
def gtm_update(path: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Updates one resource by merging a patch into its current state.

    Reads the entity, applies a shallow merge patch (a top-level key replaces
    the current value, null deletes it, lists are replaced whole, nested
    objects are not merged) and writes it back with the current fingerprint,
    retrying once if the entity changed in between. Send only the keys that
    change. For versions only name and description are updatable.

    Args:
        path: Full path of the entity to update.
        patch: The keys to change, in the API's camelCase JSON.

    Returns:
        The updated entity (templateData omitted for templates).
    """
    parsed = paths.parse(path)
    spec = _require_verb(parsed, 'update')
    get_spec = _require_verb(parsed, 'get')
    for attempt in range(2):
        current = client.execute(
            client.request(get_spec.id, path=str(parsed)), mutating=False
        )
        base = (
            {k: current[k] for k in _VERSION_PATCHABLE if k in current}
            if parsed.collection == 'versions'
            else current
        )
        kwargs: dict[str, Any] = {
            'path': str(parsed),
            'body': projection.merge_patch(base, patch),
        }
        if 'fingerprint' in spec.parameters and 'fingerprint' in current:
            kwargs['fingerprint'] = current['fingerprint']
        try:
            updated = client.execute(client.request(spec.id, **kwargs), mutating=True)
        except ToolError as error:
            if attempt == 0 and 'fingerprint mismatch' in str(error):
                continue
            raise
        return _without_template_data(updated)
    raise AssertionError('unreachable')


@tool(tier=Tier.DESTRUCTIVE, methods=_method_ids('delete'))
def gtm_delete(path: str, confirm: bool = False) -> dict[str, Any]:
    """Deletes one resource by path. Irreversible; requires confirm=true.

    Works for workspace entities (tags, triggers, variables, folders,
    templates, clients, transformations, zones, gtag_config), workspaces,
    environments, versions, containers and user_permissions. Deleting a
    workspace entity only changes the draft until published; deleting a
    container or workspace takes effect immediately.

    Args:
        path: Full path of the resource.
        confirm: Must be true; ask the user first.
    """
    parsed = paths.parse(path)
    spec = _require_verb(parsed, 'delete')
    require_confirm(confirm, f'Deleting {parsed!s}')
    client.execute(client.request(spec.id, path=str(parsed)), mutating=True)
    return {'deleted': str(parsed)}


@tool(tier=Tier.DESTRUCTIVE, methods=_method_ids('revert'))
def gtm_revert(path: str, confirm: bool = False) -> dict[str, Any]:
    """Discards the workspace's unpublished changes to one entity.

    The entity returns to its state in the latest container version; an
    entity that was added in the workspace disappears. Works for tags,
    triggers, variables, folders, templates, clients, transformations and
    zones (built-in variables have gtm_revert_built_in_variable). Requires
    confirm=true.

    Args:
        path: Full path of the workspace entity.
        confirm: Must be true; ask the user first.

    Returns:
        The entity as it is after the revert, when the API returns one.
    """
    parsed = paths.parse(path)
    spec = _require_verb(parsed, 'revert')
    require_confirm(confirm, f'Reverting {parsed!s}')
    response = client.execute(client.request(spec.id, path=str(parsed)), mutating=True)
    return {'reverted': str(parsed), **response}
