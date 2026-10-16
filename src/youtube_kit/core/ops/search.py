from typing import Annotated, Any, Literal

from pydantic import Field

from .. import client, parse
from ..models import Page, SearchHit, SearchKind
from ..operation import operation
from ..pagination import collect
from ._common import channel_url, playlist_url, video_url
from .channels import resolve_channel_id

# Lower cap than other listings: every page of 50 costs 100 units of a 10,000 daily quota.
SearchLimit = Annotated[int, Field(ge=1, le=200)]

_ID_KEY = {"video": "videoId", "channel": "channelId", "playlist": "playlistId"}
_URL = {"video": video_url, "channel": channel_url, "playlist": playlist_url}


@operation(quota=100, read_only=True, idempotent=True, paginated=True)
def search(
    query: str,
    *,
    kind: SearchKind = "video",
    limit: SearchLimit = 10,
    order: Literal["relevance", "date", "rating", "viewCount", "title"] = "relevance",
    channel: str | None = None,
    since: str | None = None,
    page_token: str | None = None,
) -> Page[SearchHit]:
    """Search YouTube for videos, channels, or playlists.

    Args:
        query: Search terms.
        kind: What to search for.
        limit: Maximum number of results. Each page of up to 50 costs 100 quota units.
        order: Sort order.
        channel: Only results from this channel: UC… ID, @handle, or channel URL.
        since: Only results published at or after this date or datetime (2026-01-01), or this long ago (90d, 4w).
        page_token: Continue from a previous result's next_page_token.
    """
    params: dict[str, Any] = {"part": "snippet", "q": query, "type": kind, "order": order}
    if channel:
        params["channelId"] = resolve_channel_id(channel)
    if since:
        params["publishedAfter"] = parse.since(since)
    return collect(
        lambda **page: client.public().search().list(**params, **page),
        limit=limit,
        page_token=page_token,
        to_item=_search_hit,
    )


def _search_hit(item: dict) -> SearchHit:
    kind = item["id"]["kind"].removeprefix("youtube#")
    resource_id = item["id"][_ID_KEY[kind]]
    snippet = item["snippet"]
    return SearchHit(
        id=resource_id,
        kind=kind,
        url=_URL[kind](resource_id),
        title=snippet["title"],
        description=snippet["description"],
        channel_id=snippet["channelId"],
        channel_title=snippet["channelTitle"],
        published_at=snippet["publishedAt"],
    )
