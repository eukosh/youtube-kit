import mimetypes
import re
from pathlib import Path
from typing import Any

from googleapiclient.http import MediaFileUpload

from .. import client, parse, progress
from ..errors import InvalidRequest, NotFound
from ..models import Privacy, ThumbnailResult, Video, VideoCategory, VideoStats
from ..operation import operation
from ..pagination import API_PAGE_SIZE
from ._common import existing_file, to_int, video_url

# Multiple of 256 KiB (API requirement); small enough to report progress regularly.
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
UPLOAD_RETRIES = 5
THUMBNAIL_MAX_BYTES = 2 * 1024 * 1024
_THUMBNAIL_TYPES = {"image/jpeg", "image/png"}


@operation(quota=1, read_only=True, idempotent=True)
def get_videos(videos: list[str]) -> list[Video]:
    """Full metadata, statistics, and status for one or more videos.

    Videos that don't exist or aren't visible to you are left out of the result;
    if none are found, that's a not-found error.

    Args:
        videos: Video IDs or URLs. Fetched in batches of 50, 1 quota unit per batch.
    """
    ids = list(dict.fromkeys(parse.video_id(v) for v in videos))
    if not ids:
        raise InvalidRequest("Pass at least one video ID or URL.")
    found: list[Video] = []
    for start in range(0, len(ids), API_PAGE_SIZE):
        batch = ids[start : start + API_PAGE_SIZE]
        response = (
            client.public().videos().list(part="snippet,contentDetails,statistics,status", id=",".join(batch)).execute()
        )
        found.extend(_video(item) for item in response.get("items", []))
    if not found:
        raise NotFound(f"Video {ids[0]} not found." if len(ids) == 1 else f"None of the {len(ids)} videos were found.")
    return found


@operation(quota=1, read_only=True, idempotent=True)
def list_video_categories(*, region: str = "US") -> list[VideoCategory]:
    """Video categories that can be assigned to uploads in a region, with the IDs to pass as category_id.

    Args:
        region: ISO 3166-1 alpha-2 country code.
    """
    response = client.public().videoCategories().list(part="snippet", regionCode=region).execute()
    return [
        VideoCategory(id=item["id"], title=item["snippet"]["title"])
        for item in response.get("items", [])
        if item["snippet"]["assignable"]
    ]


@operation(quota=1600, oauth=True)
def upload_video(
    file: Path,
    *,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "22",
    privacy: Privacy = "private",
    publish_at: str | None = None,
    made_for_kids: bool = False,
) -> Video:
    """Upload a video file from disk (resumable, reports progress).

    Args:
        file: Path to the local video file.
        title: Video title.
        description: Video description.
        tags: Keyword tags.
        category_id: Category ID (see the video categories listing). 22 is People & Blogs.
        privacy: Privacy status. Must be private when publish_at is set.
        publish_at: Schedule publication at this date or datetime; YouTube makes the video public then.
        made_for_kids: Whether the video is made for kids (COPPA).
    """
    path = existing_file(file)
    status: dict[str, Any] = {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids}
    if publish_at:
        if privacy != "private":
            raise InvalidRequest("publish_at requires privacy='private'.")
        status["publishAt"] = parse.timestamp(publish_at)
    body = {
        "snippet": {"title": title, "description": description, "tags": _clean(tags or []), "categoryId": category_id},
        "status": status,
    }
    media = MediaFileUpload(str(path), chunksize=UPLOAD_CHUNK_BYTES, resumable=True)
    request = client.oauth().videos().insert(part="snippet,status", body=body, media_body=media)
    total = path.stat().st_size
    response = None
    while response is None:
        chunk, response = request.next_chunk(num_retries=UPLOAD_RETRIES)
        if chunk is not None:
            progress.report(chunk.resumable_progress, total)
    progress.report(total, total)
    return _video(response)


