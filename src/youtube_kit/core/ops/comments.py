from typing import Literal

from .. import client, parse
from ..models import Comment, Page
from ..operation import operation
from ..pagination import Limit, collect


@operation(quota=1, read_only=True, idempotent=True, paginated=True)
def list_comments(
    video: str,
    *,
    limit: Limit = 20,
    order: Literal["relevance", "time"] = "relevance",
    page_token: str | None = None,
) -> Page[Comment]:
    """Top-level comment threads on a video.

    Args:
        video: Video ID or URL.
        limit: Maximum number of comment threads.
        order: Most relevant first, or newest first.
        page_token: Continue from a previous result's next_page_token.
    """
    video_id = parse.video_id(video)
    return collect(
        lambda **page: (
            client.public()
            .commentThreads()
            .list(part="snippet", videoId=video_id, order=order, textFormat="plainText", **page)
        ),
        limit=limit,
        page_token=page_token,
        to_item=_comment,
    )


def _comment(item: dict) -> Comment:
    top = item["snippet"]["topLevelComment"]
    snippet = top["snippet"]
    return Comment(
        id=top["id"],
        author=snippet["authorDisplayName"],
        text=snippet["textDisplay"],
        likes=snippet["likeCount"],
        published_at=snippet["publishedAt"],
        reply_count=item["snippet"]["totalReplyCount"],
    )
