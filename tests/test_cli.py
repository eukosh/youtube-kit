"""CLI contract: one JSON document on stdout, structured errors on stderr, stable exit codes."""

import io
import json
import subprocess
import sys
from unittest.mock import MagicMock

import httplib2
import pytest

from youtube_kit.cli import main
from youtube_kit.core import auth, client
from youtube_kit.core.config import Settings

from .fakes import channel_item, http_error, playlist_resource, video_item, write_login


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_prints_compact_json_without_nulls(capsys, api):
    api.public.videos().list().execute.return_value = {"items": [video_item(statistics={"viewCount": "5"})]}

    code, out, _ = run(capsys, "video", "get", "dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ")

    assert code == 0
    assert out.count("\n") == 1
    [video] = json.loads(out)
    assert video["stats"] == {"views": 5}
    assert video["published_at"] == "2026-01-02T03:04:05Z"


def test_keyword_flags_and_list_options(capsys, api):
    api.oauth.videos().list().execute.return_value = {"items": [video_item()]}
    api.oauth.videos().update().execute.return_value = video_item()

    code, _, _ = run(capsys, "video", "update", "dQw4w9WgXcQ", "--tags", "x", "--tags", "y", "--privacy", "unlisted")

    assert code == 0
    body = api.oauth.videos().update.call_args.kwargs["body"]
    assert body["snippet"]["tags"] == ["x", "y"]
    assert body["status"]["privacyStatus"] == "unlisted"


def test_empty_tags_flag_clears_tags(capsys, api):
    api.oauth.videos().list().execute.return_value = {"items": [video_item()]}
    api.oauth.videos().update().execute.return_value = video_item()

    assert run(capsys, "video", "update", "dQw4w9WgXcQ", "--empty-tags")[0] == 0
    assert api.oauth.videos().update.call_args.kwargs["body"]["snippet"]["tags"] == []


@pytest.mark.parametrize(
    ("error", "exit_code", "kind"),
    [
        (http_error(404, "channelNotFound"), 3, "not_found"),
        (http_error(401), 4, "not_authorized"),
        (http_error(403, "quotaExceeded"), 5, "quota_exceeded"),
        (http_error(403, "forbidden"), 6, "forbidden"),
        (http_error(500, "backendError"), 1, "error"),
        (KeyError("snippet"), 1, "error"),  # unexpected response shape: still JSON, no traceback
        (http_error(400, "invalidParameter"), 2, "invalid_request"),
        (httplib2.ServerNotFoundError("dns"), 7, "network"),
    ],
)
def test_domain_errors_become_json_on_stderr_and_exit_codes(capsys, api, error, exit_code, kind):
    api.public.channels().list().execute.side_effect = error

    code, out, err = run(capsys, "channel", "get", "@x")

    assert code == exit_code
    assert out == ""
    assert json.loads(err)["error"]["type"] == kind


def test_invalid_input_exits_2(capsys, api):
    code, out, err = run(capsys, "video", "get", "nope")
    assert (code, out) == (2, "")
    assert json.loads(err)["error"]["type"] == "invalid_request"


@pytest.mark.parametrize(
    "argv",
    [
        ["search"],  # missing query
        ["search", "cats", "--limit", "999"],  # over the cap
        ["search", "cats", "video"],  # options are keyword-only
        ["video", "nope"],  # unknown command
    ],
)
def test_usage_errors_exit_2_and_explain_on_stderr(capsys, api, argv):
    code, out, err = run(capsys, *argv)
    assert (code, out) == (2, "")
    assert json.loads(err)["error"]["type"] == "usage"


def test_upload_takes_the_file_positionally(capsys, api, tmp_path):
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x")
    api.oauth.videos().insert().next_chunk.return_value = (None, {"id": "NEWVIDEO123"})

    code, out, _ = run(
        capsys, "video", "upload", str(file), "--title", "Hi", "--tags", "a", "--publish-at", "2026-07-01"
    )

    assert code == 0
    assert json.loads(out)["id"] == "NEWVIDEO123"
    body = api.oauth.videos().insert.call_args.kwargs["body"]
    assert body["snippet"]["tags"] == ["a"]
    assert body["status"]["publishAt"] == "2026-07-01T00:00:00Z"


def test_help_prints_no_json(capsys):
    code, out, _ = run(capsys, "search", "--help")
    assert code == 0
    assert "Quota: 100 units per page" in out


def test_auth_status_needs_no_network(capsys):
    code, out, _ = run(capsys, "auth", "status")
    assert code == 0
    assert json.loads(out)["channels"] == []


