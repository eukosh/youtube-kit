import calendar
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BeforeValidator, Field

from .. import client, parse
from ..errors import InvalidRequest
from ..models import AnalyticsReport
from ..operation import operation
from ._common import unique_ids

_API_DIMENSIONS = {
    "day": "day",
    "month": "month",
    "video": "video",
    "country": "country",
    "device": "deviceType",
    "os": "operatingSystem",
    "traffic-source": "insightTrafficSourceType",
    "playback-location": "insightPlaybackLocationType",
    "age": "ageGroup",
    "gender": "gender",
    "subscribed": "subscribedStatus",
}
Dimension = Literal[*_API_DIMENSIONS]  # type: ignore[valid-type]
# MCP arguments are snake_case, so models often write traffic_source for traffic-source.
_Dashed = BeforeValidator(lambda value: value.replace("_", "-") if isinstance(value, str) else value)
DEFAULT_METRICS = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "likes",
    "comments",
    "subscribersGained",
    "subscribersLost",
)
WATCH_METRICS = ("views", "estimatedMinutesWatched", "averageViewDuration")
# YouTube rejects likes, comments and subscriber counts for these breakdowns, and age and gender take only this one.
_DEFAULT_METRICS_BY = {
    **dict.fromkeys(("device", "os", "traffic-source", "playback-location", "subscribed"), WATCH_METRICS),
    **dict.fromkeys(("age", "gender"), ("viewerPercentage",)),
}
DEFAULT_DAYS = 28
PACIFIC = ZoneInfo("America/Los_Angeles")


@operation(quota=0, read_only=True, idempotent=True, oauth=True)
def get_analytics(
    *,
    since: str | None = None,
    until: str | None = None,
    by: Annotated[Dimension | None, _Dashed] = None,
    metrics: list[str] | None = None,
    videos: list[str] | None = None,
    sort: str | None = None,
    limit: Annotated[int, Field(ge=1)] | None = None,
) -> AnalyticsReport:
    """YouTube Analytics for your channel: totals, or rows broken down by one dimension.

    Data for the last two or three days is incomplete, so recent rows keep growing. Uses the separate
    YouTube Analytics API and its quota; enable it in the same Google Cloud project.

    Args:
        since: First day, inclusive: 2026-01-01, or 90d / 4w before until. Defaults to 28 days before until.
        until: Last day, inclusive: 2026-01-31, or 7d / 1w ago. Defaults to today.
        by: Break the numbers down by this dimension; its column is named as given here. Omit for totals.
            By month, the range widens to whole months.
        metrics: Metric names from https://developers.google.com/youtube/analytics/metrics, e.g. views,
            estimatedMinutesWatched, subscribersGained. Defaults to views, watch time, average view
            duration, likes, comments, and subscribers gained and lost. By device, os, traffic-source,
            playback-location or subscribed, only watch metrics work (views, estimatedMinutesWatched,
            averageViewDuration, averageViewPercentage), and those are the default. By age or gender,
            only viewerPercentage works.
        videos: Only these videos (IDs or URLs).
        sort: Metric or dimension to sort by; prefix with - for descending, e.g. -views. Defaults to
            chronological by day or month, and to the first metric, descending, by anything else.
        limit: Maximum number of rows. Breaking down by video returns at most 200, 25 by default;
            other breakdowns return every row by default.
    """
    today = datetime.now(PACIFIC).date()  # YouTube's reporting day
    end = parse.day(until, ago_from=today) if until else today
    start = parse.day(since, ago_from=end) if since else end - timedelta(days=DEFAULT_DAYS - 1)
    if by == "month":
        start = start.replace(day=1)
        end = end.replace(day=calendar.monthrange(end.year, end.month)[1])
    if start > end:
        raise InvalidRequest(f"since ({start}) is after until ({end}).")
    metrics = metrics or list(_DEFAULT_METRICS_BY.get(by, DEFAULT_METRICS))
    params: dict[str, Any] = {
        "ids": "channel==MINE",
        "startDate": start.isoformat(),
        # By month, YouTube wants the first day of the last month, not its last day.
        "endDate": (end.replace(day=1) if by == "month" else end).isoformat(),
        "metrics": ",".join(metrics),
    }
    if by:
        params["dimensions"] = _API_DIMENSIONS[by]
        sort = sort or (by if by in {"day", "month"} else f"-{metrics[0]}")
    if videos:
        params["filters"] = "video==" + ",".join(unique_ids(videos, parse.video_id, "video ID or URL"))
    if by == "video":
        limit = min(limit or 25, 200)  # YouTube's cap for video breakdowns
    if sort:
        params["sort"] = sort
    if limit:
        params["maxResults"] = limit
    response = client.analytics().reports().query(**params).execute()
    columns = [
        by if by and header["name"] == _API_DIMENSIONS[by] else header["name"]
        for header in response.get("columnHeaders", [])
    ]
    return AnalyticsReport(
        since=start,
        until=end,
        columns=columns,
        rows=[dict(zip(columns, row, strict=True)) for row in response.get("rows") or []],
    )
