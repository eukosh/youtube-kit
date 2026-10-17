from collections.abc import Iterator
from typing import Any

from googleapiclient.discovery import Resource

from .. import auth, client, parse
from ..config import Settings
from ..models import Activity, Channel, ChannelStats, MyChannel, Page
from ..operation import operation
from ..pagination import API_PAGE_SIZE, Limit, collect
from ._common import channel_url, one, to_int

_LOOKUP_PARAM = {"id": "id", "handle": "forHandle", "username": "forUsername"}


@operation(quota=1, read_only=True, idempotent=True)
def get_channel(channel: str | None = None) -> Channel:
    """Channel metadata, statistics, and uploads playlist ID.

    Args:
        channel: UC… channel ID, @handle, or channel URL. Omit for your own channel.
    """
    if channel is None:
        return _fetch(client.oauth(), "The authorized Google account has no YouTube channel.", mine=True)
    ref = parse.channel_ref(channel)
    return _fetch(client.public(), f"Channel {ref.value} not found.", **{_LOOKUP_PARAM[ref.by]: ref.value})


@operation(quota=0, read_only=True, idempotent=True, local=True)
def list_my_channels() -> list[MyChannel]:
    """Channels the user is logged in to, and which one is the default.

    Operations on the user's own channel work on the default unless told to use another.
    Reads stored logins only; makes no API calls.
    """
    return auth.my_channels(Settings.from_env())


@operation(quota=1, read_only=True, idempotent=True, paginated=True)
def list_activities(
    channel: str | None = None,
    *,
    since: str | None = None,
    limit: Limit = 25,
    page_token: str | None = None,
) -> Page[Activity]:
    """A channel's recent activity feed (uploads, playlist additions, and the like).

    Args:
        channel: UC… channel ID, @handle, or channel URL. Omit for your own channel.
        since: Only activity at or after this date or datetime (2026-01-01), or this long ago (90d, 4w).
        limit: Maximum number of activities.
        page_token: Continue from a previous result's next_page_token.
    """
    youtube, selector = owner_or(channel)
    if since:
        selector["publishedAfter"] = parse.since(since)
    return collect(
        lambda **page: youtube.activities().list(part="snippet,contentDetails", **selector, **page),
        limit=limit,
        page_token=page_token,
        to_item=_activity,
    )


def resolve_channel_id(channel: str) -> str:
    """UC… ID for any channel reference; costs one request unless it already is an ID."""
    ref = parse.channel_ref(channel)
    return ref.value if ref.by == "id" else get_channel(channel).id


def my_channel_id() -> str:
    """The authorized user's channel ID, for ownership checks."""
    return one(client.oauth().channels().list(part="id", mine=True).execute(), "You have no YouTube channel.")["id"]


def my_uploads_playlist_id() -> str:
    """The authorized user's uploads playlist: every video on the channel, newest first."""
    response = client.oauth().channels().list(part="contentDetails", mine=True).execute()
    return one(response, "You have no YouTube channel.")["contentDetails"]["relatedPlaylists"]["uploads"]


# How many pages of the uploads playlist to search for a public video to copy settings from.
RECENT_UPLOAD_PAGES = 3


def copied_from_recent_uploads(**given: str | None) -> dict[str, str]:
    """The given snippet fields, with any left out copied from the newest public upload that has them.

    Stands in for Studio's upload defaults, which YouTube doesn't apply to API uploads.
    """
    chosen = {key: value for key, value in given.items() if value is not None}
    if len(chosen) < len(given):
        for snippet in _recent_public_snippets():
            for key in given.keys() - chosen.keys():
                if snippet.get(key):
                    chosen[key] = snippet[key]
            if len(chosen) == len(given):
                break
    return chosen


def _recent_public_snippets() -> Iterator[dict]:
    """Snippets of the user's public uploads, newest first, among the last RECENT_UPLOAD_PAGES pages."""
    youtube = client.oauth()
    request: dict[str, Any] = {
        "part": "contentDetails",
        "playlistId": my_uploads_playlist_id(),
        "maxResults": API_PAGE_SIZE,
    }
    for _ in range(RECENT_UPLOAD_PAGES):
        page = youtube.playlistItems().list(**request).execute()
        ids = [entry["contentDetails"]["videoId"] for entry in page.get("items", [])]
        if ids:
            found = youtube.videos().list(part="snippet,status", id=",".join(ids)).execute().get("items", [])
            public = [video["snippet"] for video in found if video.get("status", {}).get("privacyStatus") == "public"]
            yield from sorted(public, key=lambda snippet: snippet.get("publishedAt", ""), reverse=True)
        if not page.get("nextPageToken"):
            return
        request["pageToken"] = page["nextPageToken"]


def owner_or(channel: str | None) -> tuple[Resource, dict[str, Any]]:
    """Client and list selector for a channel's resources: your own (mine=True) when channel is None."""
    if channel is None:
        return client.oauth(), {"mine": True}
    return client.public(), {"channelId": resolve_channel_id(channel)}


def _fetch(youtube: Resource, not_found: str, **selector: Any) -> Channel:
    response = youtube.channels().list(part="snippet,statistics,contentDetails", **selector).execute()
    return _channel(one(response, not_found))


def _activity(item: dict) -> Activity:
    snippet = item["snippet"]
    # contentDetails holds one object named after the activity type, e.g. {"upload": {"videoId": ...}}.
    details = item.get("contentDetails", {}).get(snippet["type"], {})
    resource = details.get("resourceId", {})
    return Activity(
        type=snippet["type"],
        published_at=snippet["publishedAt"],
        title=snippet.get("title"),
        channel_id=snippet["channelId"],
        video_id=details.get("videoId") or resource.get("videoId"),
        playlist_id=details.get("playlistId") or resource.get("playlistId"),
        target_channel_id=resource.get("channelId"),
    )


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
