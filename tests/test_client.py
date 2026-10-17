"""Client resolution and caching: the one piece of core with process-wide state."""

import os
import threading
from unittest.mock import MagicMock

import pytest

from youtube_kit.core import auth, client
from youtube_kit.core.config import Settings
from youtube_kit.core.errors import NotAuthorized
from youtube_kit.core.ops import channels, videos

from .fakes import channel_item, write_login

OTHER_ID = "UC" + "b" * 22


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(client, "_local", threading.local())


@pytest.fixture
def builds(monkeypatch):
    """Record build() calls instead of constructing real Resources."""
    calls = []

    def fake_build(*api, **kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(client, "_build", fake_build)
    return calls


@pytest.fixture
def tokens(monkeypatch):
    """Record which access token each built client would use. The clients accept any call."""
    used = []

    def fake_build(*api, credentials=None, **kwargs):
        used.append(credentials.token)
        youtube = MagicMock()
        youtube.channels().list().execute.return_value = {"items": [channel_item()]}
        youtube.activities().list().execute.return_value = {"items": []}
        return youtube

    monkeypatch.setattr(client, "_build", fake_build)
    return used


def test_public_uses_the_api_key_and_caches(monkeypatch, builds):
    monkeypatch.setenv("YOUTUBE_API_KEY", "key")
    assert client.public() is client.public()
    assert builds == [{"developerKey": "key"}]


def test_public_without_any_credentials_names_both_options(builds):
    with pytest.raises(NotAuthorized, match="YOUTUBE_API_KEY") as caught:
        client.public()
    assert "ytk auth login" in str(caught.value)


def test_public_falls_back_to_oauth(builds):
    write_login(Settings.from_env().token_dir)
    assert client.public() is client.oauth()
    assert "credentials" in builds[0]


def test_public_reads_use_any_login_when_there_is_no_default(builds):
    token_dir = Settings.from_env().token_dir
    write_login(token_dir)
    write_login(token_dir, OTHER_ID, "@other")
    with pytest.raises(NotAuthorized, match="none is the default"):
        client.oauth()
    assert client.public() is not None


def test_oauth_rebuilds_after_a_new_login(builds):
    token = write_login(Settings.from_env().token_dir)
    first = client.oauth()
    assert client.oauth() is first

    write_login(token.parent, token="new-access")
    os.utime(token, ns=(0, token.stat().st_mtime_ns + 1_000_000))

    assert client.oauth() is not first
    assert len(builds) == 2


def test_oauth_after_logout_explains_how_to_login(builds):
    settings = Settings.from_env()
    write_login(settings.token_dir)
    client.oauth()
    auth.logout(settings)
    with pytest.raises(NotAuthorized, match="ytk auth login"):
        client.oauth()


def test_oauth_clients_are_cached_per_channel(builds):
    token_dir = Settings.from_env().token_dir
    write_login(token_dir)
    write_login(token_dir, OTHER_ID, "@other")
    with auth.working_on("@channel"):
        first = client.oauth()
    with auth.working_on("@other"):
        other = client.oauth()
    with auth.working_on("@channel"):
        assert client.oauth() is first
    assert other is not first
    assert len(builds) == 2


def test_clients_are_per_thread(monkeypatch, builds):
    monkeypatch.setenv("YOUTUBE_API_KEY", "key")
    main = client.public()
    other = []
    thread = threading.Thread(target=lambda: other.append(client.public()))
    thread.start()
    thread.join()
    assert other[0] is not main


def test_analytics_needs_the_analytics_scope(builds):
    write_login(Settings.from_env().token_dir)
    with pytest.raises(NotAuthorized, match="analytics access"):
        client.analytics()


def test_analytics_with_the_scope(builds):
    write_login(Settings.from_env().token_dir, scopes=auth.SCOPES)
    assert client.analytics() is client.analytics()
    assert len(builds) == 1


def test_operations_work_on_the_channel_they_are_given(tokens):
    token_dir = Settings.from_env().token_dir
    write_login(token_dir)
    write_login(token_dir, OTHER_ID, "@other", token="other-access")
    auth.switch(Settings.from_env(), "@channel")

    videos.rate_video("dQw4w9WgXcQ", "like", my_channel="@other")
    videos.rate_video("dQw4w9WgXcQ", "like")

    assert tokens == ["other-access", "access"]


def test_operations_called_inside_an_operation_keep_its_channel(tokens):
    token_dir = Settings.from_env().token_dir
    write_login(token_dir)
    write_login(token_dir, OTHER_ID, "@other", token="other-access")
    auth.switch(Settings.from_env(), "@channel")

    # Without an API key, resolving the @handle (a nested get_channel) also goes through OAuth.
    channels.list_activities("@someone", my_channel="@other")

    assert set(tokens) == {"other-access"}
