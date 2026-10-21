import re
from pathlib import Path
from typing import Any

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .. import client, guard, parse
from ..errors import OTHER_CHANNEL_HINT, Forbidden, InvalidRequest, NotFound, http_reason
from ..models import CaptionTrack, Deleted, Transcript, TranscriptFormat
from ..operation import operation
from ._common import delete_if_present, existing_file, one
from .channels import my_channel_id

MAX_CAPTION_MB = 100
PARAGRAPH_SECONDS = 30
# Forced subtitles cover only the parts not in the main language, so YouTube's full track beats them.
_READ_RANK = {"standard": 0, "asr": 1, "forced": 2}
# A track YouTube failed to process can't stand in for one it serves; a syncing one may not be ready yet.
# Any other status, or none, counts as serving.
_STATUS_RANK = {"syncing": 1, "failed": 2}
# An SRT cue: its start time on the timing line, then text up to a blank line.
_CUE = re.compile(r"^(\d+):(\d{2}):(\d{2})[,.]\d{3}[ \t]*-->.*\n((?:[ \t]*\S.*(?:\n|$))*)", re.MULTILINE)


@operation(quota=50, read_only=True, idempotent=True, oauth=True)
def list_captions(video: str) -> list[CaptionTrack]:
    """A video's caption tracks: language, name, and whether YouTube generated them from the audio.

    Works on any public video, though only the owner can download a transcript.

    Args:
        video: Video ID or URL.
    """
    # Through the login: Google documents captions.list as needing OAuth, so an API key may be refused.
    return _tracks(client.oauth(), parse.video_id(video))


@operation(quota=252, read_only=True, idempotent=True, oauth=True)  # ownership check + list + download
def get_transcript(
    video: str,
    *,
    language: str | None = None,
    format: TranscriptFormat = "text",
    translate_to: str | None = None,
) -> Transcript:
    """What is said in one of your videos, from its captions, including the ones YouTube generates.

    YouTube lets only a video's owner download its captions. Of several tracks in a language, one YouTube is
    serving is preferred over one it failed to process, then a published one you wrote over YouTube's.

    Args:
        video: Video ID or URL.
        language: Caption language, e.g. en or en-US. Omit for the language spoken in the video.
        format: text: paragraphs of about 30 seconds, each starting with its [m:ss] time. srt or vtt: the
            caption file itself.
        translate_to: Machine-translate the captions into this language, e.g. de.
    """
    video_id = parse.video_id(video)
    youtube = client.oauth()
    # Checked first: YouTube would charge for listing the tracks and then refuse the download.
    _require_own(youtube, video_id, f"Only its owner can download captions; listing them works. {OTHER_CHANNEL_HINT}")
    track = _to_read(_tracks(youtube, video_id), video_id, language)
    params: dict[str, Any] = {"id": track.id, "tfmt": "vtt" if format == "vtt" else "srt"}
    if translate_to:
        params["tlang"] = translate_to
    text = youtube.captions().download(**params).execute().decode("utf-8", errors="replace")
    return Transcript(
        video_id=video_id,
        caption_id=track.id,
        language=track.language,
        kind=track.kind,
        translated_to=translate_to,
        format=format,
        text=_paragraphs(text) if format == "text" else text,
    )


@operation(quota=400, oauth=True)
def upload_caption(video: str, file: Path, *, language: str, name: str = "", draft: bool = False) -> CaptionTrack:
    """Add a caption track to one of your videos from a caption file, such as SRT or VTT.

    Args:
        video: Video ID or URL.
        file: Path to the caption file, at most 100 MB.
        language: Language of the captions, e.g. en or en-US.
        name: Track name viewers see next to the language. Two tracks in one language need different names.
        draft: Upload it hidden from viewers.
    """
    video_id = parse.video_id(video)
    media = _caption_file(file)
    body = {"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": draft}}
    try:
        response = client.oauth().captions().insert(part="snippet", body=body, media_body=media).execute()
    except HttpError as e:
        if http_reason(e) == "captionExists":
            raise InvalidRequest(
                f"Video {video_id} already has a track in {language} named {name!r}. "
                "Replace that track's file instead, or choose another name."
            ) from e
        raise
    return _track(response)


