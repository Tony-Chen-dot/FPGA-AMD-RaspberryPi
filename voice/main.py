from __future__ import annotations

import time

from voice.service import AssistantService
from voice.config import load_config
from voice.status import AssistantStatus


def main() -> None:
    config = load_config()
    if not config.wake_enabled:
        print("Vosk 语音唤醒已关闭（VOICE_WAKE_ENABLED=0），不加载语音模型。")
        return

    from voice.speech.recognition import SpeechToTextModule
    from voice.speech.synthesis import TTSModule
    from voice.speech.wake_word import WakeWordModule

    status = AssistantStatus()
    wake = WakeWordModule(config)
    stt = SpeechToTextModule(config)
    assistant = AssistantService(config)
    tts = TTSModule(config)

    status.print_startup(config)
    status.mark("待命监听中")

    try:
        while True:
            result = wake.listen_once()
            print(f"识别到: {result.text}")
            status.mark("已唤醒")
            tts.speak("我在，请说")
            time.sleep(0.15)

            status.mark("录制问题中")
            print(f"开始录制问题，时长 {config.question_record_seconds} 秒...")
            question = stt.transcribe_once(seconds=config.question_record_seconds)
            retrieval = assistant.prepare_context(question)
            status.record_question(question, retrieval)

            if not question:
                status.mark("未听清，等待下一轮")
                tts.speak("我没有听清，请再试一次")
                continue

            status.mark("查询数据库并调用 AI 中")
            answer = assistant.answer(question, retrieval)
            status.record_answer(answer)
            status.mark("播报回答中")
            tts.speak(answer)
            if config.wake_rearm_delay_seconds > 0:
                status.mark(f"防误唤醒冷却中 {config.wake_rearm_delay_seconds:.1f} 秒")
                time.sleep(config.wake_rearm_delay_seconds)
            status.mark("待命监听中")
    except KeyboardInterrupt:
        print("\n已退出 AI 语音助手。")


if __name__ == "__main__":
    main()
