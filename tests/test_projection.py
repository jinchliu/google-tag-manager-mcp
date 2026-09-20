from google_tag_manager_mcp import projection

TAG = {
    'path': 'accounts/1/containers/2/workspaces/3/tags/4',
    'tagId': '4',
    'name': 'GA4 - purchase',
    'type': 'gaawe',
    'firingTriggerId': ['12'],
    'parameter': [{'type': 'template', 'key': 'eventName', 'value': 'purchase'}],
    'fingerprint': '1700000000000',
}


def test_slim_keeps_only_present_slim_fields():
    slimmed = projection.slim(TAG, 'tags')
    assert slimmed == {
        'path': TAG['path'],
        'tagId': '4',
        'name': 'GA4 - purchase',
        'type': 'gaawe',
        'firingTriggerId': ['12'],
    }


def test_slim_reads_dotted_fields_and_flattens_container_access():
    template = {'templateId': '9', 'name': 'T', 'galleryReference': {'owner': 'acme'}}
    assert projection.slim(template, 'templates') == {
        'templateId': '9',
        'name': 'T',
        'galleryReference.owner': 'acme',
    }
    permission = {
        'emailAddress': 'a@b.c',
        'accountAccess': {'permission': 'admin'},
        'containerAccess': [
            {'containerId': '2', 'permission': 'edit'},
            {'permission': 'read'},
        ],
    }
    assert projection.slim(permission, 'user_permissions') == {
        'emailAddress': 'a@b.c',
        'accountAccess.permission': 'admin',
        'containerAccess': ['2:edit', '?:read'],
    }


def test_slim_version_covers_every_entity_kind():
    version = {
        'path': 'accounts/1/containers/2/versions/5',
        'containerVersionId': '5',
        'name': 'v5',
        'fingerprint': '1',
        'container': {
            'containerId': '2',
            'name': 'Site',
            'publicId': 'GTM-X',
            'notes': 'n',
        },
        'tag': [TAG],
        'trigger': [
            {'triggerId': '12', 'name': 'All Pages', 'type': 'pageview', 'filter': []}
        ],
        'variable': [{'variableId': '7', 'name': 'DLV', 'type': 'v', 'parameter': []}],
        'folder': [{'folderId': '3', 'name': 'F'}],
        'builtInVariable': [{'type': 'pageUrl', 'name': 'Page URL'}],
        'client': [
            {'clientId': '1', 'name': 'GA4', 'type': 'gaaw_client', 'parameter': []}
        ],
        'transformation': [{'transformationId': '1', 'name': 'T', 'type': 'x'}],
        'customTemplate': [{'templateId': '1', 'name': 'CT', 'templateData': 'huge'}],
        'gtagConfig': [{'gtagConfigId': '1', 'type': 'googtag', 'parameter': []}],
        'zone': [{'zoneId': '1', 'name': 'Z', 'boundary': {}}],
    }
    summary = projection.slim_version(version)
    assert summary['container'] == {
        'containerId': '2',
        'name': 'Site',
        'publicId': 'GTM-X',
    }
    assert summary['tag'] == [projection.slim(TAG, 'tags')]
    assert summary['customTemplate'] == [{'templateId': '1', 'name': 'CT'}]
    assert summary['builtInVariable'] == [{'type': 'pageUrl', 'name': 'Page URL'}]
    for key in projection.ENTITY_KEYS:
        assert key in summary
    assert 'description' not in summary
    assert summary['fingerprint'] == '1'


def test_slim_version_leaves_out_absent_arrays():
    assert projection.slim_version({'containerVersionId': '0'}) == {
        'containerVersionId': '0'
    }


def test_slim_status():
    status = {
        'workspaceChange': [
            {'changeStatus': 'added', 'tag': TAG},
            {
                'changeStatus': 'deleted',
                'builtInVariable': {'type': 'pageUrl', 'path': 'p'},
            },
        ],
        'mergeConflict': [
            {
                'entityInWorkspace': {
                    'changeStatus': 'updated',
                    'trigger': {'path': 't', 'name': 'T'},
                },
                'entityInBaseVersion': {
                    'changeStatus': 'deleted',
                    'trigger': {'path': 't'},
                },
            }
        ],
        'syncStatus': {'mergeConflict': True},
    }
    summary = projection.slim_status(status)
    assert summary['changes'] == [
        {
            'kind': 'tags',
            'path': TAG['path'],
            'name': 'GA4 - purchase',
            'changeStatus': 'added',
        },
        {
            'kind': 'built_in_variables',
            'path': 'p',
            'name': 'pageUrl',
            'changeStatus': 'deleted',
        },
    ]
    assert summary['mergeConflicts'] == [
        {
            'kind': 'triggers',
            'path': 't',
            'name': 'T',
            'workspaceStatus': 'updated',
            'baseStatus': 'deleted',
        }
    ]
    assert summary['syncStatus'] == {'mergeConflict': True}


def test_slim_entity_without_a_known_kind():
    assert projection.slim_entity({'changeStatus': 'none'}) == {
        'kind': 'unknown',
        'changeStatus': 'none',
    }


def test_merge_patch():
    base = {
        'name': 'a',
        'notes': 'n',
        'firingTriggerId': ['1'],
        'consentSettings': {'x': 1},
    }
    patch = {'notes': None, 'firingTriggerId': ['2', '3'], 'consentSettings': {'y': 2}}
    assert projection.merge_patch(base, patch) == {
        'name': 'a',
        'firingTriggerId': ['2', '3'],
        'consentSettings': {'y': 2},
    }
    assert base['notes'] == 'n'


def test_paginate_follows_tokens_and_tolerates_empty_pages():
    pages = {
        None: {'tag': [{'tagId': '1'}], 'nextPageToken': 'p2'},
        'p2': {'nextPageToken': 'p3'},
        'p3': {'tag': [{'tagId': '3'}]},
    }
    items, token = projection.paginate(lambda t: pages[t], 'tag')
    assert [item['tagId'] for item in items] == ['1', '3']
    assert token is None


def test_paginate_stops_at_max_pages_and_returns_the_token():
    pages = {
        None: {'tag': [{'tagId': '1'}], 'nextPageToken': 'p2'},
        'p2': {'tag': [], 'nextPageToken': 'p3'},
    }
    items, token = projection.paginate(lambda t: pages[t], 'tag', max_pages=2)
    assert len(items) == 1
    assert token == 'p3'
