import itertools
import re
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from googleapiclient.http import MediaFileUpload
from pydantic import Field

from .. import client, guard, parse, progress
from ..errors import Forbidden, InvalidRequest, NotFound, TimedOut
from ..models import Deleted, Privacy, ProcessingStatus, ThumbnailResult, Video, VideoCategory, VideoRating, VideoStats
from ..operation import operation
from ..pagination import API_PAGE_SIZE
from ._common import changes, delete_if_present, existing_file, image_upload, one, pick, to_int, unique_ids, video_url
from .channels import my_channel_id

# Multiple of 256 KiB (API requirement); small enough to report progress regularly.
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
UPLOAD_RETRIES = 5
POLL_SECONDS = 10


@operation(quota=1, read_only=True, idempotent=True)
def get_videos(videos: list[str]) -> list[Video]:
    """Full metadata, statistics, and status for one or more videos.

    Videos that don't exist or aren't visible to you are left out of the result;
    if none are found, that's a not-found error.

    Args:
        videos: Video IDs or URLs. Fetched in batches of 50, 1 quota unit per batch.
    """
    ids = unique_ids(videos, parse.video_id, "video ID or URL")
    found: list[Video] = []
    for batch in itertools.batched(ids, API_PAGE_SIZE):
        response = (
            client.public().videos().list(part="snippet,contentDetails,statistics,status", id=",".join(batch)).execute()
        )
        found.extend(_video(item) for item in response.get("items", []))
    if not found:
        raise NotFound(f"Video {ids[0]} not found." if len(ids) == 1 else f"None of the {len(ids)} videos were found.")
    return found


@operation(quota=50, idempotent=True, oauth=True)
def rate_video(video: str, rating: Literal["like", "dislike", "none"]) -> VideoRating:
    """Like or dislike a video as the authorized user, or clear the rating with none.

    Args:
        video: Video ID or URL.
        rating: like, dislike, or none.
    """
    video_id = parse.video_id(video)
    client.oauth().videos().rate(id=video_id, rating=rating).execute()
    return VideoRating(video_id=video_id, rating=rating)


@operation(quota=1, read_only=True, idempotent=True, oauth=True)
def get_my_ratings(videos: list[str]) -> list[VideoRating]:
    """Whether the authorized user liked or disliked each video.

    Args:
        videos: Video IDs or URLs. Fetched in batches of 50, 1 quota unit per batch.
    """
    ids = unique_ids(videos, parse.video_id, "video ID or URL")
    ratings: list[VideoRating] = []
    for batch in itertools.batched(ids, API_PAGE_SIZE):
        response = client.oauth().videos().getRating(id=",".join(batch)).execute()
        ratings.extend(
            VideoRating(video_id=item["videoId"], rating=item["rating"] if item["rating"] != "unspecified" else "none")
            for item in response.get("items", [])
        )
    return ratings


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
    current = one(youtube.videos().list(part="snippet,status", id=video_id).execute(), f"Video {video_id} not found.")
    # videos.update replaces whole parts: writable fields left out are reset, read-only ones rejected.
    snippet = pick(current["snippet"], _WRITABLE_SNIPPET)
    status = pick(current["status"], _WRITABLE_STATUS)
    snippet.update(
        changes(
            title=title,
            description=description,
            tags=None if tags is None else _clean(tags),
            categoryId=category_id,
        )
    )
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


@operation(quota=50, destructive=True, idempotent=True, oauth=True)
def set_thumbnail(video: str, image: Path) -> ThumbnailResult:
    """Set a video's custom thumbnail. The channel must be verified.

    Args:
        video: Video ID or URL.
        image: Path to a JPEG or PNG, at most 2 MB.
    """
    video_id = parse.video_id(video)
    media = image_upload(image, max_mb=2)
    response = client.oauth().thumbnails().set(videoId=video_id, media_body=media).execute()
    thumbnails = (response.get("items") or [{}])[0]
    best = thumbnails.get("maxres") or thumbnails.get("high") or thumbnails.get("default") or {}
    return ThumbnailResult(video_id=video_id, thumbnail_url=best.get("url"))


@operation(quota=52, destructive=True, idempotent=True, oauth=True)  # lookup + ownership check + delete
def delete_video(video: str, *, confirm: str | None = None) -> Deleted:
    """Permanently delete one of your videos.

    Only recent, little-watched videos can be deleted here: by default at most 100 views and, if public,
    uploaded within the last 7 days (the limits are set in the toolkit's config file). Anything else must be
    deleted in YouTube Studio. Without confirm, nothing is deleted and the error describes the video.

    Args:
        video: Video ID or URL.
        confirm: The video ID again, passed only after the user has approved deleting this video.
    """
    video_id = parse.video_id(video)
    youtube = client.oauth()
    items = youtube.videos().list(part="snippet,statistics,status", id=video_id).execute().get("items", [])
    if not items:
        return Deleted(kind="video", id=video_id, already_gone=True)
    target = _video(items[0])
    if target.channel_id != my_channel_id():
        raise Forbidden(f"Video {video_id} belongs to another channel.")
    guard.check_protected(target)
    plan = {
        "title": target.title,
        "url": target.url,
        "privacy": target.privacy,
        "views": target.stats.views if target.stats else None,
    }
    guard.require_confirm("video", video_id, confirm, plan)
    deleted = delete_if_present(youtube.videos().delete(id=video_id))
    return Deleted(kind="video", id=video_id, already_gone=not deleted)


@operation(quota=1, read_only=True, idempotent=True, oauth=True)
def get_processing_status(
    video: str, *, wait: bool = False, timeout: Annotated[int, Field(ge=1)] = 600
) -> ProcessingStatus:
    """Whether YouTube has finished processing one of your uploads.

    Args:
        video: Video ID or URL.
        wait: Keep checking every 10 seconds (1 quota unit each, with progress reports) until processing ends.
            If it hasn't ended within timeout, that's a timeout error, so a script can chain the next step on success.
        timeout: Seconds to wait at most. Callers that can't block for long should wait briefly and check again.
    """
    video_id = parse.video_id(video)
    deadline = time.monotonic() + (timeout if wait else 0)
    status = _processing_status(video_id)
    while status.status == "processing" and time.monotonic() < deadline:
        if status.parts_total:
            progress.report(status.parts_processed or 0, status.parts_total)
        time.sleep(max(0.0, min(POLL_SECONDS, deadline - time.monotonic())))
        status = _processing_status(video_id)
    if wait and status.status == "processing":
        raise TimedOut(f"Video {video_id} is still processing after {timeout} seconds.", details=status.model_dump())
    return status


def _processing_status(video_id: str) -> ProcessingStatus:
    response = client.oauth().videos().list(part="processingDetails", id=video_id).execute()
    details = one(response, f"Video {video_id} not found.").get("processingDetails")
    if details is None:
        raise Forbidden(f"Processing status of {video_id} is only visible to the video's owner.")
    parts = details.get("processingProgress", {})
    return ProcessingStatus(
        video_id=video_id,
        status=details["processingStatus"],
        failure_reason=details.get("processingFailureReason"),
        parts_total=to_int(parts.get("partsTotal")),
        parts_processed=to_int(parts.get("partsProcessed")),
        time_left_ms=to_int(parts.get("timeLeftMs")),
    )


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
