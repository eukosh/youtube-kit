"""The guided first-run setup behind `ytk auth login`: prompts on stderr, answers on stdin.

stdout stays reserved for the command's JSON result. The steps come from core, which also hands
them to agents and MCP clients.
"""

import sys
import webbrowser
from pathlib import Path

from rich.console import Console, Group
from rich.markup import escape
from rich.padding import Padding
from rich.style import Style
from rich.table import Table
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
    parts: list = [Text(task.do)]
    if task.url:
        parts.append(Text.assemble((task.url, Style(color="cyan", link=task.url))))
        if open_page:
            webbrowser.open(task.url)
    if task.values:
        values = Table.grid(padding=(0, 2))
        values.add_column(style="dim", no_wrap=True)
        values.add_column()
        for field, value in task.values.items():
            values.add_row(field, value)
        parts.append(Padding(values, (0, 0, 0, 2)))
    body = Group(*parts)
    if bullet:  # a grid keeps wrapped lines indented under the text, not the bullet
        row = Table.grid(padding=(0, 1, 0, 0))
        row.add_column(no_wrap=True)
        row.add_column()
        row.add_row(bullet.strip(), body)
        body = row
    console.print(Padding(body, (0, 0, 0, 2)))


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
