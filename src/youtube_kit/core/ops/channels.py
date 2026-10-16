from typing import Any

from googleapiclient.discovery import Resource

from .. import client, parse
from ..errors import NotFound
from ..models import Channel, ChannelStats
from ..operation import operation
from ._common import channel_url, to_int

_LOOKUP_PARAM = {"id": "id", "handle": "forHandle", "username": "forUsername"}


@operation(quota=1, read_only=True, idempotent=True)
def get_channel(channel: str) -> Channel:
    """Channel metadata, statistics, and uploads playlist ID.

    Args:
        channel: UC… channel ID, @handle (the @ is optional), or channel URL.
    """
    ref = parse.channel_ref(channel)
    return _fetch(client.public(), f"Channel {ref.value} not found.", **{_LOOKUP_PARAM[ref.by]: ref.value})


@operation(quota=1, read_only=True, idempotent=True, oauth=True)
def get_my_channel() -> Channel:
    """The authorized user's own channel, including its uploads playlist ID."""
    return _fetch(client.oauth(), "The authorized Google account has no YouTube channel.", mine=True)


def resolve_channel_id(channel: str) -> str:
    """UC… ID for any channel reference; costs one request unless it already is an ID."""
    ref = parse.channel_ref(channel)
    return ref.value if ref.by == "id" else get_channel(channel).id


def _fetch(youtube: Resource, not_found: str, **selector: Any) -> Channel:
    response = youtube.channels().list(part="snippet,statistics,contentDetails", **selector).execute()
    items = response.get("items", [])
    if not items:
        raise NotFound(not_found)
    return _channel(items[0])


def _channel(item: dict) -> Channel:
    snippet, stats = item["snippet"], item.get("statistics")
    handle = snippet.get("customUrl")
    return Channel(
        id=item["id"],
        url=f"https://www.youtube.com/{handle}" if handle else channel_url(item["id"]),
        title=snippet["title"],
        description=snippet["description"],
        handle=handle,
        published_at=snippet["publishedAt"],
        country=snippet.get("country"),
        stats=None
        if stats is None
        else ChannelStats(
            views=to_int(stats.get("viewCount")),
            subscribers=None if stats.get("hiddenSubscriberCount") else to_int(stats.get("subscriberCount")),
            videos=to_int(stats.get("videoCount")),
        ),
        uploads_playlist_id=item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
    )
