from unittest.mock import MagicMock

import pytest

from youtube_kit.core import progress
from youtube_kit.core.errors import Forbidden, InvalidRequest, NotFound, TimedOut
from youtube_kit.core.ops import videos

from ..fakes import video_item


def test_get_videos_parses_urls_dedupes_and_types_stats(api):
    api.public.videos().list().execute.return_value = {"items": [video_item()]}

    [video] = videos.get_videos(["dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"])

    assert api.public.videos().list.call_args.kwargs["id"] == "dQw4w9WgXcQ"
    assert video.stats.views == 1000
    assert video.duration_seconds == 3723
    assert video.published_at.year == 2026


def test_get_videos_batches_by_50(api):
    api.public.videos().list().execute.return_value = {"items": [video_item()]}
    ids = [f"{i:011d}" for i in range(120)]

    videos.get_videos(ids)

    requests = [call.kwargs for call in api.public.videos().list.call_args_list if call.kwargs]
    batches = [len(request["id"].split(",")) for request in requests]
    assert batches == [50, 50, 20]


def test_get_videos_handles_hidden_counts(api):
    item = video_item(statistics={"viewCount": "7"})
    api.public.videos().list().execute.return_value = {"items": [item]}

    stats = videos.get_videos(["dQw4w9WgXcQ"])[0].stats

    assert (stats.views, stats.likes, stats.comments) == (7, None, None)


def test_get_videos_requires_input(api):
    with pytest.raises(InvalidRequest):
        videos.get_videos([])


def test_get_videos_not_found_when_nothing_matches(api):
    # Any 11-character string looks like an ID, so the API is the only judge.
    api.public.videos().list().execute.return_value = {"items": []}
    with pytest.raises(NotFound, match="cats-videos"):
        videos.get_videos(["cats-videos"])


def test_list_video_categories_keeps_assignable_only(api):
    api.public.videoCategories().list().execute.return_value = {
        "items": [
            {"id": "22", "snippet": {"title": "People & Blogs", "assignable": True}},
            {"id": "18", "snippet": {"title": "Short Movies", "assignable": False}},
        ]
    }
    assert [c.id for c in videos.list_video_categories(region="DE")] == ["22"]
    assert api.public.videoCategories().list.call_args.kwargs["regionCode"] == "DE"


def test_update_video_changes_only_given_fields(api):
    current = video_item(status={"privacyStatus": "private", "publishAt": "2026-05-01T00:00:00Z"})
    api.oauth.videos().list().execute.return_value = {"items": [current]}
    api.oauth.videos().update().execute.return_value = current

    videos.update_video("https://youtu.be/dQw4w9WgXcQ", tags=[], privacy="public")

    body = api.oauth.videos().update.call_args.kwargs["body"]
    assert body["snippet"]["tags"] == []
    assert body["snippet"]["title"] == "Title"
    assert body["status"] == {"privacyStatus": "public"}  # going public cancels the schedule


def test_update_video_rejects_schedule_on_public_video(api):
    api.oauth.videos().list().execute.return_value = {"items": [video_item()]}
    with pytest.raises(InvalidRequest, match="private"):
        videos.update_video("dQw4w9WgXcQ", publish_at="2026-06-01")


def test_update_video_not_found(api):
    api.oauth.videos().list().execute.return_value = {"items": []}
    with pytest.raises(NotFound):
        videos.update_video("dQw4w9WgXcQ", title="x")


def test_upload_video_reports_progress(api, tmp_path):
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x" * 1000)
    request = api.oauth.videos().insert()
    request.next_chunk.side_effect = [
        (MagicMock(resumable_progress=400), None),
        (None, {"id": "NEWVIDEO123", "status": {"privacyStatus": "private"}}),
    ]
    reports = []

    with progress.reporting_to(lambda done, total: reports.append((done, total))):
        result = videos.upload_video(file, title="Hi", publish_at="2026-06-01T12:00:00+00:00")

    assert result.id == "NEWVIDEO123"
    assert reports == [(400, 1000), (1000, 1000)]
    body = api.oauth.videos().insert.call_args.kwargs["body"]
    assert body["status"]["publishAt"] == "2026-06-01T12:00:00Z"


def test_upload_video_validates_before_calling_the_api(api, tmp_path):
    with pytest.raises(InvalidRequest, match="File not found"):
        videos.upload_video(tmp_path / "missing.mp4", title="x")
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x")
    with pytest.raises(InvalidRequest, match="private"):
        videos.upload_video(file, title="x", privacy="public", publish_at="2026-06-01")
    api.oauth.videos().insert.assert_not_called()


def test_set_thumbnail_rejects_large_files(api, tmp_path):
    image = tmp_path / "big.jpg"
    image.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(InvalidRequest, match="2 MB"):
        videos.set_thumbnail("dQw4w9WgXcQ", image)


