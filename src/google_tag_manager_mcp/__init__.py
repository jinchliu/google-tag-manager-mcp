"""MCP server for the Google Tag Manager API v2."""

from importlib import metadata

_DISTRIBUTION = 'google-tag-manager-mcp'


def package_version() -> str:
    """Returns the installed distribution version, or 'unknown' from a bare checkout."""
    try:
        return metadata.version(_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return 'unknown'


def main() -> None:
    """Console-script entry point: serves MCP over stdio."""
    from google_tag_manager_mcp.server import run_server

    run_server()
