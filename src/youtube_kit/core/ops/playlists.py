import itertools
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError

from .. import client, guard, parse
from ..errors import (
    OTHER_CHANNEL_HINT,
    Forbidden,
    InvalidRequest,
    NotFound,
    YouTubeError,
    from_http_error,
    http_reason,
)
from ..models import Deleted, Page, Playlist, PlaylistEntry, PlaylistImage, PlaylistItem, PlaylistRemoval, Privacy
from ..operation import operation
from ..pagination import API_PAGE_SIZE, Limit, collect
from ._common import (
    changes,
    delete_if_present,
    existing_file,
    image_size,
    image_upload,
    one,
    pick,
    playlist_url,
    to_int,
    unique_ids,
    video_url,
)
from .channels import copied_from_recent_uploads, my_channel_id, owner_or

_PARTS = "snippet,status,contentDetails"
_MAX_PLAYLIST_LENGTH = 5000  # YouTube's cap on a user playlist (uploads and Watch Later can be longer)


@operation(quota=1, read_only=True, idempotent=True, paginated=True)
def list_playlists(
    channel: str | None = None,
    *,
    limit: Limit = 25,
    page_token: str | None = None,
) -> Page[Playlist]:
    """A channel's playlists.

    Args:
        channel: UC… channel ID, @handle, or channel URL. Omit for your own channel, including private playlists.
        limit: Maximum number of playlists.
        page_token: Continue from a previous result's next_page_token.
    """
    youtube, selector = owner_or(channel)
    return collect(
        lambda **page: youtube.playlists().list(part=_PARTS, **selector, **page),
        limit=limit,
        page_token=page_token,
        to_item=_playlist,
    )


@operation(quota=1, read_only=True, idempotent=True)
def get_playlists(playlists: list[str]) -> list[Playlist]:
    """Metadata of one or more playlists: title, description, privacy, and item count.

    Args:
        playlists: Playlist IDs or URLs with a list= parameter. Fetched in batches of 50, 1 quota unit per batch.
    """
    ids = unique_ids(playlists, parse.playlist_id, "playlist ID or URL")
    found: list[Playlist] = []
    for batch in itertools.batched(ids, API_PAGE_SIZE):
        request = client.public().playlists().list(part=_PARTS, id=",".join(batch))
        found.extend(_playlist(item) for item in request.execute().get("items", []))
    if not found:
        raise NotFound(
            f"Playlist {ids[0]} not found." if len(ids) == 1 else f"None of the {len(ids)} playlists were found."
        )
    return found


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


@operation(quota=57, oauth=True)  # insert + at most 7 reads in copied_from_recent_uploads
def create_playlist(
    title: str, *, description: str = "", language: str | None = None, privacy: Privacy = "private"
) -> Playlist:
    """Create a playlist on the authorized user's channel.

    Left out, the language is copied from your most recent public upload, as video uploads do.

    Args:
        title: Playlist title.
        description: Playlist description.
        language: Language of the title and description, e.g. en-US.
        privacy: Privacy status.
    """
    snippet = {"title": title, "description": description, **copied_from_recent_uploads(defaultLanguage=language)}
    body = {"snippet": snippet, "status": {"privacyStatus": privacy}}
    return _playlist(client.oauth().playlists().insert(part="snippet,status", body=body).execute())


@operation(quota=51, destructive=True, idempotent=True, oauth=True)
def update_playlist(
    playlist: str,
    *,
    title: str | None = None,
    description: str | None = None,
    language: str | None = None,
    privacy: Privacy | None = None,
) -> Playlist:
    """Change one of your playlists. Only the fields you pass change.

    Args:
        playlist: Playlist ID or URL.
        title: New title.
        description: New description.
        language: Language of the title and description, e.g. en-US.
        privacy: New privacy status.
    """
    playlist_id = parse.playlist_id(playlist)
    youtube = client.oauth()
    current = one(
        youtube.playlists().list(part="snippet,status", id=playlist_id).execute(), f"Playlist {playlist_id} not found."
    )
    # playlists.update replaces each part it is sent, so carry over the writable fields.
    body: dict[str, Any] = {
        "id": playlist_id,
        "snippet": pick(current["snippet"], ("title", "description", "defaultLanguage", "tags"))
        | changes(title=title, description=description, defaultLanguage=language),
    }
    parts = ["snippet"]
    if privacy is not None:
        body["status"] = pick(current["status"], ("podcastStatus",)) | {"privacyStatus": privacy}
        parts.append("status")
    return _playlist(youtube.playlists().update(part=",".join(parts), body=body).execute())


