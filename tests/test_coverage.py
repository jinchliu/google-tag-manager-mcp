"""Mechanical full-coverage check against the bundled discovery document.

Every one of the 106 methods must be claimed by exactly one (tool, resource)
pair, and driving that pair must send the HTTP method and path template the
discovery document declares for it. NOT_YET shrinks phase by phase.
"""

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest

from google_tag_manager_mcp import discovery
from google_tag_manager_mcp.registry import REGISTRY
from google_tag_manager_mcp.tools import containers, generic, versions, workspaces

BASE = 'https://tagmanager.googleapis.com/'

NOT_YET: set[str] = set()


def canonical_path(collection: str) -> str:
    """accounts/1/containers/2/... with one id per level."""
    parts: list[str] = []
    for level, name in enumerate(discovery.collections()[collection], start=1):
        parts += [name, str(level)]
    return '/'.join(parts)


def parent_of(collection: str) -> str:
    return canonical_path(collection).rsplit('/', 2)[0]


WORKSPACE = canonical_path('workspaces')
Driver = Callable[[str | None], tuple[Callable[..., Any], dict[str, Any], Any]]

# tool name -> driver(resource) -> (function, kwargs, queued response or list of them)
DRIVERS: dict[str, Driver] = {
    'gtm_list': lambda r: (
        generic.gtm_list,
        {'resource': r, 'parent': None if r == 'accounts' else parent_of(str(r))},
        {},
    ),
    'gtm_get': lambda r: (generic.gtm_get, {'path': canonical_path(str(r))}, {}),
    'gtm_create': lambda r: (
        generic.gtm_create,
        {'resource': r, 'parent': parent_of(str(r)), 'body': {'name': 'x'}},
        {},
    ),
    'gtm_update': lambda r: (
        generic.gtm_update,
        {'path': canonical_path(str(r)), 'patch': {'name': 'x'}},
        [{'fingerprint': '1'}, {}],
    ),
    'gtm_delete': lambda r: (
        generic.gtm_delete,
        {'path': canonical_path(str(r)), 'confirm': True},
        None,
    ),
    'gtm_revert': lambda r: (
        generic.gtm_revert,
        {'path': canonical_path(str(r)), 'confirm': True},
        {},
    ),
    'gtm_lookup_container': lambda r: (
        containers.gtm_lookup_container,
        {'tag_id': 'GTM-ABC'},
        {},
    ),
    'gtm_get_container_snippet': lambda r: (
        containers.gtm_get_container_snippet,
        {'container': canonical_path('containers')},
        {},
    ),
    'gtm_get_latest_version_header': lambda r: (
        versions.gtm_get_latest_version_header,
        {'container': canonical_path('containers')},
        {},
    ),
    'gtm_get_live_version': lambda r: (
        versions.gtm_get_live_version,
        {'container': canonical_path('containers')},
        {},
    ),
    'gtm_get_workspace_status': lambda r: (
        workspaces.gtm_get_workspace_status,
        {'workspace': WORKSPACE},
        {},
    ),
    'gtm_quick_preview_workspace': lambda r: (
        workspaces.gtm_quick_preview_workspace,
        {'workspace': WORKSPACE},
        {},
    ),
    'gtm_list_folder_entities': lambda r: (
        workspaces.gtm_list_folder_entities,
        {'folder': canonical_path('folders')},
        {},
    ),
    'gtm_sync_workspace': lambda r: (
        workspaces.gtm_sync_workspace,
        {'workspace': WORKSPACE},
        {},
    ),
    'gtm_resolve_workspace_conflict': lambda r: (
        workspaces.gtm_resolve_workspace_conflict,
        {'workspace': WORKSPACE, 'entity': {'changeStatus': 'added'}},
        None,
    ),
    'gtm_bulk_update_workspace': lambda r: (
        workspaces.gtm_bulk_update_workspace,
        {'workspace': WORKSPACE, 'changes': [], 'confirm': True},
        {},
    ),
    'gtm_enable_built_in_variables': lambda r: (
        workspaces.gtm_enable_built_in_variables,
        {'workspace': WORKSPACE, 'types': ['pageUrl']},
        {},
    ),
    'gtm_disable_built_in_variables': lambda r: (
        workspaces.gtm_disable_built_in_variables,
        {'workspace': WORKSPACE, 'types': ['pageUrl']},
        None,
    ),
    'gtm_revert_built_in_variable': lambda r: (
        workspaces.gtm_revert_built_in_variable,
        {'workspace': WORKSPACE, 'type': 'pageUrl', 'confirm': True},
        {},
    ),
    'gtm_move_entities_to_folder': lambda r: (
        workspaces.gtm_move_entities_to_folder,
        {'folder': canonical_path('folders'), 'tag_ids': ['4']},
        [{'folderId': '4'}, None],
    ),
    'gtm_combine_containers': lambda r: (
        containers.gtm_combine_containers,
        {
            'container': canonical_path('containers'),
            'source_container_id': '9',
            'confirm': True,
        },
        {},
    ),
    'gtm_move_tag_id': lambda r: (
        containers.gtm_move_tag_id,
        {'container': canonical_path('containers'), 'tag_id': 'G-1', 'confirm': True},
        {},
    ),
    'gtm_link_destination': lambda r: (
        containers.gtm_link_destination,
        {
            'container': canonical_path('containers'),
            'destination_id': 'AW-1',
            'confirm': True,
        },
        {},
    ),
    'gtm_reauthorize_environment': lambda r: (
        containers.gtm_reauthorize_environment,
        {'environment': canonical_path('environments'), 'confirm': True},
        [{}, {}],
    ),
    'gtm_publish_version': lambda r: (
        versions.gtm_publish_version,
        {'version': canonical_path('versions'), 'confirm': True},
        {},
    ),
    'gtm_set_latest_version': lambda r: (
        versions.gtm_set_latest_version,
        {'version': canonical_path('versions'), 'confirm': True},
        {},
    ),
    'gtm_undelete_version': lambda r: (
        versions.gtm_undelete_version,
        {'version': canonical_path('versions')},
        {},
    ),
    'gtm_create_version': lambda r: (
        workspaces.gtm_create_version,
        {'workspace': WORKSPACE, 'confirm': True},
        {},
    ),
    'gtm_import_template_from_gallery': lambda r: (
        workspaces.gtm_import_template_from_gallery,
        {'workspace': WORKSPACE, 'gallery_owner': 'o', 'gallery_repository': 'r'},
        {},
    ),
}


