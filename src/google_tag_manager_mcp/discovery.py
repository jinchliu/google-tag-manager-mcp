"""Index over the bundled Tag Manager v2 discovery document.

The document ships inside google-api-python-client (``discovery_cache``), so the
index works offline and is the single source of truth for method ids,
parameters, scopes, list response keys and schema descriptions.
"""

import difflib
import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Any

from googleapiclient.discovery_cache import get_static_doc

SERVICE = 'tagmanager'
VERSION = 'v2'
_ID_PREFIX = f'{SERVICE}.'


@dataclass(frozen=True)
class Method:
    """One API method, for example ``accounts.containers.workspaces.tags.list``."""

    id: str
    resource: tuple[str, ...]
    name: str
    http_method: str
    path: str
    description: str
    parameters: dict[str, dict[str, Any]]
    scopes: tuple[str, ...]
    request_schema: str | None
    response_schema: str | None

    @property
    def collection(self) -> str:
        """The innermost resource collection, for example ``tags``."""
        return self.resource[-1]


@cache
def document() -> dict[str, Any]:
    """Returns the parsed discovery document."""
    raw = get_static_doc(SERVICE, VERSION)
    if raw is None:
        raise RuntimeError('google-api-python-client ships no tagmanager v2 document')
    parsed: dict[str, Any] = json.loads(raw)
    return parsed


@cache
def methods() -> dict[str, Method]:
    """Returns every method keyed by its dotted id (without the service prefix)."""
    found: dict[str, Method] = {}

    def walk(resources: dict[str, Any], path: tuple[str, ...]) -> None:
        for name, resource in resources.items():
            here = (*path, name)
            for method_name, spec in resource.get('methods', {}).items():
                method_id = spec['id'].removeprefix(_ID_PREFIX)
                found[method_id] = Method(
                    id=method_id,
                    resource=here,
                    name=method_name,
                    http_method=spec['httpMethod'],
                    path=spec['path'],
                    description=spec.get('description', ''),
                    parameters=spec.get('parameters', {}),
                    scopes=tuple(spec.get('scopes', ())),
                    request_schema=spec.get('request', {}).get('$ref'),
                    response_schema=spec.get('response', {}).get('$ref'),
                )
            walk(resource.get('resources', {}), here)

    walk(document()['resources'], ())
    return found


def method(method_id: str) -> Method:
    """Returns one method by id; raises ``KeyError`` naming close matches."""
    try:
        return methods()[method_id]
    except KeyError:
        hint = _suggest(method_id, methods())
        raise KeyError(f'unknown Tag Manager API method {method_id!r}{hint}') from None


@cache
def collections() -> dict[str, tuple[str, ...]]:
    """Maps each collection name to its resource path.

    Collection names are unique across the API, so ``tags`` unambiguously means
    ``('accounts', 'containers', 'workspaces', 'tags')``.
    """
    found: dict[str, tuple[str, ...]] = {}
    for spec in methods().values():
        found.setdefault(spec.collection, spec.resource)
    return found


def parent_collection(collection: str) -> str | None:
    """Returns the collection a resource lives under, or None for accounts."""
    path = collections()[collection]
    return path[-2] if len(path) > 1 else None


def find_method(collection: str, name: str) -> Method | None:
    """Returns ``<collection>.<name>`` when the API has it, else None."""
    return methods().get('.'.join((*collections()[collection], name)))


def schemas() -> dict[str, dict[str, Any]]:
    """Returns every schema keyed by name."""
    found: dict[str, dict[str, Any]] = document()['schemas']
    return found


def schema(name: str) -> dict[str, Any]:
    """Returns one schema by name; raises ``KeyError`` naming close matches."""
    try:
        return schemas()[name]
    except KeyError:
        hint = _suggest(name, schemas())
        raise KeyError(f'unknown Tag Manager API type {name!r}{hint}') from None


@cache
def list_items_key(collection: str) -> str:
    """Returns the array key of a list response, for example ``tag``.

    Every ``List*Response`` has exactly one array property next to
    ``nextPageToken``, so the key is derived instead of hand-maintained.
    """
    spec = find_method(collection, 'list')
    if spec is None or spec.response_schema is None:
        raise KeyError(f'{collection} has no list method')
    properties = schema(spec.response_schema)['properties']
    arrays = [
        str(key) for key, prop in properties.items() if prop.get('type') == 'array'
    ]
    if len(arrays) != 1:
        raise KeyError(f'{spec.response_schema} has {len(arrays)} array properties')
    return arrays[0]


def bind(service: Any, method_id: str) -> Callable[..., Any]:
    """Returns the discovery client callable for a method id.

    ``bind(service, 'accounts.containers.workspaces.tags.list')`` is
    ``service.accounts().containers().workspaces().tags().list``; calling it
    with the API's keyword arguments yields an ``HttpRequest``.
    """
    spec = method(method_id)
    node = service
    for segment in spec.resource:
        node = getattr(node, segment)()
    bound: Callable[..., Any] = getattr(node, spec.name)
    return bound


def describe(name: str) -> dict[str, Any]:
    """Describes a schema (fields, enums) or a method (parameters, scopes)."""
    if name in schemas():
        return _describe_schema(name)
    if name in methods():
        return _describe_method(methods()[name])
    hint = _suggest(name, {**schemas(), **methods()})
    raise KeyError(f'{name!r} is neither a Tag Manager API type nor a method id{hint}')


def _describe_schema(name: str) -> dict[str, Any]:
    spec = schema(name)
    fields: dict[str, dict[str, Any]] = {}
    for key, prop in spec.get('properties', {}).items():
        field: dict[str, Any] = {'type': _type_name(prop)}
        enum = prop.get('enum') or prop.get('items', {}).get('enum')
        if enum:
            field['enum'] = enum
        if prop.get('description'):
            field['description'] = prop['description']
        fields[key] = field
    return {
        'type': name,
        'description': spec.get('description', ''),
        'fields': fields,
    }


def _describe_method(spec: Method) -> dict[str, Any]:
    parameters = {
        key: {
            'type': param.get('type', 'string'),
            'required': bool(param.get('required')),
            'repeated': bool(param.get('repeated')),
            **({'enum': param['enum']} if 'enum' in param else {}),
            'description': param.get('description', ''),
        }
        for key, param in spec.parameters.items()
    }
    return {
        'method': spec.id,
        'httpMethod': spec.http_method,
        'path': spec.path,
        'description': spec.description,
        'parameters': parameters,
        'requestBody': spec.request_schema,
        'response': spec.response_schema,
        'scopes': list(spec.scopes),
    }


def _type_name(prop: dict[str, Any]) -> str:
    if '$ref' in prop:
        return str(prop['$ref'])
    if prop.get('type') == 'array':
        return f'array<{_type_name(prop.get("items", {}))}>'
    return str(prop.get('type', 'string'))


def _suggest(name: str, candidates: dict[str, Any]) -> str:
    matches = difflib.get_close_matches(name, candidates, n=3, cutoff=0.5)
    return f'; did you mean {", ".join(matches)}?' if matches else ''