@operation(quota=502, destructive=True, idempotent=True, oauth=True)  # ownership check + list + update
def update_caption(
    video: str,
    *,
    language: str,
    name: str | None = None,
    file: Path | None = None,
    draft: bool | None = None,
) -> CaptionTrack:
    """Replace the file of a caption track on one of your videos, or show or hide the track.

    Args:
        video: Video ID or URL.
        language: Language of the track, e.g. en or en-US.
        name: Name of the track, when the video has several in that language.
        file: Path to the new caption file, at most 100 MB.
        draft: Whether the track is hidden from viewers.
    """
    if file is None and draft is None:
        raise InvalidRequest("Pass a file, draft, or both.")
    video_id = parse.video_id(video)
    media = {"media_body": _caption_file(file)} if file is not None else {}
    youtube = client.oauth()
    _require_own(youtube, video_id)
    track = _to_change(_tracks(youtube, video_id), video_id, language, name)
    # isDraft is the only writable snippet field, and update resets it unless sent.
    body = {"id": track.id, "snippet": {"isDraft": track.draft if draft is None else draft}}
    return _track(youtube.captions().update(part="snippet", body=body, **media).execute())


@operation(quota=102, destructive=True, idempotent=True, oauth=True)  # ownership check + list + delete
def delete_caption(video: str, *, language: str, name: str | None = None, confirm: str | None = None) -> Deleted:
    """Permanently delete a caption track from one of your videos.

    Without confirm, nothing is deleted and the error describes the track.

    Args:
        video: Video ID or URL.
        language: Language of the track, e.g. en or en-US.
        name: Name of the track, when the video has several in that language.
        confirm: The track's ID, passed only after the user has approved deleting this track.
    """
    video_id = parse.video_id(video)
    youtube = client.oauth()
    videos = youtube.videos().list(part="snippet", id=video_id).execute().get("items", [])
    if not videos:
        if confirm is None:
            raise NotFound(f"Video {video_id} not found.")
        return Deleted(kind="caption", id=confirm, already_gone=True)
    _check_owner(videos[0])
    tracks = _tracks(youtube, video_id)
    # Tracks are picked by language and name, so once the confirmed one is gone a rerun would pick another.
    if confirm is not None and confirm not in {track.id for track in tracks}:
        return Deleted(kind="caption", id=confirm, already_gone=True)
    track = _to_change(tracks, video_id, language, name)
    plan = {"video_id": video_id, "language": track.language, "name": track.name, "track_kind": track.kind}
    guard.require_confirm("caption", track.id, confirm, plan)
    deleted = delete_if_present(youtube.captions().delete(id=track.id))
    return Deleted(kind="caption", id=track.id, already_gone=not deleted)


def _require_own(youtube: Resource, video_id: str, hint: str = OTHER_CHANNEL_HINT) -> None:
    _check_owner(
        one(youtube.videos().list(part="snippet", id=video_id).execute(), f"Video {video_id} not found."), hint
    )


def _check_owner(video: dict, hint: str = OTHER_CHANNEL_HINT) -> None:
    if video["snippet"].get("channelId") != my_channel_id():
        raise Forbidden(f"Video {video['id']} belongs to another channel. {hint}")


def _tracks(youtube: Resource, video_id: str) -> list[CaptionTrack]:
    response = youtube.captions().list(part="snippet", videoId=video_id).execute()
    return [_track(item) for item in response.get("items", [])]


