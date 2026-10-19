"""The `@operation` decorator: marks a core function as part of the public surface.

It records transport-neutral metadata (quota cost, side effects, auth) that the
CLI and MCP adapters render in their own way, adds the quota cost to the
docstring both adapters publish, and translates API errors into domain errors so
neither adapter ever sees a googleapiclient exception. Operations that reach
YouTube also gain a `my_channel` parameter: which of the user's logged-in
channels to work on. It is a per-call argument rather than a "current channel"
the MCP model switches, so every tool call shows which channel it touches.
"""

import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from . import auth
from .errors import LOGIN_HINT, NETWORK_ERRORS, NetworkError, NotAuthorized, from_http_error


@dataclass(frozen=True)
class OperationInfo:
    quota: int
    """Quota units per API request. Paginated operations make one request per page of 50."""
    bucket: Literal["search", "upload"] | None
    """YouTube's separate daily call limit this operation draws one call from; quota then counts only extra reads."""
    read_only: bool
    destructive: bool
    """Overwrites or deletes existing data (as opposed to only adding new data)."""
    idempotent: bool
    oauth: bool
    """Works on the user's own channel rather than reading public data."""
    paginated: bool
    local: bool
    """Reads only local state and never calls YouTube."""

    @property
    def quota_note(self) -> str:
        per_page = " per page of up to 50 results" if self.paginated else ""
        units = f"{self.quota} unit{'s' if self.quota != 1 else ''}"
        if self.bucket:
            extra = f", plus up to {units}" if self.quota else ""
            return f"Quota: 1 of the project's 100 daily {self.bucket} calls{per_page}{extra}."
        if self.quota == 0:
            return "Quota: no YouTube Data API units."
        return f"Quota: {units}{per_page}."


OPERATIONS: list[Callable] = []
"""Every operation, in import order. Adapters must expose each one (enforced by tests)."""

MY_CHANNEL = "my_channel"
_MY_CHANNEL_DOC = (
    "Which of your logged-in channels to work on: UC… ID, @handle or exact title. Omit for the default channel."
)


def operation[**P, R](
    *,
    quota: int,
    bucket: Literal["search", "upload"] | None = None,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    oauth: bool = False,
    paginated: bool = False,
    local: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        meta = OperationInfo(
            quota=quota,
            bucket=bucket,
            read_only=read_only,
            destructive=destructive,
            idempotent=idempotent,
            oauth=oauth,
            paginated=paginated,
            local=local,
        )

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                with auth.working_on(kwargs.pop(MY_CHANNEL, None)):  # type: ignore[arg-type]
                    return fn(*args, **kwargs)
            except HttpError as e:
                raise from_http_error(e) from e
            except RefreshError as e:
                raise NotAuthorized(f"OAuth token was rejected by Google ({e}). {LOGIN_HINT}") from e
            except NETWORK_ERRORS as e:
                raise NetworkError(f"Could not reach YouTube ({type(e).__name__}: {e}). Retry later.") from e

        doc = _with_note(fn.__doc__ or "", meta.quota_note)
        if not local:
            doc = _with_my_channel(wrapper, doc)
        wrapper.__doc__ = doc
        wrapper.__operation__ = meta  # type: ignore[attr-defined]
        OPERATIONS.append(wrapper)
        return wrapper

    return decorate


def info(fn: Callable) -> OperationInfo:
    return fn.__operation__  # type: ignore[attr-defined]


def _with_my_channel(wrapper: Callable, doc: str) -> str:
    """Add the keyword-only `my_channel` parameter to the published signature and Args section."""
    signature = inspect.signature(wrapper)
    parameter = inspect.Parameter(MY_CHANNEL, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=str | None)
    wrapper.__signature__ = signature.replace(parameters=[*signature.parameters.values(), parameter])
    annotations = {**inspect.get_annotations(wrapper), MY_CHANNEL: str | None}
    wrapper.__annotations__ = annotations
    # From Python 3.14, functools.wraps copies __annotate__ rather than __annotations__, and the MCP adapter wraps again.
    wrapper.__annotate__ = lambda format: annotations  # type: ignore[attr-defined]
    line = f"    {MY_CHANNEL}: {_MY_CHANNEL_DOC}"
    return f"{doc}\n{line}" if "\nArgs:" in doc else f"{doc}\n\nArgs:\n{line}"


def _with_note(doc: str, note: str) -> str:
    """Insert `note` as the last paragraph before the Args: section."""
    doc = inspect.cleandoc(doc)
    head, sep, args = doc.partition("\nArgs:")
    return f"{head.rstrip()}\n\n{note}\n{sep}{args}" if sep else f"{doc}\n\n{note}"
