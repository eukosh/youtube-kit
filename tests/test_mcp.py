"""MCP adapter. The snapshot pins the public tool surface; regenerate it deliberately with
UPDATE_SNAPSHOTS=1 after an intended change or a FastMCP upgrade, and review the diff."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from youtube_kit.mcp_server import build_server

from .fakes import http_error

SNAPSHOT = Path(__file__).parent / "snapshots" / "mcp_tools.json"

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def mcp():
    async with Client(build_server()) as connected:
        yield connected


async def test_tool_surface_matches_snapshot(mcp):
    tools = [
        tool.model_dump(mode="json", include={"name", "description", "input_schema", "output_schema", "annotations"})
        for tool in await mcp.list_tools()
    ]
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(tools, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    assert tools == json.loads(SNAPSHOT.read_text())


async def test_domain_errors_reach_the_model(mcp, api):
    api.public.channels().list().execute.side_effect = http_error(403, "quotaExceeded", "Quota gone.")
    with pytest.raises(ToolError, match="Quota gone"):
        await mcp.call_tool("get_channel", {"channel": "@x"})


async def test_input_errors_reach_the_model(mcp, api):
    with pytest.raises(ToolError, match="Not a YouTube video ID or URL"):
        await mcp.call_tool("get_videos", {"videos": ["nope"]})


async def test_unexpected_errors_are_masked(mcp, api):
    api.public.videoCategories().list().execute.side_effect = RuntimeError("internal detail")
    with pytest.raises(ToolError) as caught:
        await mcp.call_tool("list_video_categories", {})
    assert "internal detail" not in str(caught.value)


async def test_structured_results(mcp, api):
    api.public.videoCategories().list().execute.return_value = {
        "items": [{"id": "22", "snippet": {"title": "People & Blogs", "assignable": True}}]
    }
    result = await mcp.call_tool("list_video_categories", {"region": "US"})
    assert result.structured_content == {"result": [{"id": "22", "title": "People & Blogs"}]}


async def test_upload_progress_becomes_mcp_notifications(api, tmp_path):
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x" * 1000)
    api.oauth.videos().insert().next_chunk.side_effect = [
        (MagicMock(resumable_progress=500), None),
        (None, {"id": "NEWVIDEO123"}),
    ]
    updates = []

    async def on_progress(done, total, message):
        updates.append((done, total))

    async with Client(build_server(), progress_handler=on_progress) as mcp:
        await mcp.call_tool("upload_video", {"file": str(file), "title": "Hi"})

    assert updates == [(500, 1000), (1000, 1000)]
