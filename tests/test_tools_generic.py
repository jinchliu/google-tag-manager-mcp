import pytest
from mcp.server.mcpserver.exceptions import ToolError

from google_tag_manager_mcp.tools import generic

WORKSPACE = 'accounts/1/containers/2/workspaces/3'
TAG = {
    'path': f'{WORKSPACE}/tags/4',
    'tagId': '4',
    'name': 'GA4 | purchase',
    'type': 'gaawe',
    'parameter': [{'type': 'template', 'key': 'eventName', 'value': 'purchase'}],
    'fingerprint': '1',
}


def test_list_follows_pages_and_renders_markdown(http):
    http.queue({'tag': [TAG], 'nextPageToken': 'p2'})
    http.queue({'tag': [{**TAG, 'tagId': '5', 'path': f'{WORKSPACE}/tags/5'}]})
    result = generic.gtm_list('tags', WORKSPACE)
    text = result.content[0].text
    assert result.structured_content is None
    assert text.startswith(f'tags under {WORKSPACE}: 2 items')
    assert '| path | tagId | name | type |' in text
    assert 'GA4 \\| purchase' in text
    assert 'page_token' not in text
    assert [c['uri'].split('?')[1] for c in http.calls] == [
        'alt=json',
        'pageToken=p2&alt=json',
    ]


def test_list_json_is_slim_and_json_full_is_verbatim(http):
    http.queue({'tag': [TAG]})
    slim = generic.gtm_list('tags', WORKSPACE, response_format='json')
    assert slim.structured_content['items'] == [
        {'path': TAG['path'], 'tagId': '4', 'name': 'GA4 | purchase', 'type': 'gaawe'}
    ]
    http.queue({'tag': [TAG]})
    full = generic.gtm_list('tags', WORKSPACE, response_format='json_full')
    assert full.structured_content['items'] == [TAG]
    assert full.structured_content['count'] == 1


def test_list_reports_a_continuation_token(http):
    http.queue({'tag': [TAG], 'nextPageToken': 'p2'})
    result = generic.gtm_list('tags', WORKSPACE, max_pages=1)
    assert "page_token='p2'" in result.content[0].text
    http.queue({'tag': []})
    generic.gtm_list('tags', WORKSPACE, page_token='p2')
    assert http.last['uri'].endswith('pageToken=p2&alt=json')


def test_list_accounts_needs_no_parent_and_passes_flags(http):
    http.queue({'account': [{'path': 'accounts/1', 'name': 'A'}]})
    generic.gtm_list('accounts', include_google_tags=True)
    assert http.last['uri'].endswith(
        '/tagmanager/v2/accounts?includeGoogleTags=true&alt=json'
    )
    http.queue({'containerVersionHeader': []})
    generic.gtm_list('version_headers', 'accounts/1/containers/2', include_deleted=True)
    assert 'includeDeleted=true' in http.last['uri']


def test_list_validates_parent_and_flags(http):
    with pytest.raises(ToolError, match='tags need a parent'):
        generic.gtm_list('tags')
    with pytest.raises(ToolError, match='tags live under workspaces'):
        generic.gtm_list('tags', 'accounts/1')
    with pytest.raises(ToolError, match='include_deleted only applies'):
        generic.gtm_list('tags', WORKSPACE, include_deleted=True)
    with pytest.raises(ToolError, match='include_google_tags only applies'):
        generic.gtm_list('tags', WORKSPACE, include_google_tags=True)
    assert http.calls == []


def test_list_handles_collections_without_pagination(http):
    http.queue({'destination': [{'path': 'accounts/1/containers/2/destinations/AW-1'}]})
    result = generic.gtm_list(
        'destinations', 'accounts/1/containers/2', response_format='json'
    )
    assert result.structured_content['count'] == 1


def test_get_returns_the_full_entity(http):
    http.queue(TAG)
    result = generic.gtm_get(f'{WORKSPACE}/tags/4')
    assert result.structured_content == TAG
    assert http.last['method'] == 'GET'
    assert http.last['uri'].endswith('/workspaces/3/tags/4?alt=json')


def test_get_summarises_versions_unless_asked_for_full(http):
    version = {'containerVersionId': '7', 'tag': [TAG], 'fingerprint': '9'}
    http.queue(version)
    summary = generic.gtm_get('accounts/1/containers/2/versions/7').structured_content
    assert summary['tag'] == [
        {'path': TAG['path'], 'tagId': '4', 'name': 'GA4 | purchase', 'type': 'gaawe'}
    ]
    http.queue(version)
    full = generic.gtm_get(
        'accounts/1/containers/2/versions/7', response_format='json_full'
    )
    assert full.structured_content == version


def test_get_rejects_collections_without_get(http):
    with pytest.raises(ToolError, match='get is not available for built_in_variables'):
        generic.gtm_get(f'{WORKSPACE}/built_in_variables')
    with pytest.raises(ToolError, match='get is not available for tags'):
        generic.gtm_get(f'{WORKSPACE}/tags')
    assert http.calls == []
