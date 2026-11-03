from __future__ import annotations

import asyncio
import contextlib
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from voice.config import AssistantConfig

try:
    import edge_tts
except Exception:
    edge_tts = None

try:
    from piper import PiperVoice, SynthesisConfig
except Exception:
    PiperVoice = None
    SynthesisConfig = None


class TTSModule:
    def __init__(self, config: AssistantConfig) -> None:
        self.config = config
        self._piper_cache: dict[str, PiperVoice] = {}

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        provider = self.config.tts_provider
        if provider == "piper":
            self._speak_with_piper(text)
            return
        if provider == "edge":
            self._speak_with_edge(text)
            return
        if provider == "espeak":
            self._speak_with_espeak(text)
            return

        if self._can_use_piper():
            try:
                self._speak_with_piper(text)
                return
            except Exception as exc:
                print(f"piper 播报失败，自动切换其他方案: {exc}")

        if self._can_use_edge():
            try:
                self._speak_with_edge(text)
                return
            except Exception as exc:
                print(f"edge-tts 播报失败，自动切换 espeak-ng: {exc}")

        self._speak_with_espeak(text)

    def _can_use_piper(self) -> bool:
        return PiperVoice is not None and SynthesisConfig is not None and shutil.which("aplay") is not None

    def _can_use_edge(self) -> bool:
        return edge_tts is not None and shutil.which("ffmpeg") is not None and shutil.which("aplay") is not None

    def _is_chinese_text(self, text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _choose_edge_voice(self, text: str) -> str:
        if self._is_chinese_text(text):
            return self.config.edge_voice_zh
        return self.config.edge_voice_en

    def _choose_piper_voice_name(self, text: str) -> str:
        if self._is_chinese_text(text):
            return self.config.piper_voice_zh
        return self.config.piper_voice_en

    def _piper_voice_path(self, voice_name: str) -> Path:
        return self.config.piper_data_dir / f"{voice_name}.onnx"

    def _piper_config_path(self, voice_name: str) -> Path:
        return self.config.piper_data_dir / f"{voice_name}.onnx.json"

    def _find_existing_piper_onnx(self, voice_name: str) -> Path | None:
        expected = self._piper_voice_path(voice_name)
        if expected.exists():
            return expected
        for path in self.config.piper_data_dir.rglob("*.onnx"):
            if path.stem.lower() == voice_name.lower():
                return path
        return None

    def _find_existing_piper_json(self, voice_name: str) -> Path | None:
        expected = self._piper_config_path(voice_name)
        if expected.exists():
            return expected
        for path in self.config.piper_data_dir.rglob("*.onnx.json"):
            if path.stem.lower() == f"{voice_name}.onnx".lower():
                return path
        return None

    def _voice_exists(self, voice_name: str) -> bool:
        return self._find_existing_piper_onnx(voice_name) is not None

    def _resolve_piper_voice_name(self, requested_voice_name: str) -> str:
        if self._voice_exists(requested_voice_name):
            return requested_voice_name
        if requested_voice_name != self.config.piper_voice_zh and self._voice_exists(self.config.piper_voice_zh):
            print(f"Piper 英文音色缺失，自动回退到中文音色: {self.config.piper_voice_zh}")
            return self.config.piper_voice_zh
        if requested_voice_name != self.config.piper_voice_en and self._voice_exists(self.config.piper_voice_en):
            print(f"Piper 中文音色缺失，自动回退到英文音色: {self.config.piper_voice_en}")
            return self.config.piper_voice_en
        available = sorted(path.stem for path in self.config.piper_data_dir.rglob("*.onnx"))
        if available:
            print(f"Piper 请求音色不存在，自动改用目录中的第一个音色: {available[0]}")
            return available[0]
        raise RuntimeError(
            f"Piper 音色目录为空: {self.config.piper_data_dir}。"
            f"当前至少需要放入 {self.config.piper_voice_zh}.onnx 和对应的 .onnx.json"
        )

    def _speed_scale(self) -> float:
        return min(1.5, max(0.7, self.config.tts_speed))

    def _length_scale(self) -> float:
        return 1.0 / self._speed_scale()

    def _audio_filter(self) -> str:
        filters: list[str] = []
        if self.config.tts_leading_silence_ms > 0:
            filters.append(f"adelay={self.config.tts_leading_silence_ms}:all=1")
        filters.append(f"atempo={self._speed_scale()}")
        return ",".join(filters)

    def _play_wav_stream(self, stream) -> None:
        proc = subprocess.run(
            ["aplay", "-D", self.config.playback_device, "-q"],
            stdin=stream,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or b"").decode("utf-8", errors="ignore").strip()
            raise RuntimeError(detail or "aplay 播放失败")

    def _play_wav_file(self, wav_path: Path) -> None:
        if shutil.which("ffmpeg"):
            decode_proc = subprocess.Popen(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(wav_path),
                    "-filter:a",
                    self._audio_filter(),
                    "-f",
                    "wav",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                self._play_wav_stream(decode_proc.stdout)
            finally:
                if decode_proc.stdout is not None:
                    decode_proc.stdout.close()
            stderr = decode_proc.stderr.read() if decode_proc.stderr is not None else b""
            decode_proc.wait(timeout=20)
            if decode_proc.returncode != 0:
                detail = stderr.decode("utf-8", errors="ignore").strip()
                raise RuntimeError(detail or "ffmpeg 解码失败")
            return

        proc = subprocess.run(
            ["aplay", "-D", self.config.playback_device, "-q", str(wav_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(detail or "aplay 播放失败")

    def _load_piper_voice(self, voice_name: str) -> PiperVoice:
        if voice_name not in self._piper_cache:
            voice_path = self._find_existing_piper_onnx(voice_name)
            config_path = self._find_existing_piper_json(voice_name)
            if voice_path is None or config_path is None:
                raise RuntimeError(f"找不到 Piper 音色文件或配置: {voice_name}")
            print(f"Piper 正在使用音色文件: {voice_path}")
            print(f"Piper 正在使用配置文件: {config_path}")
            self._piper_cache[voice_name] = PiperVoice.load(str(voice_path), config_path=str(config_path))
        return self._piper_cache[voice_name]

    def _speak_with_piper(self, text: str) -> None:
        if not self._can_use_piper():
            raise RuntimeError("当前环境无法使用 piper")
        voice_name = self._resolve_piper_voice_name(self._choose_piper_voice_name(text))
        voice = self._load_piper_voice(voice_name)
        synth_config = SynthesisConfig(length_scale=self._length_scale())

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            with wave.open(str(wav_path), "wb") as wav_file:
                voice.synthesize_wav(text, wav_file, syn_config=synth_config)
            self._play_wav_file(wav_path)
        finally:
            wav_path.unlink(missing_ok=True)

    async def _save_edge_audio(self, text: str, target: Path) -> None:
        voice = self._choose_edge_voice(text)
        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(str(target))

    def _speak_with_edge(self, text: str) -> None:
        if edge_tts is None:
            raise RuntimeError("当前环境没有安装 edge-tts")
        if not shutil.which("ffmpeg") or not shutil.which("aplay"):
            raise RuntimeError("系统缺少 ffmpeg 或 aplay")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            temp_path = Path(tmp.name)
        try:
            asyncio.run(self._save_edge_audio(text, temp_path))
            decode_proc = subprocess.Popen(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(temp_path),
                    "-filter:a",
                    self._audio_filter(),
                    "-f",
                    "wav",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                self._play_wav_stream(decode_proc.stdout)
            finally:
                if decode_proc.stdout is not None:
                    decode_proc.stdout.close()
            stderr = decode_proc.stderr.read() if decode_proc.stderr is not None else b""
            decode_proc.wait(timeout=20)
            if decode_proc.returncode != 0:
                detail = stderr.decode("utf-8", errors="ignore").strip()
                raise RuntimeError(detail or "ffmpeg 解码失败")
        finally:
            temp_path.unlink(missing_ok=True)

    def _speak_with_espeak(self, text: str) -> None:
        if not shutil.which(self.config.tts_command):
            if shutil.which("say"):
                subprocess.run(["say", text], check=False)
                return
            raise RuntimeError("既没有 piper、edge-tts，也没有 espeak-ng 或 say")

        voice = "zh" if self._is_chinese_text(text) else "en-us"
        if shutil.which("ffmpeg") and shutil.which("aplay"):
            espeak_proc = subprocess.Popen(
                [self.config.tts_command, "-v", voice, "--stdout", text],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            decode_proc = subprocess.Popen(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "wav",
                    "-i",
                    "-",
                    "-filter:a",
                    self._audio_filter(),
                    "-f",
                    "wav",
                    "-",
                ],
                stdin=espeak_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                self._play_wav_stream(decode_proc.stdout)
            finally:
                if espeak_proc.stdout is not None:
                    espeak_proc.stdout.close()
                if decode_proc.stdout is not None:
                    decode_proc.stdout.close()

            espeak_stderr = espeak_proc.stderr.read() if espeak_proc.stderr is not None else b""
            decode_stderr = decode_proc.stderr.read() if decode_proc.stderr is not None else b""
            with contextlib.suppress(subprocess.TimeoutExpired):
                espeak_proc.wait(timeout=10)
            with contextlib.suppress(subprocess.TimeoutExpired):
                decode_proc.wait(timeout=10)
            if espeak_proc.returncode == 0 and decode_proc.returncode == 0:
                return
            detail = (
                decode_stderr.decode("utf-8", errors="ignore").strip()
                or espeak_stderr.decode("utf-8", errors="ignore").strip()
            )
            raise RuntimeError(detail or "espeak-ng/aplay 播放失败")

        subprocess.run([self.config.tts_command, "-v", voice, text], check=False)
