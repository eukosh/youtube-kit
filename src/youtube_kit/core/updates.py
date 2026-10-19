"""Whether a newer youtube-kit is on PyPI, and upgrading to it.

Notices read only the cached result of the last check, so no command waits on PyPI.
`refresh_in_background` keeps that cache at most a day old.
"""

import contextlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import threading
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, distribution, version
from typing import Literal

import httplib2
from platformdirs import user_cache_path

from .config import APP_NAME, Settings
from .errors import NETWORK_ERRORS, NetworkError, YouTubeError
from .models import Update, UpgradeResult

PYPI_URL = f"https://pypi.org/pypi/{APP_NAME}/json"
CHANGELOG_URL = "https://github.com/eukosh/youtube-kit/blob/main/CHANGELOG.md"
CHECK_EVERY = timedelta(days=1)
STATE_FILE = user_cache_path(APP_NAME) / "update-check.json"
OPT_OUT_ENV = "YTK_NO_UPDATE_CHECK"
_OPT_OUT_ENVS = (OPT_OUT_ENV, "NO_UPDATE_NOTIFIER", "CI")
_TIMEOUT_SECONDS = 5
_RETRY_AFTER = timedelta(hours=1)
_REINSTALL = {"uv_tool": f"uv tool install {APP_NAME}@latest", "pipx": f"pipx install --force {APP_NAME}"}


@dataclass(frozen=True)
class Install:
    """How this copy was installed, which decides how it upgrades."""

    kind: Literal["uv_tool", "pipx", "uvx", "pip"]
    argv: list[str] | None
    """What `upgrade` runs; None when the user has to upgrade it themselves."""
    command: str
    """What to tell the user to run."""


def install() -> Install | None:
    """None for an editable install: a development checkout, updated through git rather than PyPI."""
    if _editable_source():
        return None
    prefix = os.path.realpath(sys.prefix)
    if os.path.isfile(os.path.join(prefix, "uv-receipt.toml")):
        return _replaces_itself("uv_tool", ["uv", "tool", "upgrade", APP_NAME])
    if os.path.isfile(os.path.join(prefix, "pipx_metadata.json")):
        return _replaces_itself("pipx", ["pipx", "upgrade", APP_NAME])
    # uvx runs from a cached environment (archive-v0 in uv 0.9) and keeps using it until `@latest` refreshes it.
    if os.path.basename(os.path.dirname(prefix)).startswith("archive-"):
        refresh = ["uvx", f"{APP_NAME}@latest", "--version"]
        return Install("uvx", refresh, shlex.join(refresh))
    if importlib.util.find_spec("pip"):
        pip = [sys.executable, "-m", "pip", "install", "--upgrade", APP_NAME]
    else:  # e.g. a venv made by `uv venv`
        pip = ["uv", "pip", "install", "--upgrade", APP_NAME, "--python", sys.executable]
    return Install("pip", None, shlex.join(pip))


def _replaces_itself(kind: Literal["uv_tool", "pipx"], argv: list[str]) -> Install:
    # Windows locks the running ytk's own files, so there the user runs it from another terminal.
    if os.name == "nt":
        return Install(kind, None, shlex.join(argv))
    return Install(kind, argv, "ytk upgrade")


def enabled(settings: Settings) -> bool:
    """Off with YTK_NO_UPDATE_CHECK, NO_UPDATE_NOTIFIER or CI set, with `check = false` under [updates]
    in config.toml, and for editable installs."""
    if any(os.environ.get(name) for name in _OPT_OUT_ENVS) or install() is None:
        return False
    try:
        table = tomllib.loads(settings.config_file.read_text()).get("updates")
    except (OSError, tomllib.TOMLDecodeError):
        return True
    return not (isinstance(table, dict) and table.get("check") is False)


def pending(settings: Settings) -> Update | None:
    """The newer release the last check found, if any. Never touches the network."""
    if not enabled(settings):
        return None
    latest = _load().get("latest")
    current = version(APP_NAME)
    target = install()
    if target is None or not isinstance(latest, str) or not _newer(latest, current):
        return None
    return Update(current=current, latest=latest, command=target.command, changelog=CHANGELOG_URL)


def notice(settings: Settings) -> Update | None:
    """`pending`, at most once a day for each version, for reminders nobody asked for."""
    update = pending(settings)
    if update is None:
        return None
    state = _load()
    last = state.get("noticed")
    if isinstance(last, dict) and last.get("version") == update.latest and not _older_than(last.get("at"), CHECK_EVERY):
        return None
    state["noticed"] = {"version": update.latest, "at": _now()}
    # Without a writable cache every run would repeat it.
    return update if _save(state) else None


