import itertools
from typing import Any, Literal

from .. import client, guard, parse
from ..errors import Forbidden, InvalidRequest
from ..models import Comment, CommentStatus, Deleted, Moderated, Page
from ..operation import operation
from ..pagination import API_PAGE_SIZE, Limit, collect
from ._common import delete_if_present
from .channels import my_channel_id

_API_STATUS = {"published": "published", "held": "heldForReview", "spam": "likelySpam", "rejected": "rejected"}
_STATUS = {api: ours for ours, api in _API_STATUS.items()}


@operation(quota=1, read_only=True, idempotent=True, paginated=True)
def list_comments(
    video: str | None = None,
    *,
    status: CommentStatus = "published",
    search: str | None = None,
    order: Literal["relevance", "time"] = "time",
    limit: Limit = 20,
    page_token: str | None = None,
) -> Page[Comment]:
    """Top-level comments on a video, or on all of your channel's videos.

    Args:
        video: Video ID or URL. Omit for every video on your channel.
        status: Moderation status to list; spam is what YouTube flagged as likely spam. Anything but published
            is only visible on your own videos.
        search: Only comments containing these words.
        order: Newest first, or most relevant first.
        limit: Maximum number of comments.
        page_token: Continue from a previous result's next_page_token.
    """
    params: dict[str, Any] = {"part": "snippet", "order": order, "textFormat": "plainText"}
    if status != "published":
        params["moderationStatus"] = _API_STATUS[status]
    if search:
        params["searchTerms"] = search
    if video is None:
        params["allThreadsRelatedToChannelId"] = my_channel_id()
    else:
        params["videoId"] = parse.video_id(video)
    youtube = client.oauth() if video is None or status != "published" else client.public()
    return collect(
        lambda **page: youtube.commentThreads().list(**params, **page),
        limit=limit,
        page_token=page_token,
        to_item=_thread,
    )


@operation(quota=1, read_only=True, idempotent=True, paginated=True)
def list_replies(comment: str, *, limit: Limit = 20, page_token: str | None = None) -> Page[Comment]:
    """Replies to a top-level comment.

    Args:
        comment: Comment ID or link. A reply's ID or link lists its whole thread.
        limit: Maximum number of replies.
        page_token: Continue from a previous result's next_page_token.
    """
    parent_id = _thread_id(comment)
    return collect(
        lambda **page: (
            client.public().comments().list(part="snippet", parentId=parent_id, textFormat="plainText", **page)
        ),
        limit=limit,
        page_token=page_token,
        to_item=_comment,
    )


