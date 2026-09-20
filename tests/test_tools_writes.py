import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import url_parts
from google_tag_manager_mcp.tools import generic, workspaces

WORKSPACE = 'accounts/1/containers/2/workspaces/3'
TAG_PATH = f'{WORKSPACE}/tags/4'
API = '/tagmanager/v2/'


def error(status, message, reason='badRequest'):
    return {
        'error': {'code': status, 'message': message, 'errors': [{'reason': reason}]}
    }


def test_create_posts_the_body_to_the_parent(http):
    http.queue({'path': TAG_PATH, 'tagId': '4', 'name': 'T', 'fingerprint': '1'})
    created = generic.gtm_create('tags', WORKSPACE, {'name': 'T', 'type': 'html'})
    assert created['path'] == TAG_PATH
    assert http.last['method'] == 'POST'
    assert url_parts(http.last) == (f'{API}{WORKSPACE}/tags', {})
    assert http.last['body'] == {'name': 'T', 'type': 'html'}


def test_create_validates_the_parent_shape(http):
    with pytest.raises(ToolError, match='containers live under accounts'):
        generic.gtm_create('containers', WORKSPACE, {'name': 'x'})
    assert http.calls == []


def test_create_omits_template_data_in_the_echo(http):
    http.queue({'templateId': '9', 'templateData': 'x' * 1000})
    created = generic.gtm_create(
        'templates', WORKSPACE, {'name': 'T', 'templateData': 'x'}
    )
    assert created['templateData'].startswith('(omitted')


def test_update_reads_merges_and_writes_with_the_fingerprint(http):
    http.queue(
        {
            'path': TAG_PATH,
            'name': 'old',
            'notes': 'n',
            'paused': False,
            'fingerprint': '77',
        }
    )
    http.queue({'path': TAG_PATH, 'name': 'new', 'fingerprint': '78'})
    updated = generic.gtm_update(TAG_PATH, {'name': 'new', 'notes': None})
    assert updated['fingerprint'] == '78'
    get, put = http.calls
    assert get['method'] == 'GET'
    assert put['method'] == 'PUT'
    assert url_parts(put) == (f'{API}{TAG_PATH}', {'fingerprint': ['77']})
    assert put['body'] == {
        'path': TAG_PATH,
        'name': 'new',
        'paused': False,
        'fingerprint': '77',
    }


def test_update_retries_once_after_a_fingerprint_mismatch(http):
    http.queue({'path': TAG_PATH, 'name': 'old', 'fingerprint': '1'})
    http.queue(error(400, 'The provided entity fingerprint is not valid.'), 400)
    http.queue({'path': TAG_PATH, 'name': 'old', 'fingerprint': '2'})
    http.queue({'path': TAG_PATH, 'name': 'new', 'fingerprint': '3'})
    assert generic.gtm_update(TAG_PATH, {'name': 'new'})['fingerprint'] == '3'
    assert [c['method'] for c in http.calls] == ['GET', 'PUT', 'GET', 'PUT']
    assert url_parts(http.calls[3])[1] == {'fingerprint': ['2']}


def test_update_gives_up_after_the_second_mismatch(http):
    for _ in range(2):
        http.queue({'path': TAG_PATH, 'fingerprint': '1'})
        http.queue(error(400, 'The provided entity fingerprint is not valid.'), 400)
    with pytest.raises(ToolError, match='fingerprint mismatch'):
        generic.gtm_update(TAG_PATH, {'name': 'new'})
    assert len(http.calls) == 4


def test_update_user_permissions_has_no_fingerprint(http):
    path = 'accounts/1/user_permissions/9'
    http.queue(
        {'path': path, 'emailAddress': 'a@b.c', 'accountAccess': {'permission': 'user'}}
    )
    http.queue({'path': path, 'accountAccess': {'permission': 'admin'}})
    generic.gtm_update(path, {'accountAccess': {'permission': 'admin'}})
    assert url_parts(http.last) == (f'{API}{path}', {})
    assert http.last['body']['accountAccess'] == {'permission': 'admin'}


def test_update_versions_sends_only_name_and_description(http):
    path = 'accounts/1/containers/2/versions/5'
    http.queue(
        {'path': path, 'name': 'v5', 'fingerprint': '1', 'tag': [{'tagId': '4'}]}
    )
    http.queue({'path': path, 'name': 'release', 'fingerprint': '2'})
    generic.gtm_update(path, {'name': 'release', 'description': 'd'})
    assert http.last['body'] == {'name': 'release', 'description': 'd'}


def test_delete_needs_confirmation_then_deletes(http):
    with pytest.raises(ToolError, match='confirm=true'):
        generic.gtm_delete(TAG_PATH)
    assert http.calls == []
    http.queue(None)
    assert generic.gtm_delete(TAG_PATH, confirm=True) == {'deleted': TAG_PATH}
    assert http.last['method'] == 'DELETE'
    assert url_parts(http.last) == (f'{API}{TAG_PATH}', {})


def test_delete_rejects_collections_without_delete(http):
    with pytest.raises(ToolError, match='delete is not available for accounts'):
        generic.gtm_delete('accounts/1', confirm=True)


def test_revert(http):
    http.queue({'tag': {'path': TAG_PATH, 'name': 'as published'}})
    reverted = generic.gtm_revert(TAG_PATH, confirm=True)
    assert reverted == {
        'reverted': TAG_PATH,
        'tag': {'path': TAG_PATH, 'name': 'as published'},
    }
    assert http.last['method'] == 'POST'
    assert url_parts(http.last) == (f'{API}{TAG_PATH}:revert', {})
    with pytest.raises(ToolError, match='revert is not available for gtag_config'):
        generic.gtm_revert(f'{WORKSPACE}/gtag_config/1', confirm=True)


