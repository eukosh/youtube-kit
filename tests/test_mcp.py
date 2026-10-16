"""MCP adapter. The snapshot pins the public tool surface; regenerate it deliberately with
UPDATE_SNAPSHOTS=1 after an intended change or a FastMCP upgrade, and review the diff."""

import json
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from youtube_kit.mcp_server import build_server

from .fakes import http_error, playlist_resource

SNAPSHOTS = Path(__file__).parent / "snapshots" / "mcp"

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def mcp():
    async with Client(build_server()) as connected:
        yield connected


async def test_tool_surface_matches_snapshots(mcp):
    fields = {"description", "input_schema", "output_schema", "annotations"}
    tools = {tool.name: tool.model_dump(mode="json", include=fields) for tool in await mcp.list_tools()}
    if os.environ.get("UPDATE_SNAPSHOTS"):
        shutil.rmtree(SNAPSHOTS, ignore_errors=True)
        SNAPSHOTS.mkdir(parents=True)
        for name, tool in tools.items():
            (SNAPSHOTS / f"{name}.json").write_text(
                json.dumps(tool, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            )
    snapshots = {path.stem: json.loads(path.read_text()) for path in SNAPSHOTS.glob("*.json")}
    assert sorted(tools) == sorted(snapshots)
    for name, tool in tools.items():
        assert tool == snapshots[name], f"{name} differs from its snapshot"


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


async def test_delete_confirmation_reaches_the_model_with_its_plan(mcp, api, my_channel):
    api.oauth.playlists().list().execute.return_value = {"items": [playlist_resource()]}
    with pytest.raises(ToolError, match=r'"confirm": "PL1"'):
        await mcp.call_tool("delete_playlist", {"playlist": "PL1"})
    api.oauth.playlists().delete.assert_not_called()
