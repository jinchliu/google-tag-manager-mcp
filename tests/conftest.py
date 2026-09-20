"""Shared fixtures: an HTTP-layer fake for the discovery client and a fake clock."""

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httplib2
import pytest
from googleapiclient.discovery import build

from google_tag_manager_mcp import client as client_module
from google_tag_manager_mcp import discovery
from google_tag_manager_mcp.server import register_tools

register_tools()


class RecordingHttp:
    """Serves queued responses and records every request the real client makes.

    Sitting below googleapiclient means method names, parameter names and enum
    values are validated by the discovery client itself, and the assertions
    see the real HTTP method, URI and body.
    """

    def __init__(self) -> None:
        self.queued: list[tuple[int, Any, dict[str, str]]] = []
        self.calls: list[dict[str, Any]] = []

    def queue(self, payload: Any, status: int = 200, **headers: str) -> None:
        """Queues one response; an Exception payload is raised instead."""
        self.queued.append((status, payload, headers))

    def request(
        self,
        uri: str,
        method: str = 'GET',
        body: str | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> tuple[httplib2.Response, bytes]:
        self.calls.append(
            {'method': method, 'uri': uri, 'body': json.loads(body) if body else None}
        )
        if not self.queued:
            raise AssertionError(f'unexpected request {method} {uri}')
        status, payload, extra = self.queued.pop(0)
        if isinstance(payload, Exception):
            raise payload
        response = httplib2.Response({'status': status, 'reason': 'fake', **extra})
        return response, json.dumps(payload).encode()

    @property
    def last(self) -> dict[str, Any]:
        return self.calls[-1]


def url_parts(call: dict[str, Any]) -> tuple[str, dict[str, list[str]]]:
    """Splits a recorded call into the URI path and its parsed query string."""
    split = urlsplit(call['uri'])
    query = parse_qs(split.query, keep_blank_values=True)
    query.pop('alt', None)
    return split.path, query


class FakeClock:
    """Replaces time.monotonic / time.sleep so pacing tests run instantly."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(client_module, 'monotonic', fake.monotonic)
    monkeypatch.setattr(client_module, 'sleep', fake.sleep)
    monkeypatch.setattr(client_module, 'pacer', client_module.Pacer(capacity=20))
    return fake


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> RecordingHttp:
    fake = RecordingHttp()
    service = build(
        discovery.SERVICE,
        discovery.VERSION,
        http=fake,
        static_discovery=True,
        cache_discovery=False,
    )
    monkeypatch.setattr(client_module, '_service', service)
    return fake
