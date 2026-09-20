import pytest
from mcp.server.mcpserver.exceptions import ToolError

from google_tag_manager_mcp.tools import containers, versions, workspaces

CONTAINER = 'accounts/1/containers/2'
WORKSPACE = f'{CONTAINER}/workspaces/3'
TAG = {
    'path': f'{WORKSPACE}/tags/4',
    'tagId': '4',
    'name': 'T',
    'type': 'gaawe',
    'parameter': [],
}


def test_lookup_container_needs_exactly_one_key(http):
    with pytest.raises(ToolError, match='exactly one'):
        containers.gtm_lookup_container()
    with pytest.raises(ToolError, match='exactly one'):
        containers.gtm_lookup_container(destination_id='AW-1', tag_id='GTM-1')
    http.queue({'path': CONTAINER})
    assert containers.gtm_lookup_container(destination_id='AW-1') == {'path': CONTAINER}
    assert http.last['uri'].endswith(
        '/accounts/containers:lookup?destinationId=AW-1&alt=json'
    )


def test_container_snippet(http):
    http.queue({'snippet': '<script>'})
    assert containers.gtm_get_container_snippet(CONTAINER) == {'snippet': '<script>'}
    assert http.last['uri'].endswith('/containers/2:snippet?alt=json')
    with pytest.raises(ToolError, match='Expected a containers path'):
        containers.gtm_get_container_snippet(WORKSPACE)


def test_latest_version_header(http):
    http.queue({'containerVersionId': '9', 'numTags': '3'})
    assert versions.gtm_get_latest_version_header(CONTAINER)['numTags'] == '3'
    assert http.last['uri'].endswith('/containers/2/version_headers:latest?alt=json')


def test_live_version_markdown_summarises_entities(http):
    http.queue(
        {
            'containerVersionId': '9',
            'name': 'v9',
            'tag': [TAG],
            'container': {'name': 'Site', 'publicId': 'GTM-X'},
        }
    )
    result = versions.gtm_get_live_version(CONTAINER)
    text = result.content[0].text
    assert 'containerVersionId: 9' in text
    assert 'container: Site (GTM-X)' in text
    assert 'tags: 1 items' in text
    assert 'parameter' not in text
    assert http.last['uri'].endswith('/containers/2/versions:live?alt=json')


def test_workspace_status(http):
    http.queue({'workspaceChange': [{'changeStatus': 'added', 'tag': TAG}]})
    result = workspaces.gtm_get_workspace_status(WORKSPACE, response_format='json')
    assert result.structured_content['changes'] == [
        {'kind': 'tags', 'path': TAG['path'], 'name': 'T', 'changeStatus': 'added'}
    ]
    http.queue({'workspaceChange': [{'changeStatus': 'added', 'tag': TAG}]})
    text = workspaces.gtm_get_workspace_status(WORKSPACE).content[0].text
    assert 'changes: 1 items' in text
    assert 'merge conflicts: 0 items' in text
    assert http.last['uri'].endswith('/workspaces/3/status?alt=json')


def test_quick_preview_lifts_flags(http):
    http.queue(
        {
            'compilerError': True,
            'syncStatus': {'syncError': False},
            'containerVersion': {'containerVersionId': '0', 'tag': [TAG]},
        }
    )
    result = workspaces.gtm_quick_preview_workspace(WORKSPACE, response_format='json')
    assert result.structured_content['compilerError'] is True
    assert result.structured_content['containerVersion']['tag'][0]['tagId'] == '4'
    assert http.last['method'] == 'POST'
    assert http.last['uri'].endswith('/workspaces/3:quick_preview?alt=json')


def test_folder_entities_paginate_and_group(http):
    folder = f'{WORKSPACE}/folders/6'
    http.queue({'tag': [TAG], 'nextPageToken': 'n'})
    http.queue(
        {'variable': [{'path': f'{WORKSPACE}/variables/7', 'name': 'V', 'type': 'v'}]}
    )
    result = workspaces.gtm_list_folder_entities(folder, response_format='json')
    data = result.structured_content
    assert [t['tagId'] for t in data['tag']] == ['4']
    assert data['variable'][0]['name'] == 'V'
    assert data['trigger'] == []
    assert data['next_page_token'] is None
    assert http.calls[0]['method'] == 'POST'
    assert http.calls[1]['uri'].endswith('/folders/6:entities?pageToken=n&alt=json')
    http.queue({'tag': [TAG]})
    text = workspaces.gtm_list_folder_entities(folder).content[0].text
    assert 'tags: 1 items' in text
    assert 'triggers: 0 items' in text