def claimed_pairs() -> list[tuple[str, str | None, str]]:
    return [
        (entry.name, resource, method_id)
        for entry in REGISTRY
        for resource, method_id in entry.methods.items()
    ]


def test_every_method_is_claimed_exactly_once():
    counts = Counter(method_id for _, _, method_id in claimed_pairs())
    all_ids = set(discovery.methods())
    assert set(counts) <= all_ids, set(counts) - all_ids
    assert [m for m, n in counts.items() if n > 1] == []
    assert all_ids - set(counts) == NOT_YET


def test_every_registered_tool_has_a_driver():
    assert {name for name, _, _ in claimed_pairs()} <= set(DRIVERS)


@pytest.mark.parametrize(('tool_name', 'resource', 'method_id'), claimed_pairs())
def test_each_pair_hits_its_declared_method(http, tool_name, resource, method_id):
    spec = discovery.method(method_id)
    function, kwargs, responses = DRIVERS[tool_name](resource)
    for response in responses if isinstance(responses, list) else [responses]:
        http.queue(response)
    function(**kwargs)
    call = http.calls[-1]
    # The path template becomes a pattern: {+parent} / {+path} match one API path.
    pattern = re.escape(BASE + spec.path)
    pattern = pattern.replace(re.escape('{+parent}'), r'accounts/[^?]+')
    pattern = pattern.replace(re.escape('{+path}'), r'accounts/[^?]+')
    assert call['method'] == spec.http_method
    assert re.fullmatch(pattern, call['uri'].split('?')[0]), (spec.path, call['uri'])
    assert not http.queued
