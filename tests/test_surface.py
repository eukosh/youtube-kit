"""Both adapters expose every core operation, so neither surface silently falls behind."""

import inspect
import re
from collections.abc import Callable, Iterator
from pathlib import Path

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


def _cli_paths(cli_app, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    for name in cli_app:
        if name.startswith("-"):
            continue
        sub = cli_app[name]
        if sub.default_command is not None:
            yield (*prefix, name)
        yield from _cli_paths(sub, (*prefix, name))


def test_skill_command_map_lists_every_command():
    skill = (Path(__file__).parents[1] / "skills/youtube/SKILL.md").read_text()
    command_map = skill.split("```", 2)[1].splitlines()
    for *groups, verb in _cli_paths(app):
        if (*groups, verb) == ("mcp",):  # the skill drives the CLI; MCP clients don't read it
            continue
        prefix = " ".join(["ytk", *groups]) + " "
        assert any(prefix in line and re.search(rf"\b{verb}\b", line) for line in command_map), (groups, verb)


def test_every_operation_is_a_cli_command():
    assert set(core.OPERATIONS) <= set(_cli_commands(app))


def test_every_operation_is_an_mcp_tool():
    assert set(TOOLS) == set(core.OPERATIONS)
    assert len(TOOLS) == len(core.OPERATIONS)


def test_guarded_deletes_are_marked_destructive():
    guarded = [op for op in core.OPERATIONS if "confirm" in inspect.signature(op).parameters]
    assert guarded
    assert all(core.info(op).destructive for op in guarded)
