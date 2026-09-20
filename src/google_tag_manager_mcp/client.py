"""The one place every Tag Manager API request goes through.

``execute()`` serialises calls, paces them under the per-project quota, retries
what is safe to retry, and turns every failure into a ``ToolError`` whose text
tells the model what to do next. A direct ``request.execute()`` anywhere else
is a bug.
"""

import json
import logging
import os
import random
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import google.auth.exceptions
import google_auth_httplib2
import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import set_user_agent
from mcp.server.mcpserver.exceptions import ToolError

from google_tag_manager_mcp import auth, discovery, package_version

HTTP_TIMEOUT_SECONDS = 30
# GTM quota: 25 requests per 100 s sliding window per GCP project. The default
# capacity leaves room for other clients sharing the project.
WINDOW_SECONDS = 100.0
DEFAULT_REQUESTS_PER_WINDOW = 20
MAX_RETRIES = 5
MAX_SLEEP_SECONDS = 30.0
COOL_DOWN_INTERVAL_SECONDS = 4.0
# Legacy endpoints report rate limiting as 403 with one of these reasons;
# current ones use 429. Both are retried.
RETRYABLE_REASONS = frozenset(
    {'userRateLimitExceeded', 'quotaExceeded', 'rateLimitExceeded'}
)

log = logging.getLogger(__name__)

# Replaced by tests with a fake clock.
monotonic: Callable[[], float] = time.monotonic
sleep: Callable[[float], None] = time.sleep


class Pacer:
    """Sliding-window rate limiter with a cool-down after a rejected request."""

    def __init__(self, capacity: int, window: float = WINDOW_SECONDS) -> None:
        """Allows ``capacity`` requests per ``window`` seconds."""
        self.capacity = capacity
        self.window = window
        self.sent: deque[float] = deque()
        self.cool_down = False

    def wait(self) -> None:
        """Blocks until one more request fits the window, then records it."""
        now = monotonic()
        while self.sent and now - self.sent[0] >= self.window:
            self.sent.popleft()
        if len(self.sent) >= self.capacity:
            delay = self.window - (now - self.sent[0])
            log.info('quota window full; waiting %.1fs', delay)
            sleep(delay)
            now = monotonic()
            self.sent.popleft()
        if self.cool_down and self.sent:
            gap = COOL_DOWN_INTERVAL_SECONDS - (now - self.sent[-1])
            if gap > 0:
                sleep(gap)
                now = monotonic()
        self.sent.append(now)

    def rejected(self) -> None:
        """Switches to cool-down spacing for the rest of the process."""
        self.cool_down = True


def _capacity_from_env() -> int:
    return int(
        os.environ.get('GTM_MCP_REQUESTS_PER_WINDOW', DEFAULT_REQUESTS_PER_WINDOW)
    )


pacer = Pacer(_capacity_from_env())

_call_lock = threading.Lock()
_service_lock = threading.Lock()
_service: Any = None


def service() -> Any:
    """Returns the process-wide discovery client, building it on first use."""
    global _service
    with _service_lock:
        if _service is None:
            http = set_user_agent(
                httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS),
                f'google-tag-manager-mcp/{package_version()}',
            )
            authorized = google_auth_httplib2.AuthorizedHttp(
                auth.credentials(), http=http
            )
            _service = build(
                discovery.SERVICE,
                discovery.VERSION,
                http=authorized,
                static_discovery=True,
                cache_discovery=False,
            )
        return _service


def request(method_id: str, **kwargs: Any) -> Any:
    """Builds the ``HttpRequest`` for a method id with the API's keyword arguments.

    The discovery client validates parameter names and enum values itself and
    raises ``TypeError``; that becomes a ``ToolError`` so the model sees it.
    """
    try:
        return discovery.bind(service(), method_id)(**kwargs)
    except TypeError as error:
        raise ToolError(f'Invalid arguments for {method_id}: {error}') from error


def execute(http_request: Any, *, mutating: bool) -> dict[str, Any]:
    """Runs a request under the lock, the pacer, and the retry policy.

    With ``mutating=True`` only rate-limit rejections are retried, because the
    API has no idempotency key and a retried 5xx could duplicate a write.
    """
    with _call_lock:
        for attempt in range(MAX_RETRIES + 1):
            pacer.wait()
            try:
                response = http_request.execute(num_retries=0)
            except google.auth.exceptions.RefreshError as error:
                raise ToolError(
                    'Google credentials could not be refreshed (expired or revoked).'
                    f' Log in again:\n  {auth.LOGIN_COMMAND}'
                ) from error
            except (OSError, httplib2.HttpLib2Error) as error:
                raise ToolError(
                    f'Network error reaching tagmanager.googleapis.com: {error!r}.'
                    ' Check connectivity and proxy settings.'
                ) from error
            except HttpError as error:
                status = int(error.status_code)
                reasons = _reasons(error)
                if not _should_retry(status, reasons, mutating):
                    raise ToolError(
                        _message(status, reasons, error, http_request)
                    ) from error
                if status < 500:
                    pacer.rejected()
                if attempt == MAX_RETRIES:
                    raise ToolError(
                        f'Tag Manager API kept failing (HTTP {status}) through'
                        f' {MAX_RETRIES} retries. The quota is 25 requests per 100'
                        ' seconds per project; wait a minute and retry.'
                    ) from error
                delay = _retry_delay(error, attempt)
                log.info(
                    'HTTP %s on attempt %d; retrying in %.1fs',
                    status,
                    attempt + 1,
                    delay,
                )
                sleep(delay)
            else:
                return response if isinstance(response, dict) else {}
    raise AssertionError('unreachable')


