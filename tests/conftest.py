from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from youtube_kit.core import client

from .fakes import CHANNEL_ID


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Never read the developer's real credentials or config."""
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRETS", str(tmp_path / "client_secrets.json"))
    monkeypatch.setenv("YOUTUBE_CONFIG_FILE", str(tmp_path / "config.toml"))


@pytest.fixture
def api(monkeypatch):
    """Fake googleapiclient Resources. Set responses on the chain, e.g.

    api.public.videos().list().execute.return_value = {...}

    Operations that use the wrong client get a bare MagicMock back and fail validation.
    """
    fakes = SimpleNamespace(public=MagicMock(name="public"), oauth=MagicMock(name="oauth"))
    monkeypatch.setattr(client, "public", lambda: fakes.public)
    monkeypatch.setattr(client, "oauth", lambda: fakes.oauth)
    return fakes


@pytest.fixture
def my_channel(api):
    """The authorized user owns CHANNEL_ID, the channel the fakes' videos and playlists belong to."""
    api.oauth.channels().list().execute.return_value = {"items": [{"id": CHANNEL_ID}]}
