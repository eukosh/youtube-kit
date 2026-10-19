from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from youtube_kit.core.errors import InvalidRequest
from youtube_kit.core.ops import analytics


def report(columns: list[str], rows: list[list]) -> dict:
    return {"columnHeaders": [{"name": name} for name in columns], "rows": rows}


def test_defaults_to_totals_for_the_last_28_days(api):
    api.analytics.reports().query().execute.return_value = report(["views", "likes"], [[120, 7]])

    result = analytics.get_analytics()

    assert result.rows == [{"views": 120, "likes": 7}]
    assert result.until - result.since == timedelta(days=27)
    request = api.analytics.reports().query.call_args.kwargs
    assert request["ids"] == "channel==MINE"
    assert request["metrics"].startswith("views,estimatedMinutesWatched")
    assert "dimensions" not in request


def test_breakdown_by_friendly_dimension_name(api):
    api.analytics.reports().query().execute.return_value = report(["deviceType", "views"], [["MOBILE", 3]])

    result = analytics.get_analytics(by="device", metrics=["views"], since="2026-01-01", until="2026-01-31")

    assert (result.columns, result.rows) == (["device", "views"], [{"device": "MOBILE", "views": 3}])
    request = api.analytics.reports().query.call_args.kwargs
    assert (request["dimensions"], request["startDate"], request["endDate"]) == (
        "deviceType",
        "2026-01-01",
        "2026-01-31",
    )


def test_by_video_gets_the_sort_and_row_cap_youtube_requires(api):
    api.analytics.reports().query().execute.return_value = report(["video", "views"], [])

    analytics.get_analytics(by="video", metrics=["likes", "views"], limit=500)

    request = api.analytics.reports().query.call_args.kwargs
    assert (request["sort"], request["maxResults"]) == ("-likes", 200)


def test_relative_since_counts_back_from_until(api):
    api.analytics.reports().query().execute.return_value = report(["views"], [])
    result = analytics.get_analytics(since="4w", until="2026-03-29")
    assert result.since == date(2026, 3, 1)


def test_monthly_breakdown_widens_to_whole_months(api):
    api.analytics.reports().query().execute.return_value = report(["month", "views"], [])
    result = analytics.get_analytics(by="month", since="2026-01-15", until="2026-02-10")
    assert (result.since, result.until) == (date(2026, 1, 1), date(2026, 2, 28))
    request = api.analytics.reports().query.call_args.kwargs
    assert (request["startDate"], request["endDate"], request["sort"]) == ("2026-01-01", "2026-02-01", "month")


@pytest.mark.parametrize(
    ("by", "metrics", "sort"),
    [
        ("country", analytics.DEFAULT_METRICS, "-views"),
        ("traffic-source", analytics.WATCH_METRICS, "-views"),
        ("age", ("viewerPercentage",), "-viewerPercentage"),
        ("sharing-service", ("shares",), "-shares"),
        ("content-type", analytics.DEFAULT_METRICS, "-views"),
        ("day", analytics.DEFAULT_METRICS, "day"),
    ],
)
def test_each_breakdown_defaults_to_metrics_youtube_accepts_and_a_useful_order(api, by, metrics, sort):
    api.analytics.reports().query().execute.return_value = report([], [])
    analytics.get_analytics(by=by)
    request = api.analytics.reports().query.call_args.kwargs
    assert (request["metrics"], request["sort"]) == (",".join(metrics), sort)


def test_video_filter_takes_urls(api):
    api.analytics.reports().query().execute.return_value = report(["views"], [])
    analytics.get_analytics(videos=["https://youtu.be/dQw4w9WgXcQ", "abcdefghijk"])
    assert api.analytics.reports().query.call_args.kwargs["filters"] == "video==dQw4w9WgXcQ,abcdefghijk"


def test_empty_report_has_no_rows(api):
    api.analytics.reports().query().execute.return_value = {"columnHeaders": [{"name": "views"}]}
    assert analytics.get_analytics().rows == []


@pytest.mark.parametrize(("since", "until"), [("2026-02-01", "2026-01-01"), ("last week", None)])
def test_bad_date_ranges(api, since, until):
    with pytest.raises(InvalidRequest):
        analytics.get_analytics(since=since, until=until)


def test_retention_needs_exactly_one_video(api):
    for videos in (None, ["dQw4w9WgXcQ", "abcdefghijk"]):
        with pytest.raises(InvalidRequest, match="exactly one video"):
            analytics.get_analytics(by="elapsed", videos=videos)
    api.analytics.reports().query.assert_not_called()


