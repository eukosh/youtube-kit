"""The update check: cached, never in the way, and upgrading the way ytk was installed."""

import importlib.util
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httplib2
import pytest

from youtube_kit import mcp_server
from youtube_kit.cli import main
from youtube_kit.core import NetworkError, YouTubeError, updates
from youtube_kit.core.config import Settings
from youtube_kit.core.models import Update


class FakePyPI:
    latest = "0.7.0"
    error: Exception | None = None
    requests = 0

    def __init__(self, timeout: int):
        pass

    def request(self, url: str, headers: dict) -> tuple:
        FakePyPI.requests += 1
        if FakePyPI.error:
            raise FakePyPI.error
        return SimpleNamespace(status=200), json.dumps({"info": {"version": FakePyPI.latest}}).encode()


class FakeChild:
    def wait(self) -> int:
        return 0


@pytest.fixture
def tool_env(tmp_path):
    """An environment directory the way `uv tool install` lays it out."""
    prefix = tmp_path / "tools" / "youtube-kit"
    prefix.mkdir(parents=True)
    (prefix / "uv-receipt.toml").write_text("[tool]\n")
    return prefix


@pytest.fixture
def check_on(monkeypatch, tool_env):
    """The check as a user's uv tool install of 0.6.0 sees it, with PyPI faked."""
    monkeypatch.delenv(updates.OPT_OUT_ENV)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("NO_UPDATE_NOTIFIER", raising=False)
    monkeypatch.setattr(updates, "_editable_source", lambda: None)
    monkeypatch.setattr(updates, "version", lambda name: "0.6.0")
    monkeypatch.setattr(sys, "prefix", str(tool_env))
    monkeypatch.setattr(httplib2, "Http", FakePyPI)
    monkeypatch.setattr(FakePyPI, "latest", "0.7.0")
    monkeypatch.setattr(FakePyPI, "error", None)
    monkeypatch.setattr(FakePyPI, "requests", 0)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeChild())  # no real background checks


def remember(latest: str, checked: timedelta = timedelta(0)) -> None:
    updates.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = (datetime.now(UTC) - checked).isoformat()
    updates.STATE_FILE.write_text(json.dumps({"latest": latest, "checked_at": stamp}))


def settings() -> Settings:
    return Settings.from_env()


# ---------- install detection ----------


@pytest.mark.parametrize(
    ("marker", "kind", "command"),
    [("uv-receipt.toml", "uv_tool", "ytk upgrade"), ("pipx_metadata.json", "pipx", "ytk upgrade")],
)
def test_tool_installs_upgrade_through_ytk(monkeypatch, tmp_path, marker, kind, command):
    monkeypatch.setattr(updates, "_editable_source", lambda: None)
    (tmp_path / marker).write_text("")
    monkeypatch.setattr(sys, "prefix", str(tmp_path))

    install = updates.install()

    assert (install.kind, install.command) == (kind, command)


def test_uvx_refreshes_its_cache_with_latest(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "_editable_source", lambda: None)
    prefix = tmp_path / "uv" / "archive-v0" / "QYjGkokefR0Ta"
    prefix.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(prefix))

    install = updates.install()

    assert install.argv == ["uvx", "youtube-kit@latest", "--version"]
    assert install.command == "uvx youtube-kit@latest --version"


@pytest.mark.parametrize(
    ("has_pip", "command"),
    [(True, "-m pip install --upgrade youtube-kit"), (False, "uv pip install --upgrade youtube-kit --python ")],
)
def test_unknown_installs_get_a_pip_command_to_run_themselves(monkeypatch, tmp_path, has_pip, command):
    monkeypatch.setattr(updates, "_editable_source", lambda: None)
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if has_pip else None)

    install = updates.install()

    assert install.argv is None
    assert command in install.command


@pytest.mark.parametrize(
    ("executable", "command"),
    [
        (r"C:\Python\python.exe", r"C:\Python\python.exe -m pip install --upgrade youtube-kit"),
        (
            r"C:\Program Files\Python\python.exe",
            r'& "C:\Program Files\Python\python.exe" -m pip install --upgrade youtube-kit',
        ),
    ],
)
def test_windows_commands_paste_into_powershell(monkeypatch, tmp_path, executable, command):
    monkeypatch.setattr(updates, "_editable_source", lambda: None)
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(updates.os, "name", "nt")

    assert updates.install().command == command


