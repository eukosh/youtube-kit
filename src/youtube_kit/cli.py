"""`ytk`: the command-line adapter over the core operations.

Contract (relied on by agents and scripts, documented in skills/youtube/SKILL.md):
- stdout carries exactly one JSON document per successful command, nulls omitted.
- Failures print {"error": {"type", "message"}} to stderr and exit with the
  error's code: 2 invalid input, 3 not found, 4 not authorized, 5 quota
  exceeded, 6 forbidden, 7 network, 1 anything else. Usage errors from
  argument parsing also exit 2.
"""

import contextlib
import json
import sys
from collections.abc import Iterator, Sequence
from importlib.metadata import version

import cyclopts
import pydantic_core
from cyclopts import CycloptsError

from . import core
from .core import auth, progress
from .core.config import Settings
from .core.models import AuthStatus

app = cyclopts.App(
    name="ytk",
    help="YouTube Data API from the command line. Prints JSON; see `ytk <command> --help`.",
    version=version("youtube-kit"),
)

video = app.command(cyclopts.App(name="video", help="Look up, upload, and edit videos."))
channel = app.command(cyclopts.App(name="channel", help="Look up channels."))
playlist = app.command(cyclopts.App(name="playlist", help="List, create, and add to playlists."))
auth_app = app.command(cyclopts.App(name="auth", help="Authorize access to your YouTube account."))

app.command(core.search, name="search")
video.command(core.get_videos, name="get")
video.command(core.list_comments, name="comments")
video.command(core.list_video_categories, name="categories")
video.command(core.upload_video, name="upload")
video.command(core.update_video, name="update")
video.command(core.set_thumbnail, name="thumbnail")
channel.command(core.get_channel, name="get")
channel.command(core.get_my_channel, name="mine")
playlist.command(core.list_playlist_items, name="items")
playlist.command(core.create_playlist, name="create")
playlist.command(core.add_video_to_playlist, name="add")


@auth_app.command(name="login")
def auth_login(*, browser: bool = True) -> AuthStatus:
    """Authorize your YouTube account through Google's OAuth consent screen.

    Needs an OAuth client of type "Desktop app" saved as client_secrets.json
    (see `ytk auth status` for the path). The token is stored for both the CLI
    and the MCP server.

    Args:
        browser: Open the consent page automatically. With --no-browser, open the printed URL yourself.
    """
    # The OAuth library prints the consent URL to stdout, which is reserved for JSON.
    with contextlib.redirect_stdout(sys.stderr):
        return auth.login(Settings.from_env(), open_browser=browser)


@auth_app.command(name="status")
def auth_status() -> AuthStatus:
    """Show which credentials are configured and where they are stored. Makes no API calls."""
    return auth.status(Settings.from_env())


@auth_app.command(name="logout")
def auth_logout() -> AuthStatus:
    """Delete the stored OAuth token. The API key, if any, is unaffected."""
    return auth.logout(Settings.from_env())


@app.command(name="mcp")
def serve_mcp() -> None:
    """Run the MCP server over stdio, exposing the same operations as tools."""
    from . import mcp_server  # deferred: FastMCP is slow to import and only needed here

    mcp_server.run()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        with _terminal_progress():
            result = app(argv, exit_on_error=False, result_action="return_value")
    except CycloptsError:
        return 2  # cyclopts has already printed the error
    except core.YouTubeError as e:
        error = {"type": e.kind, "message": str(e)}
        print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
        return e.exit_code
    if result is not None:
        indent = 2 if sys.stdout.isatty() else None
        print(pydantic_core.to_json(result, indent=indent, exclude_none=True).decode())
    return 0


@contextlib.contextmanager
def _terminal_progress() -> Iterator[None]:
    """Show a self-overwriting percentage on stderr when a human is watching.

    The line is ended on exit, before any error is printed after it.
    """
    if not sys.stderr.isatty():
        yield
        return
    shown = False

    def show(done: int, total: int) -> None:
        nonlocal shown
        shown = True
        percent = 100 * done // total if total else 100
        print(f"\rprogress: {percent:3d}%", end="", file=sys.stderr, flush=True)

    try:
        with progress.reporting_to(show):
            yield
    finally:
        if shown:
            print(file=sys.stderr)
