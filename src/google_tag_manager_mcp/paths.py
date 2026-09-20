"""Parsing and validation of Tag Manager API resource paths.

Every locator a tool accepts is the API's own path string, exactly as returned
in the ``path`` field of responses: ``accounts/1/containers/2/workspaces/3``.
The nesting rules come from the discovery document rather than a hand-written
table, so a path is valid here exactly when the API would accept it.
"""

from dataclasses import dataclass

from mcp.server.mcpserver.exceptions import ToolError

from google_tag_manager_mcp import discovery


@dataclass(frozen=True)
class ResourcePath:
    """A parsed path: ``((collection, id), ...)``.

    Only the last pair may lack an id, which is how collection-level paths such
    as ``.../workspaces/3/built_in_variables`` are represented.
    """

    segments: tuple[tuple[str, str | None], ...]

    @property
    def collection(self) -> str:
        """The innermost collection name, for example ``tags``."""
        return self.segments[-1][0]

    @property
    def id(self) -> str | None:
        """The innermost resource id, or None for a collection-level path."""
        return self.segments[-1][1]

    @property
    def parent(self) -> str:
        """The path of the enclosing resource (``''`` for an account)."""
        return _join(self.segments[:-1])

    def __str__(self) -> str:
        """The path in API form."""
        return _join(self.segments)


def shape(collection: str) -> str:
    """Returns the expected form of a path, for example ``accounts/{accountId}``."""
    return '/'.join(
        f'{name}/{{{_singular(name)}Id}}'
        for name in discovery.collections()[collection]
    )


def _singular(collection: str) -> str:
    return collection.removesuffix('s')


def parse(path: str) -> ResourcePath:
    """Parses and validates a path; raises ``ToolError`` describing the problem."""
    parts = [part for part in path.strip().strip('/').split('/') if part]
    if not parts:
        raise ToolError('Empty path; expected something like accounts/123')
    segments: list[tuple[str, str | None]] = []
    known = discovery.collections()
    for index in range(0, len(parts), 2):
        collection = parts[index]
        if collection not in known:
            raise ToolError(
                f'Invalid path {path!r}: {collection!r} is not a collection. '
                f'Known collections: {", ".join(sorted(known))}'
            )
        expected_parent = discovery.parent_collection(collection)
        actual_parent = segments[-1][0] if segments else None
        if expected_parent != actual_parent:
            raise ToolError(
                f'Invalid path {path!r}: {collection} must appear as'
                f' {shape(collection)}'
            )
        resource_id = parts[index + 1] if index + 1 < len(parts) else None
        segments.append((collection, resource_id))
    return ResourcePath(tuple(segments))


def expect(path: str, collection: str) -> ResourcePath:
    """Parses a path that must point at one resource of ``collection``."""
    parsed = parse(path)
    if parsed.collection != collection or parsed.id is None:
        raise ToolError(
            f'Expected a {collection} path of the form {shape(collection)},'
            f' got {path!r}'
        )
    return parsed


def expect_parent(parent: str, collection: str) -> ResourcePath:
    """Parses the parent path under which ``collection`` items live."""
    required = discovery.parent_collection(collection)
    if required is None:
        raise ToolError(f'{collection} has no parent; omit the parent argument')
    parsed = parse(parent)
    if parsed.collection != required or parsed.id is None:
        raise ToolError(
            f'{collection} live under {required}; expected a parent of the form '
            f'{shape(required)}, got {parent!r}'
        )
    return parsed


def _join(segments: tuple[tuple[str, str | None], ...]) -> str:
    parts: list[str] = []
    for collection, resource_id in segments:
        parts.append(collection)
        if resource_id is not None:
            parts.append(resource_id)
    return '/'.join(parts)
