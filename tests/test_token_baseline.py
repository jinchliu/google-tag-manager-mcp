"""Guards the response_format decision: markdown must stay the cheapest slim view."""

from google_tag_manager_mcp import projection, render
from google_tag_manager_mcp.tools import meta


def realistic_tags() -> list[dict]:
    """Twenty tags built from the shipped example bodies, ids and paths added."""
    bodies = [example['body'] for example in meta.examples()['Tag'].values()]
    tags = []
    for index in range(20):
        body = dict(bodies[index % len(bodies)])
        body['tagId'] = str(index + 1)
        body['path'] = f'accounts/1/containers/2/workspaces/3/tags/{index + 1}'
        body['fingerprint'] = '1700000000000'
        body['firingTriggerId'] = [str(10 + index)]
        tags.append(body)
    return tags


def test_markdown_is_the_cheapest_slim_view():
    tags = realistic_tags()
    slim = [projection.slim(tag, 'tags') for tag in tags]
    markdown = render.collection('tags', slim, projection.SLIM_FIELDS['tags'])
    json_slim = render.to_json({'items': slim})
    json_full = render.to_json({'items': tags})
    assert len(markdown) < len(json_slim) < len(json_full)
    # Regression bound measured at first implementation; tighten if it improves.
    assert len(markdown) <= 0.5 * len(json_slim), (len(markdown), len(json_slim))
