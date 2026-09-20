import pytest

from google_tag_manager_mcp import client, discovery

LIST_COLLECTIONS = [
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


def test_index_has_every_method():
    assert len(discovery.methods()) == 106
    spec = discovery.method('accounts.containers.workspaces.tags.list')
    assert spec.http_method == 'GET'
    assert spec.collection == 'tags'
    assert 'parent' in spec.parameters
    assert 'https://www.googleapis.com/auth/tagmanager.readonly' in spec.scopes
    assert spec.response_schema == 'ListTagsResponse'


def test_unknown_method_suggests_close_matches():
    with pytest.raises(KeyError, match='did you mean'):
        discovery.method('accounts.containers.workspaces.tags.lst')


def test_collections_nest_like_the_api():
    assert discovery.collections()['tags'] == (
        'accounts',
        'containers',
        'workspaces',
        'tags',
    )
    assert len(discovery.collections()) == 18
    assert discovery.parent_collection('accounts') is None
    assert discovery.parent_collection('user_permissions') == 'accounts'
    assert discovery.parent_collection('versions') == 'containers'
    assert discovery.parent_collection('built_in_variables') == 'workspaces'


def test_find_method_returns_none_when_absent():
    assert discovery.find_method('versions', 'list') is None
    assert discovery.find_method('versions', 'live') is not None


@pytest.mark.parametrize('collection', LIST_COLLECTIONS)
def test_list_items_key_is_derived_for_every_list_method(collection):
    key = discovery.list_items_key(collection)
    assert key and key != 'nextPageToken'


def test_list_items_key_examples():
    assert discovery.list_items_key('version_headers') == 'containerVersionHeader'
    assert discovery.list_items_key('user_permissions') == 'userPermission'
    assert discovery.list_items_key('gtag_config') == 'gtagConfig'
    with pytest.raises(KeyError):
        discovery.list_items_key('versions')


def test_bind_builds_the_real_request(http):
    http.queue({'tag': []})
    call = discovery.bind(client.service(), 'accounts.containers.workspaces.tags.list')
    call(parent='accounts/1/containers/2/workspaces/3').execute(num_retries=0)
    assert http.last['method'] == 'GET'
    assert http.last['uri'].endswith(
        '/accounts/1/containers/2/workspaces/3/tags?alt=json'
    )


def test_describe_schema_lists_fields_and_enums():
    described = discovery.describe('Trigger')
    assert described['type'] == 'Trigger'
    assert 'customEvent' in described['fields']['type']['enum']
    assert described['fields']['filter']['type'] == 'array<Condition>'
    assert described['fields']['name']['type'] == 'string'


def test_describe_method_lists_parameters_and_scopes():
    described = discovery.describe('accounts.containers.combine')
    assert described['httpMethod'] == 'POST'
    assert described['parameters']['path']['required'] is True
    assert 'current' in described['parameters']['settingSource']['enum']
    assert described['requestBody'] is None
    assert described['scopes'] == [
        'https://www.googleapis.com/auth/tagmanager.edit.containers'
    ]


def test_describe_unknown_name():
    with pytest.raises(KeyError, match='did you mean'):
        discovery.describe('Tagg')