def test_windows_tool_installs_upgrade_after_ytk_exits(monkeypatch, tool_env):
    monkeypatch.setattr(updates, "_editable_source", lambda: None)
    monkeypatch.setattr(sys, "prefix", str(tool_env))
    monkeypatch.setattr(updates.os, "name", "nt")

    install = updates.install()

    assert (install.argv, install.command) == (None, "uv tool upgrade youtube-kit")


def test_editable_installs_are_left_to_git(check_on, monkeypatch):
    monkeypatch.setattr(updates, "_editable_source", lambda: "file:///src/youtube-kit")
    remember("0.7.0")

    assert updates.install() is None
    assert updates.pending(settings()) is None
    with pytest.raises(YouTubeError, match="development install"):
        updates.upgrade()


# ---------- opting out ----------


def test_env_var_ci_and_config_turn_it_off(check_on, monkeypatch, tmp_path):
    assert updates.enabled(settings())

    monkeypatch.setenv(updates.OPT_OUT_ENV, "")
    assert not updates.enabled(settings())
    monkeypatch.delenv(updates.OPT_OUT_ENV)

    monkeypatch.setenv("CI", "true")
    assert not updates.enabled(settings())
    monkeypatch.delenv("CI")

    monkeypatch.setenv("NO_UPDATE_NOTIFIER", "1")
    assert not updates.enabled(settings())
    monkeypatch.delenv("NO_UPDATE_NOTIFIER")

    config = settings().config_file
    config.write_text("[updates]\ncheck = false\n")
    assert not updates.enabled(settings())

    config.write_text("not toml [")
    assert updates.enabled(settings())

    config.write_bytes(b"\xff")
    assert updates.enabled(settings())


# ---------- checking ----------


def test_pending_reads_only_the_cache(check_on):
    assert updates.pending(settings()) is None

    remember("0.7.0")

    assert updates.pending(settings()) == Update(
        current="0.6.0", latest="0.7.0", command="ytk upgrade", changelog=updates.CHANGELOG_URL
    )
    assert FakePyPI.requests == 0


@pytest.mark.parametrize("latest", ["0.6.0", "0.5.9", "0.7.0rc1", "garbage"])
def test_only_newer_plain_releases_count(check_on, latest):
    remember(latest)
    assert updates.pending(settings()) is None


def test_notice_is_once_a_day_per_version(check_on):
    remember("0.7.0")
    assert updates.notice(settings()).latest == "0.7.0"
    assert updates.notice(settings()) is None
    assert updates.pending(settings()) is not None  # asking directly still answers

    remember("0.8.0")
    assert updates.notice(settings()).latest == "0.8.0"

    state = json.loads(updates.STATE_FILE.read_text())
    state["noticed"]["at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    updates.STATE_FILE.write_text(json.dumps(state))
    assert updates.notice(settings()).latest == "0.8.0"


def test_no_writable_cache_means_no_repeated_notice(check_on, monkeypatch):
    remember("0.7.0")
    monkeypatch.setattr(updates, "_save", lambda state: False)

    assert updates.notice(settings()) is None
    assert updates.pending(settings()).latest == "0.7.0"  # still on usage errors


@pytest.mark.parametrize(
    ("content", "latest"),
    [
        ("not json", None),
        ("[1, 2]", None),
        ('{"latest": 7, "checked_at": "yesterday"}', None),
        ('{"latest": "0.7.0", "noticed": "x", "checked_at": "2026-01-01T00:00:00"}', "0.7.0"),
    ],
)
def test_a_damaged_cache_counts_as_unknown(check_on, content, latest):
    updates.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    updates.STATE_FILE.write_text(content)

    update = updates.notice(settings())

    assert (update and update.latest) == latest


def test_refresh_starts_one_detached_check_a_day(check_on, monkeypatch):
    spawned = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: spawned.append(argv) or FakeChild())

    remember("0.6.0", checked=timedelta(hours=1))
    updates.refresh_in_background(settings())
    assert spawned == []

    remember("0.6.0", checked=timedelta(days=2))
    updates.refresh_in_background(settings())
    updates.refresh_in_background(settings())  # the first one claimed the check
    assert spawned == [[sys.executable, "-P", "-m", "youtube_kit.core.updates"]]


