from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import threading
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows test fallback
    fcntl = None


DEFAULT_HARDWARE_LOCK_PATH = "/tmp/raspberry-arm-pump.lock"
_fallback_locks: dict[str, threading.RLock] = {}
_fallback_locks_guard = threading.Lock()


def hardware_lock_path() -> str:
    return os.environ.get("ARM_HARDWARE_LOCK_PATH", DEFAULT_HARDWARE_LOCK_PATH)


@contextmanager
def hardware_operation_lock(path: str | None = None) -> Iterator[None]:
    """Serialize arm/pump operations across production and dashboard processes."""

    lock_path = str(Path(path or hardware_lock_path()))
    if fcntl is None:
        with _fallback_locks_guard:
            lock = _fallback_locks.setdefault(lock_path, threading.RLock())
        with lock:
            yield
        return

    target = Path(lock_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
