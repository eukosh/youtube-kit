from unittest.mock import MagicMock

import pytest

from youtube_kit import core
from youtube_kit.core import progress
from youtube_kit.core.errors import InvalidRequest, NotFound

from .fakes import channel_item, video_item

CHANNEL_ID = "UC" + "a" * 22


# ---------- search ----------


def test_search_maps_hits_and_normalises_inputs(api):
    api.public.channels().list().execute.return_value = {"items": [channel_item()]}
    api.public.search().list().execute.return_value = {
        "items": [
            {
                "id": {"kind": "youtube#playlist", "playlistId": "PL1"},
                "snippet": {
                    "title": "T",
                    "description": "D",
                    "channelId": CHANNEL_ID,
                    "channelTitle": "C",
                    "publishedAt": "2026-01-01T00:00:00Z",
                },
            }
        ],
        "pageInfo": {"totalResults": 1},
    }

    page = core.search("cats", kind="playlist", channel="@channel", published_after="2026-01-01")

    hit = page.items[0]
    assert (hit.id, hit.kind, hit.url) == ("PL1", "playlist", "https://www.youtube.com/playlist?list=PL1")
    params = api.public.search().list.call_args.kwargs
    assert params["channelId"] == CHANNEL_ID
    assert params["publishedAfter"] == "2026-01-01T00:00:00Z"
    assert api.public.channels().list.call_args.kwargs["forHandle"] == "@channel"


def test_search_skips_channel_lookup_for_ids(api):
    api.public.search().list().execute.return_value = {"items": []}
    core.search("cats", channel=CHANNEL_ID)
    api.public.channels.assert_not_called()


# ---------- videos ----------


def test_get_videos_parses_urls_dedupes_and_types_stats(api):
    api.public.videos().list().execute.return_value = {"items": [video_item()]}

    videos = core.get_videos(["dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"])

    assert api.public.videos().list.call_args.kwargs["id"] == "dQw4w9WgXcQ"
    video = videos[0]
    assert video.stats.views == 1000
    assert video.duration_seconds == 3723
    assert video.published_at.year == 2026


def test_get_videos_batches_by_50(api):
    api.public.videos().list().execute.return_value = {"items": [video_item()]}
    ids = [f"{i:011d}" for i in range(120)]

    core.get_videos(ids)

    requests = [call.kwargs for call in api.public.videos().list.call_args_list if call.kwargs]
    batches = [len(request["id"].split(",")) for request in requests]
    assert batches == [50, 50, 20]


def test_get_videos_handles_hidden_counts(api):
    item = video_item(statistics={"viewCount": "7"})
    api.public.videos().list().execute.return_value = {"items": [item]}

    stats = core.get_videos(["dQw4w9WgXcQ"])[0].stats

    assert (stats.views, stats.likes, stats.comments) == (7, None, None)


def test_get_videos_requires_input(api):
    with pytest.raises(InvalidRequest):
        core.get_videos([])


def test_get_videos_not_found_when_nothing_matches(api):
    # Any 11-character string looks like an ID, so the API is the only judge.
    api.public.videos().list().execute.return_value = {"items": []}
    with pytest.raises(NotFound, match="cats-videos"):
        core.get_videos(["cats-videos"])


def test_list_video_categories_keeps_assignable_only(api):
    api.public.videoCategories().list().execute.return_value = {
        "items": [
            {"id": "22", "snippet": {"title": "People & Blogs", "assignable": True}},
            {"id": "18", "snippet": {"title": "Short Movies", "assignable": False}},
        ]
    }
    assert [c.id for c in core.list_video_categories(region="DE")] == ["22"]
    assert api.public.videoCategories().list.call_args.kwargs["regionCode"] == "DE"