def test_failed_check_is_retried_an_hour_later(check_on, monkeypatch):
    spawned = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: spawned.append(argv) or FakeChild())
    updates.refresh_in_background(settings())  # the child fails, so nothing records a check

    state = json.loads(updates.STATE_FILE.read_text())
    state["claimed_at"] = (datetime.now(UTC) - timedelta(minutes=59)).isoformat()
    updates.STATE_FILE.write_text(json.dumps(state))
    updates.refresh_in_background(settings())
    assert len(spawned) == 1

    state["claimed_at"] = (datetime.now(UTC) - timedelta(minutes=61)).isoformat()
    updates.STATE_FILE.write_text(json.dumps(state))
    updates.refresh_in_background(settings())
    assert len(spawned) == 2


def test_no_writable_cache_means_no_check(check_on, monkeypatch):
    spawned = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: spawned.append(argv) or FakeChild())
    monkeypatch.setattr(updates, "STATE_FILE", updates.STATE_FILE.parent / "not-a-dir" / "update-check.json")
    (updates.STATE_FILE.parent.parent).mkdir(parents=True, exist_ok=True)
    updates.STATE_FILE.parent.write_text("a file where the cache directory should be")

    updates.refresh_in_background(settings())

    assert spawned == []


def test_asking_pypi_records_the_answer(check_on):
    assert updates.latest_release() == "0.7.0"
    assert updates.pending(settings()).latest == "0.7.0"


def test_unreachable_pypi_is_a_network_error(check_on):
    FakePyPI.error = TimeoutError("timed out")

    with pytest.raises(NetworkError, match="Could not reach PyPI"):
        updates.latest_release()


# ---------- upgrading ----------


def fake_run(monkeypatch, *, after: str = "0.7.0", returncode: int = 0) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(argv, **kwargs):
        calls.append(argv)
        out = f"{after}\n" if argv[0] == sys.executable else ""
        return subprocess.CompletedProcess(argv, returncode if argv[0] != sys.executable else 0, out, "uv: boom")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_upgrade_when_already_latest_changes_nothing(check_on, monkeypatch):
    FakePyPI.latest = "0.6.0"
    calls = fake_run(monkeypatch)

    result = updates.upgrade()

    assert (result.upgraded, result.current) == (False, "0.6.0")
    assert calls == []


def test_upgrade_runs_uv_and_reports_the_new_version(check_on, monkeypatch):
    calls = fake_run(monkeypatch)

    result = updates.upgrade()

    assert calls[0] == ["uv", "tool", "upgrade", "youtube-kit"]
    assert (result.previous, result.current, result.upgraded) == ("0.6.0", "0.7.0", True)
    assert result.changelog == updates.CHANGELOG_URL


def test_uvx_upgrade_refreshes_the_cache_and_reads_the_new_version(check_on, monkeypatch, tool_env, tmp_path):
    prefix = tmp_path / "uv" / "archive-v0" / "abc"
    prefix.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "0.7.0\n", "Installed 86 packages")

    monkeypatch.setattr(subprocess, "run", run)

    result = updates.upgrade()

    assert calls == [["uvx", "youtube-kit@latest", "--version"]]
    assert (result.current, result.upgraded) == ("0.7.0", True)


def test_upgrade_that_did_not_move_says_how_to_unpin(check_on, monkeypatch):
    fake_run(monkeypatch, after="0.6.0")

    with pytest.raises(YouTubeError, match=r"kept youtube-kit at 0\.6\.0 \(0\.7\.0 is out\)") as raised:
        updates.upgrade()

    assert raised.value.details == {"command": "uv tool install youtube-kit@latest"}


def test_failed_upgrade_says_what_ran(check_on, monkeypatch):
    fake_run(monkeypatch, returncode=2)

    with pytest.raises(YouTubeError, match="uv: boom") as raised:
        updates.upgrade()

    assert raised.value.details == {"command": "uv tool upgrade youtube-kit"}


