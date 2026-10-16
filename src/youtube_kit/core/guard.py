"""Guards for irreversible deletes: a confirmation bound to the target, and damage limits for videos."""

from datetime import UTC, datetime
from typing import Any

from .config import DeleteProtection, Settings
from .errors import ConfirmationRequired, InvalidRequest, Protected
from .models import Video


def require_confirm(kind: str, target_id: str, confirm: str | None, plan: dict[str, Any]) -> None:
    """Pass only when `confirm` names the target; otherwise describe what would be deleted."""
    if confirm == target_id:
        return
    if confirm is not None:
        raise InvalidRequest(f"confirm must be {target_id}, the ID being deleted; got {confirm}.")
    raise ConfirmationRequired(
        f"Deleting {kind} {target_id} can't be undone. Show the user what will be deleted, "
        f"and only after they approve, repeat the request with confirm set to {target_id}.",
        details={"kind": kind, **plan, "confirm": target_id},
    )


def check_protected(video: Video) -> None:
    """Refuse videos past the configured limits, or whose view count we can't see."""
    settings = Settings.from_env()
    limits = DeleteProtection.load(settings.config_file)
    views = video.stats.views if video.stats else None
    reasons = []
    if views is None:
        reasons.append("its view count is hidden")
    elif views > limits.max_views:
        reasons.append(f"it has {views} views (limit {limits.max_views})")
    if video.privacy == "public":
        # YouTube only exposes the upload time, so a video made public later counts from its upload.
        age = (datetime.now(UTC) - video.published_at).days if video.published_at else None
        if age is None or age > limits.max_public_age_days:
            uploaded = "at an unknown time" if age is None else f"{age} days ago"
            reasons.append(f"it is public and was uploaded {uploaded} (limit {limits.max_public_age_days} days)")
    if reasons:
        raise Protected(
            f"Video {video.id} is protected from deletion: {'; '.join(reasons)}. Delete it in YouTube Studio, "
            f"or raise the limits under [delete_protection] in {settings.config_file}.",
            details={
                "studio_url": f"https://studio.youtube.com/video/{video.id}/edit",
                "config_file": str(settings.config_file),
                "max_views": limits.max_views,
                "max_public_age_days": limits.max_public_age_days,
            },
        )