def test_retention_is_chronological_and_limited_locally_since_youtube_fails_with_maxresults(api):
    rows = [[0.01, 1.1, 0.4], [0.02, 1.0, 0.3], [0.03, 0.9, 0.3]]
    columns = ["elapsedVideoTimeRatio", "audienceWatchRatio", "relativeRetentionPerformance"]
    api.analytics.reports().query().execute.return_value = report(columns, rows)

    result = analytics.get_analytics(by="elapsed", videos=["dQw4w9WgXcQ"], limit=2)

    assert result.rows == [
        {"elapsed": 0.01, "audienceWatchRatio": 1.1, "relativeRetentionPerformance": 0.4},
        {"elapsed": 0.02, "audienceWatchRatio": 1.0, "relativeRetentionPerformance": 0.3},
    ]
    request = api.analytics.reports().query.call_args.kwargs
    assert (request["dimensions"], request["filters"]) == ("elapsedVideoTimeRatio", "video==dQw4w9WgXcQ")
    assert request["metrics"] == "audienceWatchRatio,relativeRetentionPerformance"
    assert "maxResults" not in request


def test_retention_is_sorted_here_because_youtube_ignores_sort_on_it(api):
    rows = [[0.01, 1.1, 0.4], [0.02, 0.8, 0.3], [0.03, 0.9, 0.3]]
    columns = ["elapsedVideoTimeRatio", "audienceWatchRatio", "relativeRetentionPerformance"]
    api.analytics.reports().query().execute.return_value = report(columns, rows)

    result = analytics.get_analytics(by="elapsed", videos=["dQw4w9WgXcQ"], sort="audienceWatchRatio", limit=2)

    assert [row["elapsed"] for row in result.rows] == [0.02, 0.03]
    assert "sort" not in api.analytics.reports().query.call_args.kwargs
    with pytest.raises(InvalidRequest, match="audienceWatchRatio, relativeRetentionPerformance"):
        analytics.get_analytics(by="elapsed", videos=["dQw4w9WgXcQ"], sort="-views")


def test_traffic_source_detail_needs_its_source_and_gets_youtubes_sort_and_cap(api):
    with pytest.raises(InvalidRequest, match="traffic_source"):
        analytics.get_analytics(by="traffic-source-detail")

    api.analytics.reports().query().execute.return_value = report([], [])
    analytics.get_analytics(by="traffic-source-detail", traffic_source="yt_search", limit=100)

    request = api.analytics.reports().query.call_args.kwargs
    assert (request["dimensions"], request["filters"], request["sort"], request["maxResults"]) == (
        "insightTrafficSourceDetail",
        "insightTrafficSourceType==YT_SEARCH",
        "-views",
        25,
    )


def test_filters_combine(api):
    api.analytics.reports().query().execute.return_value = report([], [])
    analytics.get_analytics(by="day", videos=["dQw4w9WgXcQ"], content_type="shorts", country="us")
    assert (
        api.analytics.reports().query.call_args.kwargs["filters"]
        == "video==dQw4w9WgXcQ;creatorContentType==shorts;country==US"
    )


@pytest.mark.parametrize("sort", ["-traffic-source", "-traffic_source"])
def test_sort_takes_friendly_dimension_names_as_mcp_callers_write_them(api, sort):
    api.analytics.reports().query().execute.return_value = report([], [])
    analytics.get_analytics(by="traffic-source", sort=sort)
    assert api.analytics.reports().query.call_args.kwargs["sort"] == "-insightTrafficSourceType"


def test_sort_leaves_metric_names_as_given_so_youtubes_error_names_them(api):
    api.analytics.reports().query().execute.return_value = report([], [])
    analytics.get_analytics(by="video", sort="-estimated_minutes_watched")
    assert api.analytics.reports().query.call_args.kwargs["sort"] == "-estimated_minutes_watched"


def test_traffic_source_is_refused_outside_its_breakdown_which_youtube_rejects(api):
    with pytest.raises(InvalidRequest, match="only with by traffic-source-detail"):
        analytics.get_analytics(by="day", traffic_source="YT_SEARCH")
    api.analytics.reports().query.assert_not_called()


def reach_api(api, jobs: list[dict], reports: list[dict] | None = None, files: dict[str, str] | None = None):
    """The Reporting API with these jobs, reports and CSV files (by media resource name)."""
    reporting = api.reporting
    reporting.jobs().list().execute.return_value = {"jobs": jobs}
    reporting.jobs().list_next.return_value = None
    reporting.jobs().reports().list().execute.return_value = {"reports": reports or []}
    reporting.jobs().reports().list_next.return_value = None
    reporting.media().download_media.side_effect = lambda resourceName: MagicMock(
        execute=MagicMock(return_value=(files or {})[resourceName].encode())
    )
    return reporting


def reach_report(day: str, name: str, created: str = "2026-10-03T10:00:00Z") -> dict:
    # Daily reports start at midnight Pacific time.
    return {
        "startTime": f"{day}T07:00:00Z",
        "createTime": created,
        "downloadUrl": f"https://youtubereporting.googleapis.com/v1/media/CHANNEL_ID/jobs/J/reports/{name}?alt=media",
    }


