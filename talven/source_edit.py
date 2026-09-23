"""Explicit in-place formatting for a trusted, single-writer workspace.

Freshness checks catch observed changes. The final check and os.replace are
not an atomic compare-and-swap; another writer must be coordinated externally.
"""

import os
from pathlib import Path
import stat
import tempfile

from .frontend import CompileError, MAX_SOURCE_BYTES, Span


def read_regular(path: Path) -> tuple[bytes, os.stat_result]:
    """Read up to one byte past the source limit from a regular file.

    The nonblocking open keeps a FIFO or device path from hanging the caller.
    """
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise CompileError("E0901", "Source must be a regular file", Span(0, 0))
        return stream.read(MAX_SOURCE_BYTES + 1), metadata


def writable_source(path: Path) -> os.stat_result:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise CompileError("E0603", "In-place formatting requires a regular file with exactly one link", Span(0, 0))
    return metadata


def replace_source(path: Path, original: bytes, formatted: str, snapshot: os.stat_result):
    def unchanged():
        current = writable_source(path)
        if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_mode) != (
                snapshot.st_dev, snapshot.st_ino, snapshot.st_mtime_ns, snapshot.st_mode):
            raise CompileError("E0501", "Source changed before formatting could be written", Span(0, 0))
        with path.open("rb") as stream:
            if stream.read(MAX_SOURCE_BYTES + 1) != original:
                raise CompileError("E0501", "Source changed before formatting could be written", Span(0, 0))

    unchanged()
    if original == formatted.encode("utf-8"):
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".talven-format-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(formatted.encode("utf-8"))
        os.chmod(temporary, stat.S_IMODE(snapshot.st_mode))
        unchanged()
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
