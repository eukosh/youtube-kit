"""Results returned by core operations. Both adapters serialize these as JSON."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Privacy = Literal["private", "unlisted", "public"]
SearchKind = Literal["video", "channel", "playlist"]
CommentStatus = Literal["published", "held", "spam", "rejected"]
Corner = Literal["top-left", "top-right", "bottom-left", "bottom-right"]


class Page[T](BaseModel):
    items: list[T]
    total_results: int | None = Field(None, description="Total reported by YouTube; only an estimate for search.")
    next_page_token: str | None = Field(None, description="Pass as page_token to continue; null at the end.")


class SearchHit(BaseModel):
    id: str
    kind: SearchKind
    title: str
    description: str
    channel_id: str
    channel_title: str
    published_at: datetime
    url: str


class VideoStats(BaseModel):
    views: int | None = None
    likes: int | None = None
    comments: int | None = None


class Video(BaseModel):
    id: str
    url: str
    studio_url: str | None = Field(
        None, description="Edit page in YouTube Studio; only for videos on channels you're logged in to."
    )
    title: str | None = None
    description: str | None = None
    channel_id: str | None = None
    channel_title: str | None = None
    published_at: datetime | None = None
    tags: list[str] | None = Field(None, description="In the order YouTube stores them, which may differ from yours.")
    category_id: str | None = None
    language: str | None = Field(None, description="Language of the title and description, e.g. en-US.")
    audio_language: str | None = Field(None, description="Language spoken in the video, e.g. en-US.")
    duration: str | None = None
    duration_seconds: int | None = None
    stats: VideoStats | None = None
    privacy: Privacy | None = None
    publish_at: datetime | None = None
    paid_promotion: bool | None = Field(None, description="Declared to include paid promotion.")
    ai_content: bool | None = Field(
        None,
        description="Declared to contain realistic AI-made content, as set by this upload or update. "
        "YouTube doesn't report it when reading a video.",
    )
    upload_status: str | None = Field(None, description="uploaded, processed, failed, rejected, or deleted.")
    upload_failure_reason: str | None = Field(
        None, description="Why a failed upload failed, e.g. codec, conversion, emptyFile, invalidFile, tooSmall."
    )
    rejection_reason: str | None = Field(
        None,
        description="Why YouTube rejected the video, e.g. copyright, duplicate, length, termsOfService. "
        "YouTube reports no reason for a video kept private because its API project isn't verified.",
    )


class ChannelStats(BaseModel):
    views: int | None = None
    subscribers: int | None = None
    videos: int | None = None


class Channel(BaseModel):
    id: str
    url: str
    title: str
    description: str
    handle: str | None = None
    published_at: datetime
    country: str | None = None
    stats: ChannelStats | None = None
    uploads_playlist_id: str | None = None


class PlaylistEntry(BaseModel):
    video_id: str
    title: str
    published_at: datetime | None = None
    position: int
    url: str


class Comment(BaseModel):
    id: str
    video_id: str | None = None
    author: str
    author_channel_id: str | None = None
    text: str
    likes: int | None = None
    published_at: datetime
    updated_at: datetime | None = None
    reply_count: int | None = Field(None, description="Top-level comments only.")
    parent_id: str | None = Field(None, description="Replies only: the comment replied to.")
    status: CommentStatus | None = Field(None, description="Moderation status, where YouTube reports it.")


class Moderated(BaseModel):
    comment_ids: list[str]
    status: CommentStatus
    authors_banned: bool = False


class VideoCategory(BaseModel):
    id: str
    title: str


class ThumbnailResult(BaseModel):
    video_id: str
    thumbnail_url: str | None = None


class Playlist(BaseModel):
    id: str
    url: str
    title: str
    description: str | None = None
    language: str | None = Field(None, description="Language of the title and description, e.g. en-US.")
    channel_id: str | None = None
    published_at: datetime | None = None
    privacy: Privacy | None = None
    item_count: int | None = None


class PlaylistItem(BaseModel):
    playlist_item_id: str
    playlist_id: str
    video_id: str
    position: int


class PlaylistRemoval(BaseModel):
    playlist_id: str
    video_id: str
    removed: int = Field(description="How many occurrences were removed; 0 if the video wasn't in the playlist.")


class PlaylistImage(BaseModel):
    playlist_id: str
    image_id: str
    width: int | None = None
    height: int | None = None


class Deleted(BaseModel):
    kind: Literal["video", "playlist", "comment", "section"]
    id: str
    already_gone: bool = Field(False, description="Nothing to delete: it didn't exist or was already deleted.")


class ProcessingStatus(BaseModel):
    video_id: str
    status: Literal["processing", "succeeded", "failed", "terminated"]
    failure_reason: str | None = None
    parts_total: int | None = None
    parts_processed: int | None = None
    time_left_ms: int | None = None


class Activity(BaseModel):
    type: str
    published_at: datetime
    title: str | None = None
    channel_id: str
    video_id: str | None = None
    playlist_id: str | None = Field(None, description="For playlist additions.")
    target_channel_id: str | None = Field(None, description="For subscriptions and channel shares.")


class AnalyticsReport(BaseModel):
    since: date
    until: date
    columns: list[str] = Field(description="Dimension first (if any), then the metrics, in request order.")
    rows: list[dict[str, str | int | float]]


class MyChannel(BaseModel):
    id: str
    title: str
    handle: str | None = None
    url: str
    default: bool = Field(description="Operations work on this channel unless told to use another.")
    analytics: bool = Field(description="The login grants analytics access.")


class AuthStatus(BaseModel):
    api_key_set: bool
    channels: list[MyChannel] = Field(description="Channels with a stored login.")
    token_dir: str
    client_secrets_file: str
    client_secrets_present: bool
    config_file: str


class SetupTask(BaseModel):
    do: str
    url: str | None = Field(None, description="The page to do it on.")
    values: dict[str, str] | None = Field(None, description="What to enter, by field label.")


class SetupStep(BaseModel):
    title: str
    tasks: list[SetupTask]
    gcloud: str | None = Field(
        None, description="Shell command that does this step instead, if the gcloud CLI is installed and signed in."
    )


class SetupGuide(BaseModel):
    ready: bool = Field(description="At least one channel is logged in.")
    channels: list[MyChannel]
    steps: list[SetupStep] = Field(description="What is left to do, in order. Empty when ready.")


class VideoRating(BaseModel):
    video_id: str
    rating: Literal["like", "dislike", "none"]


class Subscription(BaseModel):
    id: str
    channel_id: str
    url: str
    title: str | None = None
    description: str | None = None
    subscribed_at: datetime | None = None


class Unsubscribed(BaseModel):
    channel_id: str
    was_subscribed: bool


class ChannelBranding(BaseModel):
    channel_id: str
    title: str | None = None
    description: str | None = None
    keywords: list[str] = []
    country: str | None = None
    language: str | None = None
    trailer_video_id: str | None = Field(None, description="Shown to visitors who aren't subscribed.")
    banner_url: str | None = None


class Watermark(BaseModel):
    channel_id: str
    active: bool
    corner: Corner | None = None
    start_seconds: int | None = None
    from_end: bool | None = None
    duration_seconds: int | None = None


class ChannelSection(BaseModel):
    id: str
    type: str
    title: str | None = None
    position: int | None = None
    playlist_ids: list[str] = []
    channel_ids: list[str] = []


class Update(BaseModel):
    current: str = Field(description="Installed version.")
    latest: str = Field(description="Newest release on PyPI.")
    command: str = Field(description="Upgrades this install.")
    changelog: str = Field(description="Changelog link.")


class UpgradeResult(BaseModel):
    previous: str = Field(description="Version before.")
    current: str = Field(description="Version now installed.")
    upgraded: bool = Field(description="False if it was already the latest.")
    changelog: str | None = Field(None, description="Changelog link, after an upgrade.")