@operation(quota=51, destructive=True, idempotent=True, oauth=True)
def update_video(
    video: str,
    *,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    category_id: str | None = None,
    privacy: Privacy | None = None,
    publish_at: str | None = None,
    made_for_kids: bool | None = None,
) -> Video:
    """Change a video's metadata. Only the fields you pass change; the rest keep their values.

    Args:
        video: Video ID or URL.
        title: New title.
        description: New description.
        tags: New tags, replacing the current ones. An empty list removes all tags.
        category_id: New category ID (see the video categories listing).
        privacy: New privacy status. Making a scheduled video public or unlisted cancels the schedule.
        publish_at: Schedule publication at this date or datetime. The video must end up private.
        made_for_kids: Whether the video is made for kids (COPPA).
    """
    video_id = parse.video_id(video)
    youtube = client.oauth()
    current = youtube.videos().list(part="snippet,status", id=video_id).execute().get("items", [])
    if not current:
        raise NotFound(f"Video {video_id} not found.")
    # videos.update replaces whole parts: writable fields left out are reset, read-only ones rejected.
    snippet = _pick(current[0]["snippet"], _WRITABLE_SNIPPET)
    status = _pick(current[0]["status"], _WRITABLE_STATUS)

    snippet_changes = {
        "title": title,
        "description": description,
        "tags": None if tags is None else _clean(tags),
        "categoryId": category_id,
    }
    snippet.update({key: value for key, value in snippet_changes.items() if value is not None})
    if privacy is not None:
        status["privacyStatus"] = privacy
    if made_for_kids is not None:
        status["selfDeclaredMadeForKids"] = made_for_kids
    if publish_at is not None:
        if status["privacyStatus"] != "private":
            raise InvalidRequest("publish_at requires the video to be private.")
        status["publishAt"] = parse.timestamp(publish_at)
    if status["privacyStatus"] != "private":
        # Also covers videos whose schedule already fired: YouTube keeps the stale publishAt.
        status.pop("publishAt", None)

    body = {"id": video_id, "snippet": snippet, "status": status}
    return _video(youtube.videos().update(part="snippet,status", body=body).execute())


_WRITABLE_SNIPPET = ("title", "description", "tags", "categoryId", "defaultLanguage")
_WRITABLE_STATUS = (
    "privacyStatus",
    "publishAt",
    "license",
    "embeddable",
    "publicStatsViewable",
    "selfDeclaredMadeForKids",
    "containsSyntheticMedia",
)


def _clean(tags: list[str]) -> list[str]:
    return [tag.strip() for tag in tags if tag.strip()]


def _pick(part: dict, keys: tuple[str, ...]) -> dict:
    return {key: part[key] for key in keys if key in part}


@operation(quota=50, destructive=True, idempotent=True, oauth=True)
def set_thumbnail(video: str, image: Path) -> ThumbnailResult:
    """Set a video's custom thumbnail. The channel must be verified.

    Args:
        video: Video ID or URL.
        image: Path to a JPEG or PNG, at most 2 MB.
    """
    video_id = parse.video_id(video)
    path = existing_file(image)
    mimetype, _ = mimetypes.guess_type(path)
    if mimetype not in _THUMBNAIL_TYPES:
        raise InvalidRequest(f"Thumbnail must be a .jpg or .png file, got {path.name}.")
    if path.stat().st_size > THUMBNAIL_MAX_BYTES:
        raise InvalidRequest(f"Thumbnail {path} is larger than 2 MB.")
    media = MediaFileUpload(str(path), mimetype=mimetype)
    response = client.oauth().thumbnails().set(videoId=video_id, media_body=media).execute()
    thumbnails = (response.get("items") or [{}])[0]
    best = thumbnails.get("maxres") or thumbnails.get("high") or thumbnails.get("default") or {}
    return ThumbnailResult(video_id=video_id, thumbnail_url=best.get("url"))


_DURATION = re.compile(r"^P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?$")


def _duration_seconds(iso: str | None) -> int | None:
    match = _DURATION.match(iso or "")
    if not match:
        return None
    days, hours, minutes, seconds = (int(match[group] or 0) for group in "dhms")
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def _video(item: dict) -> Video:
    snippet, status, details = item.get("snippet", {}), item.get("status", {}), item.get("contentDetails", {})
    stats = item.get("statistics")
    return Video(
        id=item["id"],
        url=video_url(item["id"]),
        title=snippet.get("title"),
        description=snippet.get("description"),
        channel_id=snippet.get("channelId"),
        channel_title=snippet.get("channelTitle"),
        published_at=snippet.get("publishedAt"),
        tags=snippet.get("tags"),
        category_id=snippet.get("categoryId"),
        duration=details.get("duration"),
        duration_seconds=_duration_seconds(details.get("duration")),
        stats=None
        if stats is None
        else VideoStats(
            views=to_int(stats.get("viewCount")),
            likes=to_int(stats.get("likeCount")),
            comments=to_int(stats.get("commentCount")),
        ),
        privacy=status.get("privacyStatus"),
        publish_at=status.get("publishAt"),
    )
