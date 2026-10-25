"""`ytk auth login`: the guided setup for people, and plain errors for scripts and agents."""

import io
import json
import sys

import pytest
from rich.text import Text

from youtube_kit import guide
from youtube_kit.cli import main
from youtube_kit.core import Forbidden, auth
from youtube_kit.core.config import Settings
from youtube_kit.core.models import MyChannel

from .fakes import CHANNEL_ID

CLIENT = json.dumps({"installed": {"client_id": "id.apps.googleusercontent.com", "client_secret": "s"}})


class Opened(list):
    connect_errors: list


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def google(monkeypatch):
    """Stand in for the browser and Google's consent screen. Records the pages opened."""
    opened = Opened()
    opened.connect_errors = []  # raised by the first connect calls, in order
    monkeypatch.setattr(guide.webbrowser, "open", opened.append)

    def fake_authorize(settings, *, open_browser=True):
        assert settings.client_secrets_file.exists()
        return "creds"

    def fake_connect(settings, creds):
        if opened.connect_errors:
            raise opened.connect_errors.pop(0)
        return MyChannel(id=CHANNEL_ID, title="Main", handle="@main", url="u", default=True, analytics=True)

    monkeypatch.setattr(auth, "authorize", fake_authorize)
    monkeypatch.setattr(auth, "connect", fake_connect)
    return opened


@pytest.fixture
def person(monkeypatch, capsys):
    """Call with each line a person types; makes stdin and stderr look like a terminal."""

    def types(*lines: str) -> None:
        monkeypatch.setattr(sys, "stdin", Terminal("".join(line + "\n" for line in lines)))
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    return types


@pytest.fixture
def downloads(monkeypatch, tmp_path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    return folder


def run(capsys, *argv):
    code = main(["auth", "login", *argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_without_a_terminal_it_says_to_run_it_in_one(capsys):
    code, out, err = run(capsys)
    assert (code, out) == (4, "")
    assert "walks you through" in json.loads(err)["error"]["message"]


STEPS = len(guide.CLIENT_STEPS)


def test_a_person_is_walked_through_every_step(capsys, google, person, downloads):
    (downloads / "client_secret_123.apps.googleusercontent.com.json").write_text(CLIENT)
    person(*[""] * STEPS, "y")

    code, out, err = run(capsys)

    assert code == 0
    assert google == [task.url for step in guide.CLIENT_STEPS for task in step.tasks if task.url]
    assert json.loads(Settings.from_env().client_secrets_file.read_text())["installed"]["client_id"]
    assert json.loads(out)["client_secrets_present"] is True
    assert f"{STEPS}/{STEPS}" in err
    assert "1. YouTube Data API v3" in err  # several pages in one step are numbered
    assert "Connected Main (@main)" in err
    assert "run ytk auth login again" in err


def test_a_wrong_file_is_explained_and_asked_again(capsys, google, person, downloads, tmp_path):
    good = tmp_path / "client.json"
    good.write_text(CLIENT)
    person(*[""] * STEPS, '{"web": {"client_id": "x", "client_secret": "y"}}', str(good))

    code, _, err = run(capsys)

    assert code == 0
    assert "Desktop app" in err


def test_no_browser_prints_links_without_opening_them(capsys, google, person, downloads):
    (downloads / "client_secret_1.json").write_text(CLIENT)
    person(*[""] * STEPS, "")

    code, _, err = run(capsys, "--no-browser")

    assert code == 0
    assert google == []
    assert "https://console.cloud.google.com/projectcreate" in err


def test_links_stay_whole_in_a_narrow_terminal(capsys, monkeypatch, google, person, downloads):
    (downloads / "client_secret_1.json").write_text(CLIENT)
    monkeypatch.setattr(guide.console, "width", 40)
    person(*[""] * STEPS, "")

    code, _, err = run(capsys, "--no-browser")

    shown = Text.from_ansi(err).plain  # with colour on, a cut link would still carry its URL in the escape code
    assert code == 0
    for step in guide.CLIENT_STEPS:
        for task in step.tasks:
            for text in [task.url, *(task.values or {}).values()]:
                if text and text.startswith("https://"):
                    assert text in shown


def test_client_secrets_flag_skips_the_steps_at_a_terminal(capsys, google, person):
    person()
    code, _, err = run(capsys, "--client-secrets", CLIENT)
    assert code == 0
    assert google == []
    assert "Google Cloud setup" not in err


@pytest.mark.parametrize("as_contents", [False, True])
def test_client_secrets_flag_needs_no_prompts(capsys, google, tmp_path, as_contents):
    path = tmp_path / "client.json"
    path.write_text(CLIENT)
    code, out, _ = run(capsys, "--client-secrets", CLIENT if as_contents else str(path))
    assert code == 0
    assert json.loads(out)["client_secrets_present"] is True


def test_an_api_that_is_not_enabled_is_retried_without_signing_in_again(capsys, google, person):
    Settings.from_env().client_secrets_file.write_text(CLIENT)
    google.connect_errors.append(Forbidden("YouTube Data API v3 has not been used in project 1. Enable it: https://x"))
    person("")

    code, _, err = run(capsys)

    assert code == 0
    assert "Enable it: https://x" in err
    assert "Connected Main" in err


def test_without_a_terminal_an_api_error_is_reported(capsys, google):
    Settings.from_env().client_secrets_file.write_text(CLIENT)
    google.connect_errors.append(Forbidden("not enabled"))
    code, _, err = run(capsys)
    assert code == 6
    assert json.loads(err)["error"]["type"] == "forbidden"


def test_with_a_client_already_saved_it_goes_straight_to_google(capsys, google, person):
    Settings.from_env().client_secrets_file.write_text(CLIENT)
    person()

    code, _, err = run(capsys)

    assert code == 0
    assert "Step 1" not in err
    assert "Go to ytk (unsafe)" in err