def test_sync_workspace_reports_conflicts(http):
    http.queue(
        {
            'syncStatus': {'mergeConflict': True},
            'mergeConflict': [
                {
                    'entityInWorkspace': {
                        'changeStatus': 'updated',
                        'tag': {'path': TAG_PATH, 'name': 'T'},
                    },
                    'entityInBaseVersion': {
                        'changeStatus': 'updated',
                        'tag': {'path': TAG_PATH},
                    },
                }
            ],
        }
    )
    text = workspaces.gtm_sync_workspace(WORKSPACE).content[0].text
    assert 'syncStatus: {"mergeConflict":true}' in text
    assert 'merge conflicts: 1 items' in text
    assert url_parts(http.last) == (f'{API}{WORKSPACE}:sync', {})


def test_resolve_conflict_posts_the_entity(http):
    http.queue(None)
    entity = {'changeStatus': 'updated', 'tag': {'path': TAG_PATH, 'name': 'T'}}
    result = workspaces.gtm_resolve_workspace_conflict(
        WORKSPACE, entity, fingerprint='5'
    )
    assert result['resolved']['kind'] == 'tags'
    assert url_parts(http.last) == (
        f'{API}{WORKSPACE}:resolve_conflict',
        {'fingerprint': ['5']},
    )
    assert http.last['body'] == entity


def test_bulk_update_needs_confirmation_and_returns_slim_rows(http):
    with pytest.raises(ToolError, match='confirm=true'):
        workspaces.gtm_bulk_update_workspace(WORKSPACE, [])
    http.queue(
        {'changes': [{'changeStatus': 'added', 'tag': {'path': TAG_PATH, 'name': 'T'}}]}
    )
    result = workspaces.gtm_bulk_update_workspace(
        WORKSPACE, [{'changeStatus': 'added', 'tag': {'name': 'T'}}], confirm=True
    )
    assert result == {
        'count': 1,
        'changes': [
            {'kind': 'tags', 'path': TAG_PATH, 'name': 'T', 'changeStatus': 'added'}
        ],
    }
    assert url_parts(http.last) == (f'{API}{WORKSPACE}/bulk_update', {})
    assert http.last['body'] == {
        'changes': [{'changeStatus': 'added', 'tag': {'name': 'T'}}]
    }


def test_built_in_variables(http):
    http.queue(
        {
            'builtInVariable': [
                {
                    'type': 'pageUrl',
                    'name': 'Page URL',
                    'path': f'{WORKSPACE}/built_in_variables',
                }
            ]
        }
    )
    enabled = workspaces.gtm_enable_built_in_variables(
        WORKSPACE, ['pageUrl', 'clickClasses']
    )
    assert enabled['enabled'][0]['type'] == 'pageUrl'
    assert url_parts(http.last) == (
        f'{API}{WORKSPACE}/built_in_variables',
        {'type': ['pageUrl', 'clickClasses']},
    )
    http.queue(None)
    assert workspaces.gtm_disable_built_in_variables(WORKSPACE, ['pageUrl']) == {
        'disabled': ['pageUrl']
    }
    assert http.last['method'] == 'DELETE'
    assert url_parts(http.last) == (
        f'{API}{WORKSPACE}/built_in_variables',
        {'type': ['pageUrl']},
    )
    http.queue({'enabled': True})
    assert workspaces.gtm_revert_built_in_variable(
        WORKSPACE, 'pageUrl', confirm=True
    ) == {'enabled': True}
    assert url_parts(http.last) == (
        f'{API}{WORKSPACE}/built_in_variables:revert',
        {'type': ['pageUrl']},
    )


def test_invalid_built_in_variable_type_is_a_tool_error(http):
    with pytest.raises(ToolError, match='Invalid arguments'):
        workspaces.gtm_enable_built_in_variables(WORKSPACE, ['pageURL'])
    assert http.calls == []


def test_move_entities_fetches_the_folder_first(http):
    folder = f'{WORKSPACE}/folders/6'
    with pytest.raises(ToolError, match='at least one'):
        workspaces.gtm_move_entities_to_folder(folder)
    http.queue({'path': folder, 'folderId': '6', 'name': 'F'})
    http.queue(None)
    result = workspaces.gtm_move_entities_to_folder(
        folder, tag_ids=['4'], variable_ids=['7', '8']
    )
    assert result == {
        'folder': folder,
        'moved': {'tagId': ['4'], 'variableId': ['7', '8']},
    }
    get, move = http.calls
    assert get['method'] == 'GET'
    assert url_parts(move) == (
        f'{API}{folder}:move_entities_to_folder',
        {'tagId': ['4'], 'variableId': ['7', '8']},
    )
    assert move['body'] == {'path': folder, 'folderId': '6', 'name': 'F'}


def test_import_template_from_gallery(http):
    http.queue({'templateId': '3', 'name': 'Consent', 'templateData': 'x' * 500})
    template = workspaces.gtm_import_template_from_gallery(
        WORKSPACE,
        'gtm-templates-example',
        'consent',
        gallery_sha='abc',
        acknowledge_permissions=True,
    )
    assert template['templateData'].startswith('(omitted')
    assert url_parts(http.last) == (
        f'{API}{WORKSPACE}/templates:import_from_gallery',
        {
            'galleryOwner': ['gtm-templates-example'],
            'galleryRepository': ['consent'],
            'acknowledgePermissions': ['true'],
            'gallerySha': ['abc'],
        },
    )
