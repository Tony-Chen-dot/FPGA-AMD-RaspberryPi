from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LABEL_KEYWORDS = {
    "脏污": ["脏污", "污渍", "脏", "污染"],
    "折皱": ["折皱", "褶皱", "褶子", "折痕"],
    "划痕": ["划痕", "刮痕", "划伤", "裂痕"],
    "针孔": ["针孔", "小孔", "孔洞"],
    "擦伤": ["擦伤", "磨损", "磨伤"],
}

METRIC_KEYWORDS = {
    "summary": ["总数", "统计", "汇总", "良率", "产量", "多少", "总共"],
    "latest": ["最新", "最近", "刚才", "上一条", "最后一次"],
    "distribution": ["分布", "最多", "哪种", "常见", "缺陷类型"],
    "trend": ["趋势", "变化", "近", "小时"],
    "device": ["设备", "在线", "离线", "连接", "板子", "状态"],
    "ok_ng": ["ok", "ng", "合格", "不合格", "坏品", "良品"],
}


@dataclass(frozen=True)
class RetrievalContext:
    keywords: list[str]
    matched_labels: list[str]
    context_text: str
    context_payload: dict[str, Any]


class DashboardContextBuilder:
    def __init__(self, db_path: Path, retrieval_limit: int = 5) -> None:
        self.db_path = db_path
        self.retrieval_limit = retrieval_limit

    def build(self, transcript: str) -> RetrievalContext:
        text = (transcript or "").strip()
        keywords = self._extract_keywords(text)
        if not self.db_path.exists():
            return RetrievalContext(
                keywords=keywords,
                matched_labels=self._match_labels(text),
                context_text="数据库文件不存在，当前无法提供检测记录上下文。",
                context_payload={"db_exists": False, "summary": {}, "inspection_records": [], "detections": []},
            )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            full_payload = self._build_full_payload(conn)
            sections = [
                self._build_summary(conn),
                self._build_latest(conn),
                self._build_distribution(conn),
                f"全库数据概况: inspection_records={len(full_payload['inspection_records'])}, detections={len(full_payload['detections'])}",
            ]
            matched_labels = self._match_labels(text)
            if matched_labels:
                sections.append(self._build_label_records(conn, matched_labels))
            if any(keyword in text for keyword in METRIC_KEYWORDS["trend"]):
                sections.append(self._build_trend(conn))
            if any(keyword in text for keyword in METRIC_KEYWORDS["ok_ng"]):
                sections.append(self._build_result_breakdown(conn))
            sections.append(self._build_recent_records(conn))

        context_text = "\n\n".join(section for section in sections if section)
        return RetrievalContext(
            keywords=keywords,
            matched_labels=matched_labels,
            context_text=context_text or "数据库当前没有可用记录。",
            context_payload=full_payload,
        )

    def database_status(self) -> dict[str, Any]:
        """Return lightweight metadata for the UI without exporting every row."""
        if not self.db_path.exists():
            return {
                "db_exists": False,
                "path": str(self.db_path),
                "record_count": 0,
                "detection_count": 0,
                "last_ts": None,
            }
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            record_row = conn.execute(
                "SELECT COUNT(*) AS total_count, MAX(ts) AS last_ts FROM inspection_records"
            ).fetchone()
            detection_row = conn.execute("SELECT COUNT(*) AS total_count FROM detections").fetchone()
        return {
            "db_exists": True,
            "path": str(self.db_path),
            "record_count": int(record_row["total_count"] or 0),
            "detection_count": int(detection_row["total_count"] or 0),
            "last_ts": record_row["last_ts"],
        }

    def _build_full_payload(self, conn: sqlite3.Connection) -> dict[str, Any]:
        summary_row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN result = 'OK' THEN 1 ELSE 0 END) AS good_count,
                SUM(CASE WHEN result = 'NG' THEN 1 ELSE 0 END) AS bad_count,
                AVG(inference_ms) AS avg_inference_ms,
                MIN(ts) AS first_ts,
                MAX(ts) AS last_ts
            FROM inspection_records
            """
        ).fetchone()
        summary = {
            "total_count": int(summary_row["total_count"] or 0),
            "good_count": int(summary_row["good_count"] or 0),
            "bad_count": int(summary_row["bad_count"] or 0),
            "avg_inference_ms": round(float(summary_row["avg_inference_ms"] or 0.0), 2),
            "first_ts": summary_row["first_ts"],
            "last_ts": summary_row["last_ts"],
        }
        inspection_rows = conn.execute(
            """
            SELECT id, frame_id, ts, result, defect_count, inference_ms, width, height, payload_json
            FROM inspection_records
            ORDER BY id DESC
            """
        ).fetchall()
        detection_rows = conn.execute(
            """
            SELECT id, record_id, label, confidence, x, y, w, h, normalized
            FROM detections
            ORDER BY id DESC
            """
        ).fetchall()
        return {
            "db_exists": True,
            "summary": summary,
            "inspection_records": [
                {
                    "id": int(row["id"] or 0),
                    "frame_id": row["frame_id"],
                    "ts": row["ts"],
                    "result": row["result"],
                    "defect_count": int(row["defect_count"] or 0),
                    "inference_ms": round(float(row["inference_ms"] or 0.0), 2),
                    "width": int(row["width"] or 0),
                    "height": int(row["height"] or 0),
                    "payload": self._safe_load_json(row["payload_json"]),
                }
                for row in inspection_rows
            ],
            "detections": [
                {
                    "id": int(row["id"] or 0),
                    "record_id": int(row["record_id"] or 0),
                    "label": row["label"],
                    "confidence": round(float(row["confidence"] or 0.0), 4),
                    "x": float(row["x"] or 0.0),
                    "y": float(row["y"] or 0.0),
                    "w": float(row["w"] or 0.0),
                    "h": float(row["h"] or 0.0),
                    "normalized": bool(row["normalized"]),
                }
                for row in detection_rows
            ],
        }

    def _extract_keywords(self, text: str) -> list[str]:
        found: list[str] = []
        for bucket in LABEL_KEYWORDS.values():
            for keyword in bucket:
                if keyword in text and keyword not in found:
                    found.append(keyword)
        for bucket in METRIC_KEYWORDS.values():
            for keyword in bucket:
                if keyword in text and keyword not in found:
                    found.append(keyword)
        if not found and text:
            found.extend(text.split()[:4])
        return found[:8]

    def _match_labels(self, text: str) -> list[str]:
        matches: list[str] = []
        for label, aliases in LABEL_KEYWORDS.items():
            if any(alias in text for alias in aliases):
                matches.append(label)
        return matches

    def _build_summary(self, conn: sqlite3.Connection) -> str:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN result = 'OK' THEN 1 ELSE 0 END) AS good_count,
                SUM(CASE WHEN result = 'NG' THEN 1 ELSE 0 END) AS bad_count,
                AVG(inference_ms) AS avg_inference_ms
            FROM inspection_records
            """
        ).fetchone()
        total = int(row["total_count"] or 0)
        good = int(row["good_count"] or 0)
        bad = int(row["bad_count"] or 0)
        avg_ms = round(float(row["avg_inference_ms"] or 0.0), 2)
        yield_rate = round((good / total) * 100, 2) if total else 0.0
        return (
            "数据库摘要:\n"
            f"- 总检测数: {total}\n"
            f"- OK: {good}\n"
            f"- NG: {bad}\n"
            f"- 良率: {yield_rate}%\n"
            f"- 平均推理耗时: {avg_ms} ms"
        )

    def _build_latest(self, conn: sqlite3.Connection) -> str:
        row = conn.execute(
            """
            SELECT id, frame_id, ts, result, defect_count, inference_ms, payload_json
            FROM inspection_records
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return "最新记录: 暂无数据。"
        labels = self._labels_from_payload(row["payload_json"])
        return (
            "最新检测记录:\n"
            f"- frame_id: {row['frame_id']}\n"
            f"- 时间: {row['ts']}\n"
            f"- 结果: {row['result']}\n"
            f"- 缺陷数: {row['defect_count']}\n"
            f"- 标签: {labels or '无'}\n"
            f"- 推理耗时: {round(float(row['inference_ms'] or 0.0), 2)} ms"
        )

    def _build_distribution(self, conn: sqlite3.Connection) -> str:
        rows = conn.execute(
            """
            SELECT label, COUNT(*) AS total
            FROM detections
            GROUP BY label
            ORDER BY total DESC, label ASC
            LIMIT 5
            """
        ).fetchall()
        if not rows:
            return "缺陷分布: 暂无缺陷数据。"
        lines = ["缺陷分布 Top5:"]
        for row in rows:
            lines.append(f"- {row['label']}: {int(row['total'] or 0)}")
        return "\n".join(lines)

    def _build_label_records(self, conn: sqlite3.Connection, labels: list[str]) -> str:
        placeholders = ",".join("?" for _ in labels)
        rows = conn.execute(
            f"""
            SELECT ir.frame_id, ir.ts, ir.result, ir.defect_count, d.label, d.confidence
            FROM detections d
            JOIN inspection_records ir ON ir.id = d.record_id
            WHERE d.label IN ({placeholders})
            ORDER BY ir.id DESC, d.confidence DESC
            LIMIT ?
            """,
            (*labels, self.retrieval_limit),
        ).fetchall()
        if not rows:
            return f"相关缺陷记录: 没有找到 {', '.join(labels)} 的历史记录。"
        lines = [f"相关缺陷记录({', '.join(labels)}):"]
        for row in rows:
            confidence = round(float(row["confidence"] or 0.0), 4)
            lines.append(
                f"- {row['ts']} frame={row['frame_id']} result={row['result']} label={row['label']} confidence={confidence}"
            )
        return "\n".join(lines)

    def _build_trend(self, conn: sqlite3.Connection) -> str:
        rows = conn.execute(
            """
            SELECT
                strftime('%m-%d %H:00', ts) AS bucket,
                COUNT(*) AS total_count,
                SUM(CASE WHEN result = 'OK' THEN 1 ELSE 0 END) AS good_count,
                SUM(CASE WHEN result = 'NG' THEN 1 ELSE 0 END) AS bad_count
            FROM inspection_records
            GROUP BY bucket
            ORDER BY bucket DESC
            LIMIT 6
            """
        ).fetchall()
        if not rows:
            return ""
        lines = ["最近趋势(按小时):"]
        for row in rows:
            lines.append(
                f"- {row['bucket']}: total={int(row['total_count'] or 0)} ok={int(row['good_count'] or 0)} ng={int(row['bad_count'] or 0)}"
            )
        return "\n".join(lines)

    def _build_result_breakdown(self, conn: sqlite3.Connection) -> str:
        rows = conn.execute(
            """
            SELECT result, COUNT(*) AS total
            FROM inspection_records
            GROUP BY result
            ORDER BY result ASC
            """
        ).fetchall()
        if not rows:
            return ""
        lines = ["结果分类统计:"]
        for row in rows:
            lines.append(f"- {row['result']}: {int(row['total'] or 0)}")
        return "\n".join(lines)

    def _build_recent_records(self, conn: sqlite3.Connection) -> str:
        rows = conn.execute(
            """
            SELECT frame_id, ts, result, defect_count, inference_ms, payload_json
            FROM inspection_records
            ORDER BY id DESC
            LIMIT ?
            """,
            (self.retrieval_limit,),
        ).fetchall()
        if not rows:
            return "最近记录: 暂无数据。"
        lines = [f"最近 {len(rows)} 条检测记录:"]
        for row in rows:
            lines.append(
                f"- {row['ts']} frame={row['frame_id']} result={row['result']} defects={row['defect_count']} labels={self._labels_from_payload(row['payload_json']) or '无'} inference_ms={round(float(row['inference_ms'] or 0.0), 2)}"
            )
        return "\n".join(lines)

    def _labels_from_payload(self, payload_json: str) -> str:
        payload = self._safe_load_json(payload_json)
        labels = []
        for item in payload.get("detections") or []:
            label = str(item.get("label") or "").strip()
            if label and label not in labels:
                labels.append(label)
        return ", ".join(labels)

    def _safe_load_json(self, payload_json: str) -> dict[str, Any]:
        try:
            return json.loads(payload_json)
        except json.JSONDecodeError:
            return {}
