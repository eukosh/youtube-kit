import struct

import pytest

from youtube_kit.core.errors import InvalidRequest, NotFound, YouTubeError
from youtube_kit.core.ops import playlists

from ..fakes import CHANNEL_ID, http_error, playlist_item_resource, playlist_resource, video_item


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

    page = playlists.list_playlist_items("https://www.youtube.com/playlist?list=PL1", limit=1)

    assert page.items[0].published_at is None
    assert page.next_page_token == "next"
    assert api.public.playlistItems().list.call_args.kwargs["playlistId"] == "PL1"


def test_add_video_to_playlist(api):
    api.oauth.playlistItems().insert().execute.return_value = playlist_item_resource(position=3)

    result = playlists.add_video_to_playlist("PL1", "https://youtu.be/dQw4w9WgXcQ", position=3)

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
    result = playlists.create_playlist("Mine", language="en", privacy="unlisted")
    assert (result.id, result.privacy) == ("PLnew", "unlisted")


def test_create_playlist_copies_the_language_of_your_recent_uploads(api):
    api.oauth.channels().list().execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]
    }
    api.oauth.playlistItems().list().execute.return_value = {"items": [{"contentDetails": {"videoId": "v1"}}]}
    api.oauth.videos().list().execute.return_value = {"items": [video_item("v1", snippet={"defaultLanguage": "uk"})]}
    api.oauth.playlists().insert().execute.return_value = playlist_resource()

    playlists.create_playlist("Mine")
    copied = api.oauth.playlists().insert.call_args.kwargs["body"]["snippet"]
    api.oauth.channels().list.reset_mock()
    api.oauth.playlistItems().list.reset_mock()
    playlists.create_playlist("Mine", language="en")
    given = api.oauth.playlists().insert.call_args.kwargs["body"]["snippet"]

    assert copied["defaultLanguage"] == "uk"
    assert given["defaultLanguage"] == "en"
    api.oauth.channels().list.assert_not_called()  # nothing to copy when the language is given
    api.oauth.playlistItems().list.assert_not_called()


def test_list_playlists_defaults_to_mine(api):
    api.oauth.playlists().list().execute.return_value = {"items": [playlist_resource()]}

    [playlist] = playlists.list_playlists().items

    assert (playlist.title, playlist.item_count, playlist.privacy) == ("Mix", 4, "public")
    assert api.oauth.playlists().list.call_args.kwargs["mine"] is True


def test_list_playlists_of_a_channel_uses_public_data(api):
    api.public.playlists().list().execute.return_value = {"items": []}
    playlists.list_playlists(CHANNEL_ID)
    assert api.public.playlists().list.call_args.kwargs["channelId"] == CHANNEL_ID


def test_get_playlists_batches_by_50(api):
    api.public.playlists().list().execute.return_value = {"items": [playlist_resource()]}

    playlists.get_playlists([f"PL{i}" for i in range(51)])

    requests = [call.kwargs for call in api.public.playlists().list.call_args_list if call.kwargs]
    assert [len(request["id"].split(",")) for request in requests] == [50, 1]


def test_update_playlist_keeps_other_fields_and_touches_status_only_when_asked(api):
    current = playlist_resource(localized={"title": "x"}, tags=["t"])
    current["status"]["podcastStatus"] = "enabled"
    api.oauth.playlists().list().execute.return_value = {"items": [current]}
    api.oauth.playlists().update().execute.return_value = playlist_resource(title="New")

    playlists.update_playlist("PL1", title="New")

    call = api.oauth.playlists().update.call_args.kwargs
    assert call["part"] == "snippet"
    assert call["body"] == {"id": "PL1", "snippet": {"title": "New", "description": "Songs", "tags": ["t"]}}

    playlists.update_playlist("PL1", privacy="private")

    call = api.oauth.playlists().update.call_args.kwargs
    assert call["part"] == "snippet,status"
    assert call["body"]["status"] == {"privacyStatus": "private", "podcastStatus": "enabled"}
    assert call["body"]["snippet"]["title"] == "Mix"

    playlists.update_playlist("PL1", language="de")

    assert api.oauth.playlists().update.call_args.kwargs["body"]["snippet"]["defaultLanguage"] == "de"


def test_remove_from_playlist_removes_every_occurrence(api):
    api.oauth.playlistItems().list().execute.return_value = {"items": [{"id": "a"}, {"id": "b"}]}

    result = playlists.remove_from_playlist("PL1", "dQw4w9WgXcQ")

    assert result.removed == 2
    deleted = [call.kwargs["id"] for call in api.oauth.playlistItems().delete.call_args_list if call.kwargs]
    assert deleted == ["a", "b"]
    assert api.oauth.playlistItems().list.call_args.kwargs["videoId"] == "dQw4w9WgXcQ"


def test_remove_from_playlist_is_idempotent(api):
    api.oauth.playlistItems().list().execute.return_value = {"items": []}
    assert playlists.remove_from_playlist("PL1", "dQw4w9WgXcQ").removed == 0


def _entries(*video_ids, token=None):
    items = [{"id": f"item-{v}", "snippet": {"resourceId": {"videoId": v}}} for v in video_ids]
    return {"items": items, "nextPageToken": token} if token else {"items": items}


VIDEO_NOT_FOUND = http_error(404, "videoNotFound", "Video not found.")


