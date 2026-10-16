"""Smoke tests against the real API: LIVE_YOUTUBE_API_KEY=... uv run pytest -m live

A separate variable, because the suite strips YOUTUBE_API_KEY to keep other tests offline.
"""

import os

import pytest

from youtube_kit import core

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("LIVE_YOUTUBE_API_KEY"), reason="set LIVE_YOUTUBE_API_KEY to run"),
]


@pytest.fixture(autouse=True)
def real_api_key(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", os.environ["LIVE_YOUTUBE_API_KEY"])


def test_channel_and_uploads():
    channel = core.get_channel("@YouTube")
    page = core.list_playlist_items(channel.uploads_playlist_id, limit=3)
    assert len(page.items) == 3
    videos = core.get_videos([entry.video_id for entry in page.items])
    assert all(video.url.startswith("https://") for video in videos)


def test_categories():
    assert any(category.id == "22" for category in core.list_video_categories())
