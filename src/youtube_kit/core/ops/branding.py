"""How your channel presents itself: about info, banner, watermark, and home page sections."""

import re
from pathlib import Path
from typing import Any, Literal

from .. import client, parse
from ..errors import InvalidRequest
from ..models import ChannelBranding, ChannelSection, Corner, Deleted, Watermark
from ..operation import operation
from ._common import changes, delete_if_present, image_upload, one, pick
from .channels import my_channel_id, owner_or, resolve_channel_id

_KEYWORD = re.compile(r'"([^"]*)"|(\S+)')
_WRITABLE_SETTINGS = (
    "description",
    "keywords",
    "country",
    "defaultLanguage",
    "unsubscribedTrailer",
    "trackingAnalyticsAccountId",
)

_API_CORNERS: dict[Corner, str] = {
    "top-left": "topLeft",
    "top-right": "topRight",
    "bottom-left": "bottomLeft",
    "bottom-right": "bottomRight",
}

# Deprecated types (likes, recentPosts, ...) are left out; existing ones still list under their API names.
_API_SECTION_TYPES = {
    "single-playlist": "singlePlaylist",
    "multiple-playlists": "multiplePlaylists",
    "popular-uploads": "popularUploads",
    "recent-uploads": "recentUploads",
    "all-playlists": "allPlaylists",
    "multiple-channels": "multipleChannels",
    "subscriptions": "subscriptions",
    "live-events": "liveEvents",
    "upcoming-events": "upcomingEvents",
    "completed-events": "completedEvents",
}
_SECTION_TYPES = {api: ours for ours, api in _API_SECTION_TYPES.items()}
SectionType = Literal[*_API_SECTION_TYPES]  # type: ignore[valid-type]


@operation(quota=51, destructive=True, idempotent=True, oauth=True)
def update_channel(
    *,
    description: str | None = None,
    keywords: list[str] | None = None,
    country: str | None = None,
    language: str | None = None,
    trailer: str | None = None,
) -> ChannelBranding:
    """Change your channel's about info. Only the fields you pass change. The name can only be changed in Studio.

    Args:
        description: Channel description.
        keywords: Channel keywords, replacing the current ones. An empty list removes them all.
        country: ISO 3166-1 alpha-2 country code.
        language: Language of the channel's title and description, e.g. en or de.
        trailer: Video (ID or URL) shown to visitors who aren't subscribed.
    """
    return _update_branding(
        changes(
            description=description,
            keywords=None if keywords is None else _join_keywords(keywords),
            country=country,
            defaultLanguage=language,
            unsubscribedTrailer=None if trailer is None else parse.video_id(trailer),
        )
    )


@operation(quota=101, destructive=True, idempotent=True, oauth=True)
def set_channel_banner(image: Path) -> ChannelBranding:
    """Upload and set your channel's banner. Use a 16:9 image of at least 2048x1152, at most 6 MB.

    Args:
        image: Path to a JPEG or PNG.
    """
    media = image_upload(image, max_mb=6)
    banner = client.oauth().channelBanners().insert(media_body=media).execute()
    return _update_branding({}, banner_url=banner["url"])


@operation(quota=51, destructive=True, idempotent=True, oauth=True)
def set_watermark(
    image: Path,
    *,
    corner: Corner = "bottom-right",
    start: int = 0,
    from_end: bool = False,
    duration: int | None = None,
) -> Watermark:
    """Set the watermark shown over all your videos, replacing any current one. Viewers click it to subscribe.

    Args:
        image: Path to a square JPEG or PNG, at least 150x150, at most 1 MB.
        corner: Where it appears.
        start: Seconds from the start of the video when it appears, or from its end when counting from the end.
        from_end: Count start back from the end of the video.
        duration: Seconds to show it. Until the end of the video when omitted.
    """
    media = image_upload(image, max_mb=1)
    # uint64 fields travel as strings in the JSON API.
    timing: dict[str, Any] = {"type": "offsetFromEnd" if from_end else "offsetFromStart", "offsetMs": str(start * 1000)}
    if duration is not None:
        timing["durationMs"] = str(duration * 1000)
    body = {"position": {"type": "corner", "cornerPosition": _API_CORNERS[corner]}, "timing": timing}
    channel_id = my_channel_id()
    client.oauth().watermarks().set(channelId=channel_id, body=body, media_body=media).execute()
    # watermarks.set returns nothing and there is no way to read a watermark back.
    return Watermark(
        channel_id=channel_id,
        active=True,
        corner=corner,
        start_seconds=start,
        from_end=from_end,
        duration_seconds=duration,
    )


@operation(quota=51, destructive=True, idempotent=True, oauth=True)
def remove_watermark() -> Watermark:
    """Remove the watermark from your videos."""
    channel_id = my_channel_id()
    client.oauth().watermarks().unset(channelId=channel_id).execute()
    return Watermark(channel_id=channel_id, active=False)


@operation(quota=1, read_only=True, idempotent=True)
def list_sections(channel: str | None = None) -> list[ChannelSection]:
    """The sections on a channel's home page.

    Args:
        channel: UC… channel ID, @handle, or channel URL. Omit for your own channel.
    """
    youtube, selector = owner_or(channel)
    response = youtube.channelSections().list(part="snippet,contentDetails", **selector).execute()
    return [_section(item) for item in response.get("items", [])]