def refresh_in_background(settings: Settings) -> None:
    """Ask PyPI for the latest release when the last check is over a day old.

    The check runs in a detached process: most commands finish before PyPI answers, and a thread
    would die with them.
    """
    state = _load()
    due = _older_than(state.get("checked_at"), CHECK_EVERY) and _older_than(state.get("claimed_at"), _RETRY_AFTER)
    if not (due and enabled(settings)):
        return
    # The claim keeps commands started meanwhile (say, from xargs) from each asking PyPI, and spaces out
    # retries after a failed check. Without a writable cache there is no claim, so no check either.
    state["claimed_at"] = _now()
    if not _save(state):
        return
    detach = {"creationflags": subprocess.DETACHED_PROCESS} if os.name == "nt" else {"start_new_session": True}
    try:
        child = subprocess.Popen(
            [sys.executable, "-I", "-m", __name__],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **detach,
        )
    except OSError:
        return
    # Reaps the child in long-lived processes like the MCP server; a short command just exits first.
    threading.Thread(target=child.wait, daemon=True).start()


def latest_release() -> str:
    """The newest release on PyPI, also recorded for the notices."""
    try:
        response, body = httplib2.Http(timeout=_TIMEOUT_SECONDS).request(
            PYPI_URL, headers={"User-Agent": f"{APP_NAME}/{version(APP_NAME)}"}
        )
    except NETWORK_ERRORS as e:
        raise NetworkError(f"Could not reach PyPI ({type(e).__name__}: {e}). Retry later.") from e
    if response.status != 200:
        raise YouTubeError(f"PyPI answered HTTP {response.status} for {PYPI_URL}.")
    try:
        latest = json.loads(body)["info"]["version"]
    except (ValueError, KeyError, TypeError) as e:
        raise YouTubeError(f"Unexpected answer from {PYPI_URL}: {e}") from e
    _remember(latest)
    return latest


def upgrade() -> UpgradeResult:
    """Upgrade this install to the latest release, the way it was installed."""
    target = install()
    if target is None:
        raise YouTubeError(f"This is a development install from {_editable_source()}; update it with git.")
    current = version(APP_NAME)
    latest = latest_release()
    if not _newer(latest, current):
        return UpgradeResult(previous=current, current=current, upgraded=False)
    if target.argv is None:
        raise YouTubeError(
            f"ytk can't upgrade this install itself. Run `{target.command}`, or the equivalent for how you "
            "installed it.",
            details={"command": target.command},
        )
    command = shlex.join(target.argv)
    try:
        done = subprocess.run(target.argv, capture_output=True, text=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise YouTubeError(f"Could not run `{command}`: {e}", details={"command": command}) from e
    if done.returncode != 0:
        output = (done.stderr or done.stdout).strip()
        raise YouTubeError(f"`{command}` failed: {output}", details={"command": command})
    now = _version_after(target, done.stdout) or latest  # the command succeeded, so trust it if the probe fails
    if now == current:
        reinstall = _REINSTALL.get(target.kind, target.command)
        raise YouTubeError(
            f"`{command}` left youtube-kit at {current} though {latest} is out, usually because it was installed "
            f"with a version pin. Run `{reinstall}` to move to the latest.",
            details={"command": reinstall},
        )
    return UpgradeResult(previous=current, current=now, upgraded=True, changelog=CHANGELOG_URL)


def _version_after(target: Install, stdout: str) -> str | None:
    if target.kind == "uvx":  # the refreshed environment prints its own --version
        lines = stdout.strip().splitlines()
        return lines[-1].strip() if lines else None
    # This process still has the old version loaded; ask a fresh interpreter in the same environment.
    probe = [sys.executable, "-I", "-c", f"from importlib.metadata import version; print(version({APP_NAME!r}))"]
    try:
        done = subprocess.run(probe, capture_output=True, text=True, timeout=60, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None


def _newer(latest: str, current: str) -> bool:
    """Plain X.Y.Z releases only; anything else (pre-releases, local builds) never counts as newer."""
    try:
        return _release(latest) > _release(current)
    except ValueError:
        return False


def _release(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _editable_source() -> str | None:
    try:
        direct = json.loads(distribution(APP_NAME).read_text("direct_url.json") or "{}")
    except (PackageNotFoundError, ValueError):
        return None
    editable = isinstance(direct, dict) and direct.get("dir_info", {}).get("editable")
    return direct.get("url", "a local checkout") if editable else None


def _remember(latest: str) -> None:
    state = _load()
    state.update(latest=latest, checked_at=_now())
    _save(state)


def _load() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save(state: dict) -> bool:
    """Write through a temporary file, so concurrent runs never read half a file. False if it couldn't."""
    temporary = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}")
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(state))
        temporary.replace(STATE_FILE)
    except OSError:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
        return False
    return True


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _older_than(stamp: object, age: timedelta) -> bool:
    """True for a missing or unreadable timestamp too."""
    try:
        return datetime.now(UTC) - datetime.fromisoformat(stamp) > age  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True


if __name__ == "__main__":  # the detached check refresh_in_background starts
    with contextlib.suppress(Exception):
        latest_release()
