"""`ytk`: the command-line adapter over the core operations.

Contract (relied on by agents and scripts, documented in skills/youtube/SKILL.md):
- stdout carries exactly one JSON document per successful command, nulls omitted.
- Failures print {"error": {"type", "message", "details"?}} to stderr and exit
  with the error's code: 2 invalid input, 3 not found, 4 not authorized, 5 quota
  exceeded, 6 forbidden, 7 network, 8 confirmation required, 9 protected,
  10 timeout, 1 anything else. Usage errors from argument parsing also exit 2.
- Guarded deletes ask a human at a terminal instead of exiting 8; declining exits 1.
  For agents, the exit-8 details include `rerun`, the exact command that confirms.
"""

import contextlib
import json
import shlex
import sys
from collections.abc import Iterator, Sequence
from importlib.metadata import version
from typing import Annotated

import cyclopts
import pydantic_core
from cyclopts import CycloptsError

from . import core
from .core import auth, progress
from .core.config import Settings
from .core.models import AuthStatus
from .core.ops import analytics, channels, comments, playlists, search, videos

app = cyclopts.App(
    name="ytk",
    help="YouTube Data API from the command line. Prints JSON; see `ytk <command> --help`.",
    version=version("youtube-kit"),
    # No --no-X / --empty-X flags, except on update commands where "unset" and "clear" mean something.
    default_parameter=cyclopts.Parameter(negative_bool=(), negative_iterable=()),
)

video = app.command(cyclopts.App(name="video", help="Look up, upload, edit, and delete videos."))
playlist = app.command(cyclopts.App(name="playlist", help="Look up and manage playlists."))
comment = app.command(cyclopts.App(name="comment", help="Read, write, and moderate comments."))
channel = app.command(cyclopts.App(name="channel", help="Look up channels and their activity."))
auth_app = app.command(cyclopts.App(name="auth", help="Authorize access to your YouTube account."))

_NEGATIVES = cyclopts.Parameter(negative_bool=None, negative_iterable=None)

app.command(search.search, name="search")
app.command(analytics.get_analytics, name="analytics")

video.command(videos.get_videos, name="get")
video.command(videos.list_video_categories, name="categories")
video.command(videos.upload_video, name="upload")
video.command(videos.get_processing_status, name="status")
video.command(videos.update_video, name="update", default_parameter=_NEGATIVES)
video.command(videos.set_thumbnail, name="thumbnail")
video.command(videos.delete_video, name="delete")

playlist.command(playlists.list_playlists, name="list")
playlist.command(playlists.get_playlists, name="get")
playlist.command(playlists.list_playlist_items, name="items")
playlist.command(playlists.create_playlist, name="create")
playlist.command(playlists.update_playlist, name="update")
playlist.command(playlists.set_playlist_thumbnail, name="thumbnail")
playlist.command(playlists.delete_playlist, name="delete")
playlist.command(playlists.add_video_to_playlist, name="add")
playlist.command(playlists.remove_from_playlist, name="remove")
playlist.command(playlists.move_in_playlist, name="move")

comment.command(comments.list_comments, name="list")
comment.command(comments.list_replies, name="replies")
comment.command(comments.post_comment, name="post")
comment.command(comments.reply_to_comment, name="reply")
comment.command(comments.edit_comment, name="edit")
comment.command(comments.delete_comment, name="delete")
comment.command(comments.approve_comments, name="approve")
comment.command(comments.hold_comments, name="hold")
comment.command(comments.reject_comments, name="reject")

channel.command(channels.get_channel, name="get")
channel.command(channels.get_my_channel, name="mine")
channel.command(channels.list_activities, name="activity")


@auth_app.command(name="login")
def auth_login(*, browser: Annotated[bool, cyclopts.Parameter(negative_bool=None)] = True) -> AuthStatus:
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
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        with _terminal_progress():
            result = app(argv, exit_on_error=False, result_action="return_value")
    except CycloptsError:
        return 2  # cyclopts has already printed the error
    except core.ConfirmationRequired as e:
        confirmed = _with_confirm(argv, e.details["confirm"])
        if not (sys.stdin.isatty() and sys.stderr.isatty()):
            e.details["rerun"] = shlex.join(["ytk", *confirmed])
            return _fail(e)
        if not _approved(e.details):
            print("Cancelled; nothing was deleted.", file=sys.stderr)
            return 1
        # Rerunning fetches and checks the target again rather than trusting what was shown.
        return main(confirmed)
    except core.YouTubeError as e:
        return _fail(e)
    if result is not None:
        indent = 2 if sys.stdout.isatty() else None
        print(pydantic_core.to_json(result, indent=indent, exclude_none=True).decode())
    return 0


def _fail(error: core.YouTubeError) -> int:
    body = {"type": error.kind, "message": str(error)}
    if error.details:
        body["details"] = error.details
    print(json.dumps({"error": body}, ensure_ascii=False), file=sys.stderr)
    return error.exit_code


def _with_confirm(argv: list[str], value: str) -> list[str]:
    end = argv.index("--") if "--" in argv else len(argv)
    return [*argv[:end], "--confirm", value, *argv[end:]]


def _approved(plan: dict) -> bool:
    print(f"About to permanently delete {plan['kind']} {plan['confirm']}:", file=sys.stderr)
    for key, value in plan.items():
        if key not in {"kind", "confirm"}:
            print(f"  {key}: {value}", file=sys.stderr)
    print("Delete it? [y/N] ", end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip().lower() in {"y", "yes"}


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
