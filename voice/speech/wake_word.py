from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Iterator

from vosk import KaldiRecognizer, Model

from voice.config import AssistantConfig


@dataclass
class WakeWordResult:
    text: str
    triggered: bool


class WakeWordModule:
    def __init__(self, config: AssistantConfig) -> None:
        if not config.vosk_model_path.exists():
            raise RuntimeError(f"找不到 Vosk 模型: {config.vosk_model_path}")
        self.config = config
        self.model = Model(str(config.vosk_model_path))
        self.recognizer = KaldiRecognizer(self.model, config.sample_rate)

    def _reset_recognizer(self) -> None:
        self.recognizer = KaldiRecognizer(self.model, self.config.sample_rate)

    def _launch_arecord(self) -> subprocess.Popen[bytes]:
        cmd = [
            "arecord",
            "-D",
            self.config.record_device,
            "-f",
            "S16_LE",
            "-c",
            "1",
            "-r",
            str(self.config.sample_rate),
            "-t",
            "raw",
            "-q",
        ]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def iter_results(self) -> Iterator[WakeWordResult]:
        self._reset_recognizer()
        proc = self._launch_arecord()
        if proc.stdout is None:
            raise RuntimeError("arecord 没有输出")
        try:
            while True:
                chunk = proc.stdout.read(self.config.wake_chunk_bytes)
                if not chunk:
                    if proc.poll() is not None:
                        stderr = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
                        raise RuntimeError(f"arecord 退出: {stderr.strip()}")
                    continue
                if not self.recognizer.AcceptWaveform(chunk):
                    partial_payload = json.loads(self.recognizer.PartialResult())
                    partial_text = (partial_payload.get("partial") or "").strip()
                    if partial_text and self.config.wake_word in partial_text:
                        yield WakeWordResult(text=partial_text, triggered=True)
                    continue
                payload = json.loads(self.recognizer.Result())
                text = (payload.get("text") or "").strip()
                if not text:
                    continue
                yield WakeWordResult(text=text, triggered=self.config.wake_word in text)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()

    def listen_once(self) -> WakeWordResult:
        results = self.iter_results()
        try:
            for result in results:
                if result.triggered:
                    return result
        finally:
            results.close()
        raise RuntimeError("未检测到唤醒词")
