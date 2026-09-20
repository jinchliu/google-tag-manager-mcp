import google.auth.exceptions
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from google_tag_manager_mcp import client

LIST = 'accounts.containers.workspaces.tags.list'
UPDATE = 'accounts.containers.workspaces.tags.update'
WORKSPACE = 'accounts/1/containers/2/workspaces/3'


def error_body(status, reason, message):
    return {
        'error': {
            'code': 0,
            'message': message,
            'status': status,
            'errors': [{'reason': reason, 'message': message, 'domain': 'global'}],
        }
    }


def list_request():
    return client.request(LIST, parent=WORKSPACE)


def test_success_returns_the_payload(http, clock):
    http.queue({'tag': [{'tagId': '4'}]})
    assert client.execute(list_request(), mutating=False) == {'tag': [{'tagId': '4'}]}
    assert clock.sleeps == []
    assert http.last['uri'].endswith('/workspaces/3/tags?alt=json')


def test_empty_response_becomes_an_empty_dict(http, clock):
    http.queue(None)
    assert client.execute(list_request(), mutating=False) == {}


def test_429_is_retried_after_retry_after(http, clock):
    http.queue(
        error_body('RESOURCE_EXHAUSTED', 'rateLimitExceeded', 'slow down'),
        429,
        **{'retry-after': '7'},
    )
    http.queue({'tag': []})
    assert client.execute(list_request(), mutating=False) == {'tag': []}
    assert clock.sleeps[0] == 7.0
    assert len(http.calls) == 2
    assert client.pacer.cool_down is True


def test_403_with_quota_reason_is_retried_with_backoff(http, clock):
    http.queue(error_body('PERMISSION_DENIED', 'userRateLimitExceeded', 'quota'), 403)
    http.queue({'tag': []})
    client.execute(list_request(), mutating=False)
    assert 1.0 <= clock.sleeps[0] <= 2.0
    assert len(http.calls) == 2


def test_403_without_quota_reason_is_not_retried(http, clock):
    http.queue(error_body('PERMISSION_DENIED', 'forbidden', 'no access'), 403)
    with pytest.raises(ToolError, match='Permission denied'):
        client.execute(list_request(), mutating=False)
    assert len(http.calls) == 1


def test_5xx_is_retried_for_reads_only(http, clock):
    http.queue(error_body('UNAVAILABLE', 'backendError', 'try later'), 503)
    http.queue({'tag': []})
    assert client.execute(list_request(), mutating=False) == {'tag': []}
    assert len(http.calls) == 2

    write = client.request(
        UPDATE, path=f'{WORKSPACE}/tags/4', fingerprint='1', body={'name': 'x'}
    )
    http.queue(error_body('UNAVAILABLE', 'backendError', 'try later'), 503)
    with pytest.raises(ToolError, match='HTTP 503'):
        client.execute(write, mutating=True)
    assert len(http.calls) == 3
    assert len(clock.sleeps) == 1


def test_gives_up_after_max_retries(http, clock):
    for _ in range(client.MAX_RETRIES + 1):
        http.queue(
            error_body('RESOURCE_EXHAUSTED', 'rateLimitExceeded', 'slow down'), 429
        )
    with pytest.raises(ToolError, match='kept failing'):
        client.execute(list_request(), mutating=False)
    assert len(http.calls) == client.MAX_RETRIES + 1


def test_scope_error_names_the_needed_scopes_and_the_login_command(http, clock):
    http.queue(
        error_body(
            'PERMISSION_DENIED',
            'insufficientPermissions',
            'Request had insufficient authentication scopes.',
        ),
        403,
    )
    with pytest.raises(ToolError) as info:
        client.execute(list_request(), mutating=False)
    text = str(info.value)
    assert 'tagmanager.readonly' in text
    assert 'gcloud auth application-default login' in text


def test_api_not_enabled_points_at_the_quota_project(http, clock):
    http.queue(
        error_body(
            'PERMISSION_DENIED', 'accessNotConfigured', 'Access Not Configured.'
        ),
        403,
    )
    with pytest.raises(ToolError, match='not enabled on the quota project'):
        client.execute(list_request(), mutating=False)


def test_fingerprint_mismatch_is_explained(http, clock):
    write = client.request(
        UPDATE, path=f'{WORKSPACE}/tags/4', fingerprint='1', body={'name': 'x'}
    )
    http.queue(
        error_body(
            'INVALID_ARGUMENT',
            'badRequest',
            'The provided entity fingerprint is not valid.',
        ),
        400,
    )
    with pytest.raises(ToolError, match='fingerprint mismatch'):
        client.execute(write, mutating=True)


def test_400_diagnoses_unknown_fields_and_bad_enums(http, clock):
    body = {'name': 'x', 'firingTriggerIds': ['1'], 'tagFiringOption': 'always'}
    write = client.request(
        UPDATE, path=f'{WORKSPACE}/tags/4', fingerprint='1', body=body
    )
    http.queue(error_body('INVALID_ARGUMENT', 'badRequest', 'Bad Request'), 400)
    with pytest.raises(ToolError) as info:
        client.execute(write, mutating=True)
    text = str(info.value)
    assert 'unknown fields for Tag: firingTriggerIds' in text
    assert 'tagFiringOption must be one of' in text
    assert "gtm_describe_schema('Tag')" in text


def test_404_explains_paths(http, clock):
    http.queue(error_body('NOT_FOUND', 'notFound', 'Not found'), 404)
    with pytest.raises(ToolError, match='Check the path against gtm_list'):
        client.execute(list_request(), mutating=False)


def test_refresh_error_asks_for_a_new_login(http, clock):
    http.queue(google.auth.exceptions.RefreshError('expired'))
    with pytest.raises(ToolError, match='Log in again'):
        client.execute(list_request(), mutating=False)


def test_network_error_is_reported(http, clock):
    http.queue(OSError('boom'))
    with pytest.raises(ToolError, match='Network error'):
        client.execute(list_request(), mutating=False)


def test_pacer_waits_when_the_window_is_full(clock):
    pacer = client.Pacer(capacity=2, window=100.0)
    pacer.wait()
    clock.now += 10
    pacer.wait()
    pacer.wait()
    assert clock.sleeps == [90.0]
    assert list(pacer.sent) == [1010.0, 1100.0]


def test_pacer_spaces_requests_after_a_rejection(clock):
    pacer = client.Pacer(capacity=5)
    pacer.wait()
    pacer.rejected()
    pacer.wait()
    assert clock.sleeps == [client.COOL_DOWN_INTERVAL_SECONDS]
