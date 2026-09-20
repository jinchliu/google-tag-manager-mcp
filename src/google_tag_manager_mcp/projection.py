"""Projections that keep tool output readable.

Slim views keep the fields a model needs to pick and reference an entity; full
configs are one ``gtm_get`` away. Container versions embed every entity of the
container, so they are summarised the same way. Also home to the merge patch
used by updates and the pagination loop used by lists.
"""

from collections.abc import Callable
from typing import Any

# Slim fields per collection; the same lists drive the Markdown columns.
# Dotted names reach into nested objects.
SLIM_FIELDS: dict[str, tuple[str, ...]] = {
    'accounts': ('path', 'accountId', 'name'),
    'containers': ('path', 'containerId', 'publicId', 'name', 'usageContext'),
    'destinations': ('path', 'destinationLinkId', 'destinationId', 'name'),
    'environments': (
        'path',
        'environmentId',
        'name',
        'type',
        'containerVersionId',
        'enableDebug',
    ),
    'version_headers': (
        'path',
        'containerVersionId',
        'name',
        'deleted',
        'numTags',
        'numTriggers',
        'numVariables',
        'numClients',
        'numTransformations',
    ),
    'workspaces': ('path', 'workspaceId', 'name', 'description'),
    'built_in_variables': ('path', 'type', 'name'),
    'clients': ('path', 'clientId', 'name', 'type', 'priority'),
    'folders': ('path', 'folderId', 'name'),
    'gtag_config': ('path', 'gtagConfigId', 'type'),
    'tags': (
        'path',
        'tagId',
        'name',
        'type',
        'firingTriggerId',
        'blockingTriggerId',
        'paused',
        'parentFolderId',
    ),
    'templates': (
        'path',
        'templateId',
        'name',
        'galleryReference.owner',
        'galleryReference.repository',
    ),
    'transformations': ('path', 'transformationId', 'name', 'type'),
    'triggers': ('path', 'triggerId', 'name', 'type', 'parentFolderId'),
    'variables': ('path', 'variableId', 'name', 'type', 'parentFolderId'),
    'zones': ('path', 'zoneId', 'name'),
    'user_permissions': (
        'path',
        'emailAddress',
        'accountAccess.permission',
        'containerAccess',
    ),
}

# ContainerVersion / Entity keys -> collection names.
ENTITY_KEYS: dict[str, str] = {
    'tag': 'tags',
    'trigger': 'triggers',
    'variable': 'variables',
    'folder': 'folders',
    'builtInVariable': 'built_in_variables',
    'client': 'clients',
    'transformation': 'transformations',
    'customTemplate': 'templates',
    'gtagConfig': 'gtag_config',
    'zone': 'zones',
}

VERSION_META_FIELDS = (
    'path',
    'containerVersionId',
    'name',
    'description',
    'deleted',
    'fingerprint',
)


def lookup(entity: dict[str, Any], dotted: str) -> Any:
    """Returns ``entity['a']['b']`` for ``'a.b'``, or None when any step is missing."""
    node: Any = entity
    for key in dotted.split('.'):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def slim(entity: dict[str, Any], collection: str) -> dict[str, Any]:
    """Keeps the slim fields of one entity; absent fields stay absent.

    The API omits empty arrays and zero counters entirely, so presence is
    tested per field rather than filled with defaults.
    """
    kept: dict[str, Any] = {}
    for field in SLIM_FIELDS[collection]:
        value = lookup(entity, field)
        if value is not None:
            kept[field] = value
    if collection == 'user_permissions' and 'containerAccess' in kept:
        kept['containerAccess'] = [
            f'{access.get("containerId", "?")}:{access.get("permission", "?")}'
            for access in kept['containerAccess']
        ]
    return kept


def slim_version(version: dict[str, Any]) -> dict[str, Any]:
    """Summarises a ContainerVersion: metadata, container, and slimmed entity lists."""
    summary: dict[str, Any] = {
        key: version[key] for key in VERSION_META_FIELDS if key in version
    }
    if 'container' in version:
        summary['container'] = slim(version['container'], 'containers')
    for key, collection in ENTITY_KEYS.items():
        if key in version:
            summary[key] = [slim(entity, collection) for entity in version[key]]
    return summary


def slim_entity(wrapper: dict[str, Any]) -> dict[str, Any]:
    """Reduces an Entity wrapper (status / conflict / bulk update) to one row."""
    for key, collection in ENTITY_KEYS.items():
        if key in wrapper:
            entity = wrapper[key]
            return {
                'kind': collection,
                'path': entity.get('path'),
                'name': entity.get('name') or entity.get('type'),
                'changeStatus': wrapper.get('changeStatus'),
            }
    return {'kind': 'unknown', 'changeStatus': wrapper.get('changeStatus')}


def slim_status(status: dict[str, Any]) -> dict[str, Any]:
    """Summarises GetWorkspaceStatusResponse (also used for sync results)."""
    summary: dict[str, Any] = {
        'changes': [
            slim_entity(change) for change in status.get('workspaceChange', [])
        ],
        'mergeConflicts': [
            slim_conflict(conflict) for conflict in status.get('mergeConflict', [])
        ],
    }
    if 'syncStatus' in status:
        summary['syncStatus'] = status['syncStatus']
    return summary


def slim_conflict(conflict: dict[str, Any]) -> dict[str, Any]:
    """Reduces a MergeConflict to the two sides' identities and statuses."""
    workspace = slim_entity(conflict.get('entityInWorkspace', {}))
    base = slim_entity(conflict.get('entityInBaseVersion', {}))
    return {
        'kind': workspace['kind'],
        'path': workspace.get('path') or base.get('path'),
        'name': workspace.get('name') or base.get('name'),
        'workspaceStatus': workspace.get('changeStatus'),
        'baseStatus': base.get('changeStatus'),
    }


def merge_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Applies a shallow merge patch and returns a copy.

    Each top-level key in ``patch`` replaces the value in ``base``; None
    removes the key. Lists are replaced whole and nested dicts are not merged.
    """
    merged = dict(base)
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def paginate(
    fetch_page: Callable[[str | None], dict[str, Any]],
    items_key: str,
    *,
    page_token: str | None = None,
    max_pages: int = 20,
) -> tuple[list[dict[str, Any]], str | None]:
    """Collects list pages until exhausted or ``max_pages`` is reached.

    Returns the items and the token to continue from (None when finished).
    The API omits the items array entirely on an empty page.
    """
    items: list[dict[str, Any]] = []
    token = page_token
    for _ in range(max_pages):
        page = fetch_page(token)
        items.extend(page.get(items_key, []))
        token = page.get('nextPageToken') or None
        if token is None:
            break
    return items, token