@operation(quota=52, destructive=True, idempotent=True, oauth=True)  # lookup + ownership check + delete
def delete_playlist(playlist: str, *, confirm: str | None = None) -> Deleted:
    """Permanently delete one of your playlists. The videos in it are not affected.

    Without confirm, nothing is deleted and the error describes the playlist.

    Args:
        playlist: Playlist ID or URL.
        confirm: The playlist ID again, passed only after the user has approved deleting this playlist.
    """
    playlist_id = parse.playlist_id(playlist)
    youtube = client.oauth()
    items = youtube.playlists().list(part=_PARTS, id=playlist_id).execute().get("items", [])
    if not items:
        return Deleted(kind="playlist", id=playlist_id, already_gone=True)
    target = _playlist(items[0])
    if target.channel_id != my_channel_id():
        raise Forbidden(f"Playlist {playlist_id} belongs to another channel. {OTHER_CHANNEL_HINT}")
    plan = {"title": target.title, "url": target.url, "privacy": target.privacy, "videos": target.item_count}
    guard.require_confirm("playlist", playlist_id, confirm, plan)
    deleted = delete_if_present(youtube.playlists().delete(id=playlist_id))
    return Deleted(kind="playlist", id=playlist_id, already_gone=not deleted)


@operation(quota=50, oauth=True)
def add_video_to_playlist(playlist: str, video: str, *, position: int | None = None) -> PlaylistItem:
    """Add a video to a playlist on the authorized user's channel.

    Args:
        playlist: Playlist ID or URL.
        video: Video ID or URL.
        position: 0-based position in the playlist. Appends to the end when omitted.
    """
    snippet = _item_snippet(parse.playlist_id(playlist), parse.video_id(video), position)
    return _playlist_item(client.oauth().playlistItems().insert(part="snippet", body={"snippet": snippet}).execute())


@operation(quota=51, destructive=True, idempotent=True, oauth=True)
def remove_from_playlist(playlist: str, video: str) -> PlaylistRemoval:
    """Remove a video from one of your playlists, every time it appears. The video itself is not affected.

    YouTube can't look up entries of a deleted video, so for a deleted or unknown video the whole playlist is read:
    1 more unit per 50 entries.

    Args:
        playlist: Playlist ID or URL.
        video: Video ID or URL.
    """
    playlist_id, video_id = parse.playlist_id(playlist), parse.video_id(video)
    youtube = client.oauth()
    removed = sum(
        delete_if_present(youtube.playlistItems().delete(id=item["id"]))
        for item in _occurrences(playlist_id, video_id, deleted_video=True)
    )
    return PlaylistRemoval(playlist_id=playlist_id, video_id=video_id, removed=removed)


@operation(quota=51, destructive=True, idempotent=True, oauth=True)
def move_in_playlist(playlist: str, video: str, *, position: int) -> PlaylistItem:
    """Move a video to another position in one of your playlists.

    Args:
        playlist: Playlist ID or URL.
        video: Video ID or URL. Refused if the video appears in the playlist more than once.
        position: New 0-based position.
    """
    playlist_id, video_id = parse.playlist_id(playlist), parse.video_id(video)
    items = _occurrences(playlist_id, video_id)
    if not items:
        raise NotFound(f"Video {video_id} is not in playlist {playlist_id}.")
    if len(items) > 1:
        raise InvalidRequest(
            f"Video {video_id} appears {len(items)} times in playlist {playlist_id}. "
            "Remove it from the playlist and add it again at the position you want."
        )
    body = {"id": items[0]["id"], "snippet": _item_snippet(playlist_id, video_id, position)}
    return _playlist_item(client.oauth().playlistItems().update(part="snippet", body=body).execute())


