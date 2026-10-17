from datetime import date, timedelta

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
