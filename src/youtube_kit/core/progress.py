"""Progress reporting for long operations, decoupled from how it is displayed.

Adapters install a reporter for the duration of a call; core code calls `report()`.
A ContextVar (not a parameter) keeps reporters out of operation signatures, which
both adapters turn into their public schema.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

type Reporter = Callable[[int, int], None]
"""Called with (done, total) in bytes or items."""

_reporter: ContextVar[Reporter | None] = ContextVar("youtube_kit_progress", default=None)


@contextmanager
def reporting_to(reporter: Reporter) -> Iterator[None]:
    token = _reporter.set(reporter)
    try:
        yield
    finally:
        _reporter.reset(token)


def report(done: int, total: int) -> None:
    if (reporter := _reporter.get()) is not None:
        reporter(done, total)
