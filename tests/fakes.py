"""Canned API responses and errors for tests.

`video_item` and `channel_item` take top-level overrides; the `*_resource` builders take snippet fields.
"""

import json

import httplib2
from googleapiclient.errors import HttpError

CHANNEL_ID = "UC" + "a" * 22


def http_error(status: int, reason: str = "", message: str = "API says no.", details: str | None = None) -> HttpError:
    response = httplib2.Response({"status": status})
    response.reason = "Error"
    content = {"error": {"code": status, "message": message, "errors": [{"reason": reason, "message": message}]}}
    if details:
        content["error"]["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": details}]
    return HttpError(response, json.dumps(content).encode())


def video_item(video_id: str = "dQw4w9WgXcQ", **overrides) -> dict:
    item = {
        "id": video_id,
        "snippet": {
            "title": "Title",
            "description": "Description",
            "channelId": CHANNEL_ID,
            "channelTitle": "Channel",
            "publishedAt": "2026-01-02T03:04:05Z",
            "tags": ["a", "b"],
            "categoryId": "22",
        },
        "contentDetails": {"duration": "PT1H2M3S"},
        "statistics": {"viewCount": "1000", "likeCount": "10", "commentCount": "1"},
        "status": {"privacyStatus": "public"},
    }
    item.update(overrides)
    return item


def channel_item(channel_id: str = CHANNEL_ID) -> dict:
    return {
        "id": channel_id,
        "snippet": {
            "title": "Channel",
            "description": "About",
            "customUrl": "@channel",
            "publishedAt": "2020-01-01T00:00:00Z",
        },
        "statistics": {"viewCount": "5", "subscriberCount": "3", "hiddenSubscriberCount": False, "videoCount": "2"},
        "contentDetails": {"relatedPlaylists": {"uploads": "UU" + "a" * 22}},
    }


def write_token(path, **overrides) -> None:
    """An authorized-user token file, valid until 2999 unless overridden. No channel unless given one."""
    token = {
        "token": "access",
        "refresh_token": "refresh",
        "client_id": "id",
        "client_secret": "secret",
        "token_uri": "https://oauth2.googleapis.com/token",
        "expiry": "2999-01-01T00:00:00Z",
        "scopes": ["https://www.googleapis.com/auth/youtube.force-ssl"],
        **overrides,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token))


def write_login(token_dir, channel_id: str = CHANNEL_ID, handle: str | None = "@channel", **overrides):
    """A stored login for a channel, as `ytk auth login` leaves it. Returns the token's path."""
    path = token_dir / f"{channel_id}.json"
    channel = {"id": channel_id, "title": f"Title of {handle or channel_id}", "handle": handle}
    write_token(path, channel=channel, **overrides)
    return path


def playlist_item_resource(position: int = 0, item_id: str = "item1") -> dict:
    return {
        "id": item_id,
        "snippet": {
            "playlistId": "PL1",
            "resourceId": {"kind": "youtube#video", "videoId": "dQw4w9WgXcQ"},
            "position": position,
        },
    }


def playlist_resource(playlist_id: str = "PL1", **snippet) -> dict:
    return {
        "id": playlist_id,
        "snippet": {"title": "Mix", "description": "Songs", "channelId": CHANNEL_ID, **snippet},
        "status": {"privacyStatus": "public"},
        "contentDetails": {"itemCount": 4},
    }


def comment_resource(comment_id: str = "Ugc1", author_channel_id: str = CHANNEL_ID, **snippet) -> dict:
    return {
        "id": comment_id,
        "snippet": {
            "videoId": "dQw4w9WgXcQ",
            "authorDisplayName": "Me",
            "authorChannelId": {"value": author_channel_id},
            "textDisplay": "Nice",
            "likeCount": 5,
            "publishedAt": "2026-01-01T00:00:00Z",
            **snippet,
        },
    }


def thread_resource(comment: dict | None = None, replies: int = 2) -> dict:
    comment = comment or comment_resource()
    return {
        "id": comment["id"],
        "snippet": {"videoId": "dQw4w9WgXcQ", "totalReplyCount": replies, "topLevelComment": comment},
    }