@operation(quota=50, oauth=True)
def post_comment(video: str, text: str) -> Comment:
    """Post a top-level comment on a video as the authorized user.

    Args:
        video: Video ID or URL.
        text: The comment.
    """
    video_id = parse.video_id(video)
    body = {"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}}
    return _thread(client.oauth().commentThreads().insert(part="snippet", body=body).execute())


@operation(quota=50, oauth=True)
def reply_to_comment(comment: str, text: str) -> Comment:
    """Reply to a top-level comment as the authorized user.

    Args:
        comment: Comment ID or link. Replying to a reply adds to the same thread.
        text: The reply.
    """
    body = {"snippet": {"parentId": _thread_id(comment), "textOriginal": text}}
    return _comment(client.oauth().comments().insert(part="snippet", body=body).execute())


@operation(quota=50, destructive=True, idempotent=True, oauth=True)
def edit_comment(comment: str, text: str) -> Comment:
    """Replace the text of one of your own comments or replies.

    Args:
        comment: Comment ID or link.
        text: The new text.
    """
    body = {"id": parse.comment_id(comment), "snippet": {"textOriginal": text}}
    return _comment(client.oauth().comments().update(part="snippet", body=body).execute())


@operation(quota=52, destructive=True, idempotent=True, oauth=True)  # lookup + ownership check + delete
def delete_comment(comment: str, *, confirm: str | None = None) -> Deleted:
    """Permanently delete one of your own comments or replies. Deleting a top-level comment deletes its replies.

    Others' comments on your videos can't be deleted, only rejected, which hides them.
    Without confirm, nothing is deleted and the error describes the comment.

    Args:
        comment: Comment ID or link.
        confirm: The comment ID again, passed only after the user has approved deleting this comment.
    """
    comment_id = parse.comment_id(comment)
    youtube = client.oauth()
    items = youtube.comments().list(part="snippet", id=comment_id, textFormat="plainText").execute().get("items", [])
    if not items:
        return Deleted(kind="comment", id=comment_id, already_gone=True)
    target = _comment(items[0])
    if target.author_channel_id != my_channel_id():
        raise Forbidden(f"Comment {comment_id} was written by someone else. Reject it to hide it instead.")
    plan = {"author": target.author, "text": target.text, "video_id": target.video_id}
    guard.require_confirm("comment", comment_id, confirm, plan)
    deleted = delete_if_present(youtube.comments().delete(id=comment_id))
    return Deleted(kind="comment", id=comment_id, already_gone=not deleted)


@operation(quota=50, destructive=True, idempotent=True, oauth=True)
def approve_comments(comments: list[str]) -> Moderated:
    """Publish comments on your videos that are held for review or marked as likely spam.

    Args:
        comments: Comment IDs or links. 50 quota units per 50 comments.
    """
    return _moderate(comments, "published")


@operation(quota=50, destructive=True, idempotent=True, oauth=True)
def hold_comments(comments: list[str]) -> Moderated:
    """Hide comments on your videos until you review them.

    Args:
        comments: Comment IDs or links. 50 quota units per 50 comments.
    """
    return _moderate(comments, "held")


@operation(quota=50, destructive=True, idempotent=True, oauth=True)
def reject_comments(comments: list[str], *, ban_author: bool = False) -> Moderated:
    """Reject comments on your videos, hiding them from viewers. They can still be approved later.

    Args:
        comments: Comment IDs or links. 50 quota units per 50 comments.
        ban_author: Also reject all future comments on your channel by each comment's author.
    """
    return _moderate(comments, "rejected", ban_author=ban_author)


def _moderate(
    comments: list[str], status: Literal["published", "held", "rejected"], *, ban_author: bool = False
) -> Moderated:
    ids = list(dict.fromkeys(parse.comment_id(c) for c in comments))
    if not ids:
        raise InvalidRequest("Pass at least one comment ID or link.")
    youtube = client.oauth()
    extra = {"banAuthor": True} if ban_author else {}  # only valid with rejected
    for batch in itertools.batched(ids, API_PAGE_SIZE, strict=False):
        youtube.comments().setModerationStatus(
            id=",".join(batch), moderationStatus=_API_STATUS[status], **extra
        ).execute()
    return Moderated(comment_ids=ids, status=status, authors_banned=ban_author)


def _thread_id(comment: str) -> str:
    """The top-level comment of a comment's thread. Threads are one level deep; replies are "<thread>.<reply>"."""
    return parse.comment_id(comment).split(".")[0]


def _thread(item: dict) -> Comment:
    snippet = item["snippet"]
    return _comment(snippet["topLevelComment"]).model_copy(update={"reply_count": snippet.get("totalReplyCount")})


def _comment(item: dict) -> Comment:
    snippet = item["snippet"]
    return Comment(
        id=item["id"],
        video_id=snippet.get("videoId"),
        author=snippet["authorDisplayName"],
        author_channel_id=snippet.get("authorChannelId", {}).get("value"),
        # textOriginal (only shown to the author) is plain text; textDisplay is HTML unless a list asked otherwise.
        text=snippet.get("textOriginal") or snippet.get("textDisplay", ""),
        likes=snippet.get("likeCount"),
        published_at=snippet["publishedAt"],
        updated_at=snippet.get("updatedAt"),
        parent_id=snippet.get("parentId"),
        status=_STATUS.get(snippet.get("moderationStatus")),
    )
