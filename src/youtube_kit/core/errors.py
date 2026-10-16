"""Domain errors. Adapters map these to MCP tool errors and CLI exit codes."""

import json
from typing import Any, ClassVar

from googleapiclient.errors import HttpError


class YouTubeError(Exception):
    """Base class. `kind` is a stable machine-readable name; `exit_code` is the CLI status.

    `details` is optional structured context the caller can act on.
    """

    kind: ClassVar[str] = "error"
    exit_code: ClassVar[int] = 1

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class InvalidRequest(YouTubeError):
    kind = "invalid_request"
    exit_code = 2


class NotFound(YouTubeError):
    kind = "not_found"
    exit_code = 3


class NotAuthorized(YouTubeError):
    kind = "not_authorized"
    exit_code = 4


class QuotaExceeded(YouTubeError):
    kind = "quota_exceeded"
    exit_code = 5


class Forbidden(YouTubeError):
    """Authorized, but YouTube refuses the action (e.g. comments disabled)."""

    kind = "forbidden"
    exit_code = 6


class NetworkError(YouTubeError):
    """YouTube could not be reached. Safe to retry."""

    kind = "network"
    exit_code = 7


class ConfirmationRequired(YouTubeError):
    """A guarded delete needs `confirm`; `details` describe the target and the value to pass."""

    kind = "confirmation_required"
    exit_code = 8


class Protected(YouTubeError):
    """Refused by the delete protection limits. No flag overrides them; only the config file does."""

    kind = "protected"
    exit_code = 9


class TimedOut(YouTubeError):
    """Waiting for YouTube took longer than allowed. The work may still finish."""

    kind = "timeout"
    exit_code = 10


LOGIN_HINT = "Run `ytk auth login` to authorize your YouTube account."
API_KEY_HINT = "Check YOUTUBE_API_KEY, or unset it to use your OAuth login for public data too."

_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}
_AUTH_REASONS = {"authError", "insufficientPermissions"}


def from_http_error(error: HttpError) -> YouTubeError:
    """Translate a googleapiclient HttpError into the matching domain error."""
    status = error.resp.status
    reason = _first_reason(error.content)
    message = error.reason or f"HTTP {status}"

    if reason in _QUOTA_REASONS:
        return QuotaExceeded(f"{message} Daily quota resets at midnight Pacific Time.")
    # A bad key is a generic 400 badRequest; the specific reason only appears in error details.
    if b"API_KEY_INVALID" in error.content:
        return NotAuthorized(f"{message} {API_KEY_HINT}")
    if reason == "youtubeSignupRequired":
        return Forbidden(f"{message} The authorized Google account needs a YouTube channel.")
    if status == 401 or reason in _AUTH_REASONS:
        return NotAuthorized(f"{message} {LOGIN_HINT}")
    if status == 403:
        return Forbidden(message)
    if status == 404:
        return NotFound(message)
    if status == 400:
        return InvalidRequest(message)
    return YouTubeError(f"YouTube API error (HTTP {status}): {message}")


def _first_reason(content: bytes) -> str | None:
    try:
        errors = json.loads(content)["error"]["errors"]
        return errors[0]["reason"]
    except ValueError, KeyError, IndexError, TypeError:
        return None
