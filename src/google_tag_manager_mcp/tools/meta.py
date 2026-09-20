"""Offline helpers (schema and method descriptions) and the raw API escape hatch."""

import json
import os
from functools import cache
from importlib import resources
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from google_tag_manager_mcp import client, discovery
from google_tag_manager_mcp.registry import Tier, require_confirm, tool


@cache
def examples() -> dict[str, dict[str, dict[str, Any]]]:
    """Loads the bundled example bodies, keyed by type and then by label.

    ``examples/Tag.gaawe.json`` becomes ``examples()['Tag']['gaawe']`` with the
    keys ``note`` and ``body``. The bodies are anonymised shapes taken from
    real containers, since the discovery document says nothing about which
    parameter keys a given tag or variable type expects.
    """
    found: dict[str, dict[str, dict[str, Any]]] = {}
    folder = resources.files('google_tag_manager_mcp').joinpath('examples')
    for entry in folder.iterdir():
        if not entry.name.endswith('.json'):
            continue
        type_name, label = entry.name.removesuffix('.json').split('.', 1)
        found.setdefault(type_name, {})[label] = json.loads(entry.read_text('utf-8'))
    return found


@tool(tier=Tier.READ)
def gtm_describe_schema(name: str) -> dict[str, Any]:
    """Describes a Tag Manager API type or method, offline and without quota.

    Use it before building a body for gtm_create / gtm_update, or to check a
    method's parameters and scopes. Types come with example bodies for common
    tag, trigger and variable types (for example gaawe, googtag, customEvent).

    Args:
        name: A type such as 'Tag', 'Trigger', 'Variable', 'Parameter',
            'Condition', 'BuiltInVariable', or a method id such as
            'accounts.containers.workspaces.tags.create'.

    Returns:
        For a type: its fields with type, enum values and description, plus
        examples. For a method: HTTP method, path template, parameters, body
        type and scopes.
    """
    try:
        described = discovery.describe(name)
    except KeyError as error:
        raise ToolError(str(error)) from None
    if name in examples():
        described['examples'] = examples()[name]
    return described


def raw_api_enabled() -> bool:
    """True when ``GTM_MCP_ENABLE_RAW_API`` asks for the escape hatch."""
    return os.environ.get('GTM_MCP_ENABLE_RAW_API', '').lower() in {'1', 'true', 'yes'}


def gtm_call_api(
    method_id: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Calls any Tag Manager API v2 method directly. An escape hatch.

    Use it only for methods the dedicated tools do not cover yet (the API
    gains methods over time). Look the method up with gtm_describe_schema
    first. Query parameters are validated against the discovery document;
    the body is sent as is. Non-GET methods require confirm=true.

    Args:
        method_id: Dotted id without the service prefix, for example
            accounts.containers.workspaces.tags.list.
        params: Query and path parameters by their API names (parent, path,
            fingerprint, ...).
        body: Request body for methods that take one.
        confirm: Must be true for any method that is not a GET.

    Returns:
        The verbatim API response.
    """
    try:
        spec = discovery.method(method_id)
    except KeyError as error:
        raise ToolError(str(error)) from None
    kwargs: dict[str, Any] = dict(params or {})
    unknown = sorted(set(kwargs) - set(spec.parameters))
    if unknown:
        raise ToolError(
            f'{method_id} has no parameter {", ".join(unknown)}; it takes:'
            f' {", ".join(sorted(spec.parameters))}'
        )
    if body is not None:
        if spec.request_schema is None:
            raise ToolError(f'{method_id} takes no request body')
        kwargs['body'] = body
    mutating = spec.http_method != 'GET'
    if mutating:
        require_confirm(confirm, f'{method_id} ({spec.http_method})')
    return client.execute(client.request(spec.id, **kwargs), mutating=mutating)


if raw_api_enabled():
    tool(tier=Tier.DESTRUCTIVE)(gtm_call_api)
