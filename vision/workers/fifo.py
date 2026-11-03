from __future__ import annotations
import threading
from queue import Empty, Full, Queue

WORKER_STOP = object()


class BoundedFifoWorker:
    """Single-consumer bounded FIFO used for deterministic competition timing."""

    def __init__(
        self,
        name: str,
        capacity: int,
        handler,
        error_handler,
        *,
        capacity_includes_active: bool = False,
    ) -> None:
        self.name = name
        self._capacity = max(1, int(capacity))
        self._capacity_includes_active = bool(capacity_includes_active)
        self.queue: Queue = Queue(maxsize=self._capacity)
        self.handler = handler
        self.error_handler = error_handler
        self._state_lock = threading.Lock()
        self._active = 0
        self._in_flight = 0
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)
        self.thread.start()

    @property
    def depth(self) -> int:
        return self.queue.qsize()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def active(self) -> int:
        with self._state_lock:
            return self._active

    @property
    def in_flight(self) -> int:
        with self._state_lock:
            return self._in_flight

    def submit(self, item, accepted_handler=None) -> bool:
        with self._state_lock:
            if self._capacity_includes_active and self._in_flight >= self._capacity:
                return False
            self._in_flight += 1
            in_flight = self._in_flight
        if accepted_handler is not None:
            try:
                accepted_handler(in_flight, self.queue.qsize() + 1)
            except Exception:
                with self._state_lock:
                    self._in_flight -= 1
                raise
        try:
            self.queue.put_nowait(item)
            return True
        except Full:
            with self._state_lock:
                self._in_flight -= 1
            return False

    def _run(self) -> None:
        while True:
            try:
                item = self.queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                if item is WORKER_STOP:
                    return
                with self._state_lock:
                    self._active += 1
                self.handler(item)
            except Exception as exc:
                self.error_handler(self.name, exc)
            finally:
                if item is not WORKER_STOP:
                    with self._state_lock:
                        self._active -= 1
                        self._in_flight -= 1
                self.queue.task_done()

    def close(self, timeout_seconds: float = 1.0) -> None:
        try:
            self.queue.put_nowait(WORKER_STOP)
        except Full:
            return
        self.thread.join(timeout=max(0.0, timeout_seconds))

