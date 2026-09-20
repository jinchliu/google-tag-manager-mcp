"""Protocol-level checks: what an MCP client actually sees."""

import os
import sys
import tomllib
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from google_tag_manager_mcp import package_version
from google_tag_manager_mcp.server import (
    INSTRUCTIONS,
    SERVER_DESCRIPTION,
    SERVER_NAME,
    SERVER_TITLE,
    server,
)

pytestmark = pytest.mark.anyio

# Claude Code truncates tool descriptions and server instructions at 2KB each.
CLAUDE_CODE_TEXT_LIMIT = 2048


async def test_initialize_reports_identity() -> None:
    async with Client(server) as client:
        assert client.server_info is not None
        assert client.server_info.name == SERVER_NAME
        assert client.server_info.title == SERVER_TITLE
        assert client.server_info.description == SERVER_DESCRIPTION
        assert client.server_info.version == package_version()


def test_pyproject_summary_matches_the_server_description() -> None:
    # PyPI shows the pyproject summary and MCP clients show SERVER_DESCRIPTION;
    # one wording for both, and this fails when only one of them is edited.
    pyproject = Path(__file__).parent.parent / 'pyproject.toml'
    metadata = tomllib.loads(pyproject.read_text(encoding='utf-8'))
    assert metadata['project']['description'] == SERVER_DESCRIPTION


def test_instructions_fit_the_claude_code_truncation_limit() -> None:
    assert len(INSTRUCTIONS.encode()) <= CLAUDE_CODE_TEXT_LIMIT


async def test_stdio_transport_completes_the_handshake() -> None:
    # A stray write to stdout would corrupt the framing and fail this handshake.
    params = StdioServerParameters(
        command=sys.executable,
        args=['-c', 'from google_tag_manager_mcp import main; main()'],
    )
    async with Client(params) as client:
        assert client.server_info is not None
        assert client.server_info.name == SERVER_NAME


async def test_tools_carry_annotations_and_fit_the_limit() -> None:
    async with Client(server) as client:
        listed = (await client.list_tools()).tools
        names = {tool.name for tool in listed}
        assert 'gtm_describe_schema' in names
        assert len(listed) == 30
        for tool in listed:
            assert tool.name.startswith('gtm_')
            assert tool.description
            assert len(tool.description.encode()) <= CLAUDE_CODE_TEXT_LIMIT
            assert tool.annotations is not None
            wire = tool.annotations.model_dump(by_alias=True, exclude_none=True)
            assert 'readOnlyHint' in wire
        read_only = {
            t.name for t in listed if t.annotations and t.annotations.read_only_hint
        }
        destructive = {
            t.name for t in listed if t.annotations and t.annotations.destructive_hint
        }
        assert len(read_only) == 10
        assert len(destructive) == 11
        for tool in listed:
            needs_confirm = 'confirm' in tool.input_schema.get('properties', {})
            assert needs_confirm == (tool.name in destructive), tool.name


async def test_tool_errors_reach_the_client_as_text() -> None:
    async with Client(server) as client:
        result = await client.call_tool('gtm_describe_schema', {'name': 'Tagg'})
        assert result.is_error is True
        assert 'did you mean Tag' in result.content[0].text


async def _tool_names_over_stdio(**env: str) -> set[str]:
    params = StdioServerParameters(
        command=sys.executable,
        args=['-c', 'from google_tag_manager_mcp import main; main()'],
        env={**os.environ, **env},
    )
    async with Client(params) as client:
        return {tool.name for tool in (await client.list_tools()).tools}


async def test_read_only_mode_registers_only_read_tools() -> None:
    names = await _tool_names_over_stdio(GTM_MCP_READ_ONLY='1')
    assert len(names) == 10
    assert 'gtm_delete' not in names
    assert 'gtm_list' in names


async def test_raw_api_tool_is_opt_in() -> None:
    assert 'gtm_call_api' not in await _tool_names_over_stdio(GTM_MCP_ENABLE_RAW_API='')
    assert 'gtm_call_api' in await _tool_names_over_stdio(GTM_MCP_ENABLE_RAW_API='1')
