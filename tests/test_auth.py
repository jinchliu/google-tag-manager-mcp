import google.auth.exceptions
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from google_tag_manager_mcp import auth


def test_missing_credentials_give_the_setup_steps(monkeypatch):
    monkeypatch.setattr(auth, '_credentials', None)

    def missing(scopes):
        raise google.auth.exceptions.DefaultCredentialsError('none')

    monkeypatch.setattr(auth.google.auth, 'default', missing)
    with pytest.raises(ToolError, match='gcloud auth application-default login'):
        auth.credentials()


def test_credentials_are_loaded_once(monkeypatch):
    monkeypatch.setattr(auth, '_credentials', None)
    calls = []

    def fake_default(scopes):
        calls.append(scopes)
        return object(), None

    monkeypatch.setattr(auth.google.auth, 'default', fake_default)
    first = auth.credentials()
    assert auth.credentials() is first
    assert calls == [list(auth.SCOPES)]


def test_login_command_requests_every_scope():
    for scope in auth.SCOPES:
        assert scope in auth.LOGIN_COMMAND
    assert 'cloud-platform' in auth.LOGIN_COMMAND
    assert len(auth.SCOPES) == 7