def _reasons(error: HttpError) -> set[str]:
    """Collects machine-readable reason codes from an error body.

    The body is untrusted input (proxies return HTML, payloads vary), so any
    parse failure yields whatever was collected so far.
    """
    reasons: set[str] = set()
    try:
        payload = json.loads(error.content.decode('utf-8'))['error']
        reasons.add(str(payload.get('status', '')))
        for item in payload.get('errors', []) + payload.get('details', []):
            reasons.add(str(item.get('reason', '')))
    except ValueError, KeyError, TypeError, AttributeError:
        pass
    reasons.discard('')
    return reasons


def _should_retry(status: int, reasons: set[str], mutating: bool) -> bool:
    if status == 429:
        return True
    if status >= 500:
        return not mutating
    return status == 403 and bool(reasons & RETRYABLE_REASONS)


def _retry_delay(error: HttpError, attempt: int) -> float:
    retry_after = error.resp.get('retry-after') if error.resp else None
    if retry_after:
        try:
            return min(float(retry_after), MAX_SLEEP_SECONDS)
        except ValueError:
            pass
    return min(2.0**attempt + random.uniform(0, 1), MAX_SLEEP_SECONDS)


def _method_for(http_request: Any) -> discovery.Method | None:
    method_id = getattr(http_request, 'methodId', None)
    if not method_id:
        return None
    return discovery.methods().get(str(method_id).removeprefix(discovery.SERVICE + '.'))


def _message(
    status: int, reasons: set[str], error: HttpError, http_request: Any
) -> str:
    """Maps an API error to a message that tells the caller what to do."""
    spec = _method_for(http_request)
    text = str(error)
    # Classify on the API's own message; the repr also contains the request
    # URI, whose query string (fingerprint=...) must not be mistaken for it.
    reason = str(error.reason).lower()
    if (
        'ACCESS_TOKEN_SCOPE_INSUFFICIENT' in reasons
        or 'authentication scopes' in reason
    ):
        needed = (
            ', '.join(scope.removeprefix(auth.SCOPE_PREFIX) for scope in spec.scopes)
            if spec
            else 'tagmanager.*'
        )
        return (
            f'The credentials lack a scope this call needs (one of: {needed}).'
            f' Log in again with all scopes:\n  {auth.LOGIN_COMMAND}'
        )
    if 'accessNotConfigured' in reasons or 'SERVICE_DISABLED' in reasons:
        return (
            'The Tag Manager API is not enabled on the quota project, or the'
            f' quota project points at the wrong GCP project: {error.reason}\n'
            'Either enable it there:\n'
            '  gcloud services enable tagmanager.googleapis.com'
            ' --project=THAT_PROJECT\n'
            'or set GOOGLE_CLOUD_QUOTA_PROJECT to a project that has it enabled.'
        )
    if status == 412 or (status == 400 and 'fingerprint' in reason):
        return (
            'The entity changed on the server between read and write (fingerprint'
            ' mismatch). Re-read it and apply the change again.'
        )
    if status == 400:
        return f'Invalid request (HTTP 400): {text}{_diagnose_body(spec, http_request)}'
    if status == 404:
        return (
            f'Not found (HTTP 404): {text}. Check the path against gtm_list output;'
            ' every locator is the full API path such as accounts/1/containers/2.'
        )
    if status == 403:
        return (
            f'Permission denied (HTTP 403): {text}. Verify that the Google account'
            ' has access to this GTM resource (Admin > User management).'
        )
    return f'Tag Manager API error (HTTP {status}): {text}'


def _diagnose_body(spec: discovery.Method | None, http_request: Any) -> str:
    """Compares the sent body with the discovery schema, only after a 400."""
    if spec is None or spec.request_schema is None:
        return ''
    raw = getattr(http_request, 'body', None)
    if not raw:
        return ''
    try:
        body = json.loads(raw)
    except ValueError:
        return ''
    if not isinstance(body, dict):
        return ''
    properties = discovery.schema(spec.request_schema).get('properties', {})
    notes: list[str] = []
    unknown = sorted(key for key in body if key not in properties)
    if unknown:
        notes.append(f'unknown fields for {spec.request_schema}: {", ".join(unknown)}')
    for key, value in body.items():
        prop = properties.get(key, {})
        allowed = prop.get('enum') or prop.get('items', {}).get('enum')
        if not allowed:
            continue
        values = value if isinstance(value, list) else [value]
        bad = [str(item) for item in values if item not in allowed]
        if bad:
            notes.append(
                f'{key} must be one of {", ".join(allowed)}; got {", ".join(bad)}'
            )
    if not notes:
        return ''
    return (
        '\nBody check: '
        + '; '.join(notes)
        + f". See gtm_describe_schema('{spec.request_schema}')."
    )
