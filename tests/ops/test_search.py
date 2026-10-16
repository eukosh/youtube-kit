from youtube_kit.core.ops import search

from ..fakes import CHANNEL_ID, channel_item


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

    page = search.search("cats", kind="playlist", channel="@channel", since="2026-01-01")

    hit = page.items[0]
    assert (hit.id, hit.kind, hit.url) == ("PL1", "playlist", "https://www.youtube.com/playlist?list=PL1")
    params = api.public.search().list.call_args.kwargs
    assert params["channelId"] == CHANNEL_ID
    assert params["publishedAfter"] == "2026-01-01T00:00:00Z"
    assert api.public.channels().list.call_args.kwargs["forHandle"] == "@channel"


def test_search_skips_channel_lookup_for_ids(api):
    api.public.search().list().execute.return_value = {"items": []}
    search.search("cats", channel=CHANNEL_ID)
    api.public.channels.assert_not_called()
