from typing import Literal

from .. import client
from ..models import Page, Subscription, Unsubscribed
from ..operation import operation
from ..pagination import Limit, collect
from ._common import channel_url, delete_if_present
from .channels import resolve_channel_id


@operation(quota=1, read_only=True, idempotent=True, oauth=True, paginated=True)
def list_subscriptions(
    *,
    order: Literal["alphabetical", "relevance", "unread"] = "alphabetical",
    limit: Limit = 25,
    page_token: str | None = None,
) -> Page[Subscription]:
    """Channels the authorized user is subscribed to.

    Args:
        order: Alphabetical, by relevance, or by activity (unread first).
        limit: Maximum number of subscriptions.
        page_token: Continue from a previous result's next_page_token.
    """
    return collect(
        lambda **page: client.oauth().subscriptions().list(part="snippet", mine=True, order=order, **page),
        limit=limit,
        page_token=page_token,
        to_item=_subscription,
    )


@operation(quota=51, idempotent=True, oauth=True)
def subscribe(channel: str) -> Subscription:
    """Subscribe the authorized user to a channel. Already being subscribed is fine.

    Args:
        channel: UC… channel ID, @handle, or channel URL. A handle or URL costs 1 more quota unit.
    """
    channel_id = resolve_channel_id(channel)
    existing = _find(channel_id)
    if existing is not None:
        return _subscription(existing)
    body = {"snippet": {"resourceId": {"kind": "youtube#channel", "channelId": channel_id}}}
    return _subscription(client.oauth().subscriptions().insert(part="snippet", body=body).execute())


@operation(quota=51, destructive=True, idempotent=True, oauth=True)
def unsubscribe(channel: str) -> Unsubscribed:
    """Unsubscribe the authorized user from a channel. Not being subscribed is fine.

    Args:
        channel: UC… channel ID, @handle, or channel URL. A handle or URL costs 1 more quota unit.
    """
    channel_id = resolve_channel_id(channel)
    existing = _find(channel_id)
    removed = existing is not None and delete_if_present(client.oauth().subscriptions().delete(id=existing["id"]))
    return Unsubscribed(channel_id=channel_id, was_subscribed=removed)


def _find(channel_id: str) -> dict | None:
    request = client.oauth().subscriptions().list(part="snippet", mine=True, forChannelId=channel_id)
    items = request.execute().get("items", [])
    return items[0] if items else None


def _subscription(item: dict) -> Subscription:
    snippet = item["snippet"]
    channel_id = snippet["resourceId"]["channelId"]
    return Subscription(
        id=item["id"],
        channel_id=channel_id,
        url=channel_url(channel_id),
        title=snippet.get("title"),
        description=snippet.get("description"),
        subscribed_at=snippet.get("publishedAt"),
    )
