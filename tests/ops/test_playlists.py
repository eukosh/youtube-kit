import pytest

from youtube_kit.core.errors import InvalidRequest, NotFound
from youtube_kit.core.ops import playlists

from ..fakes import CHANNEL_ID, playlist_item_resource, playlist_resource


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
    result = playlists.create_playlist("Mine", privacy="unlisted")
    assert (result.id, result.privacy) == ("PLnew", "unlisted")


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


@pytest.mark.parametrize(
    ("current", "method"), [([], "insert"), ([{"id": "img", "snippet": {"type": "hero"}}], "update")]
)
def test_set_playlist_thumbnail_inserts_or_replaces(api, tmp_path, current, method):
    image = tmp_path / "cover.png"
    image.write_bytes(b"png")
    images = api.oauth.playlistImages()
    images.list().execute.return_value = {"items": current}
    getattr(images, method)().execute.return_value = {"id": "img", "snippet": {"width": 2048, "height": 1152}}

    result = playlists.set_playlist_thumbnail("PL1", image)

    assert (result.image_id, result.width) == ("img", 2048)
    body = getattr(images, method).call_args.kwargs["body"]
    assert body["snippet"] == {"playlistId": "PL1", "type": "hero"}
    assert body.get("id") == (None if method == "insert" else "img")
