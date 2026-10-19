from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from youtube_kit.core import client, updates

from .fakes import CHANNEL_ID


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Never read the developer's real credentials or config."""
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_CHANNEL", raising=False)
    monkeypatch.setenv("YOUTUBE_TOKEN_DIR", str(tmp_path / "tokens"))
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRETS", str(tmp_path / "client_secrets.json"))
    monkeypatch.setenv("YOUTUBE_CONFIG_FILE", str(tmp_path / "config.toml"))
    # Never ask PyPI; tests of the update check turn it back on.
    monkeypatch.setenv(updates.OPT_OUT_ENV, "1")
    monkeypatch.setattr(updates, "STATE_FILE", tmp_path / "cache" / "update-check.json")


@pytest.fixture
def api(monkeypatch):
    """Fake googleapiclient Resources. Set responses on the chain, e.g.

    api.public.videos().list().execute.return_value = {...}

    Operations that use the wrong client get a bare MagicMock back and fail validation.
    """
    fakes = SimpleNamespace(
        public=MagicMock(name="public"),
        oauth=MagicMock(name="oauth"),
        analytics=MagicMock(name="analytics"),
        reporting=MagicMock(name="reporting"),
    )
    monkeypatch.setattr(client, "public", lambda: fakes.public)
    monkeypatch.setattr(client, "oauth", lambda: fakes.oauth)
    monkeypatch.setattr(client, "analytics", lambda: fakes.analytics)
    monkeypatch.setattr(client, "reporting", lambda: fakes.reporting)
    return fakes


@pytest.fixture
def my_channel(api):
    """The authorized user owns CHANNEL_ID, the channel the fakes' videos and playlists belong to."""
    api.oauth.channels().list().execute.return_value = {"items": [{"id": CHANNEL_ID}]}
