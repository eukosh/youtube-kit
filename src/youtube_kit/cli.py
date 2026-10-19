"""`ytk`: the command-line adapter over the core operations.

Contract (relied on by agents and scripts, documented in skills/youtube/SKILL.md):
- stdout carries exactly one JSON document per successful command, nulls omitted.
- Failures print {"error": {"type", "message", "details"?}} to stderr and exit
  with the error's code: 2 invalid input, 3 not found, 4 not authorized, 5 quota
  exceeded, 6 forbidden, 7 network, 8 confirmation required, 9 protected,
  10 timeout, 1 anything else (type "error"). Usage errors from argument parsing exit 2 with type
  "usage". When stderr is a terminal, errors print as readable text instead of JSON.
- Long commands print {"progress": {"done", "total", "percent"}} lines to stderr as they go,
  so on failure the error is the last stderr line. At a terminal it's a percentage instead.
- When stdout is a terminal, the JSON is indented and colored.
- Guarded deletes ask a human at a terminal instead of exiting 8; declining exits 1.
  For agents, the exit-8 details include `rerun`, the exact command that confirms.
- When a newer release is out, stderr starts with an {"update": {...}} line, at most once a day
  per version (at a terminal, a reminder after the output), and usage errors carry it in
  `details.update`.
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
from rich.console import Console
from rich.markup import escape

from . import core, guide
from .core import auth, progress, updates
from .core.config import Settings
from .core.models import AuthStatus, UpgradeResult
from .core.ops import analytics, branding, captions, channels, comments, playlists, search, subscriptions, videos
from .core.ops import auth as auth_ops

app = cyclopts.App(
    name="ytk",
    help="YouTube Data, Analytics and Reporting APIs from the command line. Prints JSON; see `ytk <command> --help`.",
    version=version("youtube-kit"),
    # No --no-X / --empty-X flags, except on update commands where "unset" and "clear" mean something.
    default_parameter=cyclopts.Parameter(negative_bool=(), negative_iterable=()),
)

video = app.command(cyclopts.App(name="video", help="Look up, upload, edit, and delete videos."))
playlist = app.command(cyclopts.App(name="playlist", help="Look up and manage playlists."))
comment = app.command(cyclopts.App(name="comment", help="Read, write, and moderate comments."))
caption = app.command(cyclopts.App(name="caption", help="Transcripts of your videos, and their caption tracks."))
channel = app.command(cyclopts.App(name="channel", help="Look up channels, and brand your own."))
watermark = channel.command(cyclopts.App(name="watermark", help="The subscribe watermark shown over your videos."))
section = channel.command(cyclopts.App(name="section", help="Sections on a channel's home page."))
subscription = app.command(cyclopts.App(name="subscription", help="Your subscriptions to other channels."))
SETUP = "Setup"  # commands about ytk itself, grouped apart in --help
auth_app = app.command(cyclopts.App(name="auth", help="Log in to your YouTube channels.", group=SETUP))

_NEGATIVES = cyclopts.Parameter(negative_bool=None, negative_iterable=None)

app.command(search.search, name="search")
app.command(analytics.get_analytics, name="analytics")
app.command(analytics.get_impressions, name="impressions")

video.command(videos.get_videos, name="get")
video.command(videos.list_video_categories, name="categories")
video.command(videos.upload_video, name="upload")
video.command(videos.get_processing_status, name="status")
video.command(videos.update_video, name="update", default_parameter=_NEGATIVES)
video.command(videos.set_thumbnail, name="thumbnail")
video.command(videos.rate_video, name="rate")
video.command(videos.get_my_ratings, name="rating")
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

caption.command(captions.list_captions, name="list")
caption.command(captions.get_transcript, name="transcript")
caption.command(captions.upload_caption, name="upload")
caption.command(captions.update_caption, name="update", default_parameter=_NEGATIVES)
caption.command(captions.delete_caption, name="delete")

channel.command(channels.get_channel, name="get")
channel.command(channels.list_my_channels, name="mine")
channel.command(channels.list_activities, name="activity")
channel.command(branding.update_channel, name="update", default_parameter=_NEGATIVES)
channel.command(branding.set_channel_banner, name="banner")
watermark.command(branding.set_watermark, name="set")
watermark.command(branding.remove_watermark, name="remove")
section.command(branding.list_sections, name="list")
section.command(branding.add_section, name="add")
section.command(branding.update_section, name="update")
section.command(branding.delete_section, name="delete")

subscription.command(subscriptions.list_subscriptions, name="list")
subscription.command(subscriptions.subscribe, name="add")
subscription.command(subscriptions.unsubscribe, name="remove")


auth_app.command(auth_ops.setup_guide, name="guide")


@auth_app.command(name="login")
def auth_login(
    *,
    # negative_bool=None brings back --no-browser, which the app-wide default turns off.
    browser: Annotated[bool, cyclopts.Parameter(negative_bool=None)] = True,
    client_secrets: str | None = None,
) -> AuthStatus:
    """Connect one of your YouTube channels. Run it again to add another.

    The first run walks you through creating the Google Cloud OAuth client ytk
    needs, then Google asks which channel to connect. The first channel becomes
    the default (`ytk auth switch` changes it). Logins are shared by the CLI and
    the MCP server.

    Args:
        browser: Open pages in the browser automatically. With --no-browser, open the printed links yourself.
        client_secrets: The OAuth client JSON downloaded from Google Cloud (path or contents). Skips the guided setup.
    """
    settings = Settings.from_env()
    interactive = sys.stdin.isatty() and sys.stderr.isatty()
    if client_secrets is not None:
        auth.save_client_secrets(settings, client_secrets)
    elif interactive and not settings.client_secrets_file.exists():
        guide.set_up_client(settings, open_pages=browser)
    if interactive:
        guide.before_consent(open_browser=browser)
    # The OAuth library prints the consent URL to stdout, which is reserved for JSON.
    with contextlib.redirect_stdout(sys.stderr):
        creds = auth.authorize(settings, open_browser=browser)
    while True:
        try:
            channel = auth.connect(settings, creds)
            break
        except core.Forbidden as e:  # typically: YouTube Data API not enabled in the project yet
            if not interactive:
                raise
            guide.retry(e)
    guide.connected(channel)
    return auth.status(settings)


@auth_app.command(name="status")
def auth_status() -> AuthStatus:
    """Show the logged-in channels and where credentials are stored. Makes no API calls."""
    return auth.status(Settings.from_env())


@auth_app.command(name="switch")
def auth_switch(channel: str, /) -> AuthStatus:
    """Make a logged-in channel the default that commands work on without --my-channel.

    The YOUTUBE_CHANNEL environment variable, when set, still takes precedence.

    Args:
        channel: UC… ID, @handle or exact title of a logged-in channel.
    """
    return auth.switch(Settings.from_env(), channel)


@auth_app.command(name="logout")
def auth_logout(channel: str | None = None, /) -> AuthStatus:
    """Delete a channel's stored OAuth token. The API key, if any, is unaffected.

    Args:
        channel: UC… ID, @handle or exact title of a logged-in channel. Omit for the default channel (YOUTUBE_CHANNEL when set).
    """
    return auth.logout(Settings.from_env(), channel)


@app.command(name="upgrade", group=SETUP)
def upgrade() -> UpgradeResult:
    """Upgrade ytk to the latest release, the way it was installed (uv tool, uvx or pipx).

    Does nothing if already the latest. Where it can't (pip; uv tool or pipx on Windows), exits 1
    with the command to run in `details.command`. Restart MCP clients afterwards.
    """
    if not sys.stderr.isatty():
        return updates.upgrade()
    with Console(stderr=True).status("Looking for a newer ytk…"):
        return updates.upgrade()


@app.command(name="mcp", group=SETUP)
def serve_mcp() -> None:
    """Run the MCP server over stdio, exposing the same operations as tools."""
    from . import mcp_server  # deferred: FastMCP is slow to import and only needed here

    mcp_server.run()


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    human = sys.stderr.isatty()
    # mcp owns stdio; upgrade reports versions itself.
    remind = argv[:1] not in (["mcp"], ["upgrade"])
    settings = Settings.from_env()
    if remind:
        updates.refresh_in_background(settings)
    # Own stamp, so agent runs don't use up the person's daily reminder.
    if remind and not human and (update := updates.notice(settings, stamp="noticed_agent")):
        print(json.dumps({"update": update.model_dump()}, ensure_ascii=False), file=sys.stderr)
    code = _run(argv)
    # After the output, never after an error.
    if remind and human and code == 0 and (update := updates.notice(settings)):
        Console(stderr=True, highlight=False).print(
            f"[yellow]Update available:[/] ytk {update.current} → {update.latest}. Run `{escape(update.command)}`."
            f" [dim]Changelog: {update.changelog}[/]",
            soft_wrap=True,
        )
    return code


def _run(argv: list[str]) -> int:
    human = sys.stderr.isatty()
    try:
        with _progress():
            result = app(argv, exit_on_error=False, print_error=human, result_action="return_value")
    except CycloptsError as e:
        # The command may only exist in a newer release.
        update = updates.pending(Settings.from_env())
        if human:  # a person got cyclopts' formatted message already
            if update:
                Console(stderr=True, highlight=False).print(
                    f"[dim]ytk {update.latest} is out and may have this command. Run `{escape(update.command)}`.[/]",
                    soft_wrap=True,
                )
        else:
            error = {"type": "usage", "message": str(e)}
            if update:
                error["details"] = {"update": update.model_dump()}
            print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
        return 2
    except core.ConfirmationRequired as e:
        confirmed = _with_confirm(argv, e.details["confirm"])
        if not (sys.stdin.isatty() and sys.stderr.isatty()):
            e.details["rerun"] = shlex.join(["ytk", *confirmed])
            return _fail(e)
        if not _approved(e.details):
            print("Cancelled; nothing was deleted.", file=sys.stderr)
            return 1
        # Rerunning fetches and checks the target again rather than trusting what was shown.
        return _run(confirmed)
    except core.YouTubeError as e:
        return _fail(e)
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001  -- keep the JSON contract even for bugs and odd responses
        return _fail(core.YouTubeError(f"{type(e).__name__}: {e}"))
    if result is not None:
        text = pydantic_core.to_json(result, exclude_none=True).decode()
        try:
            if sys.stdout.isatty():
                Console(highlight=True).print_json(text, indent=2)
            else:
                print(text)
        except BrokenPipeError:  # e.g. piped into head
            sys.stdout = None  # stop the interpreter's final flush from raising again
    return 0


def _fail(error: core.YouTubeError) -> int:
    body = {"type": error.kind, "message": str(error)}
    if error.details:
        body["details"] = error.details
    if sys.stderr.isatty():
        console = Console(stderr=True, highlight=False)
        console.print(f"[red]✗[/] {escape(str(error))} [dim]({error.kind})[/]", soft_wrap=True)
        if error.details:
            console.print_json(data=error.details, indent=2)
    else:
        print(json.dumps({"error": body}, ensure_ascii=False), file=sys.stderr)
    return error.exit_code


def _with_confirm(argv: list[str], value: str) -> list[str]:
    end = argv.index("--") if "--" in argv else len(argv)
    return [*argv[:end], "--confirm", value, *argv[end:]]


def _approved(plan: dict) -> bool:
    print(f"About to permanently delete {plan['kind']} {plan['confirm']}:", file=sys.stderr)
    for key, value in plan.items():
        if key not in {"kind", "confirm"}:
            print(f"  {key}: {str(value).replace(chr(10), chr(10) + '    ')}", file=sys.stderr)
    print("Delete it? [y/N] ", end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip().lower() in {"y", "yes"}


@contextlib.contextmanager
def _progress() -> Iterator[None]:
    """Report progress on stderr: a self-overwriting percentage for a person, JSON lines otherwise.

    The terminal line is ended on exit, before any error is printed after it.
    """
    human = sys.stderr.isatty()
    shown = False
    step = -1

    def show(done: int, total: int) -> None:
        nonlocal shown, step
        percent = 100 * done // total if total else 100
        if human:
            shown = True
            print(f"\rprogress: {percent:3d}%", end="", file=sys.stderr, flush=True)
        elif percent // 10 > step:  # every 10 points, so a log stays short
            step = percent // 10
            line = {"progress": {"done": done, "total": total, "percent": percent}}
            print(json.dumps(line), file=sys.stderr, flush=True)

    try:
        with progress.reporting_to(show):
            yield
    finally:
        if shown:
            print(file=sys.stderr)