def test_update_video_changes_only_given_fields(api):
    current = video_item(status={"privacyStatus": "private", "publishAt": "2026-05-01T00:00:00Z"})
    api.oauth.videos().list().execute.return_value = {"items": [current]}
    api.oauth.videos().update().execute.return_value = current

    core.update_video("https://youtu.be/dQw4w9WgXcQ", tags=[], privacy="public")

    body = api.oauth.videos().update.call_args.kwargs["body"]
    assert body["snippet"]["tags"] == []
    assert body["snippet"]["title"] == "Title"
    assert body["status"] == {"privacyStatus": "public"}  # going public cancels the schedule


def test_update_video_rejects_schedule_on_public_video(api):
    api.oauth.videos().list().execute.return_value = {"items": [video_item()]}
    with pytest.raises(InvalidRequest, match="private"):
        core.update_video("dQw4w9WgXcQ", publish_at="2026-06-01")


def test_update_video_not_found(api):
    api.oauth.videos().list().execute.return_value = {"items": []}
    with pytest.raises(NotFound):
        core.update_video("dQw4w9WgXcQ", title="x")


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
        result = core.upload_video(file, title="Hi", publish_at="2026-06-01T12:00:00+00:00")

    assert result.id == "NEWVIDEO123"
    assert reports == [(400, 1000), (1000, 1000)]
    body = api.oauth.videos().insert.call_args.kwargs["body"]
    assert body["status"]["publishAt"] == "2026-06-01T12:00:00Z"


def test_upload_video_validates_before_calling_the_api(api, tmp_path):
    with pytest.raises(InvalidRequest, match="File not found"):
        core.upload_video(tmp_path / "missing.mp4", title="x")
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x")
    with pytest.raises(InvalidRequest, match="private"):
        core.upload_video(file, title="x", privacy="public", publish_at="2026-06-01")
    api.oauth.videos().insert.assert_not_called()


def test_set_thumbnail_rejects_large_files(api, tmp_path):
    image = tmp_path / "big.jpg"
    image.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(InvalidRequest, match="2 MB"):
        core.set_thumbnail("dQw4w9WgXcQ", image)


# ---------- channels ----------


@pytest.mark.parametrize(
    ("ref", "param", "value"),
    [
        (CHANNEL_ID, "id", CHANNEL_ID),
        ("channel", "forHandle", "@channel"),
        ("https://www.youtube.com/user/legacy", "forUsername", "legacy"),
    ],
)
def test_get_channel_lookup(api, ref, param, value):
    api.public.channels().list().execute.return_value = {"items": [channel_item()]}

    result = core.get_channel(ref)

    assert api.public.channels().list.call_args.kwargs[param] == value
    assert result.url == "https://www.youtube.com/@channel"
    assert result.stats.subscribers == 3


def test_get_channel_hidden_subscribers(api):
    item = channel_item()
    item["statistics"]["hiddenSubscriberCount"] = True
    api.public.channels().list().execute.return_value = {"items": [item]}
    assert core.get_channel(CHANNEL_ID).stats.subscribers is None


def test_get_channel_not_found(api):
    api.public.channels().list().execute.return_value = {"items": []}
    with pytest.raises(NotFound):
        core.get_channel("@nobody")


def test_get_my_channel_uses_oauth(api):
    api.oauth.channels().list().execute.return_value = {"items": [channel_item()]}
    assert core.get_my_channel().id == CHANNEL_ID
    assert api.oauth.channels().list.call_args.kwargs["mine"] is True


# ---------- playlists and comments ----------


def test_list_playlist_items(api):
    api.public.playlistItems().list().execute.return_value = {
        "items": [
            {
                "snippet": {"title": "Private video", "position": 0},
                "contentDetails": {"videoId": "dQw4w9WgXcQ"},
            }
        ],
        "nextPageToken": "next",
    }

    page = core.list_playlist_items("https://www.youtube.com/playlist?list=PL1", limit=1)

    assert page.items[0].published_at is None
    assert page.next_page_token == "next"
    assert api.public.playlistItems().list.call_args.kwargs["playlistId"] == "PL1"


