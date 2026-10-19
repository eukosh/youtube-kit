import calendar
import csv
import io
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

from googleapiclient.discovery import Resource
from pydantic import BeforeValidator, Field

from .. import client, parse
from ..errors import InvalidRequest
from ..models import AnalyticsReport, ImpressionsReport
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
    "traffic-source-detail": "insightTrafficSourceDetail",
    "playback-location": "insightPlaybackLocationType",
    "age": "ageGroup",
    "gender": "gender",
    "subscribed": "subscribedStatus",
    "content-type": "creatorContentType",
    "sharing-service": "sharingService",
    "elapsed": "elapsedVideoTimeRatio",
}
Dimension = Literal[*_API_DIMENSIONS]  # type: ignore[valid-type]
# MCP arguments are snake_case, so models often write traffic_source for traffic-source.
_Dashed = BeforeValidator(lambda value: value.replace("_", "-") if isinstance(value, str) else value)
ContentType = Literal["videoOnDemand", "shorts", "liveStream"]
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
# YouTube rejects likes, comments and subscriber counts for these breakdowns, and the rest take only their own.
_DEFAULT_METRICS_BY = {
    **dict.fromkeys(("device", "os", "traffic-source", "playback-location", "subscribed"), WATCH_METRICS),
    **dict.fromkeys(("age", "gender"), ("viewerPercentage",)),
    "traffic-source-detail": ("views", "estimatedMinutesWatched"),
    "sharing-service": ("shares",),
    "elapsed": ("audienceWatchRatio", "relativeRetentionPerformance"),
}
# YouTube's row caps; breakdowns by these must also be sorted.
_MAX_ROWS = {"video": 200, "traffic-source-detail": 25}
DEFAULT_DAYS = 28
PACIFIC = ZoneInfo("America/Los_Angeles")
REACH_REPORT = "channel_reach_basic_a1"


