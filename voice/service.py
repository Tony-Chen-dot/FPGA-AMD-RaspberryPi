from __future__ import annotations

from typing import Any
from dataclasses import replace
import json

from voice.config import AssistantConfig, load_config
from voice.dialogue.history import ConversationStore
from voice.context.inspection_context import DashboardContextBuilder, RetrievalContext
from voice.dialogue.model_client import LLMModule
from voice.speech.synthesis import TTSModule


class AssistantService:
    """One service used by both the continuous voice loop and the web chat."""

    def __init__(self, config: AssistantConfig | None = None) -> None:
        self.config = config or load_config()
        self.context_builder = DashboardContextBuilder(self.config.dashboard_db_path, self.config.retrieval_limit)
        self.llm = LLMModule(self.config)
        self.store = ConversationStore(self.config.dashboard_db_path)
        self._tts: TTSModule | None = None

    def _get_tts(self) -> TTSModule:
        if self._tts is None:
            self._tts = TTSModule(self.config)
        return self._tts

    def create_conversation(self, title: str = "新对话") -> dict[str, Any]:
        return self.store.create(title)

    def list_conversations(self) -> list[dict[str, Any]]:
        return self.store.list()

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        conversation = self.store.get(conversation_id)
        if conversation is None:
            return None
        conversation["messages"] = self.store.messages(conversation_id)
        return conversation

    def delete_conversation(self, conversation_id: str) -> bool:
        return self.store.delete(conversation_id)

    def database_status(self) -> dict[str, Any]:
        return self.context_builder.database_status()

    def prepare_context(self, question: str) -> RetrievalContext:
        retrieval = self.context_builder.build(question)
        payload = dict(retrieval.context_payload)
        payload["production_line"] = {"id": self.config.production_line_id,
                                      "scope": "仅当前产线，不代表其他产线或全厂"}
        return replace(retrieval, context_payload=payload,
                       context_text=json.dumps(payload, ensure_ascii=False, indent=2))

    def answer(
        self,
        question: str,
        retrieval: RetrievalContext,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        return self.llm.ask(question, retrieval, history=history)

    def chat(
        self,
        message: str,
        conversation_id: str | None = None,
        speak: bool = False,
    ) -> dict[str, Any]:
        question = (message or "").strip()
        if not question:
            raise ValueError("消息内容不能为空")
        conversation = self.store.get(conversation_id) if conversation_id else None
        if conversation is None:
            conversation = self.store.create()
            conversation_id = conversation["id"]
        assert conversation_id is not None

        history = [
            {"role": item["role"], "content": item["content"]}
            for item in self.store.messages(conversation_id, limit=24)
            if item["role"] in {"user", "assistant"}
        ]
        retrieval = self.prepare_context(question)
        answer = self.answer(
            question,
            retrieval,
            history=[*history, {"role": "user", "content": question}],
        )
        user_message = self.store.append(conversation_id, "user", question)
        assistant_message = self.store.append(
            conversation_id,
            "assistant",
            answer,
            metadata={
                "keywords": retrieval.keywords,
                "matched_labels": retrieval.matched_labels,
                "database": {
                    "records": len(retrieval.context_payload.get("inspection_records", [])),
                    "detections": len(retrieval.context_payload.get("detections", [])),
                },
            },
        )
        if speak:
            self._get_tts().speak(answer)
        refreshed = self.get_conversation(conversation_id) or conversation
        return {
            "conversation": refreshed,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "database_status": self.database_status(),
            "spoken": bool(speak),
        }

    def answer_for_voice(self, question: str) -> tuple[str, RetrievalContext]:
        retrieval = self.prepare_context(question)
        return self.answer(question, retrieval), retrieval