def test_update_video_sends_only_writable_fields_and_drops_stale_schedule(api):
    # A schedule that already fired leaves publishAt behind on a now-public video.
    current = video_item(status={"privacyStatus": "public", "publishAt": "2025-01-01T00:00:00Z", "uploadStatus": "x"})
    current["snippet"]["localized"] = {"title": "Title"}
    api.oauth.videos().list().execute.return_value = {"items": [current]}
    api.oauth.videos().update().execute.return_value = current

    videos.update_video("dQw4w9WgXcQ", title="New", made_for_kids=False)

    body = api.oauth.videos().update.call_args.kwargs["body"]
    assert body["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    assert set(body["snippet"]) == {"title", "description", "tags", "categoryId"}
    assert body["snippet"]["title"] == "New"


def test_upload_retries_transient_chunk_failures(api, tmp_path):
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x")
    request = api.oauth.videos().insert()
    request.next_chunk.return_value = (None, {"id": "NEWVIDEO123"})

    videos.upload_video(file, title="Hi")

    assert request.next_chunk.call_args.kwargs["num_retries"] > 0


def test_set_thumbnail_rejects_non_images(api, tmp_path):
    image = tmp_path / "thumb.gif"
    image.write_bytes(b"x")
    with pytest.raises(InvalidRequest, match=r"\.jpg or \.png"):
        videos.set_thumbnail("dQw4w9WgXcQ", image)


def test_set_thumbnail_sends_explicit_mimetype(api, tmp_path):
    image = tmp_path / "thumb.png"
    image.write_bytes(b"x")
    api.oauth.thumbnails().set().execute.return_value = {"items": [{"high": {"url": "https://i.ytimg.com/x.png"}}]}

    result = videos.set_thumbnail("dQw4w9WgXcQ", image)

    assert result.thumbnail_url == "https://i.ytimg.com/x.png"
    assert api.oauth.thumbnails().set.call_args.kwargs["media_body"].mimetype() == "image/png"


@pytest.fixture
def clock(monkeypatch):
    """Fake time for polling: sleeping advances the clock instantly."""
    now = [0.0]
    monkeypatch.setattr(videos.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(videos.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    return now


def processing(status: str, **progress_fields) -> dict:
    details = {"processingStatus": status, "processingProgress": progress_fields}
    return {"items": [{"id": "dQw4w9WgXcQ", "processingDetails": details}]}


def test_processing_status_without_wait_checks_once(api, clock):
    api.oauth.videos().list().execute.return_value = processing("processing", partsTotal="10", partsProcessed="3")

    status = videos.get_processing_status("dQw4w9WgXcQ")

    assert (status.status, status.parts_processed, status.parts_total) == ("processing", 3, 10)
    assert clock[0] == 0


def test_processing_status_waits_and_reports_progress(api, clock):
    api.oauth.videos().list().execute.side_effect = [
        processing("processing", partsTotal="10", partsProcessed="5"),
        processing("succeeded"),
    ]
    updates = []

    with progress.reporting_to(lambda done, total: updates.append((done, total))):
        status = videos.get_processing_status("dQw4w9WgXcQ", wait=True, timeout=60)

    assert status.status == "succeeded"
    assert updates == [(5, 10)]
    assert clock[0] == videos.POLL_SECONDS


def test_processing_status_times_out(api, clock):
    api.oauth.videos().list().execute.return_value = processing("processing")
    with pytest.raises(TimedOut, match="still processing") as caught:
        videos.get_processing_status("dQw4w9WgXcQ", wait=True, timeout=25)
    assert caught.value.details["status"] == "processing"
    assert clock[0] == 25


def test_processing_status_is_owner_only(api):
    api.oauth.videos().list().execute.return_value = {"items": [{"id": "dQw4w9WgXcQ"}]}
    with pytest.raises(Forbidden, match="owner"):
        videos.get_processing_status("dQw4w9WgXcQ")


def test_rate_video(api):
    assert videos.rate_video("https://youtu.be/dQw4w9WgXcQ", "like").rating == "like"
    assert api.oauth.videos().rate.call_args.kwargs == {"id": "dQw4w9WgXcQ", "rating": "like"}


def test_get_my_ratings_reports_unrated_as_none(api):
    api.oauth.videos().getRating().execute.return_value = {
        "items": [{"videoId": "dQw4w9WgXcQ", "rating": "dislike"}, {"videoId": "abcdefghijk", "rating": "unspecified"}]
    }
    ratings = videos.get_my_ratings(["dQw4w9WgXcQ", "abcdefghijk"])
    assert [(r.video_id, r.rating) for r in ratings] == [("dQw4w9WgXcQ", "dislike"), ("abcdefghijk", "none")]
