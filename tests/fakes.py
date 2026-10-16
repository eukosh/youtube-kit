"""Canned API responses and errors for tests."""

import json

import httplib2
from googleapiclient.errors import HttpError


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
            "channelId": "UC" + "a" * 22,
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


def channel_item(channel_id: str = "UC" + "a" * 22) -> dict:
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
    """An authorized-user token file, valid until 2999 unless overridden."""
    token = {
        "token": "access",
        "refresh_token": "refresh",
        "client_id": "id",
        "client_secret": "secret",
        "token_uri": "https://oauth2.googleapis.com/token",
        "expiry": "2999-01-01T00:00:00Z",
        **overrides,
    }
    path.write_text(json.dumps(token))