@operation(quota=0, read_only=True, idempotent=True, oauth=True)
def get_analytics(
    *,
    since: str | None = None,
    until: str | None = None,
    by: Annotated[Dimension | None, _Dashed] = None,
    metrics: list[str] | None = None,
    videos: list[str] | None = None,
    content_type: ContentType | None = None,
    country: str | None = None,
    traffic_source: str | None = None,
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
            By month, the range widens to whole months. By elapsed: the audience retention of exactly one
            video, a row per 1% of its length (0.01 to 1). By traffic-source-detail, which needs
            traffic_source: the search terms behind YT_SEARCH, the videos behind RELATED_VIDEO, the sites
            behind EXT_URL.
        metrics: Metric names from https://developers.google.com/youtube/analytics/metrics, e.g. views,
            estimatedMinutesWatched, subscribersGained. Defaults to views, watch time, average view
            duration, likes, comments, and subscribers gained and lost. By device, os, traffic-source,
            playback-location or subscribed, only watch metrics work (views, estimatedMinutesWatched,
            averageViewDuration, averageViewPercentage), and those are the default. By age or gender,
            only viewerPercentage works. By elapsed: audienceWatchRatio (share of viewers watching at that
            point, above 1 with rewatches) and relativeRetentionPerformance (0 to 1, against videos of
            similar length) by default, or startedWatching and stoppedWatching. By traffic-source-detail:
            views and estimatedMinutesWatched. By sharing-service: shares.
        videos: Only these videos (IDs or URLs).
        content_type: Only long-form videos (videoOnDemand), shorts, or live streams (liveStream), as the
            content-type breakdown names them. Not by elapsed.
        country: Only viewers in this country, e.g. US. Not by elapsed.
        traffic_source: The source to break down by traffic-source-detail, as the traffic-source breakdown names
            it, e.g. YT_SEARCH. Only with that breakdown.
        sort: Metric or dimension to sort by; prefix with - for descending, e.g. -views. Defaults to
            chronological by day, month or elapsed, and to the first metric, descending, by anything else.
        limit: Maximum number of rows. Breaking down by video returns at most 200, 25 by default; by
            traffic-source-detail, at most 25. Other breakdowns return every row by default.
    """
    start, end = _days(since, until)
    if by == "month":
        start = start.replace(day=1)
        end = end.replace(day=calendar.monthrange(end.year, end.month)[1])
    video_ids = unique_ids(videos, parse.video_id, "video ID or URL") if videos else []
    if by == "elapsed" and len(video_ids) != 1:
        raise InvalidRequest("Audience retention (by elapsed) needs exactly one video.")
    if by == "traffic-source-detail" and not traffic_source:
        raise InvalidRequest("Breaking down by traffic-source-detail needs traffic_source, e.g. YT_SEARCH.")
    if traffic_source and by != "traffic-source-detail":
        raise InvalidRequest("traffic_source works only with by traffic-source-detail.")
    metrics = metrics or list(_DEFAULT_METRICS_BY.get(by, DEFAULT_METRICS))
    params: dict[str, Any] = {
        "ids": "channel==MINE",
        "startDate": start.isoformat(),
        # By month, YouTube wants the first day of the last month, not its last day.
        "endDate": (end.replace(day=1) if by == "month" else end).isoformat(),
        "metrics": ",".join(metrics),
    }
    filters = {
        "video": ",".join(video_ids),
        "creatorContentType": content_type,
        "country": country and country.upper(),
        "insightTrafficSourceType": traffic_source and traffic_source.upper(),
    }
    if any(filters.values()):
        params["filters"] = ";".join(f"{name}=={value}" for name, value in filters.items() if value)
    if by:
        params["dimensions"] = _API_DIMENSIONS[by]
        sort = sort or (by if by in {"day", "month", "elapsed"} else f"-{metrics[0]}")
    if by in _MAX_ROWS:
        limit = min(limit or 25, _MAX_ROWS[by])
    local_sort = None
    if sort:
        name = sort.removeprefix("-")
        name = _API_DIMENSIONS.get(name.replace("_", "-"), name)
        if by == "elapsed":
            # YouTube ignores sort on retention queries and fails them with maxResults, so both happen here.
            local_sort = by if name == _API_DIMENSIONS[by] else name
            if local_sort not in {by, *metrics}:
                raise InvalidRequest(f"Sort retention by elapsed or one of its metrics: {', '.join(metrics)}.")
        else:
            params["sort"] = ("-" if sort.startswith("-") else "") + name
    if limit and by != "elapsed":
        params["maxResults"] = limit
    response = client.analytics().reports().query(**params).execute()
    columns = [
        by if by and header["name"] == _API_DIMENSIONS[by] else header["name"]
        for header in response.get("columnHeaders", [])
    ]
    rows = [dict(zip(columns, row, strict=True)) for row in response.get("rows") or []]
    if local_sort:
        rows.sort(key=lambda row: row[local_sort], reverse=sort.startswith("-"))
    return AnalyticsReport(since=start, until=end, columns=columns, rows=rows[:limit])


@operation(quota=0, idempotent=True, oauth=True)
def get_impressions(
    *,
    since: str | None = None,
    until: str | None = None,
    by: Literal["day", "video"] | None = None,
    videos: list[str] | None = None,
    limit: Annotated[int, Field(ge=1)] | None = None,
) -> ImpressionsReport:
    """Thumbnail impressions and click-through rate for your channel, which YouTube Analytics doesn't offer.

    They come from YouTube's daily bulk reports. The first call asks YouTube to start making them: the first
    ones arrive within two days and cover the 30 days before. YouTube keeps daily reports for 60 days, those
    first 30 days for 30. ctr is clicks per impression: 0.05 is 5%. Uses the YouTube Reporting API; enable it
    in the same Google Cloud project.

    Args:
        since: First day, inclusive: 2026-01-01, or 90d / 4w before until. Defaults to 28 days before until.
        until: Last day, inclusive: 2026-01-31, or 7d / 1w ago. Defaults to today.
        by: Break the numbers down by day or by video. Omit for totals.
        videos: Only these videos (IDs or URLs).
        limit: Maximum number of rows by video, most impressions first. 25 by default.
    """
    start, end = _days(since, until)
    wanted = set(unique_ids(videos, parse.video_id, "video ID or URL")) if videos else None
    reporting = client.reporting()
    job_id = _reach_job_id(reporting)
    note = None
    if job_id is None:
        reporting.jobs().create(body={"reportTypeId": REACH_REPORT, "name": "ytk impressions"}).execute()
        downloads = {}
        note = "YouTube started making these reports now. They arrive within two days, covering the 30 days before."
    else:
        downloads = _reach_downloads(reporting, job_id, start, end)
    impressions: Counter[str] = Counter()
    clicks: Counter[str] = Counter()
    for day, resource in downloads.items():
        text = reporting.media().download_media(resourceName=resource).execute().decode()
        for row in csv.DictReader(io.StringIO(text)):
            if wanted is not None and row["video_id"] not in wanted:
                continue
            if by == "day":
                key = day.isoformat()
            elif by == "video":
                key = row["video_id"]
            else:
                key = ""
            shown = int(row["video_thumbnail_impressions"])
            impressions[key] += shown
            clicks[key] += shown * float(row["video_thumbnail_impressions_ctr"])
    keys = sorted(impressions) if by == "day" else [key for key, _ in impressions.most_common()]
    if by == "video":
        keys = keys[: limit or 25]
    return ImpressionsReport(
        since=start,
        until=end,
        columns=[*([by] if by else []), "impressions", "ctr"],
        rows=[
            {**({by: key} if by else {}), "impressions": impressions[key], "ctr": _ratio(clicks[key], impressions[key])}
            for key in keys
        ],
        missing_days=[day for day in _each_day(start, end) if day not in downloads],
        note=note,
    )


def _days(since: str | None, until: str | None) -> tuple[date, date]:
    today = datetime.now(PACIFIC).date()  # YouTube's reporting day
    end = parse.day(until, ago_from=today) if until else today
    start = parse.day(since, ago_from=end) if since else end - timedelta(days=DEFAULT_DAYS - 1)
    if start > end:
        raise InvalidRequest(f"since ({start}) is after until ({end}).")
    return start, end


def _each_day(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _ratio(part: float, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _reach_job_id(reporting: Resource) -> str | None:
    request = reporting.jobs().list()
    while request is not None:
        response = request.execute()
        for job in response.get("jobs", []):
            if job["reportTypeId"] == REACH_REPORT:
                return job["id"]
        request = reporting.jobs().list_next(request, response)
    return None


def _reach_downloads(reporting: Resource, job_id: str, start: date, end: date) -> dict[date, str]:
    """Each day's report as a media resource name. Of a day YouTube regenerated, only the newest report."""
    newest: dict[date, dict] = {}
    request = (
        reporting.jobs()
        .reports()
        .list(
            jobId=job_id,
            # Reports start at midnight Pacific, hours after midnight UTC, so UTC day bounds catch each day once.
            startTimeAtOrAfter=f"{start.isoformat()}T00:00:00Z",
            startTimeBefore=f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
        )
    )
    while request is not None:
        response = request.execute()
        for report in response.get("reports", []):
            day = datetime.fromisoformat(report["startTime"]).astimezone(PACIFIC).date()
            created = datetime.fromisoformat(report["createTime"])
            if day not in newest or created > datetime.fromisoformat(newest[day]["createTime"]):
                newest[day] = report
        request = reporting.jobs().reports().list_next(request, response)
    return {day: unquote(urlparse(r["downloadUrl"]).path.removeprefix("/v1/media/")) for day, r in newest.items()}
