"""One live process at a time: an exclusive OS lock on ``<data_dir>/live/live.lock``, held for the process's lifetime and
released by the OS when it exits (also on a crash), so a stale lock file can never block a restart. The Task Scheduler
watchdog starts ``arven live run`` every few minutes; a second copy sees the lock and exits at once."""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO


def acquire(path: Path) -> IO[str] | None:
    """The open, locked file (keep a reference for the process's lifetime), or ``None`` if another process holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")  # noqa: SIM115 - must stay open while the process runs
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


__all__ = ["acquire"]
