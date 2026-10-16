from pathlib import Path

from ..errors import InvalidRequest


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def channel_url(channel_id: str) -> str:
    return f"https://www.youtube.com/channel/{channel_id}"


def to_int(value: str | None) -> int | None:
    """The API sends counts as strings, and omits them when the owner hides them."""
    return int(value) if value is not None else None


def existing_file(path: Path) -> Path:
    path = Path(path).expanduser()
    if not path.is_file():
        raise InvalidRequest(f"File not found: {path}")
    return path
