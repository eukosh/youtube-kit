import pytest

from youtube_kit.core.errors import NotFound
from youtube_kit.core.ops import channels

from ..fakes import CHANNEL_ID, channel_item


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

    result = channels.get_channel(ref)

    assert api.public.channels().list.call_args.kwargs[param] == value
    assert result.url == "https://www.youtube.com/@channel"
    assert result.stats.subscribers == 3


def test_get_channel_hidden_subscribers(api):
    item = channel_item()
    item["statistics"]["hiddenSubscriberCount"] = True
    api.public.channels().list().execute.return_value = {"items": [item]}
    assert channels.get_channel(CHANNEL_ID).stats.subscribers is None


def test_get_channel_not_found(api):
    api.public.channels().list().execute.return_value = {"items": []}
    with pytest.raises(NotFound):
        channels.get_channel("@nobody")


def test_get_channel_defaults_to_mine(api):
    api.oauth.channels().list().execute.return_value = {"items": [channel_item()]}
    assert channels.get_channel().id == CHANNEL_ID
    assert api.oauth.channels().list.call_args.kwargs["mine"] is True


def test_list_activities_maps_type_specific_details(api):
    api.oauth.activities().list().execute.return_value = {
        "items": [
            {
                "snippet": {
                    "type": "upload",
                    "publishedAt": "2026-01-01T00:00:00Z",
                    "title": "New",
                    "channelId": CHANNEL_ID,
                },
                "contentDetails": {"upload": {"videoId": "dQw4w9WgXcQ"}},
            },
            {
                "snippet": {
                    "type": "playlistItem",
                    "publishedAt": "2026-01-01T00:00:00Z",
                    "title": "Add",
                    "channelId": CHANNEL_ID,
                },
                "contentDetails": {
                    "playlistItem": {
                        "resourceId": {"kind": "youtube#video", "videoId": "abcdefghijk"},
                        "playlistId": "PL1",
                    }
                },
            },
        ]
    }

    upload, added = channels.list_activities(since="2026-01-01").items

    assert (upload.type, upload.video_id) == ("upload", "dQw4w9WgXcQ")
    assert (added.video_id, added.playlist_id) == ("abcdefghijk", "PL1")
    request = api.oauth.activities().list.call_args.kwargs
    assert (request["mine"], request["publishedAfter"]) == (True, "2026-01-01T00:00:00Z")
