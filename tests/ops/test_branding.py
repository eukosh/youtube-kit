import pytest

from youtube_kit.core.errors import InvalidRequest
from youtube_kit.core.ops import branding

from ..fakes import CHANNEL_ID


def branded(**settings) -> dict:
    return {
        "id": CHANNEL_ID,
        "brandingSettings": {
            "channel": {"title": "Mine", "description": "About", "keywords": 'tech "home lab" don\'t', **settings},
            "image": {"bannerExternalUrl": "https://banner"},
            "hints": [{"property": "x", "value": "y"}],
        },
    }


@pytest.fixture
def branding_api(api):
    api.oauth.channels().list().execute.return_value = {"items": [branded(moderateComments=True)]}
    api.oauth.channels().update().execute.return_value = branded()
    return api.oauth.channels()


def sent(channels) -> dict:
    return channels.update.call_args.kwargs["body"]["brandingSettings"]


def test_update_channel_keeps_writable_settings_and_drops_the_rest(branding_api):
    result = branding.update_channel(
        description="New", keywords=["ai", "home lab"], trailer="https://youtu.be/dQw4w9WgXcQ"
    )

    body = sent(branding_api)
    assert body["channel"] == {
        "description": "New",
        "keywords": 'ai "home lab"',
        "unsubscribedTrailer": "dQw4w9WgXcQ",
    }
    assert body["image"] == {"bannerExternalUrl": "https://banner"}
    assert "hints" not in body
    assert result.keywords == ["tech", "home lab", "don't"]


def test_empty_keywords_clear_them(branding_api):
    branding.update_channel(keywords=[])
    assert sent(branding_api)["channel"]["keywords"] == ""


def test_set_channel_banner_uploads_then_points_branding_at_it(api, branding_api, tmp_path):
    image = tmp_path / "banner.jpg"
    image.write_bytes(b"jpg")
    api.oauth.channelBanners().insert().execute.return_value = {"url": "https://new-banner"}

    branding.set_channel_banner(image)

    assert sent(branding_api)["image"] == {"bannerExternalUrl": "https://new-banner"}


def test_set_watermark(api, my_channel, tmp_path):
    image = tmp_path / "logo.png"
    image.write_bytes(b"png")

    result = branding.set_watermark(image, corner="top-left", start=15, from_end=True, duration=10)

    call = api.oauth.watermarks().set.call_args.kwargs
    assert call["channelId"] == CHANNEL_ID
    assert call["body"] == {
        "position": {"type": "corner", "cornerPosition": "topLeft"},
        "timing": {"type": "offsetFromEnd", "offsetMs": "15000", "durationMs": "10000"},
    }
    assert (result.active, result.corner) == (True, "top-left")


def test_remove_watermark(api, my_channel):
    assert not branding.remove_watermark().active
    assert api.oauth.watermarks().unset.call_args.kwargs == {"channelId": CHANNEL_ID}


def section_item(**snippet) -> dict:
    return {
        "id": "sec1",
        "snippet": {"type": "multiplePlaylists", "title": "Best", "position": 1, **snippet},
        "contentDetails": {"playlists": ["PL1", "PL2"]},
    }


def test_list_sections_uses_friendly_types(api):
    api.oauth.channelSections().list().execute.return_value = {"items": [section_item()]}
    [section] = branding.list_sections()
    assert (section.type, section.playlist_ids) == ("multiple-playlists", ["PL1", "PL2"])
    assert api.oauth.channelSections().list.call_args.kwargs["mine"] is True


def test_add_section(api):
    api.oauth.channelSections().insert().execute.return_value = section_item()

    branding.add_section(
        "multiple-playlists", title="Best", playlists=["PL1", "https://www.youtube.com/playlist?list=PL2"]
    )

    body = api.oauth.channelSections().insert.call_args.kwargs["body"]
    assert body == {
        "snippet": {"type": "multiplePlaylists", "title": "Best"},
        "contentDetails": {"playlists": ["PL1", "PL2"]},
    }


def test_update_section_keeps_what_isnt_changed(api):
    sections = api.oauth.channelSections()
    sections.list().execute.return_value = {"items": [section_item(defaultLanguage="en", style="horizontalRow")]}
    sections.update().execute.return_value = section_item(position=0)

    branding.update_section("sec1", position=0)

    assert sections.update.call_args.kwargs["body"] == {
        "id": "sec1",
        "snippet": {"type": "multiplePlaylists", "title": "Best", "position": 0, "defaultLanguage": "en"},
        "contentDetails": {"playlists": ["PL1", "PL2"]},
    }


def test_delete_section(api):
    assert branding.delete_section("sec1").kind == "section"
    assert api.oauth.channelSections().delete.call_args.kwargs == {"id": "sec1"}


@pytest.mark.parametrize(
    ("kind", "options"),
    [("single-playlist", {"playlists": ["PL1", "PL2"]}), ("multiple-channels", {"channels": ["@a"]})],
)
def test_add_section_checks_what_each_kind_needs(api, kind, options):
    with pytest.raises(InvalidRequest):
        branding.add_section(kind, **options)
    api.oauth.channelSections().insert.assert_not_called()


def test_sections_without_content_send_none(api):
    api.oauth.channelSections().insert().execute.return_value = section_item(type="recentUploads")
    branding.add_section("recent-uploads")
    assert api.oauth.channelSections().insert.call_args.kwargs["body"] == {"snippet": {"type": "recentUploads"}}
