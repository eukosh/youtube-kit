"""googleapiclient Resources for the YouTube Data, Analytics and Reporting APIs.

Resources are cached per thread because httplib2 connections are not thread-safe
and the MCP server runs sync tools on worker threads. OAuth clients are cached per
channel and keyed by the token file's mtime, so a long-running server picks up
`ytk auth login` without a restart.
"""

import threading
from pathlib import Path

from googleapiclient.discovery import Resource, build

from . import auth
from .config import Settings
from .errors import LOGIN_HINT, NotAuthorized

_local = threading.local()


def public() -> Resource:
    """Client for public data: the API key if set, otherwise the user's OAuth token."""
    settings = Settings.from_env()
    if settings.api_key is None:
        if not auth.has_login(settings):
            raise NotAuthorized(f"No credentials. Set YOUTUBE_API_KEY for public data, or: {LOGIN_HINT}")
        return _oauth(auth.token_file(settings, any_login=True))
    return _cached("public", settings.api_key, lambda: _build(developerKey=settings.api_key))


def oauth() -> Resource:
    """Client for the channel being worked on (uploads, edits, own channel); see `auth.working_on`."""
    return _oauth(auth.token_file(Settings.from_env()))


def _oauth(token: Path) -> Resource:
    return _cached(f"oauth:{token}", _mtime(token), lambda: _build(credentials=auth.load_credentials(token)))


def analytics() -> Resource:
    """YouTube Analytics client for the channel being worked on."""
    token = auth.token_file(Settings.from_env())
    return _cached(
        f"analytics:{token}",
        _mtime(token),
        lambda: _build("youtubeAnalytics", "v2", credentials=auth.load_credentials(token, auth.ANALYTICS)),
    )


def reporting() -> Resource:
    """YouTube Reporting client (daily bulk reports) for the channel being worked on."""
    token = auth.token_file(Settings.from_env())
    return _cached(
        f"reporting:{token}",
        _mtime(token),
        lambda: _build("youtubereporting", "v1", credentials=auth.load_credentials(token, auth.ANALYTICS)),
    )


def _mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None  # load_credentials raises the actionable error


def _cached(slot: str, key: object, make) -> Resource:
    cached = getattr(_local, slot, None)
    if cached is None or cached[0] != key:
        cached = (key, make())
        setattr(_local, slot, cached)
    return cached[1]


def _build(service: str = "youtube", version: str = "v3", **kwargs) -> Resource:
    return build(service, version, cache_discovery=False, static_discovery=True, **kwargs)
