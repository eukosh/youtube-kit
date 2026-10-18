import mimetypes
import struct
from collections.abc import Callable
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest, MediaFileUpload

from ..errors import InvalidRequest, NotFound

_IMAGE_TYPES = {"image/jpeg", "image/png"}


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def studio_url(video_id: str) -> str:
    return f"https://studio.youtube.com/video/{video_id}/edit"


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


def image_upload(path: Path, *, max_mb: int) -> MediaFileUpload:
    """A JPEG or PNG from disk, checked before spending quota on an upload YouTube would reject."""
    path = existing_file(path)
    mimetype, _ = mimetypes.guess_type(path)
    if mimetype not in _IMAGE_TYPES:
        raise InvalidRequest(f"Image must be a .jpg or .png file, got {path.name}.")
    if path.stat().st_size > max_mb * 1024 * 1024:
        raise InvalidRequest(f"Image {path} is larger than {max_mb} MB.")
    return MediaFileUpload(str(path), mimetype=mimetype)


def image_size(path: Path) -> tuple[int, int] | None:
    """Width and height of a PNG or baseline/progressive JPEG, or None if the header can't be read."""
    data = Path(path).read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if not data.startswith(b"\xff\xd8"):
        return None
    i = 2
    while i + 9 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # markers without a length
            i += 2
            continue
        # Start-of-frame markers carry the size; C4, C8 and CC share the range but are tables.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
    return None


def delete_if_present(request: HttpRequest) -> bool:
    """Run a delete request. False if the target was already gone, which makes deletes idempotent."""
    try:
        request.execute()
    except HttpError as e:
        if e.resp.status == 404:
            return False
        raise
    return True


def unique_ids(refs: list[str], parse_one: Callable[[str], str], what: str) -> list[str]:
    """Parsed and deduplicated, in input order. Empty input is an error."""
    ids = list(dict.fromkeys(parse_one(ref) for ref in refs))
    if not ids:
        raise InvalidRequest(f"Pass at least one {what}.")
    return ids


def one(response: dict, not_found: str) -> dict:
    """The single item of a list response, or NotFound."""
    items = response.get("items", [])
    if not items:
        raise NotFound(not_found)
    return items[0]


def pick(part: dict, keys: tuple[str, ...]) -> dict:
    """The writable subset of a resource part, for update calls that replace the whole part."""
    return {key: part[key] for key in keys if key in part}


def changes(**fields: Any) -> dict:
    """Only the fields the caller set."""
    return {key: value for key, value in fields.items() if value is not None}
