"""Tool registration: annotations per tier, read-only mode, and the coverage ledger.

Every tool declares its tier and the discovery methods it covers. The ledger is
what ``tests/test_coverage.py`` checks against the 106 methods of the API.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from google_tag_manager_mcp.server import server

F = TypeVar('F', bound=Callable[..., Any])


class Tier(Enum):
    """How a tool may affect the account: read-only, ordinary write, or destructive."""

    READ = 'read'
    WRITE = 'write'
    DESTRUCTIVE = 'destructive'


ANNOTATIONS: dict[Tier, ToolAnnotations] = {
    Tier.READ: ToolAnnotations(read_only_hint=True),
    Tier.WRITE: ToolAnnotations(read_only_hint=False, destructive_hint=False),
    Tier.DESTRUCTIVE: ToolAnnotations(read_only_hint=False, destructive_hint=True),
}


@dataclass(frozen=True)
class ToolEntry:
    """One registered tool and the API methods it covers, keyed by resource."""

    name: str
    tier: Tier
    methods: dict[str | None, str] = field(default_factory=dict)


REGISTRY: list[ToolEntry] = []


def read_only_mode() -> bool:
    """True when ``GTM_MCP_READ_ONLY`` asks for read tools only."""
    return os.environ.get('GTM_MCP_READ_ONLY', '').lower() in {'1', 'true', 'yes'}


def tool(
    *, tier: Tier, methods: dict[str | None, str] | None = None
) -> Callable[[F], F]:
    """Registers a tool on the server (unless excluded by read-only mode).

    Args:
        tier: Drives the annotations and the read-only filter.
        methods: Discovery method ids covered, keyed by resource name (None
            when the tool has a single method).
    """

    def decorator(fn: F) -> F:
        REGISTRY.append(ToolEntry(fn.__name__, tier, dict(methods or {})))
        if tier is Tier.READ or not read_only_mode():
            server.tool(annotations=ANNOTATIONS[tier])(fn)
        return fn

    return decorator


def require_confirm(confirm: bool, action: str) -> None:
    """Stops a destructive tool before it touches the API unless confirmed."""
    if not confirm:
        raise ToolError(
            f'{action} is not reversible. Ask the user, then call again with'
            ' confirm=true.'
        )
