import json
import stat
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.oauth2.credentials import Credentials

from youtube_kit.core import auth
from youtube_kit.core.config import Settings
from youtube_kit.core.errors import InvalidRequest, NotAuthorized

from .fakes import CHANNEL_ID, write_login

OTHER_ID = "UC" + "b" * 22


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture
def two_logins(settings):
    """Logged in to CHANNEL_ID (@channel) and OTHER_ID (@other), with no default chosen."""
    write_login(settings.token_dir)
    write_login(settings.token_dir, OTHER_ID, "@Other", token="other-access")


@pytest.fixture
def fake_flow(monkeypatch):
    """Make login() finish without a browser, as `fake_flow.channel` with `fake_flow.granted` scopes."""
    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)  # login sets it; undo after the test
    state = SimpleNamespace(channel={"id": CHANNEL_ID, "title": "Main", "handle": "@channel"}, granted=auth.SCOPES)

    class Flow:
        @classmethod
        def from_client_secrets_file(cls, path, scopes):
            assert scopes == auth.SCOPES
            return cls()

        def run_local_server(self, **kwargs):
            return Credentials(token="t", refresh_token="r", scopes=auth.SCOPES, granted_scopes=state.granted)

    monkeypatch.setattr(auth, "InstalledAppFlow", Flow)
    monkeypatch.setattr(auth, "_identify", lambda creds: dict(state.channel))
    Settings.from_env().client_secrets_file.write_text("{}")
    return state


def test_settings_follow_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "key")
    monkeypatch.setenv("YOUTUBE_CHANNEL", "@other")
    settings = Settings.from_env()
    assert settings.api_key == "key"
    assert settings.channel == "@other"
    assert settings.token_dir == tmp_path / "tokens"


def test_status_is_local_only(settings):
    status = auth.status(settings)
    assert status.channels == []
    assert not status.client_secrets_present
    assert not status.api_key_set


def test_without_a_login_explains_how_to_login(settings):
    with pytest.raises(NotAuthorized, match="ytk auth login"):
        auth.token_file(settings)


def test_the_only_login_is_the_default(settings):
    path = write_login(settings.token_dir)
    assert auth.token_file(settings) == path
    [channel] = auth.my_channels(settings)
    assert channel.default
    assert channel.url == "https://www.youtube.com/@channel"


def test_several_logins_without_a_default_name_the_choices(settings, two_logins):
    with pytest.raises(NotAuthorized, match=r"none is the default: .*\(@channel\), .*\(@Other\)"):
        auth.token_file(settings)
    assert not any(channel.default for channel in auth.my_channels(settings))


@pytest.mark.parametrize("ref", [OTHER_ID, "@other", "other", f"https://www.youtube.com/channel/{OTHER_ID}"])
def test_my_channel_picks_a_login_by_id_or_handle(settings, two_logins, ref):
    with auth.working_on(ref):
        assert auth.token_file(settings).stem == OTHER_ID


def test_my_channel_none_keeps_the_outer_choice(settings, two_logins):
    with auth.working_on("@other"), auth.working_on(None):
        assert auth.token_file(settings).stem == OTHER_ID


def test_my_channel_a_channel_without_a_login_lists_the_logins(settings, two_logins):
    with auth.working_on("@stranger"), pytest.raises(NotAuthorized, match=r"Not logged in to @stranger .*@Other"):
        auth.token_file(settings)


def test_my_channel_rejects_what_is_not_a_channel(settings, two_logins):
    with auth.working_on("a/b"), pytest.raises(InvalidRequest):
        auth.token_file(settings)


def test_switch_sets_the_default(settings, two_logins):
    assert [c.default for c in auth.switch(settings, "@other").channels] == [False, True]
    assert auth.token_file(settings).stem == OTHER_ID


def test_switch_to_a_channel_without_a_login_fails(settings, two_logins):
    with pytest.raises(NotAuthorized, match="Not logged in"):
        auth.switch(settings, "@stranger")


@pytest.mark.parametrize("value", ["@nobody", "a/b"])
def test_env_channel_that_is_not_logged_in_is_named_in_the_error(settings, two_logins, monkeypatch, value):
    monkeypatch.setenv("YOUTUBE_CHANNEL", value)
    settings = Settings.from_env()
    with pytest.raises(NotAuthorized, match=f"YOUTUBE_CHANNEL={value} isn't one of your logged-in channels"):
        auth.token_file(settings)
    assert not any(channel.default for channel in auth.status(settings).channels)


