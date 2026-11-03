from __future__ import annotations

from dataclasses import dataclass

from voice.config import AssistantConfig
from voice.context.inspection_context import RetrievalContext


@dataclass
class AssistantStatus:
    state: str = "初始化中"
    last_transcript: str = ""
    last_keywords: list[str] | None = None
    last_answer: str = ""

    def print_startup(self, config: AssistantConfig) -> None:
        print("连续待机 AI 语音助手已启动")
        print(f"实时状态: {self.state}")
        print(f"唤醒词: {config.wake_word}")
        print(f"录音设备: {config.record_device}")
        print(f"播放设备: {config.playback_device}")
        print(f"问题录音时长: {config.question_record_seconds} 秒")
        print(f"数据库路径: {config.dashboard_db_path}")
        print(f"可视化页面: {config.dashboard_url}")
        print(f"联网模型提供方: {config.llm_provider}")
        print(f"DeepSeek 模型: {config.deepseek_model}")
        print("现在你可以反复说唤醒词进行测试。按 Ctrl+C 退出。")

    def mark(self, state: str) -> None:
        self.state = state
        print(f"实时状态: {self.state}")

    def record_question(self, transcript: str, retrieval: RetrievalContext) -> None:
        self.last_transcript = transcript
        self.last_keywords = retrieval.keywords
        print(f"问题转写: {transcript or '[空]'}")
        print(f"关键词: {', '.join(retrieval.keywords) or '无'}")
        if retrieval.matched_labels:
            print(f"匹配缺陷标签: {', '.join(retrieval.matched_labels)}")

    def record_answer(self, answer: str) -> None:
        self.last_answer = answer
        print("模型回答:")
        print(answer)