def _to_read(tracks: list[CaptionTrack], video_id: str, language: str | None) -> CaptionTrack:
    """The track asked for, else the spoken language's: a working one, the author's own over YouTube's, then the
    exact language."""
    if language:
        matches = _in_language(tracks, video_id, language)
    else:
        if not tracks:
            raise NotFound(
                f"Video {video_id} has no captions. YouTube generates them some time after upload, "
                "for the languages it supports."
            )
        # A generated track is in the spoken language.
        spoken = {_base(track.language) for track in tracks if track.kind == "asr"}
        bases = spoken or {_base(track.language) for track in tracks}
        if len(bases) > 1:
            raise InvalidRequest(f"Video {video_id} has captions in {_languages(tracks)}; pass language to pick one.")
        matches = [track for track in tracks if _base(track.language) in bases]
    return max(
        matches,
        key=lambda track: (
            -_STATUS_RANK.get(track.status, 0),
            not track.draft,
            -_READ_RANK[track.kind],
            track.language.lower() == (language or "").lower(),
            track.updated_at.timestamp() if track.updated_at else 0,
        ),
    )


def _to_change(tracks: list[CaptionTrack], video_id: str, language: str, name: str | None) -> CaptionTrack:
    matches = _in_language(tracks, video_id, language)
    if name is not None:
        matches = [track for track in matches if (track.name or "") == name]
        if not matches:
            raise NotFound(f"Video {video_id} has no {language} track named {name!r}.")
    candidates = [track for track in matches if track.kind != "asr"] or matches
    if len(candidates) > 1:
        candidates = [track for track in candidates if track.language.lower() == language.lower()] or candidates
    if len(candidates) > 1:
        found = ", ".join(f"{track.language} {track.name or ''!r}" for track in candidates)
        exact = all(track.language.lower() == language.lower() for track in candidates)
        needed = "name" if exact else "the exact language" if name is not None else "name or the exact language"
        raise InvalidRequest(f"Video {video_id} has {len(candidates)} {language} tracks ({found}); pass {needed}.")
    return candidates[0]


def _in_language(tracks: list[CaptionTrack], video_id: str, language: str) -> list[CaptionTrack]:
    """Tracks in this language, its base or its variants: en matches en-US, but en-US not en-GB."""
    wanted = language.lower()
    matches = [
        track
        for track in tracks
        if wanted in (track.language.lower(), _base(track.language)) or track.language.lower() == _base(wanted)
    ]
    if not matches:
        have = f"it has {_languages(tracks)}" if tracks else "it has none"
        raise NotFound(f"Video {video_id} has no captions in {language}; {have}.")
    return matches


def _base(language: str) -> str:
    return language.lower().split("-")[0]


def _languages(tracks: list[CaptionTrack]) -> str:
    return ", ".join(sorted({track.language for track in tracks}))


def _caption_file(file: Path) -> MediaFileUpload:
    path = existing_file(file)
    if path.stat().st_size > MAX_CAPTION_MB * 1024 * 1024:
        raise InvalidRequest(f"Caption file {path} is larger than {MAX_CAPTION_MB} MB.")
    return MediaFileUpload(str(path), mimetype="application/octet-stream")


def _paragraphs(srt: str) -> str:
    """SRT cues joined into paragraphs of about PARAGRAPH_SECONDS, each starting with its [m:ss] time."""
    paragraphs: list[str] = []
    start = 0
    words: list[str] = []
    for cue in _CUE.finditer(srt.replace("\r\n", "\n")):
        hours, minutes, seconds = map(int, cue.group(1, 2, 3))
        at = hours * 3600 + minutes * 60 + seconds
        text = " ".join(re.sub(r"<[^>]+>", "", cue.group(4)).split())
        if not text:
            continue
        if words and at - start >= PARAGRAPH_SECONDS:
            paragraphs.append(f"[{_clock(start)}] {' '.join(words)}")
            words = []
        if not words:
            start = at
        words.append(text)
    if words:
        paragraphs.append(f"[{_clock(start)}] {' '.join(words)}")
    return "\n".join(paragraphs)


def _clock(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _track(item: dict) -> CaptionTrack:
    snippet = item.get("snippet", {})
    return CaptionTrack(
        id=item["id"],
        video_id=snippet["videoId"],
        language=snippet["language"],
        name=snippet.get("name") or None,
        kind=snippet.get("trackKind", "standard").lower(),
        draft=snippet.get("isDraft", False),
        status=snippet.get("status"),
        updated_at=snippet.get("lastUpdated"),
    )
