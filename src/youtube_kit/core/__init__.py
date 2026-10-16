"""Transport-neutral YouTube Data API core. No printing, no exit codes, no MCP."""

from .errors import Forbidden, InvalidRequest, NetworkError, NotAuthorized, NotFound, QuotaExceeded, YouTubeError
from .operation import OPERATIONS, OperationInfo, info
from .ops import (
    add_video_to_playlist,
    create_playlist,
    get_channel,
    get_my_channel,
    get_videos,
    list_comments,
    list_playlist_items,
    list_video_categories,
    search,
    set_thumbnail,
    update_video,
    upload_video,
)

__all__ = [
    "OPERATIONS",
    "Forbidden",
    "InvalidRequest",
    "NetworkError",
    "NotAuthorized",
    "NotFound",
    "OperationInfo",
    "QuotaExceeded",
    "YouTubeError",
    "add_video_to_playlist",
    "create_playlist",
    "get_channel",
    "get_my_channel",
    "get_videos",
    "info",
    "list_comments",
    "list_playlist_items",
    "list_video_categories",
    "search",
    "set_thumbnail",
    "update_video",
    "upload_video",
]
