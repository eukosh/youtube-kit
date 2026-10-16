from datetime import UTC, date, datetime, timedelta

import pytest

from youtube_kit.core import parse
from youtube_kit.core.errors import InvalidRequest

VIDEO = "dQw4w9WgXcQ"
CHANNEL = "UC" + "x" * 22


@pytest.mark.parametrize(
    "ref",
    [
        VIDEO,
        f" {VIDEO} ",
        f"https://www.youtube.com/watch?v={VIDEO}",
        f"https://youtube.com/watch?v={VIDEO}&t=42s&list=PL123",
        f"youtube.com/watch?v={VIDEO}",
        f"https://m.youtube.com/watch?v={VIDEO}",
        f"https://music.youtube.com/watch?v={VIDEO}",
        f"https://youtu.be/{VIDEO}?si=abc",
        f"https://www.youtube.com/shorts/{VIDEO}",
        f"https://www.youtube.com/embed/{VIDEO}",
        f"https://www.youtube.com/live/{VIDEO}",
        f"https://www.youtube-nocookie.com/embed/{VIDEO}",
        f"https://studio.youtube.com/video/{VIDEO}/edit",
    ],
)
def test_video_id_accepts_ids_and_urls(ref):
    assert parse.video_id(ref) == VIDEO


@pytest.mark.parametrize(
    "ref",
    [
        "",
        "short",
        "https://vimeo.com/watch?v=dQw4w9WgXcQ",
        "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/@x",
    ],
)
def test_video_id_rejects_garbage(ref):
    with pytest.raises(InvalidRequest):
        parse.video_id(ref)


@pytest.mark.parametrize(
    ("ref", "by", "value"),
    [
        (CHANNEL, "id", CHANNEL),
        ("@mkbhd", "handle", "@mkbhd"),
        ("mkbhd", "handle", "@mkbhd"),
        ("https://www.youtube.com/@mkbhd", "handle", "@mkbhd"),
        ("https://www.youtube.com/@mkbhd/videos", "handle", "@mkbhd"),
        (f"https://www.youtube.com/channel/{CHANNEL}", "id", CHANNEL),
        ("https://www.youtube.com/user/marquesbrownlee", "username", "marquesbrownlee"),
    ],
)
def test_channel_ref(ref, by, value):
    assert parse.channel_ref(ref) == parse.ChannelRef(by, value)


@pytest.mark.parametrize("ref", ["", "https://www.youtube.com/c/legacy", "https://example.com/@x", "a/b"])
def test_channel_ref_rejects_unresolvable(ref):
    with pytest.raises(InvalidRequest):
        parse.channel_ref(ref)


@pytest.mark.parametrize(
    "ref",
    [
        "PLabc_123-x",
        "https://www.youtube.com/playlist?list=PLabc_123-x",
        "https://youtu.be/dQw4w9WgXcQ?list=PLabc_123-x",
    ],
)
def test_playlist_id(ref):
    assert parse.playlist_id(ref) == "PLabc_123-x"


@pytest.mark.parametrize("ref", ["", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "not a playlist"])
def test_playlist_id_rejects(ref):
    with pytest.raises(InvalidRequest):
        parse.playlist_id(ref)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-01-01", "2026-01-01T00:00:00Z"),
        ("2026-01-01T10:30:00", "2026-01-01T10:30:00Z"),
        ("2026-01-01T10:30:00Z", "2026-01-01T10:30:00Z"),
        ("2026-01-01T12:30:00+02:00", "2026-01-01T10:30:00Z"),
    ],
)
def test_timestamp_normalises_to_utc(value, expected):
    assert parse.timestamp(value) == expected


def test_timestamp_rejects_garbage():
    with pytest.raises(InvalidRequest):
        parse.timestamp("last tuesday")


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("UgzAbc123", "UgzAbc123"),
        ("UgzAbc123.9xYz", "UgzAbc123.9xYz"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&lc=UgzAbc123", "UgzAbc123"),
    ],
)
def test_comment_id(ref, expected):
    assert parse.comment_id(ref) == expected


@pytest.mark.parametrize("ref", ["", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "a b"])
def test_comment_id_rejects(ref):
    with pytest.raises(InvalidRequest):
        parse.comment_id(ref)


def test_since_takes_relative_spans():
    assert parse.since("2026-01-01") == "2026-01-01T00:00:00Z"
    ago = datetime.fromisoformat(parse.since("2w"))
    assert timedelta(days=13) < datetime.now(UTC) - ago < timedelta(days=15)


def test_day():
    assert parse.day("2026-03-31", ago_from=date(2000, 1, 1)) == date(2026, 3, 31)
    assert parse.day("10d", ago_from=date(2026, 3, 31)) == date(2026, 3, 21)
    with pytest.raises(InvalidRequest):
        parse.day("yesterday", ago_from=date(2026, 3, 31))