def test_remove_from_playlist_finds_a_deleted_video_by_reading_the_playlist(api):
    # YouTube rejects the videoId filter once the video is deleted, though the playlist still holds it.
    api.oauth.playlistItems().list().execute.side_effect = [
        VIDEO_NOT_FOUND,
        _entries("gKcKEGRfoAM", "7A22uuMVA6w", token="next"),
        _entries("7A22uuMVA6w"),
    ]

    result = playlists.remove_from_playlist("PL1", "7A22uuMVA6w")

    assert result.removed == 2
    deleted = [call.kwargs["id"] for call in api.oauth.playlistItems().delete.call_args_list if call.kwargs]
    assert deleted == ["item-7A22uuMVA6w", "item-7A22uuMVA6w"]
    scan = api.oauth.playlistItems().list.call_args.kwargs
    assert (scan["part"], scan["pageToken"]) == ("snippet", "next")
    assert "videoId" not in scan


def test_remove_from_playlist_of_a_video_in_no_entry_removes_nothing(api):
    api.oauth.playlistItems().list().execute.side_effect = [VIDEO_NOT_FOUND, _entries("gKcKEGRfoAM")]

    assert playlists.remove_from_playlist("PL1", "7A22uuMVA6w").removed == 0
    api.oauth.playlistItems().delete.assert_not_called()


def test_remove_from_playlist_raises_other_errors_without_reading_the_playlist(api):
    items = api.oauth.playlistItems()
    items.list().execute.side_effect = http_error(404, "playlistNotFound", "Playlist not found.")
    items.list.reset_mock()

    with pytest.raises(NotFound):
        playlists.remove_from_playlist("PL1", "7A22uuMVA6w")
    assert items.list.call_count == 1


def test_move_in_playlist_does_not_read_the_playlist_for_a_deleted_video(api):
    items = api.oauth.playlistItems()
    items.list().execute.side_effect = VIDEO_NOT_FOUND
    items.list.reset_mock()

    with pytest.raises(NotFound):
        playlists.move_in_playlist("PL1", "7A22uuMVA6w", position=0)
    assert items.list.call_count == 1


def test_move_in_playlist(api):
    api.oauth.playlistItems().list().execute.return_value = {"items": [{"id": "item1"}]}
    api.oauth.playlistItems().update().execute.return_value = playlist_item_resource(position=0)

    assert playlists.move_in_playlist("PL1", "dQw4w9WgXcQ", position=0).position == 0

    body = api.oauth.playlistItems().update.call_args.kwargs["body"]
    assert body["id"] == "item1"
    assert body["snippet"]["position"] == 0


@pytest.mark.parametrize(("items", "error"), [([], NotFound), ([{"id": "a"}, {"id": "b"}], InvalidRequest)])
def test_move_in_playlist_needs_exactly_one_occurrence(api, items, error):
    api.oauth.playlistItems().list().execute.return_value = {"items": items}
    with pytest.raises(error):
        playlists.move_in_playlist("PL1", "dQw4w9WgXcQ", position=0)


def _png(path, width: int, height: int):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height))
    return path


@pytest.mark.parametrize("current", [[], [{"id": "img", "snippet": {"type": "hero"}}]])
def test_set_playlist_thumbnail_replaces_by_deleting_first(api, tmp_path, current):
    images = api.oauth.playlistImages()
    images.list().execute.return_value = {"items": current}
    images.insert().execute.return_value = {"id": "img", "snippet": {"width": 1024, "height": 1024}}

    result = playlists.set_playlist_thumbnail("PL1", _png(tmp_path / "cover.png", 1024, 1024))

    assert (result.image_id, result.width) == ("img", 1024)
    assert images.insert.call_args.kwargs["body"] == {"snippet": {"playlistId": "PL1", "type": "hero"}}
    assert [c.kwargs for c in images.delete.call_args_list if c.kwargs] == [{"id": "img"} for _ in current]
    images.update.assert_not_called()


def test_set_playlist_thumbnail_refuses_non_square_before_touching_the_current_image(api, tmp_path):
    with pytest.raises(InvalidRequest, match="is 1280x720"):
        playlists.set_playlist_thumbnail("PL1", _png(tmp_path / "cover.png", 1280, 720))
    api.oauth.playlistImages().delete.assert_not_called()


@pytest.mark.parametrize(("current", "removed"), [([], False), ([{"id": "img", "snippet": {"type": "hero"}}], True)])
def test_set_playlist_thumbnail_explains_a_failed_insert(api, tmp_path, current, removed):
    image = tmp_path / "cover.jpg"
    image.write_bytes(b"not a real jpeg")
    images = api.oauth.playlistImages()
    images.list().execute.return_value = {"items": current}
    images.insert().execute.side_effect = http_error(500, "INVALID_ASPECT_RATIO", "Internal error encountered.")

    with pytest.raises(InvalidRequest, match="must be square") as caught:
        playlists.set_playlist_thumbnail("PL1", image)
    assert ("previous thumbnail was already removed" in str(caught.value)) is removed


def test_set_playlist_thumbnail_right_after_setting_one_says_to_wait(api, tmp_path):
    images = api.oauth.playlistImages()
    images.list().execute.return_value = {"items": []}
    images.insert().execute.side_effect = http_error(500, "IMAGE_TYPE_ALREADY_EXISTS", "Internal error encountered.")

    with pytest.raises(YouTubeError, match="Try again in a minute"):
        playlists.set_playlist_thumbnail("PL1", _png(tmp_path / "cover.png", 512, 512))
