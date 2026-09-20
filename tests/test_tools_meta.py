import pytest
from mcp.server.mcpserver.exceptions import ToolError

from google_tag_manager_mcp.tools import meta


def test_describe_a_type():
    described = meta.gtm_describe_schema('Tag')
    assert 'firingTriggerId' in described['fields']
    assert described['fields']['tagFiringOption']['enum'][1] == 'unlimited'


def test_describe_a_method():
    described = meta.gtm_describe_schema('accounts.list')
    assert described['httpMethod'] == 'GET'
    assert 'includeGoogleTags' in described['parameters']


def test_unknown_name_is_a_tool_error_with_a_hint():
    with pytest.raises(ToolError, match='did you mean Tag'):
        meta.gtm_describe_schema('Tagg')


def test_examples_are_attached_to_types():
    described = meta.gtm_describe_schema('Tag')
    assert described['examples']['gaawe']['body']['type'] == 'gaawe'
    assert 'note' in described['examples']['googtag']
    assert 'examples' not in meta.gtm_describe_schema('Parameter')


@pytest.mark.parametrize(
    ('type_name', 'label'),
    [(t, label) for t, labels in meta.examples().items() for label in labels],
)
def test_every_example_matches_the_discovery_schema(type_name, label):
    from google_tag_manager_mcp import discovery

    body = meta.examples()[type_name][label]['body']
    properties = discovery.schema(type_name)['properties']
    unknown = set(body) - set(properties)
    assert not unknown, unknown
    for key, value in body.items():
        prop = properties[key]
        allowed = prop.get('enum') or prop.get('items', {}).get('enum')
        if allowed:
            values = value if isinstance(value, list) else [value]
            assert all(item in allowed for item in values), (key, value)
        if prop.get('type') == 'array':
            assert isinstance(value, list), key
    for parameter in body.get('parameter', []):
        assert (
            parameter['type']
            in discovery.schema('Parameter')['properties']['type']['enum']
        )
