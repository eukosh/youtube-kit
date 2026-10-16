from collections.abc import Callable
from typing import Annotated, Any

from googleapiclient.http import HttpRequest
from pydantic import Field

from .models import Page

API_PAGE_SIZE = 50

Limit = Annotated[int, Field(ge=1, le=500)]
"""Maximum items a listing returns, fetched in pages of up to 50."""


def collect[T](
    request: Callable[..., HttpRequest],
    *,
    limit: int,
    page_token: str | None,
    to_item: Callable[[dict], T],
) -> Page[T]:
    """Fetch pages until `limit` items or the end of the list.

    Each request asks for exactly the items still missing, so next_page_token always
    points at the first item not returned. If a later page fails, the error propagates
    and earlier pages are discarded.
    """
    items: list[T] = []
    total: int | None = None
    token = page_token
    while True:
        page: dict[str, Any] = {"maxResults": min(API_PAGE_SIZE, limit - len(items))}
        if token:
            page["pageToken"] = token
        response = request(**page).execute()
        if total is None:
            total = response.get("pageInfo", {}).get("totalResults")
        items.extend(to_item(item) for item in response.get("items", []))
        token = response.get("nextPageToken")
        if not token or len(items) >= limit:
            return Page(items=items, total_results=total, next_page_token=token)
