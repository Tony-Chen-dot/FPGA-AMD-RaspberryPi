from __future__ import annotations

import json
import subprocess

from vosk import KaldiRecognizer, Model

from voice.config import AssistantConfig


class SpeechToTextModule:
    def __init__(self, config: AssistantConfig) -> None:
        if not config.vosk_model_path.exists():
            raise RuntimeError(f"找不到 Vosk 模型: {config.vosk_model_path}")
        self.config = config
        self.model = Model(str(config.vosk_model_path))

    def transcribe_once(self, seconds: int | None = None) -> str:
        record_seconds = seconds or self.config.question_record_seconds
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
            "-d",
            str(record_seconds),
            "-t",
            "raw",
            "-q",
        ]
        raw = subprocess.check_output(cmd)
        recognizer = KaldiRecognizer(self.model, self.config.sample_rate)
        recognizer.AcceptWaveform(raw)
        payload = json.loads(recognizer.FinalResult())
        return (payload.get("text") or "").strip()