def test_add_video_to_playlist(api):
    api.oauth.playlistItems().insert().execute.return_value = {"id": "item1", "snippet": {"position": 3}}

    result = core.add_video_to_playlist("PL1", "https://youtu.be/dQw4w9WgXcQ", position=3)

    assert result.position == 3
    snippet = api.oauth.playlistItems().insert.call_args.kwargs["body"]["snippet"]
    assert snippet == {
        "playlistId": "PL1",
        "resourceId": {"kind": "youtube#video", "videoId": "dQw4w9WgXcQ"},
        "position": 3,
    }


def test_create_playlist(api):
    api.oauth.playlists().insert().execute.return_value = {
        "id": "PLnew",
        "snippet": {"title": "Mine"},
        "status": {"privacyStatus": "unlisted"},
    }
    result = core.create_playlist("Mine", privacy="unlisted")
    assert (result.id, result.privacy) == ("PLnew", "unlisted")


def test_list_comments(api):
    api.public.commentThreads().list().execute.return_value = {
        "items": [
            {
                "snippet": {
                    "totalReplyCount": 2,
                    "topLevelComment": {
                        "id": "c1",
                        "snippet": {
                            "authorDisplayName": "A",
                            "textDisplay": "Nice",
                            "likeCount": 5,
                            "publishedAt": "2026-01-01T00:00:00Z",
                        },
                    },
                }
            }
        ]
    }

    page = core.list_comments("dQw4w9WgXcQ", order="time")

    assert (page.items[0].id, page.items[0].reply_count) == ("c1", 2)
    assert api.public.commentThreads().list.call_args.kwargs["order"] == "time"


# ---------- metadata ----------


def test_quota_note_is_part_of_the_published_docstring():
    assert "Quota: 100 units per page" in core.search.__doc__
    assert core.search.__doc__.index("Quota:") < core.search.__doc__.index("Args:")
    assert "Quota: 1600 units." in core.upload_video.__doc__


def test_update_video_sends_only_writable_fields_and_drops_stale_schedule(api):
    # A schedule that already fired leaves publishAt behind on a now-public video.
    current = video_item(status={"privacyStatus": "public", "publishAt": "2025-01-01T00:00:00Z", "uploadStatus": "x"})
    current["snippet"]["localized"] = {"title": "Title"}
    api.oauth.videos().list().execute.return_value = {"items": [current]}
    api.oauth.videos().update().execute.return_value = current

    core.update_video("dQw4w9WgXcQ", title="New", made_for_kids=False)

    body = api.oauth.videos().update.call_args.kwargs["body"]
    assert body["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    assert set(body["snippet"]) == {"title", "description", "tags", "categoryId"}
    assert body["snippet"]["title"] == "New"


def test_upload_retries_transient_chunk_failures(api, tmp_path):
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x")
    request = api.oauth.videos().insert()
    request.next_chunk.return_value = (None, {"id": "NEWVIDEO123"})

    core.upload_video(file, title="Hi")

    assert request.next_chunk.call_args.kwargs["num_retries"] > 0


def test_set_thumbnail_rejects_non_images(api, tmp_path):
    image = tmp_path / "thumb.gif"
    image.write_bytes(b"x")
    with pytest.raises(InvalidRequest, match=r"\.jpg or \.png"):
        core.set_thumbnail("dQw4w9WgXcQ", image)


def test_set_thumbnail_sends_explicit_mimetype(api, tmp_path):
    image = tmp_path / "thumb.png"
    image.write_bytes(b"x")
    api.oauth.thumbnails().set().execute.return_value = {"items": [{"high": {"url": "https://i.ytimg.com/x.png"}}]}

    result = core.set_thumbnail("dQw4w9WgXcQ", image)

    assert result.thumbnail_url == "https://i.ytimg.com/x.png"
    assert api.oauth.thumbnails().set.call_args.kwargs["media_body"].mimetype() == "image/png"
