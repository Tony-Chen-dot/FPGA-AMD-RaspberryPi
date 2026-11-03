from __future__ import annotations
import threading
import time
import cv2

class LatestFrameReader:
    def __init__(self, cap: cv2.VideoCapture) -> None:
        self.cap = cap
        self._condition = threading.Condition()
        self._latest_frame = None
        self._latest_preview_frame = None
        self._latest_sequence = 0
        self._running = False
        self._thread = threading.Thread(target=self._run, name="camera-latest-frame-reader", daemon=True)

    def start(self) -> None:
        self._running = True
        self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._running = False
            self._condition.notify_all()
        self._thread.join(timeout=1.0)

    def get_latest(self, last_sequence: int, timeout_seconds: float = 0.5):
        sequence, frame, _ = self.get_latest_with_preview(last_sequence, timeout_seconds)
        return sequence, frame

    def get_latest_with_preview(self, last_sequence: int, timeout_seconds: float = 0.5):
        deadline = time.monotonic() + max(0.05, timeout_seconds)
        with self._condition:
            while self._running and self._latest_sequence <= last_sequence:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            if self._latest_sequence <= last_sequence or self._latest_frame is None:
                return last_sequence, None, None
            return self._latest_sequence, self._latest_frame.copy(), self._latest_preview_frame.copy()

    def _run(self) -> None:
        while self._running:
            if hasattr(self.cap, "read_with_preview"):
                ok, frame, preview_frame = self.cap.read_with_preview()
            else:
                ok, frame = self.cap.read()
                preview_frame = frame
            if not ok or frame is None:
                time.sleep(0.02)
                continue
            with self._condition:
                self._latest_sequence += 1
                self._latest_frame = frame
                self._latest_preview_frame = preview_frame
                self._condition.notify_all()

