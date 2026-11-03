from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from common.production_lines import configured_line_id, data_root, line_data_dir


@dataclass(frozen=True)
class AssistantConfig:
    wake_enabled: bool
    wake_word: str
    record_device: str
    playback_device: str
    sample_rate: int
    question_record_seconds: int
    wake_chunk_bytes: int
    vosk_model_path: Path
    dashboard_db_path: Path
    dashboard_url: str
    llm_provider: str
    deepseek_base_url: str
    deepseek_api_key: str
    deepseek_model: str
    deepseek_timeout_seconds: int
    deepseek_max_tokens: int
    deepseek_chunk_chars: int
    deepseek_chunk_max_tokens: int
    tts_command: str
    tts_provider: str
    edge_voice_zh: str
    edge_voice_en: str
    piper_voice_zh: str
    piper_voice_en: str
    piper_data_dir: Path
    tts_speed: float
    tts_leading_silence_ms: int
    wake_rearm_delay_seconds: float
    retrieval_limit: int
    production_line_id: int = 1


def load_config() -> AssistantConfig:
    wake_enabled = os.environ.get("VOICE_WAKE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    return AssistantConfig(
        production_line_id=configured_line_id(),
        wake_enabled=wake_enabled,
        wake_word=os.environ.get("VOICE_WAKE_WORD", "小助手").strip() or "小助手",
        record_device=os.environ.get("VOICE_RECORD_DEVICE", "plughw:3,0").strip(),
        playback_device=os.environ.get("VOICE_PLAYBACK_DEVICE", "plughw:CARD=vc4hdmi1,DEV=0").strip(),
        sample_rate=int(os.environ.get("VOICE_SAMPLE_RATE", "16000")),
        question_record_seconds=int(os.environ.get("VOICE_QUESTION_SECONDS", "5")),
        wake_chunk_bytes=int(os.environ.get("VOICE_WAKE_CHUNK_BYTES", "2048")),
        vosk_model_path=Path(
            os.environ.get(
                "VOICE_VOSK_MODEL_PATH",
                str(Path.home() / "models" / "vosk-model-small-cn-0.22"),
            )
        ).expanduser().resolve(),
        dashboard_db_path=line_data_dir(data_root(), configured_line_id()) / "dashboard.sqlite3",
        dashboard_url=os.environ.get("DASHBOARD_URL", "http://172.20.10.12:8000").strip(),
        llm_provider=os.environ.get("LLM_PROVIDER", "deepseek").strip().lower(),
        deepseek_base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
        deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY", "").strip(),
        deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
        deepseek_timeout_seconds=int(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "180")),
        deepseek_max_tokens=int(os.environ.get("DEEPSEEK_MAX_TOKENS", "2048")),
        deepseek_chunk_chars=int(os.environ.get("DEEPSEEK_DB_CHUNK_CHARS", "160000")),
        deepseek_chunk_max_tokens=int(os.environ.get("DEEPSEEK_CHUNK_MAX_TOKENS", "900")),
        tts_command=os.environ.get("TTS_COMMAND", "espeak-ng").strip(),
        tts_provider=os.environ.get("TTS_PROVIDER", "auto").strip().lower(),
        edge_voice_zh=os.environ.get("EDGE_TTS_VOICE_ZH", "zh-CN-XiaoxiaoNeural").strip(),
        edge_voice_en=os.environ.get("EDGE_TTS_VOICE_EN", "en-US-AriaNeural").strip(),
        piper_voice_zh=os.environ.get("PIPER_VOICE_ZH", "zh_CN-huayan-medium").strip(),
        piper_voice_en=os.environ.get("PIPER_VOICE_EN", "en_US-lessac-medium").strip(),
        piper_data_dir=Path(
            os.environ.get("PIPER_DATA_DIR", str(Path.home() / "piper_voices"))
        ).expanduser().resolve(),
        tts_speed=float(os.environ.get("TTS_SPEED", "0.92")),
        tts_leading_silence_ms=int(os.environ.get("TTS_LEADING_SILENCE_MS", "180")),
        wake_rearm_delay_seconds=float(os.environ.get("VOICE_WAKE_REARM_DELAY", "1.2")),
        retrieval_limit=int(os.environ.get("VOICE_DB_RETRIEVAL_LIMIT", "5")),
    )
