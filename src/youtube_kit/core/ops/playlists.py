from typing import Any

from .. import client, parse
from ..models import Page, Playlist, PlaylistEntry, PlaylistItemAdded, Privacy
from ..operation import operation
from ..pagination import Limit, collect
from ._common import playlist_url, video_url


@operation(quota=1, read_only=True, idempotent=True, paginated=True)
def list_playlist_items(
    playlist: str,
    *,
    limit: Limit = 25,
    page_token: str | None = None,
) -> Page[PlaylistEntry]:
    """Videos in a playlist, in playlist order.

    To list everything a channel has uploaded, pass the channel's uploads_playlist_id.

    Args:
        playlist: Playlist ID or a URL with a list= parameter.
        limit: Maximum number of entries.
        page_token: Continue from a previous result's next_page_token.
    """
    playlist_id = parse.playlist_id(playlist)
    return collect(
        lambda **page: (
            client.public().playlistItems().list(part="snippet,contentDetails", playlistId=playlist_id, **page)
        ),
        limit=limit,
        page_token=page_token,
        to_item=_playlist_entry,
    )


@operation(quota=50, oauth=True)
def create_playlist(title: str, *, description: str = "", privacy: Privacy = "private") -> Playlist:
    """Create a playlist on the authorized user's channel.

    Args:
        title: Playlist title.
        description: Playlist description.
        privacy: Privacy status.
    """
    body = {"snippet": {"title": title, "description": description}, "status": {"privacyStatus": privacy}}
    response = client.oauth().playlists().insert(part="snippet,status", body=body).execute()
    return Playlist(
        id=response["id"],
        url=playlist_url(response["id"]),
        title=response["snippet"]["title"],
        privacy=response.get("status", {}).get("privacyStatus"),
    )


@operation(quota=50, oauth=True)
def add_video_to_playlist(playlist: str, video: str, *, position: int | None = None) -> PlaylistItemAdded:
    """Add a video to a playlist on the authorized user's channel.

    Args:
        playlist: Playlist ID or URL.
        video: Video ID or URL.
        position: 0-based position in the playlist. Appends to the end when omitted.
    """
    playlist_id, video_id = parse.playlist_id(playlist), parse.video_id(video)
    snippet: dict[str, Any] = {
        "playlistId": playlist_id,
        "resourceId": {"kind": "youtube#video", "videoId": video_id},
    }
    if position is not None:
        snippet["position"] = position
    response = client.oauth().playlistItems().insert(part="snippet", body={"snippet": snippet}).execute()
    return PlaylistItemAdded(
        playlist_item_id=response["id"],
        playlist_id=playlist_id,
        video_id=video_id,
        position=response["snippet"]["position"],
    )


def _playlist_entry(item: dict) -> PlaylistEntry:
    video_id = item["contentDetails"]["videoId"]
    return PlaylistEntry(
        video_id=video_id,
        url=video_url(video_id),
        title=item["snippet"]["title"],
        published_at=item["contentDetails"].get("videoPublishedAt"),
        position=item["snippet"]["position"],
    )
