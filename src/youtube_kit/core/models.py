"""Results returned by core operations. Both adapters serialize these as JSON."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Privacy = Literal["private", "unlisted", "public"]
SearchKind = Literal["video", "channel", "playlist"]


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
    author: str
    text: str
    likes: int
    published_at: datetime
    reply_count: int


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
    privacy: Privacy | None = None


class PlaylistItemAdded(BaseModel):
    playlist_item_id: str
    playlist_id: str
    video_id: str
    position: int


class AuthStatus(BaseModel):
    api_key_set: bool
    token_file: str
    token_present: bool
    client_secrets_file: str
    client_secrets_present: bool
