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
from .core import progress, updates
from .core.config import Settings
from .core.models import Update

INSTRUCTIONS = """\
Read and manage YouTube through the YouTube Data API v3, YouTube Analytics and the YouTube Reporting API.

- Video, channel, and playlist parameters accept IDs or pasted YouTube URLs; channels also accept @handles.
- Listings return at most `limit` items plus a next_page_token; pass it back as page_token to continue.
- Every call spends daily API quota (10,000 units by default). search costs 100 units per page, so prefer
  cheaper reads: a channel's uploads_playlist_id with list_playlist_items, then get_videos.
- Tools that act on the user's own channel need a one-time setup and a sign-in per channel. When a tool says
  the user isn't logged in, setup_guide lists what is left; walk them through it one step at a time.
- The user may be logged in to several channels. list_my_channels shows them and the default one. Tools work on
  the default channel unless my_channel names another. When the user's channel matters and they have several,
  make sure which one they mean before writing.
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
                "openWorldHint": not meta.local,
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
    settings = Settings.from_env()
    updates.refresh_in_background(settings)
    if update := updates.notice(settings, stamp="noticed_mcp"):
        mcp.instructions = instructions_with(update)
    mcp.run(show_banner=False)


def instructions_with(update: Update) -> str:
    """No terminal here, so the model passes the reminder on."""
    return (
        f"{INSTRUCTIONS}- youtube-kit {update.latest} is out (this server runs {update.current}). After the user's"
        f" first request, tell them once to run `{update.command}` in a terminal and restart the MCP client."
        f" Changelog: {update.changelog}\n"
    )