@operation(quota=50, oauth=True)
def add_section(
    kind: SectionType,
    *,
    title: str | None = None,
    playlists: list[str] | None = None,
    channels: list[str] | None = None,
    position: int | None = None,
) -> ChannelSection:
    """Add a section to your channel's home page. A channel has at most 10.

    Args:
        kind: What the section shows. single-playlist needs one playlist, multiple-playlists several
            playlists and a title, multiple-channels channels and a title.
        title: Section title, for the multiple-playlists and multiple-channels kinds.
        playlists: Playlist IDs or URLs to show.
        channels: Channels to show: UC… IDs, @handles, or channel URLs.
        position: 0-based position on the home page. Added at the end when omitted.
    """
    if kind == "single-playlist" and len(playlists or []) != 1:
        raise InvalidRequest("A single-playlist section shows exactly one playlist.")
    if kind.startswith("multiple-") and not title:
        raise InvalidRequest(f"A {kind} section needs a title.")
    snippet = {"type": _API_SECTION_TYPES[kind]} | changes(title=title, position=position)
    body = _section_body(snippet, _section_content(playlists, channels))
    return _section(client.oauth().channelSections().insert(part="snippet,contentDetails", body=body).execute())


@operation(quota=51, destructive=True, idempotent=True, oauth=True)
def update_section(
    section: str,
    *,
    title: str | None = None,
    playlists: list[str] | None = None,
    channels: list[str] | None = None,
    position: int | None = None,
) -> ChannelSection:
    """Change a section on your channel's home page. Only the fields you pass change.

    Args:
        section: Section ID, as listed for your channel.
        title: New title.
        playlists: Playlists to show instead of the current ones (IDs or URLs).
        channels: Channels to show instead of the current ones (UC… IDs, @handles, or URLs).
        position: New 0-based position on the home page.
    """
    youtube = client.oauth()
    current = one(
        youtube.channelSections().list(part="snippet,contentDetails", id=section).execute(),
        f"Section {section} not found.",
    )
    # channelSections.update replaces both parts, so carry over what isn't changing.
    snippet = pick(current["snippet"], ("type", "title", "position", "defaultLanguage")) | changes(
        title=title, position=position
    )
    content = pick(current.get("contentDetails", {}), ("playlists", "channels")) | _section_content(playlists, channels)
    body = {"id": section, **_section_body(snippet, content)}
    return _section(youtube.channelSections().update(part="snippet,contentDetails", body=body).execute())


@operation(quota=50, destructive=True, idempotent=True, oauth=True)
def delete_section(section: str) -> Deleted:
    """Delete a section from your channel's home page. Its playlists and videos are not affected.

    Args:
        section: Section ID, as listed for your channel.
    """
    deleted = delete_if_present(client.oauth().channelSections().delete(id=section))
    return Deleted(kind="section", id=section, already_gone=not deleted)


def _update_branding(settings_changes: dict, *, banner_url: str | None = None) -> ChannelBranding:
    youtube = client.oauth()
    current = one(youtube.channels().list(part="brandingSettings", mine=True).execute(), "You have no YouTube channel.")
    branding = current.get("brandingSettings", {})
    # channels.update replaces the whole part, and rejects the read-only and deprecated fields it returns.
    body: dict[str, Any] = {"channel": pick(branding.get("channel", {}), _WRITABLE_SETTINGS) | settings_changes}
    banner_url = banner_url or branding.get("image", {}).get("bannerExternalUrl")
    if banner_url:
        body["image"] = {"bannerExternalUrl": banner_url}
    response = youtube.channels().update(part="brandingSettings", body={"id": current["id"], "brandingSettings": body})
    return _branding(response.execute())


def _join_keywords(keywords: list[str]) -> str:
    """YouTube stores keywords as one space-separated string, quoting multi-word keywords."""
    cleaned = [k.strip() for k in keywords if k.strip()]
    return " ".join(f'"{k}"' if " " in k else k for k in cleaned)


def _split_keywords(keywords: str) -> list[str]:
    # Not shlex: keywords typed in Studio may hold a lone quote or apostrophe.
    return [quoted or bare for quoted, bare in _KEYWORD.findall(keywords) if quoted or bare]


def _branding(item: dict) -> ChannelBranding:
    settings = item.get("brandingSettings", {}).get("channel", {})
    return ChannelBranding(
        channel_id=item["id"],
        title=settings.get("title"),
        description=settings.get("description"),
        keywords=_split_keywords(settings.get("keywords", "")),
        country=settings.get("country"),
        language=settings.get("defaultLanguage"),
        trailer_video_id=settings.get("unsubscribedTrailer"),
        banner_url=item.get("brandingSettings", {}).get("image", {}).get("bannerExternalUrl"),
    )


def _section_body(snippet: dict, content: dict) -> dict:
    # Kinds like recent-uploads take no contentDetails at all.
    return {"snippet": snippet, "contentDetails": content} if content else {"snippet": snippet}


def _section_content(playlists: list[str] | None, channels: list[str] | None) -> dict:
    return changes(
        playlists=None if playlists is None else [parse.playlist_id(p) for p in playlists],
        channels=None if channels is None else [resolve_channel_id(c) for c in channels],
    )


def _section(item: dict) -> ChannelSection:
    snippet, details = item["snippet"], item.get("contentDetails", {})
    return ChannelSection(
        id=item["id"],
        type=_SECTION_TYPES.get(snippet["type"], snippet["type"]),
        title=snippet.get("title"),
        position=snippet.get("position"),
        playlist_ids=details.get("playlists", []),
        channel_ids=details.get("channels", []),
    )
