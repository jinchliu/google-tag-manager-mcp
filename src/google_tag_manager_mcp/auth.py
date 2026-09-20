"""Application Default Credentials, resolved the way Google's analytics-mcp does.

No OAuth client ships with this package. Users create a Desktop client in their
own Google Cloud project and log in with gcloud; google-auth then finds the
credentials through ``GOOGLE_APPLICATION_CREDENTIALS`` or the gcloud ADC file,
and the quota project through the ADC file or ``GOOGLE_CLOUD_QUOTA_PROJECT``.
"""

import subprocess
import threading
from typing import Any
from unittest.mock import patch

import google.auth
import google.auth.exceptions
from google.auth.credentials import Credentials
from mcp.server.mcpserver.exceptions import ToolError

SCOPE_PREFIX = 'https://www.googleapis.com/auth/'
SCOPES = tuple(
    SCOPE_PREFIX + name
    for name in (
        'tagmanager.readonly',
        'tagmanager.edit.containers',
        'tagmanager.delete.containers',
        'tagmanager.edit.containerversions',
        'tagmanager.publish',
        'tagmanager.manage.users',
        'tagmanager.manage.accounts',
    )
)
# cloud-platform unlocks nothing in GTM; it is what lets a quota project other
# than the OAuth client's own be validated.
LOGIN_COMMAND = (
    'gcloud auth application-default login'
    ' --client-id-file=YOUR_DESKTOP_CLIENT.json'
    f' --scopes={",".join((*SCOPES, SCOPE_PREFIX + "cloud-platform"))}'
)
SETUP_HINT = (
    'Set up Application Default Credentials with your own OAuth client:\n'
    '  1. gcloud services enable tagmanager.googleapis.com --project=YOUR_PROJECT\n'
    '  2. Create a Desktop OAuth client in that project and download its JSON\n'
    f'  3. {LOGIN_COMMAND}\n'
    'Calls count against the quota of the project that owns the OAuth\n'
    'client; set GOOGLE_CLOUD_QUOTA_PROJECT to use another project.'
)

_lock = threading.Lock()
_credentials: Credentials | None = None
_ORIGINAL_POPEN = subprocess.Popen


def _safe_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
    """``subprocess.Popen`` with stdin defaulting to DEVNULL.

    On Windows, ``google.auth.default()`` may spawn gcloud without redirecting
    stdin; the child then inherits the event loop's stdio handles used by the
    MCP transport and deadlocks. A closed stdin avoids that.
    """
    if kwargs.get('stdin') is None:
        kwargs['stdin'] = subprocess.DEVNULL
    return _ORIGINAL_POPEN(*args, **kwargs)


def _default_credentials() -> tuple[Credentials, str | None]:
    """Runs ``google.auth.default()`` with child processes kept off our stdio."""
    patcher = patch('subprocess.Popen', new=_safe_popen)
    patcher.start()
    try:
        return google.auth.default(scopes=list(SCOPES))
    finally:
        patcher.stop()


def credentials() -> Credentials:
    """Loads ADC once per process; thread-safe."""
    global _credentials
    with _lock:
        if _credentials is None:
            try:
                _credentials, _ = _default_credentials()
            except google.auth.exceptions.DefaultCredentialsError as error:
                raise ToolError(f'No Google credentials found. {SETUP_HINT}') from error
        return _credentials
