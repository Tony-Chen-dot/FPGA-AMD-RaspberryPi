from __future__ import annotations

import json
from typing import Any

import requests

from voice.config import AssistantConfig
from voice.context.inspection_context import RetrievalContext
from voice.dialogue.prompts import CHUNK_PROMPT, FINAL_ANSWER_PROMPT, SYSTEM_PROMPT


class LLMModule:
    def __init__(self, config: AssistantConfig) -> None:
        self.config = config

    def ask(
        self,
        question: str,
        retrieval: RetrievalContext,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        if self.config.llm_provider != "deepseek":
            raise RuntimeError(f"当前仅实现 deepseek 联网模式，收到 provider={self.config.llm_provider}")
        if not self.config.deepseek_api_key:
            raise RuntimeError("未设置 DEEPSEEK_API_KEY，无法调用 DeepSeek API。")

        compact_payload = self._compact_database_payload(retrieval.context_payload)
        chunks = self._database_chunks(compact_payload)
        history_messages = self._normalize_history(history or [], question)
        if len(chunks) == 1:
            return self._ask_with_complete_payload(question, retrieval, chunks[0], history_messages)

        chunk_analyses: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks, start=1):
            chunk_request = {
                "task": CHUNK_PROMPT,
                "question": question,
                "answer_priority": FINAL_ANSWER_PROMPT,
                "chunk_index": index,
                "chunk_total": len(chunks),
                "database_chunk": chunk,
            }
            chunk_answer = self._request(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    *history_messages,
                    {"role": "user", "content": json.dumps(chunk_request, ensure_ascii=False)},
                ],
                max_tokens=self.config.deepseek_chunk_max_tokens,
            )
            chunk_analyses.append({"chunk_index": index, "analysis": chunk_answer})

        user_payload = {
            "question": question,
            "answer_instruction": FINAL_ANSWER_PROMPT,
            "keywords": retrieval.keywords,
            "matched_labels": retrieval.matched_labels,
            "database_context_text": retrieval.context_text,
            "database_delivery": {
                "mode": "all_rows_chunked",
                "chunk_count": len(chunks),
                "inspection_record_count": len(compact_payload["inspection_records"]["rows"]),
                "detection_count": len(compact_payload["detections"]["rows"]),
                "instruction": "以上每个分片已经由同一模型逐一读取；请综合所有相关证据，但最终只回答当前 question。",
            },
            "database_chunk_analyses": chunk_analyses,
        }
        return self._request(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                *history_messages,
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ]
        )

    def _ask_with_complete_payload(
        self,
        question: str,
        retrieval: RetrievalContext,
        compact_payload: dict[str, Any],
        history_messages: list[dict[str, str]],
    ) -> str:
        user_payload = {
            "question": question,
            "answer_instruction": FINAL_ANSWER_PROMPT,
            "keywords": retrieval.keywords,
            "matched_labels": retrieval.matched_labels,
            "database_context_text": retrieval.context_text,
            "database_delivery": {"mode": "all_rows_single_request", "chunk_count": 1},
            "database_full_payload": compact_payload,
        }
        return self._request(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                *history_messages,
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ]
        )

    def _request(self, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        response = requests.post(
            f"{self.config.deepseek_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.deepseek_model,
                "messages": messages,
                "thinking": {"type": "disabled"},
                "max_tokens": max_tokens or self.config.deepseek_max_tokens,
                "stream": False,
            },
            timeout=self.config.deepseek_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            return "DeepSeek 没有返回可播报的回答。"
        message = choices[0].get("message") or {}
        return (message.get("content") or "").strip() or "DeepSeek 没有返回可播报的回答。"

    def _normalize_history(
        self,
        history: list[dict[str, str]],
        question: str,
    ) -> list[dict[str, str]]:
        normalized = [
            {"role": item.get("role", "user"), "content": (item.get("content") or "").strip()}
            for item in history[-24:]
            if item.get("role") in {"user", "assistant"} and (item.get("content") or "").strip()
        ]
        if normalized and normalized[-1]["role"] == "user" and normalized[-1]["content"] == question:
            normalized.pop()
        return normalized

    def _compact_database_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        inspection_columns = [
            "id",
            "frame_id",
            "ts",
            "result",
            "defect_count",
            "inference_ms",
            "width",
            "height",
            "payload",
        ]
        detection_columns = [
            "id",
            "record_id",
            "label",
            "confidence",
            "x",
            "y",
            "w",
            "h",
            "normalized",
        ]
        return {
            "db_exists": bool(payload.get("db_exists")),
            "summary": payload.get("summary") or {},
            "inspection_records": {
                "columns": inspection_columns,
                "rows": [
                    [item.get(column) for column in inspection_columns]
                    for item in payload.get("inspection_records") or []
                ],
            },
            "detections": {
                "columns": detection_columns,
                "rows": [
                    [item.get(column) for column in detection_columns]
                    for item in payload.get("detections") or []
                ],
            },
        }

    def _database_chunks(self, compact_payload: dict[str, Any]) -> list[dict[str, Any]]:
        chunk_limit = max(20000, self.config.deepseek_chunk_chars)
        chunks: list[dict[str, Any]] = []
        for table_name in ("inspection_records", "detections"):
            table = compact_payload[table_name]
            columns = table["columns"]
            current_rows: list[list[Any]] = []
            current_size = 0
            for row in table["rows"]:
                row_size = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                if current_rows and current_size + row_size > chunk_limit:
                    chunks.append(
                        {
                            "table": table_name,
                            "columns": columns,
                            "rows": current_rows,
                        }
                    )
                    current_rows = []
                    current_size = 0
                current_rows.append(row)
                current_size += row_size
            if current_rows or not table["rows"]:
                chunks.append({"table": table_name, "columns": columns, "rows": current_rows})

        if len(chunks) == 2:
            single_payload = {
                "db_exists": compact_payload["db_exists"],
                "summary": compact_payload["summary"],
                "inspection_records": compact_payload["inspection_records"],
                "detections": compact_payload["detections"],
            }
            if len(json.dumps(single_payload, ensure_ascii=False, separators=(",", ":"))) <= chunk_limit:
                return [single_payload]
        for chunk in chunks:
            chunk["summary"] = compact_payload["summary"]
        return chunks
