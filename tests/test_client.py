"""Client resolution and caching: the one piece of core with process-wide state."""

import os
import threading

import pytest

from youtube_kit.core import auth, client
from youtube_kit.core.config import Settings
from youtube_kit.core.errors import NotAuthorized

from .fakes import write_token


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(client, "_local", threading.local())


@pytest.fixture
def builds(monkeypatch):
    """Record build() calls instead of constructing real Resources."""
    calls = []

    def fake_build(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(client, "_build", fake_build)
    return calls


def test_public_uses_the_api_key_and_caches(monkeypatch, builds):
    monkeypatch.setenv("YOUTUBE_API_KEY", "key")
    assert client.public() is client.public()
    assert builds == [{"developerKey": "key"}]


def test_public_without_any_credentials_names_both_options(builds):
    with pytest.raises(NotAuthorized, match="YOUTUBE_API_KEY") as caught:
        client.public()
    assert "ytk auth login" in str(caught.value)


def test_public_falls_back_to_oauth(builds):
    write_token(Settings.from_env().token_file)
    assert client.public() is client.oauth()
    assert "credentials" in builds[0]


def test_oauth_rebuilds_after_a_new_login(builds):
    token = Settings.from_env().token_file
    write_token(token)
    first = client.oauth()
    assert client.oauth() is first

    write_token(token, token="new-access")
    os.utime(token, ns=(0, token.stat().st_mtime_ns + 1_000_000))

    assert client.oauth() is not first
    assert len(builds) == 2


def test_oauth_after_logout_explains_how_to_login(builds):
    settings = Settings.from_env()
    write_token(settings.token_file)
    client.oauth()
    auth.logout(settings)
    with pytest.raises(NotAuthorized, match="ytk auth login"):
        client.oauth()


def test_clients_are_per_thread(monkeypatch, builds):
    monkeypatch.setenv("YOUTUBE_API_KEY", "key")
    main = client.public()
    other = []
    thread = threading.Thread(target=lambda: other.append(client.public()))
    thread.start()
    thread.join()
    assert other[0] is not main
