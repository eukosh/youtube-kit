from unittest.mock import MagicMock

from youtube_kit.core.pagination import collect


def _pages(*responses):
    request = MagicMock()
    request.return_value.execute.side_effect = list(responses)
    return request


def _page(n: int, token: str | None, total: int = 120) -> dict:
    return {"items": [{"n": i} for i in range(n)], "nextPageToken": token, "pageInfo": {"totalResults": total}}


def test_requests_only_what_is_missing_so_the_token_stays_exact():
    request = _pages(_page(50, "t2"), _page(25, "t3"))
    page = collect(request, limit=75, page_token=None, to_item=lambda item: item["n"])

    assert len(page.items) == 75
    assert page.next_page_token == "t3"
    assert page.total_results == 120
    sizes = [call.kwargs["maxResults"] for call in request.call_args_list]
    assert sizes == [50, 25]
    assert "pageToken" not in request.call_args_list[0].kwargs
    assert request.call_args_list[1].kwargs["pageToken"] == "t2"


def test_stops_at_the_end_of_the_list():
    request = _pages(_page(50, "t2"), _page(10, None))
    page = collect(request, limit=500, page_token=None, to_item=lambda item: item)

    assert len(page.items) == 60
    assert page.next_page_token is None


def test_resumes_from_a_page_token():
    request = _pages(_page(5, None))
    collect(request, limit=5, page_token="resume", to_item=lambda item: item)

    assert request.call_args.kwargs == {"maxResults": 5, "pageToken": "resume"}


def test_short_pages_keep_fetching_until_the_limit():
    request = _pages(_page(3, "t2"), _page(2, "t3"))
    page = collect(request, limit=5, page_token=None, to_item=lambda item: item)

    assert len(page.items) == 5
    assert [call.kwargs["maxResults"] for call in request.call_args_list] == [5, 2]
