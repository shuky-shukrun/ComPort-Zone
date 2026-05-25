"""Windows advisory file lock used to serialize settings.json writes across
processes (e.g. GUI + concurrent CLI invocations).

On non-Windows platforms the lock is a no-op so the module stays importable
in cross-platform test runners. ComPort Zone itself is Windows-only at
runtime, so this is purely a test-ergonomics affordance.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def settings_advisory_lock(lock_path: Path) -> Iterator[None]:
    """Acquire an exclusive advisory lock on ``lock_path`` for the duration
    of the context. The lock file is created if missing and is *not* deleted
    on exit (standard advisory-lock practice — keeping the inode stable
    prevents lock-file churn races between concurrent writers).
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform != "win32":
        yield
        return

    import msvcrt  # local import: no-op on non-Windows code paths

    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
    finally:
        os.close(fd)
