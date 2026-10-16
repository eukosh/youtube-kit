import mimetypes
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError
from googleapiclient.http import HttpRequest, MediaFileUpload

from ..errors import InvalidRequest, NotFound

_IMAGE_TYPES = {"image/jpeg", "image/png"}


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


def image_upload(path: Path, *, max_mb: int) -> MediaFileUpload:
    """A JPEG or PNG from disk, checked before spending quota on an upload YouTube would reject."""
    path = existing_file(path)
    mimetype, _ = mimetypes.guess_type(path)
    if mimetype not in _IMAGE_TYPES:
        raise InvalidRequest(f"Image must be a .jpg or .png file, got {path.name}.")
    if path.stat().st_size > max_mb * 1024 * 1024:
        raise InvalidRequest(f"Image {path} is larger than {max_mb} MB.")
    return MediaFileUpload(str(path), mimetype=mimetype)


def delete_if_present(request: HttpRequest) -> bool:
    """Run a delete request. False if the target was already gone, which makes deletes idempotent."""
    try:
        request.execute()
    except HttpError as e:
        if e.resp.status == 404:
            return False
        raise
    return True


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
