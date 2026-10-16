from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from youtube_kit.core import client


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Never read the developer's real credentials or config."""
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRETS", str(tmp_path / "client_secrets.json"))


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