def test_logged_in_channels_switch_and_my_channel(capsys, api, monkeypatch):
    token_dir = Settings.from_env().token_dir
    write_login(token_dir)
    write_login(token_dir, "UC" + "b" * 22, "@other")
    acted_as = []
    monkeypatch.setattr(
        client, "oauth", lambda: acted_as.append(auth.token_file(Settings.from_env()).stem) or api.oauth
    )
    api.oauth.channels().list().execute.return_value = {"items": [channel_item()]}

    assert run(capsys, "channel", "get")[0] == 4  # two logins, no default yet
    code, out, _ = run(capsys, "auth", "switch", "@other")
    assert code == 0
    assert [c["default"] for c in json.loads(out)["channels"]] == [False, True]
    run(capsys, "channel", "get")
    run(capsys, "channel", "get", "--my-channel", "@channel")
    code, out, _ = run(capsys, "channel", "mine")

    assert acted_as == ["UC" + "b" * 22, "UC" + "a" * 22]
    assert [c["handle"] for c in json.loads(out)] == ["@channel", "@other"]


def test_channel_get_defaults_to_mine(capsys, api):
    api.oauth.channels().list().execute.return_value = {"items": [channel_item()]}
    code, out, _ = run(capsys, "channel", "get")
    assert code == 0
    assert json.loads(out)["handle"] == "@channel"


def test_cli_startup_does_not_import_fastmcp():
    code = "import sys, youtube_kit.cli; sys.exit('fastmcp' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_progress_line_is_ended_before_an_error(capsys, api, tmp_path, monkeypatch):
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x" * 1000)
    api.oauth.videos().insert().next_chunk.side_effect = [
        (MagicMock(resumable_progress=400), None),
        http_error(403, "quotaExceeded"),
    ]

    code, _, err = run(capsys, "video", "upload", str(file), "--title", "Hi")

    assert code == 5
    progress_line, error_line = err.strip().split("\n")
    assert progress_line.endswith("progress:  40%")
    assert json.loads(error_line)["error"]["type"] == "quota_exceeded"


def test_ctrl_c_exits_130(capsys, api):
    api.public.videoCategories().list().execute.side_effect = KeyboardInterrupt
    with pytest.raises(SystemExit) as exited:
        run(capsys, "video", "categories")
    assert exited.value.code == 130


def test_bool_flags_negate(capsys, api):
    api.oauth.videos().list().execute.return_value = {"items": [video_item()]}
    api.oauth.videos().update().execute.return_value = video_item()

    assert run(capsys, "video", "update", "dQw4w9WgXcQ", "--no-made-for-kids")[0] == 0
    assert api.oauth.videos().update.call_args.kwargs["body"]["status"]["selfDeclaredMadeForKids"] is False


# ---------- guarded deletes ----------


@pytest.fixture
def deletable(api, my_channel):
    api.oauth.playlists().list().execute.return_value = {"items": [playlist_resource()]}
    return api.oauth.playlists()


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def human(monkeypatch):
    """Call with what a person at a terminal types. Patches at call time, once capsys has replaced stderr."""

    def answer(text: str) -> None:
        monkeypatch.setattr(sys, "stdin", Terminal(text))
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    return answer


def test_agents_get_exit_8_with_the_plan(capsys, deletable):
    code, out, err = run(capsys, "playlist", "delete", "PL1")

    assert (code, out) == (8, "")
    error = json.loads(err)["error"]
    assert error["type"] == "confirmation_required"
    assert error["details"]["confirm"] == "PL1"
    assert error["details"]["title"] == "Mix"
    assert error["details"]["rerun"] == "ytk playlist delete PL1 --confirm PL1"
    deletable.delete.assert_not_called()


def test_rerun_keeps_the_chosen_channel(capsys, deletable):
    _, _, err = run(capsys, "playlist", "delete", "PL1", "--my-channel", "@other")
    assert json.loads(err)["error"]["details"]["rerun"] == "ytk playlist delete PL1 --my-channel @other --confirm PL1"


def test_agents_confirm_with_the_id(capsys, deletable):
    code, out, _ = run(capsys, "playlist", "delete", "PL1", "--confirm", "PL1")
    assert code == 0
    assert json.loads(out) == {"kind": "playlist", "id": "PL1", "already_gone": False}


def test_humans_are_asked_and_their_yes_deletes(capsys, deletable, human):
    human("y\n")

    code, out, err = run(capsys, "playlist", "delete", "--", "PL1")  # --confirm must land before the --

    assert code == 0
    assert "About to permanently delete playlist PL1" in err
    assert "title: Mix" in err
    assert json.loads(out)["id"] == "PL1"
    assert deletable.delete.call_args.kwargs == {"id": "PL1"}


def test_humans_can_decline(capsys, deletable, human):
    human("\n")
    code, out, err = run(capsys, "playlist", "delete", "PL1")
    assert (code, out) == (1, "")
    assert "nothing was deleted" in err
    deletable.delete.assert_not_called()


def test_protected_exits_9(capsys, api, my_channel):
    api.oauth.videos().list().execute.return_value = {"items": [video_item()]}
    code, _, err = run(capsys, "video", "delete", "dQw4w9WgXcQ")
    assert code == 9
    assert json.loads(err)["error"]["details"]["max_views"] == 100
