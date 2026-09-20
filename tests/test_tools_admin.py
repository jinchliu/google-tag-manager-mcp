import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import url_parts
from google_tag_manager_mcp.tools import containers, versions, workspaces

CONTAINER = 'accounts/1/containers/2'
VERSION = f'{CONTAINER}/versions/5'
WORKSPACE = f'{CONTAINER}/workspaces/3'
API = '/tagmanager/v2/'


def test_combine_containers(http):
    with pytest.raises(ToolError, match='confirm=true'):
        containers.gtm_combine_containers(CONTAINER, '9')
    http.queue({'path': CONTAINER, 'name': 'merged'})
    result = containers.gtm_combine_containers(
        CONTAINER, '9', setting_source='other', confirm=True
    )
    assert result['name'] == 'merged'
    assert http.last['method'] == 'POST'
    assert url_parts(http.last) == (
        f'{API}{CONTAINER}:combine',
        {
            'containerId': ['9'],
            'settingSource': ['other'],
            'allowUserPermissionFeatureUpdate': ['false'],
        },
    )


def test_move_tag_id(http):
    http.queue({'path': 'accounts/1/containers/77'})
    result = containers.gtm_move_tag_id(
        CONTAINER,
        'G-ABC',
        tag_name='New',
        copy_settings=True,
        copy_terms_of_service=True,
        confirm=True,
    )
    assert result['path'] == 'accounts/1/containers/77'
    path, query = url_parts(http.last)
    assert path == f'{API}{CONTAINER}:move_tag_id'
    assert query['tagId'] == ['G-ABC']
    assert query['tagName'] == ['New']
    assert query['copySettings'] == ['true']
    assert query['copyTermsOfService'] == ['true']
    assert query['copyUsers'] == ['false']


def test_link_destination(http):
    http.queue({'path': f'{CONTAINER}/destinations/AW-1', 'destinationId': 'AW-1'})
    result = containers.gtm_link_destination(CONTAINER, 'AW-1', confirm=True)
    assert result['destinationId'] == 'AW-1'
    assert url_parts(http.last) == (
        f'{API}{CONTAINER}/destinations:link',
        {'destinationId': ['AW-1'], 'allowUserPermissionFeatureUpdate': ['false']},
    )


def test_reauthorize_environment_reads_then_posts(http):
    environment = f'{CONTAINER}/environments/4'
    http.queue({'path': environment, 'name': 'Staging', 'authorizationCode': 'old'})
    http.queue({'path': environment, 'name': 'Staging', 'authorizationCode': 'new'})
    result = containers.gtm_reauthorize_environment(environment, confirm=True)
    assert result['authorizationCode'] == 'new'
    get, post = http.calls
    assert get['method'] == 'GET'
    assert url_parts(post) == (f'{API}{environment}:reauthorize', {})
    assert post['body']['authorizationCode'] == 'old'


def test_publish_version_lifts_compiler_error(http):
    with pytest.raises(ToolError, match='confirm=true'):
        versions.gtm_publish_version(VERSION)
    http.queue(
        {
            'compilerError': False,
            'containerVersion': {'containerVersionId': '5', 'name': 'v5'},
        }
    )
    result = versions.gtm_publish_version(VERSION, confirm=True, response_format='json')
    assert result.structured_content == {
        'compilerError': False,
        'containerVersion': {'containerVersionId': '5', 'name': 'v5'},
    }
    assert url_parts(http.last) == (f'{API}{VERSION}:publish', {})


def test_set_latest_and_undelete_return_summaries(http):
    http.queue({'containerVersionId': '5', 'tag': [{'tagId': '1', 'parameter': []}]})
    assert versions.gtm_set_latest_version(VERSION, confirm=True) == {
        'containerVersionId': '5',
        'tag': [{'tagId': '1'}],
    }
    assert url_parts(http.last) == (f'{API}{VERSION}:set_latest', {})
    http.queue({'containerVersionId': '5', 'deleted': False})
    assert versions.gtm_undelete_version(VERSION) == {
        'containerVersionId': '5',
        'deleted': False,
    }
    assert url_parts(http.last) == (f'{API}{VERSION}:undelete', {})


def test_create_version_lifts_the_new_workspace_path(http):
    with pytest.raises(ToolError, match='confirm=true'):
        workspaces.gtm_create_version(WORKSPACE, name='v6')
    http.queue(
        {
            'compilerError': False,
            'newWorkspacePath': f'{CONTAINER}/workspaces/4',
            'syncStatus': {'mergeConflict': False, 'syncError': False},
            'containerVersion': {'containerVersionId': '6', 'name': 'v6'},
        }
    )
    result = workspaces.gtm_create_version(
        WORKSPACE, name='v6', notes='n', confirm=True
    )
    text = result.content[0].text
    assert f'newWorkspacePath: {CONTAINER}/workspaces/4' in text
    assert 'compilerError: false' in text
    assert 'containerVersionId: 6' in text
    assert url_parts(http.last) == (f'{API}{WORKSPACE}:create_version', {})
    assert http.last['body'] == {'name': 'v6', 'notes': 'n'}
