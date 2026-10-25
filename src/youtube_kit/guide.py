"""The guided first-run setup behind `ytk auth login`: prompts on stderr, answers on stdin.

stdout stays reserved for the command's JSON result. The steps come from core, which also hands
them to agents and MCP clients.
"""

import sys
import textwrap
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.style import Style
from rich.text import Text

from .core import InvalidRequest, auth
from .core.config import Settings
from .core.models import MyChannel, SetupTask
from .core.ops.auth import CLIENT_STEPS, SIGN_IN_TIPS

console = Console(stderr=True, highlight=False)


def set_up_client(settings: Settings, *, open_pages: bool) -> None:
    """Walk the user through creating an OAuth client in Google Cloud, then store its JSON."""
    say(f"[bold]One-time Google Cloud setup[/] [dim]· {len(CLIENT_STEPS)} steps · about 5 minutes[/]")
    for number, step in enumerate(CLIENT_STEPS, 1):
        say(f"\n[bold white on #2563eb] {number}/{len(CLIENT_STEPS)} [/] [bold]{escape(step.title)}[/]")
        numbered = len(step.tasks) > 1
        for index, task in enumerate(step.tasks, 1):
            _show(task, f"{index}. " if numbered else "", open_page=open_pages)
        ask("  [dim]Press Enter when done[/] ")
    _save(settings, _downloaded_or_asked())


def before_consent(*, open_browser: bool) -> None:
    where = "Google's sign-in opens in your browser." if open_browser else "Open the link below to sign in with Google."
    say(f"\n[bold]{where}[/]")
    for tip in SIGN_IN_TIPS:
        _show(tip, "• ", open_page=False)


def retry(error: Exception) -> None:
    """After the sign-in worked but YouTube refused the first call, e.g. because an API isn't enabled yet."""
    say(f"\n[red]✗[/] {escape(str(error))}")
    ask("[dim]Fix that, then press Enter to try again (Ctrl-C to stop)[/] ")


def connected(channel: MyChannel) -> None:
    name = f"[bold]{escape(channel.title)}[/] ({escape(channel.handle or channel.id)})"
    default = " It's your default channel." if channel.default else ""
    say(f"\n[green]✓[/] Connected {name}.{default}")
    say("[dim]To add another channel, run[/] ytk auth login [dim]again and pick a different one.[/]")


def _show(task: SetupTask, bullet: str, *, open_page: bool) -> None:
    indent = " " * (2 + len(bullet))
    _hang(task.do, "  " + bullet)
    if task.url:
        _hang(task.url, indent, Style(color="cyan", link=task.url))
        if open_page:
            webbrowser.open(task.url)
    if task.values:
        width = max(map(len, task.values))
        for field, value in task.values.items():
            _hang(value, Text(f"{indent}  {field:<{width}}  ", "dim"))


def _hang(text: str, first: str | Text, style: str | Style = "") -> None:
    """Print text after the prefix `first`, wrapping under it.

    Rich layouts cut a word wider than the line with "…". Here a long URL stays whole on one line
    the terminal soft-wraps, so copying it gives the whole URL.
    """
    rest = " " * len(first)
    width = max(console.width - len(rest), 20)
    lines = textwrap.wrap(text, width, break_long_words=False, break_on_hyphens=False) or [""]
    for index, line in enumerate(lines):
        console.print(Text.assemble(rest if index else first, (line, style)), soft_wrap=True)


def _downloaded_or_asked() -> str:
    found = auth.downloaded_client_secrets()
    if found is not None:
        answer = ask(f"\nFound [bold]{escape(_tilde(found))}[/]. Use it? [dim]\\[Y/n][/] ")
        if answer.lower() in {"", "y", "yes"}:
            return str(found)
    return ask("\nDrag the downloaded JSON file here (or paste its path or contents), then press Enter: ")


def _save(settings: Settings, source: str) -> None:
    while True:
        try:
            auth.save_client_secrets(settings, source)
        except InvalidRequest as e:
            source = ask(f"[red]✗[/] {escape(str(e))} Try again: ")
        else:
            say(f"[green]✓[/] Saved the OAuth client to {escape(_tilde(settings.client_secrets_file))}.")
            return


def _tilde(path: Path) -> str:
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def say(text: str) -> None:
    console.print(text, soft_wrap=True)


def ask(prompt: str) -> str:
    console.print(prompt, end="", soft_wrap=True)
    line = sys.stdin.readline()
    if not line:  # stdin closed
        raise KeyboardInterrupt
    return line.strip()
