"""Results returned by core operations. Both adapters serialize these as JSON."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Privacy = Literal["private", "unlisted", "public"]
SearchKind = Literal["video", "channel", "playlist"]
CommentStatus = Literal["published", "held", "spam", "rejected"]


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
    title: str | None = None
    description: str | None = None
    channel_id: str | None = None
    channel_title: str | None = None
    published_at: datetime | None = None
    tags: list[str] | None = None
    category_id: str | None = None
    duration: str | None = None
    duration_seconds: int | None = None
    stats: VideoStats | None = None
    privacy: Privacy | None = None
    publish_at: datetime | None = None


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
    kind: Literal["video", "playlist", "comment"]
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


class AuthStatus(BaseModel):
    api_key_set: bool
    token_file: str
    token_present: bool
    granted_scopes: list[str] | None = None
    client_secrets_file: str
    client_secrets_present: bool
