"""MCP adapter: exposes core operations as FastMCP tools.

Tool names, schemas, and descriptions come straight from the core functions.
This module only adds what is MCP-specific: annotations, error translation,
and progress notifications.
"""

import functools
import json
from collections.abc import Callable
from importlib.metadata import version

import anyio.from_thread
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_context

from . import core
from .core import progress

INSTRUCTIONS = """\
Read and manage YouTube through the YouTube Data API v3.

- Video, channel, and playlist parameters accept IDs or pasted YouTube URLs; channels also accept @handles.
- Listings return at most `limit` items plus a next_page_token; pass it back as page_token to continue.
- Every call spends daily API quota (10,000 units by default). search costs 100 units per page, so prefer
  cheaper reads: a channel's uploads_playlist_id with list_playlist_items, then get_videos.
- Tools that act on the user's own channel need the user to have run `ytk auth login` once.
- Deletes are permanent. Called without `confirm`, a delete tool changes nothing and fails with a description
  of the target. Show that to the user and call again with `confirm` set to the given ID only after they
  approve. Videos past the delete protection limits can't be deleted here; send the user to YouTube Studio.
"""

# Read-only tools first, so the safe ones lead the list clients show.
TOOLS: list[Callable] = sorted(core.OPERATIONS, key=lambda operation: not core.info(operation).read_only)


def build_server() -> FastMCP:
    server = FastMCP("YouTube", version=version("youtube-kit"), instructions=INSTRUCTIONS, mask_error_details=True)
    for operation in TOOLS:
        meta = core.info(operation)
        server.tool(
            as_tool(operation),
            annotations={
                "readOnlyHint": meta.read_only,
                "destructiveHint": meta.destructive,
                "idempotentHint": meta.idempotent,
                "openWorldHint": True,
            },
        )
    return server


def as_tool[**P, R](operation: Callable[P, R]) -> Callable[P, R]:
    """Wrap an operation so domain errors reach the model and progress reaches the client.

    FastMCP masks any exception that isn't a ToolError, so errors must be translated
    here rather than in middleware. Sync tools run on an AnyIO worker thread with the
    caller's context copied, which is what lets the progress bridge work.
    """

    @functools.wraps(operation)
    def tool(*args: P.args, **kwargs: P.kwargs) -> R:
        ctx = get_context()

        def report(done: int, total: int) -> None:
            anyio.from_thread.run(ctx.report_progress, done, total)

        try:
            with progress.reporting_to(report):
                return operation(*args, **kwargs)
        except core.YouTubeError as e:
            details = f" Details: {json.dumps(e.details)}" if e.details else ""
            raise ToolError(f"{e}{details}") from e

    return tool


mcp = build_server()


def run() -> None:
    """Serve over stdio."""
    mcp.run(show_banner=False)
