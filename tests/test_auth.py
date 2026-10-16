import json
import stat

import pytest
from google.oauth2.credentials import Credentials

from youtube_kit.core import auth
from youtube_kit.core.config import Settings
from youtube_kit.core.errors import NotAuthorized

from .fakes import write_token


def test_settings_follow_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "key")
    settings = Settings.from_env()
    assert settings.api_key == "key"
    assert settings.token_file == tmp_path / "token.json"


def test_status_is_local_only():
    status = auth.status(Settings.from_env())
    assert not status.token_present
    assert not status.client_secrets_present
    assert not status.api_key_set


def test_load_credentials_without_token_explains_how_to_login():
    with pytest.raises(NotAuthorized, match="ytk auth login"):
        auth.load_credentials(Settings.from_env())


def test_load_credentials_returns_valid_token():
    settings = Settings.from_env()
    write_token(settings.token_file)
    assert auth.load_credentials(settings).token == "access"


def test_load_credentials_refreshes_and_saves_atomically(monkeypatch):
    settings = Settings.from_env()
    write_token(settings.token_file, expiry="2000-01-01T00:00:00Z")

    def fake_refresh(self, request):
        self.token = "fresh"

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    assert auth.load_credentials(settings).token == "fresh"
    assert json.loads(settings.token_file.read_text())["token"] == "fresh"
    assert stat.S_IMODE(settings.token_file.stat().st_mode) == 0o600
    assert [p.name for p in settings.token_file.parent.iterdir()] == ["token.json"]


def test_login_without_client_secrets_explains_setup():
    with pytest.raises(NotAuthorized, match="Desktop app"):
        auth.login(Settings.from_env())


def test_logout_removes_token():
    settings = Settings.from_env()
    write_token(settings.token_file)
    assert not auth.logout(settings).token_present
    assert not auth.logout(settings).token_present  # idempotent


def test_status_lists_granted_scopes():
    settings = Settings.from_env()
    write_token(settings.token_file)
    assert auth.status(settings).granted_scopes == [auth.YOUTUBE]


def test_login_stores_the_scopes_google_granted(monkeypatch):
    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)  # login sets it; undo after the test
    settings = Settings.from_env()
    settings.client_secrets_file.write_text("{}")
    granted = Credentials(token="t", refresh_token="r", scopes=auth.SCOPES, granted_scopes=[auth.YOUTUBE])

    class Flow:
        @classmethod
        def from_client_secrets_file(cls, path, scopes):
            assert scopes == auth.SCOPES
            return cls()

        def run_local_server(self, **kwargs):
            return granted

    monkeypatch.setattr(auth, "InstalledAppFlow", Flow)

    assert auth.login(settings).granted_scopes == [auth.YOUTUBE]
    with pytest.raises(NotAuthorized, match="analytics access"):
        auth.load_credentials(settings, auth.ANALYTICS)


def test_tokens_without_a_scope_list_are_tried():
    settings = Settings.from_env()
    write_token(settings.token_file)
    info = json.loads(settings.token_file.read_text())
    del info["scopes"]
    settings.token_file.write_text(json.dumps(info))
    assert auth.load_credentials(settings, auth.ANALYTICS).token == "access"


def test_status_survives_a_corrupt_token():
    settings = Settings.from_env()
    settings.token_file.write_text("{not json")
    assert auth.status(settings).granted_scopes is None
