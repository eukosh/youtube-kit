"""Domain errors. Adapters map these to MCP tool errors and CLI exit codes."""

import json
import re
import socket
import ssl
from typing import Any, ClassVar

import httplib2
from google.auth.exceptions import TransportError
from googleapiclient.errors import HttpError

NETWORK_ERRORS = (
    httplib2.HttpLib2Error,
    TransportError,
    ConnectionError,
    TimeoutError,
    socket.gaierror,
    ssl.SSLError,
)
"""Exceptions that mean YouTube or Google could not be reached."""


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
OTHER_CHANNEL_HINT = "If it is on another of your logged-in channels, run this on that channel instead."
API_KEY_HINT = "Check YOUTUBE_API_KEY, or unset it to use your OAuth login for public data too."

_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}
_AUTH_REASONS = {"authError", "insufficientPermissions"}


def from_http_error(error: HttpError) -> YouTubeError:
    """Translate a googleapiclient HttpError into the matching domain error."""
    status = error.resp.status
    reason = http_reason(error)
    # Some messages carry HTML, like "the request's <code>playlistId</code> parameter".
    message = re.sub(r"</?[a-z]+>", "", error.reason or "") or f"HTTP {status}"

    if reason in _QUOTA_REASONS:
        return QuotaExceeded(f"{message} Daily quota resets at midnight Pacific Time.")
    if status == 429:
        return QuotaExceeded(f"{message} Too many requests; retry in a minute.")
    # A bad key (400) and a missing scope (403) only show their specific reason in the error details.
    if b"API_KEY_INVALID" in error.content:
        return NotAuthorized(f"{message} {API_KEY_HINT}")
    if b"ACCESS_TOKEN_SCOPE_INSUFFICIENT" in error.content:
        return NotAuthorized(f"{message} {LOGIN_HINT}")
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
    # Messages like "Internal error encountered." say nothing; the reason sometimes does.
    detail = f"HTTP {status}, {reason}" if reason else f"HTTP {status}"
    return YouTubeError(f"YouTube API error ({detail}): {message}")


def http_reason(error: HttpError) -> str | None:
    """The first error reason YouTube gave, like quotaExceeded or INVALID_ASPECT_RATIO."""
    try:
        errors = json.loads(error.content)["error"]["errors"]
        return errors[0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