def test_pip_installs_get_the_command_instead(check_on, monkeypatch, tool_env):
    (tool_env / "uv-receipt.toml").unlink()
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    calls = fake_run(monkeypatch)

    with pytest.raises(YouTubeError, match="can't upgrade itself here") as raised:
        updates.upgrade()

    assert "pip install --upgrade youtube-kit" in raised.value.details["command"]
    assert calls == []


# ---------- adapters ----------


def test_agents_get_one_json_line_before_the_output(check_on, capsys, api):
    remember("0.7.0")
    api.public.videoCategories().list().execute.return_value = {"items": []}

    assert main(["video", "categories"]) == 0
    assert main(["video", "categories"]) == 0

    err = capsys.readouterr().err
    assert [json.loads(line) for line in err.splitlines()] == [
        {
            "update": {
                "current": "0.6.0",
                "latest": "0.7.0",
                "command": "ytk upgrade",
                "changelog": updates.CHANGELOG_URL,
            }
        }
    ]


def test_an_agents_notice_does_not_silence_the_persons(check_on, capsys, api, monkeypatch):
    remember("0.7.0")
    api.public.videoCategories().list().execute.return_value = {"items": []}

    assert main(["video", "categories"]) == 0
    assert '"update"' in capsys.readouterr().err

    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    assert main(["video", "categories"]) == 0
    assert "Update available" in capsys.readouterr().err


def test_usage_errors_say_an_update_is_out(check_on, capsys):
    remember("0.7.0")
    updates.notice(settings(), stamp="noticed_agent")  # today's notice was already shown

    assert main(["video", "frobnicate"]) == 2

    error = json.loads(capsys.readouterr().err)["error"]
    assert error["type"] == "usage"
    assert error["details"]["update"]["latest"] == "0.7.0"


def test_people_get_a_reminder_after_the_output(check_on, capsys, api, monkeypatch):
    remember("0.7.0")
    api.public.videoCategories().list().execute.return_value = {"items": []}
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    assert main(["video", "categories"]) == 0

    err = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().err)  # drop colors
    assert "Update available: ytk 0.6.0 → 0.7.0. Run `ytk upgrade`." in err
    assert f"Changelog: {updates.CHANGELOG_URL}" in err


def test_people_get_a_hint_instead_of_the_reminder_after_a_usage_error(check_on, capsys, monkeypatch):
    remember("0.7.0")
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    assert main(["video", "frobnicate"]) == 2

    err = capsys.readouterr().err
    assert "Update available" not in err
    assert "ytk 0.7.0 is out and may have this command. Run `ytk upgrade`." in err


def test_failed_commands_still_start_the_check(check_on, capsys, monkeypatch):
    spawned = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: spawned.append(argv) or FakeChild())
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    assert main(["video", "frobnicate"]) == 2

    assert len(spawned) == 1


def test_upgrade_command_prints_the_result(check_on, capsys, monkeypatch):
    remember("0.7.0")
    fake_run(monkeypatch)

    assert main(["upgrade"]) == 0

    out, err = capsys.readouterr()
    assert json.loads(out)["upgraded"] is True
    assert err == ""


def test_mcp_tells_the_model(check_on, monkeypatch):
    remember("0.7.0")
    monkeypatch.setattr(mcp_server.mcp, "run", lambda **kwargs: None)
    monkeypatch.setattr(mcp_server.mcp, "instructions", mcp_server.INSTRUCTIONS)

    mcp_server.run()

    assert mcp_server.mcp.instructions.startswith(mcp_server.INSTRUCTIONS)
    assert "youtube-kit 0.7.0 is out (this server runs 0.6.0)" in mcp_server.mcp.instructions
    assert "`ytk upgrade`" in mcp_server.mcp.instructions

    monkeypatch.setattr(mcp_server.mcp, "instructions", mcp_server.INSTRUCTIONS)
    mcp_server.run()
    assert mcp_server.mcp.instructions == mcp_server.INSTRUCTIONS  # once a day
    assert updates.notice(settings()) is not None  # the terminal's reminder is separate
