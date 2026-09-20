import pytest
from mcp.server.mcpserver.exceptions import ToolError

from google_tag_manager_mcp import paths

TAG = 'accounts/1/containers/2/workspaces/3/tags/4'


def test_parse_full_entity_path():
    parsed = paths.parse(TAG)
    assert parsed.collection == 'tags'
    assert parsed.id == '4'
    assert parsed.parent == 'accounts/1/containers/2/workspaces/3'
    assert str(parsed) == TAG


def test_parse_collection_level_path():
    parsed = paths.parse('accounts/1/containers/2/workspaces/3/built_in_variables')
    assert parsed.collection == 'built_in_variables'
    assert parsed.id is None
    assert parsed.parent == 'accounts/1/containers/2/workspaces/3'


def test_parse_tolerates_surrounding_slashes_and_whitespace():
    assert str(paths.parse(' /accounts/1/ ')) == 'accounts/1'


def test_rejects_wrong_nesting():
    with pytest.raises(
        ToolError, match='must appear as accounts/{accountId}/containers'
    ):
        paths.parse('accounts/1/tags/4')


def test_rejects_unknown_collection():
    with pytest.raises(ToolError, match="'things' is not a collection"):
        paths.parse('accounts/1/things/2')


def test_rejects_empty_path():
    with pytest.raises(ToolError, match='Empty path'):
        paths.parse('  ')


def test_expect_requires_collection_and_id():
    assert paths.expect(TAG, 'tags').id == '4'
    with pytest.raises(ToolError, match='Expected a workspaces path'):
        paths.expect('accounts/1/containers/2', 'workspaces')
    with pytest.raises(ToolError, match='Expected a workspaces path'):
        paths.expect('accounts/1/containers/2/workspaces', 'workspaces')


def test_expect_parent():
    parent = paths.expect_parent('accounts/1/containers/2/workspaces/3', 'tags')
    assert parent.collection == 'workspaces'
    with pytest.raises(ToolError, match='tags live under workspaces'):
        paths.expect_parent('accounts/1', 'tags')
    with pytest.raises(ToolError, match='has no parent'):
        paths.expect_parent('accounts/1', 'accounts')


def test_shape():
    assert paths.shape('tags') == (
        'accounts/{accountId}/containers/{containerId}/workspaces/{workspaceId}/tags/{tagId}'
    )
