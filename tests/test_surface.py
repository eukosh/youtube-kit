"""Both adapters expose every core operation, so neither surface silently falls behind."""

from collections.abc import Callable, Iterator

from youtube_kit import core
from youtube_kit.cli import app
from youtube_kit.mcp_server import TOOLS


def _cli_commands(cli_app) -> Iterator[Callable]:
    for name in cli_app:
        if name.startswith("-"):
            continue
        sub = cli_app[name]
        if sub.default_command is not None:
            yield sub.default_command
        yield from _cli_commands(sub)


def test_every_operation_is_a_cli_command():
    assert set(core.OPERATIONS) <= set(_cli_commands(app))


def test_every_operation_is_an_mcp_tool():
    assert set(TOOLS) == set(core.OPERATIONS)
    assert len(TOOLS) == len(core.OPERATIONS)
