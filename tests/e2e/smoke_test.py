"""Real-API smoke test. Opt in with GTM_MCP_E2E_CONTAINER=accounts/x/containers/y.

Runs serially against a throwaway container and cleans up after itself:
workspace -> variable, trigger, tag -> update -> status -> revert -> delete ->
delete workspace. The version chain (create_version + publish) additionally
needs GTM_MCP_E2E_PUBLISH=1 because it changes what the container serves.
Credentials come from ADC as in production; set GOOGLE_CLOUD_QUOTA_PROJECT
when the ADC quota project has no Tag Manager API enabled. Cleanup deletes
the workspaces it created, which needs the tagmanager.delete.containers
scope; without it the run leaves a workspace behind.
"""

import os
import time
from collections.abc import Iterator

import pytest

from google_tag_manager_mcp.tools import generic, versions, workspaces

pytestmark = pytest.mark.e2e

CONTAINER = os.environ.get('GTM_MCP_E2E_CONTAINER', '')


def parameter(key: str, value: str) -> dict[str, str]:
    return {'type': 'template', 'key': key, 'value': value}


@pytest.fixture(scope='module')
def container() -> str:
    if not CONTAINER:
        pytest.skip('set GTM_MCP_E2E_CONTAINER to run the smoke test')
    return CONTAINER


@pytest.fixture
def workspace(container: str) -> Iterator[str]:
    created = generic.gtm_create(
        'workspaces',
        container,
        {'name': f'mcp-e2e-{int(time.time())}', 'description': 'created by tests/e2e'},
    )
    yield created['path']
    generic.gtm_delete(created['path'], confirm=True)


def test_entity_lifecycle(workspace: str) -> None:
    variable = generic.gtm_create(
        'variables',
        workspace,
        {'name': 'C - e2e', 'type': 'c', 'parameter': [parameter('value', 'one')]},
    )
    trigger = generic.gtm_create(
        'triggers',
        workspace,
        {
            'name': 'CE - e2e',
            'type': 'customEvent',
            'customEventFilter': [
                {
                    'type': 'equals',
                    'parameter': [
                        parameter('arg0', '{{_event}}'),
                        parameter('arg1', 'e2e'),
                    ],
                }
            ],
        },
    )
    tag = generic.gtm_create(
        'tags',
        workspace,
        {
            'name': 'cHTML - e2e',
            'type': 'html',
            'parameter': [parameter('html', '<script>void 0;</script>')],
            'firingTriggerId': [trigger['triggerId']],
        },
    )
    assert tag['firingTriggerId'] == [trigger['triggerId']]

    updated = generic.gtm_update(
        variable['path'],
        {'parameter': [parameter('value', 'two')], 'notes': 'updated by e2e'},
    )
    assert updated['fingerprint'] != variable['fingerprint']
    fetched = generic.gtm_get(variable['path']).structured_content
    assert fetched is not None
    assert fetched['parameter'][0]['value'] == 'two'
    assert fetched['notes'] == 'updated by e2e'

    listed = generic.gtm_list(
        'tags', workspace, response_format='json'
    ).structured_content
    assert listed is not None
    assert 'cHTML - e2e' in [item['name'] for item in listed['items']]
    markdown = generic.gtm_list('variables', workspace).content[0].text
    assert 'C - e2e' in markdown

    status = workspaces.gtm_get_workspace_status(
        workspace, response_format='json'
    ).structured_content
    assert status is not None
    assert {change['kind'] for change in status['changes']} == {
        'tags',
        'triggers',
        'variables',
    }

    generic.gtm_revert(tag['path'], confirm=True)
    after_revert = generic.gtm_list(
        'tags', workspace, response_format='json'
    ).structured_content
    assert after_revert is not None
    assert 'cHTML - e2e' not in [item['name'] for item in after_revert['items']]

    generic.gtm_delete(trigger['path'], confirm=True)
    generic.gtm_delete(variable['path'], confirm=True)
    final = workspaces.gtm_get_workspace_status(
        workspace, response_format='json'
    ).structured_content
    assert final is not None
    assert final['changes'] == []


@pytest.mark.skipif(
    not os.environ.get('GTM_MCP_E2E_PUBLISH'), reason='set GTM_MCP_E2E_PUBLISH=1'
)
def test_version_chain(container: str) -> None:
    created_workspace = generic.gtm_create(
        'workspaces', container, {'name': f'mcp-e2e-publish-{int(time.time())}'}
    )
    generic.gtm_create(
        'variables',
        created_workspace['path'],
        {
            'name': 'C - e2e publish',
            'type': 'c',
            'parameter': [parameter('value', 'x')],
        },
    )
    created = workspaces.gtm_create_version(
        created_workspace['path'],
        name='e2e',
        notes='created by tests/e2e',
        confirm=True,
        response_format='json',
    ).structured_content
    assert created is not None
    assert created['compilerError'] is False
    version_path = created['containerVersion']['path']
    try:
        published = versions.gtm_publish_version(
            version_path, confirm=True, response_format='json'
        ).structured_content
        assert published is not None
        assert published['compilerError'] is False
        live = versions.gtm_get_live_version(
            container, response_format='json'
        ).structured_content
        assert live is not None
        assert (
            live['containerVersion']['containerVersionId']
            == created['containerVersion']['containerVersionId']
        )
    finally:
        # create_version consumed the workspace and opened a fresh one.
        if created.get('newWorkspacePath'):
            generic.gtm_delete(created['newWorkspacePath'], confirm=True)
