"""The `@operation` decorator: marks a core function as part of the public surface.

It records transport-neutral metadata (quota cost, side effects, auth) that the
CLI and MCP adapters render in their own way, adds the quota cost to the
docstring both adapters publish, and translates API errors into domain errors so
neither adapter ever sees a googleapiclient exception.
"""

import functools
import inspect
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass

import httplib2
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError

from .errors import LOGIN_HINT, NetworkError, NotAuthorized, from_http_error

_NETWORK_ERRORS = (
    httplib2.HttpLib2Error,
    TransportError,
    ConnectionError,
    TimeoutError,
    socket.gaierror,
    ssl.SSLError,
)


@dataclass(frozen=True)
class OperationInfo:
    quota: int
    """Quota units per API request. Paginated operations make one request per page of 50."""
    read_only: bool
    destructive: bool
    """Overwrites existing data (as opposed to only adding new data)."""
    idempotent: bool
    oauth: bool
    """Acts as the authorized user rather than reading public data."""
    paginated: bool

    @property
    def quota_note(self) -> str:
        if self.quota == 0:
            return "Quota: no YouTube Data API units."
        units = f"{self.quota} unit{'s' if self.quota != 1 else ''}"
        return f"Quota: {units} per page of up to 50 results." if self.paginated else f"Quota: {units}."


OPERATIONS: list[Callable] = []
"""Every operation, in import order. Adapters must expose each one (enforced by tests)."""


def operation[**P, R](
    *,
    quota: int,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    oauth: bool = False,
    paginated: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        meta = OperationInfo(
            quota=quota,
            read_only=read_only,
            destructive=destructive,
            idempotent=idempotent,
            oauth=oauth,
            paginated=paginated,
        )

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return fn(*args, **kwargs)
            except HttpError as e:
                raise from_http_error(e) from e
            except RefreshError as e:
                raise NotAuthorized(f"OAuth token was rejected by Google ({e}). {LOGIN_HINT}") from e
            except _NETWORK_ERRORS as e:
                raise NetworkError(f"Could not reach YouTube ({type(e).__name__}: {e}). Retry later.") from e

        wrapper.__doc__ = _with_note(fn.__doc__ or "", meta.quota_note)
        wrapper.__operation__ = meta  # type: ignore[attr-defined]
        OPERATIONS.append(wrapper)
        return wrapper

    return decorate


def info(fn: Callable) -> OperationInfo:
    return fn.__operation__  # type: ignore[attr-defined]


def _with_note(doc: str, note: str) -> str:
    """Insert `note` as the last paragraph before the Args: section."""
    doc = inspect.cleandoc(doc)
    head, sep, args = doc.partition("\nArgs:")
    return f"{head.rstrip()}\n\n{note}\n{sep}{args}" if sep else f"{doc}\n\n{note}"