def reach_csv(*rows: tuple[str, str, int, float]) -> str:
    lines = ["date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr"]
    return "\n".join(lines + [f"{day},UC1,{video},{shown},{ctr}" for day, video, shown, ctr in rows]) + "\n"


def test_first_impressions_call_starts_youtubes_reports(api):
    reporting = reach_api(api, jobs=[{"id": "other", "reportTypeId": "channel_basic_a2"}])

    result = analytics.get_impressions(since="2026-10-01", until="2026-10-02")

    assert reporting.jobs().create.call_args.kwargs["body"]["reportTypeId"] == "channel_reach_basic_a1"
    assert (result.rows, result.missing_days) == ([], [date(2026, 10, 1), date(2026, 10, 2)])
    assert "within two days" in result.note


def test_impressions_weight_ctr_by_impressions_and_use_regenerated_reports(api):
    files = {
        "CHANNEL_ID/jobs/J/reports/old": reach_csv(("20261001", "aaaaaaaaaaa", 1000, 0.5)),
        "CHANNEL_ID/jobs/J/reports/new": reach_csv(
            ("20261001", "aaaaaaaaaaa", 100, 0.1), ("20261001", "bbbbbbbbbbb", 300, 0.02)
        ),
        "CHANNEL_ID/jobs/J/reports/day2": reach_csv(("20261002", "aaaaaaaaaaa", 100, 0.05)),
    }
    reports = [
        reach_report("2026-10-01", "old", created="2026-10-03T10:00:00Z"),
        reach_report("2026-10-01", "new", created="2026-10-05T10:00:00Z"),
        reach_report("2026-10-02", "day2"),
    ]
    reporting = reach_api(
        api, jobs=[{"id": "J", "reportTypeId": "channel_reach_basic_a1"}], reports=reports, files=files
    )

    totals = analytics.get_impressions(since="2026-10-01", until="2026-10-03")
    by_video = analytics.get_impressions(since="2026-10-01", until="2026-10-03", by="video")
    by_day = analytics.get_impressions(since="2026-10-01", until="2026-10-03", by="day", videos=["aaaaaaaaaaa"])

    # (100 * 0.1 + 300 * 0.02 + 100 * 0.05) / 500 clicks per impression
    assert totals.rows == [{"impressions": 500, "ctr": 0.042}]
    assert totals.missing_days == [date(2026, 10, 3)]
    assert by_video.rows == [
        {"video": "bbbbbbbbbbb", "impressions": 300, "ctr": 0.02},
        {"video": "aaaaaaaaaaa", "impressions": 200, "ctr": 0.075},
    ]
    assert by_day.rows == [
        {"day": "2026-10-01", "impressions": 100, "ctr": 0.1},
        {"day": "2026-10-02", "impressions": 100, "ctr": 0.05},
    ]
    reporting.jobs().create.assert_not_called()
    request = reporting.jobs().reports().list.call_args.kwargs
    assert (request["startTimeAtOrAfter"], request["startTimeBefore"]) == (
        "2026-10-01T00:00:00Z",
        "2026-10-04T00:00:00Z",
    )


def test_impressions_follow_pages_for_the_job_and_regenerated_reports(api):
    files = {
        "CHANNEL_ID/jobs/J/reports/old": reach_csv(("20261001", "aaaaaaaaaaa", 1000, 0.5)),
        "CHANNEL_ID/jobs/J/reports/new": reach_csv(("20261001", "aaaaaaaaaaa", 10, 0.1)),
    }
    reporting = reach_api(api, jobs=[{"id": "other", "reportTypeId": "channel_basic_a2"}], files=files)
    second_jobs, second_reports = MagicMock(), MagicMock()
    second_jobs.execute.return_value = {"jobs": [{"id": "J", "reportTypeId": "channel_reach_basic_a1"}]}
    second_reports.execute.return_value = {
        "reports": [reach_report("2026-10-01", "new", created="2026-10-09T10:00:00Z")]
    }
    reporting.jobs().list_next.side_effect = [second_jobs, None]
    reporting.jobs().reports().list().execute.return_value = {"reports": [reach_report("2026-10-01", "old")]}
    reporting.jobs().reports().list_next.side_effect = [second_reports, None]

    result = analytics.get_impressions(since="2026-10-01", until="2026-10-01")

    assert result.rows == [{"impressions": 10, "ctr": 0.1}]
    reporting.jobs().create.assert_not_called()


def test_impressions_by_video_are_limited_to_the_most_seen(api):
    files = {"CHANNEL_ID/jobs/J/reports/d": reach_csv(*[("20261001", f"video{n:06d}", n, 0.1) for n in range(1, 31)])}
    reach_api(
        api,
        jobs=[{"id": "J", "reportTypeId": "channel_reach_basic_a1"}],
        reports=[reach_report("2026-10-01", "d")],
        files=files,
    )

    rows = analytics.get_impressions(since="2026-10-01", until="2026-10-01", by="video").rows

    assert [row["impressions"] for row in rows] == list(range(30, 5, -1))