@operation(quota=101, destructive=True, idempotent=True, oauth=True)
def set_playlist_thumbnail(playlist: str, image: Path) -> PlaylistImage:
    """Set the custom thumbnail of one of your playlists, replacing any current one.

    Args:
        playlist: Playlist ID or URL.
        image: Path to a square JPEG or PNG, at most 50 MB.
    """
    playlist_id = parse.playlist_id(playlist)
    path = existing_file(image)
    media = image_upload(path, max_mb=50)
    size = image_size(path)
    if size and size[0] != size[1]:
        raise InvalidRequest(f"Playlist images must be square; {path.name} is {size[0]}x{size[1]}.")
    images = client.oauth().playlistImages()
    current = images.list(part="snippet", parent=playlist_id).execute().get("items", [])
    # playlistImages.update rejects every request, and insert refuses while a hero image exists.
    removed = False
    for item in current:
        if item["snippet"].get("type") == "hero":
            removed = delete_if_present(images.delete(id=item["id"])) or removed
    body = {"snippet": {"playlistId": playlist_id, "type": "hero"}}
    try:
        response = images.insert(part="snippet", body=body, media_body=media).execute()
    except HttpError as e:
        reason = http_reason(e)
        if reason == "INVALID_ASPECT_RATIO":
            error = InvalidRequest("YouTube rejected the image's aspect ratio. Playlist images must be square.")
        elif reason == "IMAGE_TYPE_ALREADY_EXISTS":
            # Happens right after setting one: YouTube doesn't list the new image for a while, so it wasn't deleted.
            error = YouTubeError("YouTube doesn't list the playlist's current thumbnail yet. Try again in a minute.")
        else:
            error = from_http_error(e)
        if removed:
            error = type(error)(
                f"{error} The playlist's previous thumbnail was already removed.", details=error.details
            )
        raise error from e
    return PlaylistImage(
        playlist_id=playlist_id,
        image_id=response["id"],
        width=response.get("snippet", {}).get("width"),
        height=response.get("snippet", {}).get("height"),
    )


def _occurrences(playlist_id: str, video_id: str, *, deleted_video: bool = False) -> list[dict]:
    """The playlist items holding a video; more than one if it was added repeatedly.

    With deleted_video, falls back to reading the whole playlist when YouTube answers videoNotFound.
    """
    items = client.oauth().playlistItems()
    try:
        return (
            items.list(part="id", playlistId=playlist_id, videoId=video_id, maxResults=API_PAGE_SIZE)
            .execute()
            .get("items", [])
        )
    except HttpError as e:
        if not deleted_video or http_reason(e) != "videoNotFound":
            raise
    # The videoId filter fails once a video is deleted, though the playlist keeps its entry: read the whole playlist.
    page = collect(
        lambda **page: items.list(part="contentDetails", playlistId=playlist_id, **page),
        limit=_MAX_PLAYLIST_LENGTH,
        page_token=None,
        to_item=lambda item: item,
    )
    if page.next_page_token:
        raise YouTubeError(
            f"Playlist {playlist_id} has more than {_MAX_PLAYLIST_LENGTH} entries, "
            f"too many to search for video {video_id}."
        )
    return [item for item in page.items if item.get("contentDetails", {}).get("videoId") == video_id]


def _item_snippet(playlist_id: str, video_id: str, position: int | None) -> dict:
    snippet: dict[str, Any] = {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}
    if position is not None:
        snippet["position"] = position
    return snippet


def _playlist(item: dict) -> Playlist:
    snippet = item["snippet"]
    return Playlist(
        id=item["id"],
        url=playlist_url(item["id"]),
        title=snippet["title"],
        description=snippet.get("description"),
        language=snippet.get("defaultLanguage"),
        channel_id=snippet.get("channelId"),
        published_at=snippet.get("publishedAt"),
        privacy=item.get("status", {}).get("privacyStatus"),
        item_count=to_int(item.get("contentDetails", {}).get("itemCount")),
    )


def _playlist_item(item: dict) -> PlaylistItem:
    snippet = item["snippet"]
    return PlaylistItem(
        playlist_item_id=item["id"],
        playlist_id=snippet["playlistId"],
        video_id=snippet["resourceId"]["videoId"],
        position=snippet["position"],
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
