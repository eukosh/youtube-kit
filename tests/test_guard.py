"""Guarded deletes: a confirmation bound to the target, damage limits for videos, idempotency."""

from datetime import UTC, datetime, timedelta

import pytest

from youtube_kit.core.errors import ConfirmationRequired, Forbidden, InvalidRequest, Protected
from youtube_kit.core.ops import playlists, videos

from .fakes import http_error, playlist_resource, video_item

RECENT = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


def deletable_video(**overrides) -> dict:
    item = video_item(statistics={"viewCount": "12"})
    item["snippet"]["publishedAt"] = RECENT
    return {**item, **overrides}


@pytest.fixture(params=["video", "playlist"])
def target(request, api, my_channel):
    """A guarded delete op wired to an existing target: (op, target ID, the fake API resource)."""
    if request.param == "video":
        api.oauth.videos().list().execute.return_value = {"items": [deletable_video()]}
        return videos.delete_video, "dQw4w9WgXcQ", api.oauth.videos()
    api.oauth.playlists().list().execute.return_value = {"items": [playlist_resource()]}
    return playlists.delete_playlist, "PL1", api.oauth.playlists()


def test_without_confirm_nothing_is_deleted_and_the_target_is_described(target):
    delete, target_id, resource = target
    with pytest.raises(ConfirmationRequired) as caught:
        delete(target_id)
    assert caught.value.details["confirm"] == target_id
    assert caught.value.details["title"]
    resource.delete.assert_not_called()


def test_confirm_must_name_the_target(target):
    delete, target_id, resource = target
    with pytest.raises(InvalidRequest):
        delete(target_id, confirm="nope")
    resource.delete.assert_not_called()


def test_confirmed_delete(target):
    delete, target_id, resource = target
    result = delete(target_id, confirm=target_id)
    assert (result.id, result.already_gone) == (target_id, False)
    assert resource.delete.call_args.kwargs == {"id": target_id}


def test_already_gone_is_success(target):
    delete, target_id, resource = target
    resource.list().execute.return_value = {"items": []}
    assert delete(target_id).already_gone
    resource.delete.assert_not_called()


def test_gone_between_check_and_delete_is_success(target):
    delete, target_id, resource = target
    resource.delete().execute.side_effect = http_error(404, "notFound")
    assert delete(target_id, confirm=target_id).already_gone


@pytest.mark.parametrize(
    ("item", "reason"),
    [
        (deletable_video(statistics={"viewCount": "101"}), "101 views"),
        (deletable_video(statistics={}), "view count is hidden"),
        (video_item(statistics={"viewCount": "0"}), "is public"),
    ],
)
def test_protected_videos_are_refused_even_when_confirmed(api, my_channel, item, reason):
    api.oauth.videos().list().execute.return_value = {"items": [item]}
    with pytest.raises(Protected, match=reason) as caught:
        videos.delete_video("dQw4w9WgXcQ", confirm="dQw4w9WgXcQ")
    assert caught.value.details["studio_url"].endswith("/video/dQw4w9WgXcQ/edit")
    api.oauth.videos().delete.assert_not_called()


def test_old_private_videos_are_not_protected_by_age(api, my_channel):
    item = video_item(statistics={"viewCount": "0"}, status={"privacyStatus": "private"})
    api.oauth.videos().list().execute.return_value = {"items": [item]}
    assert not videos.delete_video("dQw4w9WgXcQ", confirm="dQw4w9WgXcQ").already_gone


def test_limits_come_from_the_config_file(api, my_channel, tmp_path):
    (tmp_path / "config.toml").write_text("[delete_protection]\nmax_views = 5000\n")
    api.oauth.videos().list().execute.return_value = {"items": [deletable_video(statistics={"viewCount": "4000"})]}
    assert not videos.delete_video("dQw4w9WgXcQ", confirm="dQw4w9WgXcQ").already_gone


@pytest.mark.parametrize(
    "config", ["[delete_protection]\nmax_views = -1\n", "[delete_protection]\nmax_veiws = 5\n", "["]
)
def test_invalid_config_fails_closed(api, my_channel, tmp_path, config):
    (tmp_path / "config.toml").write_text(config)
    api.oauth.videos().list().execute.return_value = {"items": [deletable_video()]}
    with pytest.raises(InvalidRequest, match=r"config\.toml"):
        videos.delete_video("dQw4w9WgXcQ", confirm="dQw4w9WgXcQ")
    api.oauth.videos().delete.assert_not_called()


def test_other_channels_videos_are_refused_before_anything_else(api, my_channel):
    api.oauth.videos().list().execute.return_value = {"items": [deletable_video(snippet={"channelId": "UCother"})]}
    with pytest.raises(Forbidden, match="another channel"):
        videos.delete_video("dQw4w9WgXcQ", confirm="dQw4w9WgXcQ")
    api.oauth.videos().delete.assert_not_called()
