"""Transport-neutral YouTube Data API core. No printing, no exit codes, no MCP.

Operations live in `core.ops.<noun>` modules; importing this package registers them all in OPERATIONS.
"""

from . import ops as ops
from .errors import (
    ConfirmationRequired,
    Forbidden,
    InvalidRequest,
    NetworkError,
    NotAuthorized,
    NotFound,
    Protected,
    QuotaExceeded,
    TimedOut,
    YouTubeError,
)
from .operation import OPERATIONS, OperationInfo, info

__all__ = [
    "OPERATIONS",
    "ConfirmationRequired",
    "Forbidden",
    "InvalidRequest",
    "NetworkError",
    "NotAuthorized",
    "NotFound",
    "OperationInfo",
    "Protected",
    "QuotaExceeded",
    "TimedOut",
    "YouTubeError",
    "info",
    "ops",
]
