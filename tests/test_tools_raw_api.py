import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import url_parts
from google_tag_manager_mcp.tools import meta

WORKSPACE = 'accounts/1/containers/2/workspaces/3'


def test_get_methods_need_no_confirmation(http):
    http.queue({'tag': []})
    result = meta.gtm_call_api(
        'accounts.containers.workspaces.tags.list', {'parent': WORKSPACE}
    )
    assert result == {'tag': []}
    assert url_parts(http.last) == (f'/tagmanager/v2/{WORKSPACE}/tags', {})


def test_non_get_methods_need_confirmation_and_a_body_when_declared(http):
    with pytest.raises(ToolError, match='confirm=true'):
        meta.gtm_call_api(
            'accounts.containers.workspaces.tags.create',
            {'parent': WORKSPACE},
            {'name': 'T'},
        )
    http.queue({'tagId': '4'})
    meta.gtm_call_api(
        'accounts.containers.workspaces.tags.create',
        {'parent': WORKSPACE},
        {'name': 'T'},
        confirm=True,
    )
    assert http.last['method'] == 'POST'
    assert http.last['body'] == {'name': 'T'}


def test_arguments_are_validated_against_discovery(http):
    with pytest.raises(ToolError, match='did you mean'):
        meta.gtm_call_api('accounts.containers.workspaces.tags.lst')
    with pytest.raises(ToolError, match='has no parameter parnt'):
        meta.gtm_call_api(
            'accounts.containers.workspaces.tags.list', {'parnt': WORKSPACE}
        )
    with pytest.raises(ToolError, match='takes no request body'):
        meta.gtm_call_api(
            'accounts.containers.workspaces.tags.list', {'parent': WORKSPACE}, {'x': 1}
        )
    assert http.calls == []
