from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[2]

from voice.service import AssistantService
from voice.config import load_config
from voice.dialogue.history import ConversationStore
from voice.context.inspection_context import DashboardContextBuilder
from voice.dialogue.model_client import LLMModule
from voice.dialogue.prompts import CHUNK_PROMPT, FINAL_ANSWER_PROMPT, PRODUCTION_BACKGROUND, SYSTEM_PROMPT


def make_database(path: Path, record_count: int = 3) -> None:
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE inspection_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                frame_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                result TEXT NOT NULL,
                defect_count INTEGER NOT NULL DEFAULT 0,
                inference_ms REAL NOT NULL DEFAULT 0,
                width INTEGER NOT NULL DEFAULT 1280,
                height INTEGER NOT NULL DEFAULT 720,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                x REAL NOT NULL DEFAULT 0,
                y REAL NOT NULL DEFAULT 0,
                w REAL NOT NULL DEFAULT 0,
                h REAL NOT NULL DEFAULT 0,
                normalized INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        for index in range(1, record_count + 1):
            is_ng = index % 2 == 0
            detections = [{"label": "划痕", "confidence": 0.9}] if is_ng else []
            payload = {
                "frame_id": f"frame-{index}",
                "result": "NG" if is_ng else "OK",
                "detections": detections,
                "notes": f"record-{index}",
            }
            cursor = conn.execute(
                """
                INSERT INTO inspection_records
                    (frame_id, ts, result, defect_count, inference_ms, width, height, payload_json)
                VALUES (?, ?, ?, ?, ?, 1280, 720, ?)
                """,
                (
                    f"frame-{index}",
                    f"2026-08-16T00:00:{index:02d}+00:00",
                    "NG" if is_ng else "OK",
                    1 if is_ng else 0,
                    10.0 + index,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            if is_ng:
                conn.execute(
                    """
                    INSERT INTO detections (record_id, label, confidence, x, y, w, h, normalized)
                    VALUES (?, '划痕', 0.9, 0.1, 0.2, 0.3, 0.4, 1)
                    """,
                    (cursor.lastrowid,),
                )


class VoiceAssistantTests(unittest.TestCase):
    def make_config(self, db_path: Path):
        return replace(
            load_config(),
            dashboard_db_path=db_path,
            deepseek_api_key="test-key",
            deepseek_chunk_chars=20000,
        )

    def test_prompt_is_aluminum_sorting_specific(self) -> None:
        self.assertIn("铝片智能分拣系统", SYSTEM_PROMPT)
        self.assertIn("优先准确理解并直接回答用户当前的 question", SYSTEM_PROMPT)
        self.assertIn("问候、身份、能力或使用方式", SYSTEM_PROMPT)
        self.assertIn("建议最多三条", SYSTEM_PROMPT)
        self.assertIn("置信度表示模型对检测标签的确信程度", SYSTEM_PROMPT)
        self.assertIn("本分片与当前问题无关", CHUNK_PROMPT)
        self.assertIn("不要因为收到了全量数据库就自动输出全库报告", FINAL_ANSWER_PROMPT)

    def test_single_request_prioritizes_the_current_question(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "dashboard.sqlite3"
            make_database(db_path)
            config = self.make_config(db_path)
            context = DashboardContextBuilder(db_path).build("你是谁")
            llm = LLMModule(config)
            with patch.object(llm, "_request", return_value="我是铝片分拣 AI 助手。") as request:
                answer = llm.ask("你是谁", context)

        messages = request.call_args.args[0]
        payload = json.loads(messages[-1]["content"])
        self.assertEqual(answer, "我是铝片分拣 AI 助手。")
        self.assertEqual(payload["question"], "你是谁")
        self.assertEqual(payload["answer_instruction"], FINAL_ANSWER_PROMPT)
        self.assertEqual(len(payload["database_full_payload"]["inspection_records"]["rows"]), 3)

    def test_assistant_input_typography_matches_answer_content(self) -> None:
        css = (ROOT_DIR / "dashboard" / "web" / "css" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn(".assistant-message-content,\n.assistant-composer textarea", css)
        self.assertIn("font-family: inherit;\n  font-size: 16px;\n  line-height: 1.75;", css)

    def test_assistant_messages_render_sanitized_markdown(self) -> None:
        static_dir = ROOT_DIR / "dashboard" / "web"
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        javascript = (static_dir / "js" / "dashboard.js").read_text(encoding="utf-8")
        css = (static_dir / "css" / "dashboard.css").read_text(encoding="utf-8")

        self.assertIn('v-html="renderAssistantMarkdown(message.content)"', html)
        self.assertIn('<div v-else class="assistant-message-content">{{ message.content }}</div>', html)
        self.assertLess(html.index("/static/vendor/marked.min.js"), html.index("/static/js/dashboard.js"))
        self.assertLess(html.index("/static/vendor/purify.min.js"), html.index("/static/js/dashboard.js"))
        self.assertIn("window.marked.parse", javascript)
        self.assertIn("window.DOMPurify.sanitize", javascript)
        self.assertIn("USE_PROFILES: { html: true }", javascript)
        self.assertIn('FORBID_TAGS: ["style", "form", "input", "button", "textarea"', javascript)
        self.assertIn('FORBID_ATTR: ["style", "srcset"]', javascript)
        for selector in (
            ".markdown-content h1",
            ".markdown-content ul",
            ".markdown-content blockquote",
            ".markdown-content pre",
            ".markdown-content table",
        ):
            self.assertIn(selector, css)
        for vendor_file in ("marked.min.js", "purify.min.js"):
            self.assertGreater((static_dir / "vendor" / vendor_file).stat().st_size, 10_000)

    def test_prompt_includes_realistic_aluminum_production_background(self) -> None:
        for phrase in ("精炼、除气和过滤", "半连续铸锭", "连续铸轧", "多道次冷轧", "成品退火", "圆形铝片", "冲裁成形"):
            self.assertIn(phrase, PRODUCTION_BACKGROUND)
        self.assertIn("缺陷与工序的排查关系只能作为待验证假设", PRODUCTION_BACKGROUND)
        self.assertIn("不能把上述行业背景写成已经确认的现场事实", PRODUCTION_BACKGROUND)
        self.assertIn(PRODUCTION_BACKGROUND, SYSTEM_PROMPT)

    def test_quick_prompts_fill_the_current_assistant_composer(self) -> None:
        static_dir = ROOT_DIR / "dashboard" / "web"
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        javascript = (static_dir / "js" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("快捷提问", html)
        self.assertIn('ref="assistantInputEl"', html)
        self.assertIn('@click="useAssistantQuickPrompt(item.prompt)"', html)
        for label in ("当前良率", "缺陷排行", "近期异常", "问题排查", "工艺优化", "识别可靠性"):
            self.assertIn(f'label: "{label}"', javascript)
        self.assertIn("useAssistantQuickPrompt(prompt)", javascript)
        self.assertIn("this.assistantInput = prompt", javascript)
        self.assertIn("input.focus()", javascript)
        self.assertIn('new URLSearchParams(window.location.search).get("view")', javascript)

    def test_database_chunks_preserve_every_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "dashboard.sqlite3"
            make_database(db_path, record_count=8)
            config = self.make_config(db_path)
            context = DashboardContextBuilder(db_path).build("分析全部记录")
            llm = LLMModule(config)
            compact = llm._compact_database_payload(context.context_payload)
            chunks = llm._database_chunks(compact)

        if len(chunks) == 1:
            record_rows = chunks[0]["inspection_records"]["rows"]
            detection_rows = chunks[0]["detections"]["rows"]
        else:
            record_rows = [row for chunk in chunks if chunk["table"] == "inspection_records" for row in chunk["rows"]]
            detection_rows = [row for chunk in chunks if chunk["table"] == "detections" for row in chunk["rows"]]
        self.assertEqual(len(record_rows), 8)
        self.assertEqual(len(detection_rows), 4)
        self.assertEqual({row[1] for row in record_rows}, {f"frame-{index}" for index in range(1, 9)})

    def test_conversations_and_messages_persist_in_dashboard_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "dashboard.sqlite3"
            make_database(db_path)
            store = ConversationStore(db_path)
            conversation = store.create()
            store.append(conversation["id"], "user", "请分析划痕")
            store.append(conversation["id"], "assistant", "划痕记录为一条。")

            reloaded = ConversationStore(db_path).get(conversation["id"])
            messages = ConversationStore(db_path).messages(conversation["id"])

        self.assertEqual(reloaded["message_count"], 2)
        self.assertEqual(reloaded["title"], "请分析划痕")
        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])

    def test_service_uses_full_context_before_persisting_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "dashboard.sqlite3"
            make_database(db_path, record_count=5)
            service = AssistantService(self.make_config(db_path))
            conversation = service.create_conversation()
            with patch.object(service.llm, "ask", return_value="基于五条记录的回答。") as ask:
                result = service.chat("分析全部数据", conversation["id"])

        retrieval = ask.call_args.args[1]
        self.assertEqual(len(retrieval.context_payload["inspection_records"]), 5)
        self.assertEqual(result["conversation"]["message_count"], 2)
        self.assertEqual(result["assistant_message"]["metadata"]["database"]["records"], 5)


if __name__ == "__main__":
    unittest.main()
