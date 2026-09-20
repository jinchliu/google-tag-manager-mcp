"""Markdown rendering and ``CallToolResult`` assembly for ``response_format``.

Tools that offer a format switch return a ``CallToolResult`` directly: the JSON
variants carry ``structured_content`` next to the JSON text, the Markdown
variant is text only. Markdown tables keep the full ``path`` of every row
because later calls copy it verbatim.
"""

import json
from collections.abc import Callable, Sequence
from typing import Any, Literal

from mcp.types import CallToolResult, TextContent

from google_tag_manager_mcp import projection

ResponseFormat = Literal['markdown', 'json', 'json_full']
JsonFormat = Literal['json', 'json_full']

# Columns are the slim fields in order; a dotted field renders under its own name.
_NONE = '(none)'


def cell(value: Any) -> str:
    """Renders one table cell; pipes and newlines are escaped."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list):
        return ', '.join(cell(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return str(value).replace('|', '\\|').replace('\n', ' ')


def table(rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> str:
    """Renders rows as a Markdown table, or ``(none)`` when there are no rows.

    Columns that are empty in every row are left out: entities embedded in a
    container version carry no ``path``, most rows have no ``parentFolderId``.
    """
    if not rows:
        return _NONE
    columns = [c for c in columns if any(row.get(c) is not None for row in rows)] or [
        columns[0]
    ]
    header = '| ' + ' | '.join(columns) + ' |'
    divider = '|' + '|'.join('---' for _ in columns) + '|'
    body = [
        '| ' + ' | '.join(cell(row.get(column)) for column in columns) + ' |'
        for row in rows
    ]
    return '\n'.join([header, divider, *body])


def collection(
    title: str,
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str],
    *,
    next_page_token: str | None = None,
) -> str:
    """Renders a titled list: a count line, the table, and a continuation hint."""
    lines = [f'{title}: {len(rows)} items', '', table(rows, columns)]
    if next_page_token:
        lines += [
            '',
            f'More pages remain; continue with page_token={next_page_token!r}',
        ]
    return '\n'.join(lines)


def to_json(payload: dict[str, Any]) -> str:
    """Serialises a payload for the text half of a JSON result."""
    return json.dumps(payload, ensure_ascii=False, indent=2)


def json_result(payload: dict[str, Any]) -> CallToolResult:
    """Wraps a payload as structured content plus its JSON text."""
    return CallToolResult(
        content=[TextContent(type='text', text=to_json(payload))],
        structured_content=payload,
    )


def markdown_result(text: str) -> CallToolResult:
    """Wraps rendered Markdown as a text-only result."""
    return CallToolResult(content=[TextContent(type='text', text=text)])


def result(
    response_format: ResponseFormat,
    *,
    full: dict[str, Any],
    slim: Callable[[], dict[str, Any]],
    markdown: Callable[[dict[str, Any]], str],
) -> CallToolResult:
    """Builds the result for a format switch.

    ``full`` is the verbatim API payload, ``slim`` computes the summary lazily,
    and ``markdown`` renders that summary.
    """
    if response_format == 'json_full':
        return json_result(full)
    summary = slim()
    if response_format == 'json':
        return json_result(summary)
    return markdown_result(markdown(summary))


def key_values(mapping: dict[str, Any]) -> str:
    """Renders ``key: value`` lines for the header of a summary."""
    return '\n'.join(f'{key}: {cell(value)}' for key, value in mapping.items())


def version(summary: dict[str, Any]) -> str:
    """Renders a slimmed container version: metadata, then one table per kind."""
    header = {
        key: summary[key] for key in projection.VERSION_META_FIELDS if key in summary
    }
    container = summary.get('container')
    if container:
        header['container'] = (
            f'{container.get("name", "")} ({container.get("publicId", "")})'
        )
    parts = [key_values(header)]
    for key, kind in projection.ENTITY_KEYS.items():
        if key in summary:
            parts.append(collection(kind, summary[key], projection.SLIM_FIELDS[kind]))
    return '\n\n'.join(parts)


def status(summary: dict[str, Any]) -> str:
    """Renders a workspace status / sync summary: changes and merge conflicts."""
    parts = [
        collection(
            'changes',
            summary.get('changes', []),
            ('kind', 'path', 'name', 'changeStatus'),
        ),
        collection(
            'merge conflicts',
            summary.get('mergeConflicts', []),
            ('kind', 'path', 'name', 'workspaceStatus', 'baseStatus'),
        ),
    ]
    if 'syncStatus' in summary:
        parts.insert(0, key_values({'syncStatus': summary['syncStatus']}))
    return '\n\n'.join(parts)