def test_switch_is_refused_while_the_env_channel_overrides_it(settings, two_logins, monkeypatch):
    monkeypatch.setenv("YOUTUBE_CHANNEL", "@other")
    with pytest.raises(InvalidRequest, match="Unset it"):
        auth.switch(Settings.from_env(), "@channel")


def test_env_channel_overrides_the_stored_default(settings, two_logins, monkeypatch):
    auth.switch(settings, "@channel")
    monkeypatch.setenv("YOUTUBE_CHANNEL", "@other")
    settings = Settings.from_env()
    assert auth.token_file(settings).stem == OTHER_ID
    assert [c.default for c in auth.my_channels(settings)] == [False, True]


def test_login_stores_the_token_under_its_channel_and_the_first_becomes_default(settings, fake_flow):
    status = auth.login(settings)

    assert [(c.id, c.title, c.default) for c in status.channels] == [(CHANNEL_ID, "Main", True)]
    stored = json.loads((settings.token_dir / f"{CHANNEL_ID}.json").read_text())
    assert stored["channel"]["handle"] == "@channel"

    fake_flow.channel = {"id": OTHER_ID, "title": "Second", "handle": "@other"}
    assert [c.default for c in auth.login(settings).channels] == [True, False]


def test_login_stores_the_scopes_google_granted(settings, fake_flow):
    fake_flow.granted = [auth.YOUTUBE]
    [channel] = auth.login(settings).channels
    assert not channel.analytics
    with pytest.raises(NotAuthorized, match="analytics access"):
        auth.load_credentials(auth.token_file(settings), auth.ANALYTICS)


def test_a_login_for_an_account_without_a_channel_is_refused(monkeypatch):
    youtube = MagicMock()
    youtube.channels().list().execute.return_value = {"items": []}
    monkeypatch.setattr(auth, "build", lambda *api, **kwargs: youtube)
    with pytest.raises(NotAuthorized, match="has no YouTube channel"):
        auth._identify(Credentials(token="t"))


def test_login_without_client_secrets_explains_setup(settings):
    with pytest.raises(NotAuthorized, match="Desktop app"):
        auth.login(settings)


def test_logout_removes_the_default_channel(settings, two_logins):
    auth.switch(settings, "@other")
    assert [c.id for c in auth.logout(settings).channels] == [CHANNEL_ID]
    assert auth.token_file(settings).stem == CHANNEL_ID  # the only one left


def test_logout_follows_the_env_channel(settings, two_logins, monkeypatch):
    auth.switch(settings, "@channel")
    monkeypatch.setenv("YOUTUBE_CHANNEL", "@other")
    assert [c.id for c in auth.logout(Settings.from_env()).channels] == [CHANNEL_ID]


def test_logout_without_a_default_asks_which(settings, two_logins):
    with pytest.raises(InvalidRequest, match="name one"):
        auth.logout(settings)


def test_logout_a_named_channel(settings, two_logins):
    assert [c.id for c in auth.logout(settings, "@channel").channels] == [OTHER_ID]


def test_logout_without_a_login_is_a_no_op(settings):
    assert auth.logout(settings).channels == []
    assert auth.logout(settings).channels == []


def test_load_credentials_returns_valid_token(settings):
    assert auth.load_credentials(write_login(settings.token_dir)).token == "access"


def test_load_credentials_refreshes_and_saves_atomically(settings, monkeypatch):
    path = write_login(settings.token_dir, expiry="2000-01-01T00:00:00Z")

    def fake_refresh(self, request):
        self.token = "fresh"

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    assert auth.load_credentials(path).token == "fresh"
    stored = json.loads(path.read_text())
    assert stored["token"] == "fresh"
    assert stored["channel"]["id"] == CHANNEL_ID
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_tokens_without_a_scope_list_are_tried(settings):
    path = write_login(settings.token_dir)
    info = json.loads(path.read_text())
    del info["scopes"]
    path.write_text(json.dumps(info))
    assert auth.load_credentials(path, auth.ANALYTICS).token == "access"


@pytest.mark.parametrize("content", ["{not json", '{"token": "access"}'])
def test_load_credentials_rejects_a_broken_token(settings, content):
    path = settings.token_dir / f"{CHANNEL_ID}.json"
    path.parent.mkdir()
    path.write_text(content)
    with pytest.raises(NotAuthorized, match="ytk auth login"):
        auth.load_credentials(auth.token_file(settings))


def test_status_survives_a_corrupt_token(settings):
    (settings.token_dir).mkdir()
    (settings.token_dir / f"{CHANNEL_ID}.json").write_text("{not json")
    [channel] = auth.status(settings).channels
    assert channel.id == channel.title == CHANNEL_ID
    assert not channel.analytics
