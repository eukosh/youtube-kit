"""Turn whatever a user or agent pastes (IDs, @handles, URLs, dates) into API values."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import parse_qs, urlparse

from .errors import InvalidRequest

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_VIDEO_PATH_PREFIXES = ("shorts", "embed", "live", "v", "e", "video")  # "video": studio.youtube.com
_YOUTUBE_DOMAINS = ("youtube.com", "youtube-nocookie.com")


@dataclass(frozen=True)
class ChannelRef:
    by: Literal["id", "handle", "username"]
    value: str


def video_id(ref: str) -> str:
    """Video ID from an ID or a watch/youtu.be/shorts/embed/live URL."""
    ref = ref.strip()
    if _VIDEO_ID.match(ref):
        return ref
    url = _parse_url(ref)
    if url is not None:
        host, path, query = url
        candidate = None
        if host == "youtu.be":
            candidate = path[0] if path else None
        elif "v" in query:
            candidate = query["v"][0]
        elif len(path) >= 2 and path[0] in _VIDEO_PATH_PREFIXES:
            candidate = path[1]
        if candidate and _VIDEO_ID.match(candidate):
            return candidate
    raise InvalidRequest(f"Not a YouTube video ID or URL: {ref!r}")


def channel_ref(ref: str) -> ChannelRef:
    """Channel lookup key from a UC… ID, an @handle (the @ is optional), or a channel URL."""
    ref = ref.strip()
    url = _parse_url(ref)
    if url is None:
        if _CHANNEL_ID.match(ref):
            return ChannelRef("id", ref)
        if ref and "/" not in ref:
            return ChannelRef("handle", ref if ref.startswith("@") else f"@{ref}")
        raise InvalidRequest(f"Not a YouTube channel ID, handle, or URL: {ref!r}")

    _, path, _ = url
    if path and path[0].startswith("@"):
        return ChannelRef("handle", path[0])
    if len(path) >= 2 and path[0] == "channel" and _CHANNEL_ID.match(path[1]):
        return ChannelRef("id", path[1])
    if len(path) >= 2 and path[0] == "user":
        return ChannelRef("username", path[1])
    if len(path) >= 2 and path[0] == "c":
        raise InvalidRequest(
            f"Legacy custom URLs (/c/{path[1]}) can't be resolved through the API. "
            "Use the channel's @handle or /channel/UC… URL instead."
        )
    raise InvalidRequest(f"Not a YouTube channel URL: {ref!r}")


def playlist_id(ref: str) -> str:
    """Playlist ID from an ID or any URL carrying a list= parameter."""
    ref = ref.strip()
    url = _parse_url(ref)
    if url is None:
        if ref and re.fullmatch(r"[A-Za-z0-9_-]+", ref):
            return ref
    else:
        _, _, query = url
        if "list" in query:
            return query["list"][0]
    raise InvalidRequest(f"Not a YouTube playlist ID or URL: {ref!r}")


def timestamp(value: str) -> str:
    """RFC 3339 UTC timestamp from an ISO date or datetime. Naive values are taken as UTC."""
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise InvalidRequest(f"Not an ISO 8601 date or datetime: {value!r}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_url(ref: str) -> tuple[str, list[str], dict[str, list[str]]] | None:
    """(host, path segments, query) for a YouTube URL, or None if `ref` isn't one."""
    if "/" not in ref and "?" not in ref:
        return None
    parsed = urlparse(ref if "://" in ref else f"https://{ref}")
    host = parsed.hostname or ""
    if host != "youtu.be" and not any(host == d or host.endswith(f".{d}") for d in _YOUTUBE_DOMAINS):
        return None
    path = [segment for segment in parsed.path.split("/") if segment]
    return host, path, parse_qs(parsed.query)
