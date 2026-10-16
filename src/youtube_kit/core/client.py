"""googleapiclient Resources for the YouTube Data and Analytics APIs.

Resources are cached per thread because httplib2 connections are not thread-safe
and the MCP server runs sync tools on worker threads. The OAuth client is keyed by
the token file's mtime, so a long-running server picks up `ytk auth login` without
a restart.
"""

import threading

from googleapiclient.discovery import Resource, build

from . import auth
from .config import Settings
from .errors import LOGIN_HINT, NotAuthorized

_local = threading.local()


def public() -> Resource:
    """Client for public data: the API key if set, otherwise the user's OAuth token."""
    settings = Settings.from_env()
    if settings.api_key is None:
        if not settings.token_file.exists():
            raise NotAuthorized(f"No credentials. Set YOUTUBE_API_KEY for public data, or: {LOGIN_HINT}")
        return oauth()
    return _cached("public", settings.api_key, lambda: _build(developerKey=settings.api_key))


def oauth() -> Resource:
    """Client acting as the authorized user (uploads, edits, own channel)."""
    settings = Settings.from_env()
    return _cached("oauth", _token_key(settings), lambda: _build(credentials=auth.load_credentials(settings)))


def analytics() -> Resource:
    """YouTube Analytics client for the authorized user's channel."""
    settings = Settings.from_env()
    return _cached(
        "analytics",
        _token_key(settings),
        lambda: _build("youtubeAnalytics", "v2", credentials=auth.load_credentials(settings, auth.ANALYTICS)),
    )


def _token_key(settings: Settings) -> int | None:
    try:
        return settings.token_file.stat().st_mtime_ns
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
