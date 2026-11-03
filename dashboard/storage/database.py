from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sqlite3
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

CANONICAL_DEFECT_LABELS = ["脏污", "折皱", "划痕", "针孔", "擦伤"]
LEGACY_CIRCLE_TIMESTAMP_PATTERN = re.compile(
    r"(?:circle-)?(?P<value>\d{8}_\d{6}(?:_\d{1,6})?)$"
)
TREND_BUCKET_COUNT = 10
LABEL_ALIASES = {
    "stain": "脏污",
    "dirty": "脏污",
    "contamination": "脏污",
    "wrinkle": "折皱",
    "fold": "折皱",
    "offset": "折皱",
    "scratch": "划痕",
    "crack": "划痕",
    "pinhole": "针孔",
    "hole": "针孔",
    "dent": "擦伤",
    "scuff": "擦伤",
    "abrasion": "擦伤",
    "脏污": "脏污",
    "折皱": "折皱",
    "划痕": "划痕",
    "针孔": "针孔",
    "擦伤": "擦伤",
}
ASCII_LABELS = {
    "脏污": "Stain",
    "折皱": "Wrinkle",
    "划痕": "Scratch",
    "针孔": "Pinhole",
    "擦伤": "Scuff",
}
NORMAL_LABELS = {"normal", "ok", "good", "zheng_chang", "zhengchang", "正常", "良品"}
ANNOTATION_FONT_PATHS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKSC-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/System/Library/Fonts/PingFang.ttc",
)


@lru_cache(maxsize=8)
def annotation_font(size: int) -> tuple[ImageFont.ImageFont, bool]:
    for font_path in ANNOTATION_FONT_PATHS:
        if not Path(font_path).exists():
            continue
        try:
            return ImageFont.truetype(font_path, size=size), True
        except OSError:
            continue
    return ImageFont.load_default(size=size), False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def parse_event_time(value: Any) -> datetime | None:
    """Parse supported ingestion timestamps into a timezone-aware UTC datetime."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Older producers sent local wall-clock ISO strings without an offset.
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)


def parse_legacy_circle_time(value: Any) -> datetime | None:
    """Recover the local trigger time embedded in legacy circle-camera identifiers."""

    if not isinstance(value, str):
        return None
    match = LEGACY_CIRCLE_TIMESTAMP_PATTERN.fullmatch(value.strip())
    if not match:
        return None
    compact_value = match.group("value")
    for time_format in ("%Y%m%d_%H%M%S_%f", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(compact_value, time_format).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def chunked_label(label: str) -> str:
    return (label or "unknown").strip() or "unknown"


def canonicalize_label(label: str) -> str:
    raw = chunked_label(label)
    return LABEL_ALIASES.get(raw.lower(), LABEL_ALIASES.get(raw, raw))


def unique_detection_labels(detections: list[dict[str, Any]]) -> set[str]:
    """Return image-level defect labels so repeated boxes count only once."""

    return {
        canonicalize_label(item.get("label"))
        for item in detections
        if item.get("label")
    }


class ClosingConnection(sqlite3.Connection):
    """sqlite context manager that commits/rolls back and also closes the file."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        result = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return result


class DashboardStorage:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root.expanduser().resolve()
        self.media_dir = self.data_root / "media"
        self.frames_dir = self.media_dir / "frames"
        self.archive_dir = self.data_root / "archive"
        self.logs_dir = self.data_root / "logs"
        self.db_path = self.data_root / "dashboard.sqlite3"
        self.latest_frame_path = self.media_dir / "latest_frame.jpg"
        self.live_frame_path = self.media_dir / "live_stream_frame.jpg"
        self._lock = asyncio.Lock()
        self.started_at = time.time()
        self.last_device_seen_monotonic = 0.0
        self.live_frame_write_interval_seconds = safe_float(
            os.environ.get("DASHBOARD_LIVE_FRAME_WRITE_INTERVAL_SECONDS"),
            2.0,
        )
        self.board_score_thresh = max(
            0.0,
            safe_float(os.environ.get("BOARD_SCORE_THRESH"), 0.2),
        )
        self._last_live_frame_disk_write_monotonic = 0.0
        self._live_frame_bytes: bytes | None = None
        self._live_frame_sequence = 0
        self._live_frame_condition = asyncio.Condition(self._lock)
        self._state = self._empty_state()

        for path in (self.data_root, self.media_dir, self.frames_dir, self.archive_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)

        self._init_db()
        self._migrate_event_timestamps()
        self._migrate_legacy_labels()
        self._reload_from_db()

    def _empty_state(self) -> dict[str, Any]:
        return {
            "generated_at": utcnow_iso(),
            "started_at": utcnow_iso(),
            "connection_plan": {
                "board_to_pi": "Pi camera -> circle detector -> HTTP multipart",
                "pi_to_browser": "MJPEG video + WebSocket data",
                "overlay_mode": "Canvas overlay",
                "ingest_api": "/api/device/ingest",
                "live_frame_api": "/api/device/live_frame",
                "mjpeg_stream_api": "/api/stream.mjpg",
            },
            "device": {
                "online": False,
                "board_name": "Zynq 多产线推理加速器",
                "transport": "Local camera + HTTP relay",
                "comm_state": "waiting",
                "model_name": "Zynq 缺陷检测模型",
                "last_seen_at": None,
                "stream_state": "waiting",
                "source_mode": "Pi local camera relay",
                "circle_count": 0,
                "selected_circle": None,
                "trigger_overlay": None,
                "trigger_queue": {"depth": 0, "capacity": 8, "warning": False},
            },
            "supported_defects": CANONICAL_DEFECT_LABELS,
            "summary": {
                "total_count": 0,
                "good_count": 0,
                "bad_count": 0,
                "yield_rate": 0.0,
                "avg_inference_ms": 0.0,
            },
            "latest_result": None,
            "recent_results": [],
            "defect_summary": [],
            "history": {
                "records": [],
                "defect_distribution": [],
                "trend": [],
            },
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=3.0, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS inspection_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    frame_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    event_epoch_ms INTEGER,
                    result TEXT NOT NULL,
                    defect_count INTEGER NOT NULL DEFAULT 0,
                    inference_ms REAL NOT NULL DEFAULT 0,
                    width INTEGER NOT NULL DEFAULT 1280,
                    height INTEGER NOT NULL DEFAULT 720,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0,
                    x REAL NOT NULL DEFAULT 0,
                    y REAL NOT NULL DEFAULT 0,
                    w REAL NOT NULL DEFAULT 0,
                    h REAL NOT NULL DEFAULT 0,
                    normalized INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(record_id) REFERENCES inspection_records(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_inspection_records_ts
                ON inspection_records(ts DESC);

                CREATE INDEX IF NOT EXISTS idx_inspection_records_frame_id
                ON inspection_records(frame_id);

                CREATE INDEX IF NOT EXISTS idx_detections_record_id
                ON detections(record_id);

                CREATE INDEX IF NOT EXISTS idx_detections_label_record
                ON detections(label, record_id);
                """
            )

            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(inspection_records)").fetchall()
            }
            if "event_epoch_ms" not in columns:
                conn.execute("ALTER TABLE inspection_records ADD COLUMN event_epoch_ms INTEGER")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_inspection_records_event_epoch "
                "ON inspection_records(event_epoch_ms DESC)"
            )

    def _migrate_event_timestamps(self) -> None:
        """Backfill sortable event times without guessing unrelated malformed records."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, frame_id, ts
                FROM inspection_records
                WHERE event_epoch_ms IS NULL
                """
            ).fetchall()
            updates: list[tuple[str, int, int]] = []
            for row in rows:
                event_time = parse_event_time(row["ts"])
                if event_time is None:
                    event_time = parse_legacy_circle_time(row["ts"])
                if event_time is None:
                    event_time = parse_legacy_circle_time(row["frame_id"])
                if event_time is None:
                    continue
                event_epoch_ms = int(event_time.timestamp() * 1000)
                updates.append((event_time.isoformat(), event_epoch_ms, safe_int(row["id"])))
            if updates:
                conn.executemany(
                    "UPDATE inspection_records SET ts = ?, event_epoch_ms = ? WHERE id = ?",
                    updates,
                )
                conn.commit()

    def _migrate_legacy_labels(self) -> None:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, label FROM detections").fetchall()
            for row in rows:
                canonical = canonicalize_label(row["label"])
                if canonical != row["label"]:
                    conn.execute("UPDATE detections SET label = ? WHERE id = ?", (canonical, safe_int(row["id"])))

            record_rows = conn.execute("SELECT id, payload_json FROM inspection_records").fetchall()
            for row in record_rows:
                try:
                    payload = json.loads(row["payload_json"])
                except json.JSONDecodeError:
                    continue
                changed = False
                for item in payload.get("detections") or []:
                    canonical = canonicalize_label(item.get("label") or item.get("class_name") or item.get("name"))
                    if item.get("label") != canonical:
                        item["label"] = canonical
                        changed = True
                if changed:
                    conn.execute(
                        "UPDATE inspection_records SET payload_json = ? WHERE id = ?",
                        (json.dumps(payload, ensure_ascii=False), safe_int(row["id"])),
                    )
            conn.commit()

    def _reload_from_db(self) -> None:
        with self._connect() as conn:
            self._state["summary"] = self._build_summary(conn)
            self._state["recent_results"] = self._fetch_recent_cards(conn, limit=3)
            self._state["latest_result"] = (
                self._state["recent_results"][0] if self._state["recent_results"] else None
            )
            self._state["defect_summary"] = self._build_defect_summary(conn)
            self._state["history"] = self._build_history_payload(conn)
            self._state["generated_at"] = utcnow_iso()

    def _build_summary(self, conn: sqlite3.Connection) -> dict[str, Any]:
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
        total_count = safe_int(row["total_count"])
        good_count = safe_int(row["good_count"])
        bad_count = safe_int(row["bad_count"])
        yield_rate = round((good_count / total_count) * 100, 2) if total_count else 0.0
        return {
            "total_count": total_count,
            "good_count": good_count,
            "bad_count": bad_count,
            "yield_rate": yield_rate,
            "avg_inference_ms": round(safe_float(row["avg_inference_ms"]), 2),
        }

    def _fetch_recent_cards(self, conn: sqlite3.Connection, limit: int = 3) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT *
            FROM inspection_records
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        cards: list[dict[str, Any]] = []
        for row in rows:
            detections = self._fetch_detections(conn, safe_int(row["id"]))
            payload = json.loads(row["payload_json"])
            cards.append(
                {
                    "id": safe_int(row["id"]),
                    "frame_id": row["frame_id"],
                    "timestamp": row["ts"],
                    "result": row["result"],
                    "defect_count": safe_int(row["defect_count"]),
                    "inference_ms": round(safe_float(row["inference_ms"]), 2),
                    "board_inference_ms": round(
                        safe_float(payload.get("board_inference_ms"), row["inference_ms"]), 2
                    ),
                    "board_roundtrip_ms": round(
                        safe_float(payload.get("board_roundtrip_ms"), row["inference_ms"]), 2
                    ),
                    "pipeline_timing": dict(payload.get("pipeline_timing") or {}),
                    "frame": {
                        "width": safe_int(row["width"], 1280),
                        "height": safe_int(row["height"], 720),
                    },
                    "detections": detections,
                    "top_labels": self._top_labels(detections),
                    "payload": payload,
                    "image_url": self._frame_url(row["frame_id"]),
                }
            )
        return cards

    def _fetch_records(self, conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT *
            FROM inspection_records
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            detections = self._fetch_detections(conn, safe_int(row["id"]))
            records.append(
                {
                    "id": safe_int(row["id"]),
                    "frame_id": row["frame_id"],
                    "timestamp": row["ts"],
                    "result": row["result"],
                    "defect_count": safe_int(row["defect_count"]),
                    "inference_ms": round(safe_float(row["inference_ms"]), 2),
                    "labels": ", ".join(self._top_labels(detections)) or "--",
                    "width": safe_int(row["width"], 1280),
                    "height": safe_int(row["height"], 720),
                    "image_url": self._frame_url(row["frame_id"]),
                }
            )
        return records

    def _frame_url(self, frame_id: str) -> str | None:
        frame_path = self.frames_dir / f"{frame_id}.jpg"
        if not frame_path.exists():
            archive_path = self.archive_dir / f"{frame_id}.jpg"
            if not archive_path.exists():
                return None
        return f"/api/frame/{frame_id}"

    def _build_history_payload(
        self,
        conn: sqlite3.Connection,
        *,
        include_trend: bool = False,
    ) -> dict[str, Any]:
        defect_distribution = self._build_defect_summary(conn)[:8]
        trend = self._build_history_trend(conn) if include_trend else []
        return {
            "records": self._fetch_records(conn, limit=50),
            "defect_distribution": defect_distribution,
            "trend": trend,
        }

    def _build_history_trend(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        bounds = conn.execute(
            """
            SELECT
                (
                    SELECT event_epoch_ms
                    FROM inspection_records
                    WHERE event_epoch_ms IS NOT NULL
                    ORDER BY event_epoch_ms ASC
                    LIMIT 1
                ) AS oldest_epoch_ms,
                (
                    SELECT event_epoch_ms
                    FROM inspection_records
                    WHERE event_epoch_ms IS NOT NULL
                    ORDER BY event_epoch_ms DESC
                    LIMIT 1
                ) AS newest_epoch_ms
            """
        ).fetchone()
        if not bounds or bounds["oldest_epoch_ms"] is None or bounds["newest_epoch_ms"] is None:
            return []

        oldest_epoch_ms = safe_int(bounds["oldest_epoch_ms"])
        newest_epoch_ms = safe_int(bounds["newest_epoch_ms"])
        span_ms = newest_epoch_ms - oldest_epoch_ms
        if span_ms <= 0:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN result = 'OK' THEN 1 ELSE 0 END) AS good_count,
                    SUM(CASE WHEN result = 'NG' THEN 1 ELSE 0 END) AS bad_count,
                    AVG(inference_ms) AS avg_inference_ms
                FROM inspection_records
                WHERE event_epoch_ms = ?
                """,
                (oldest_epoch_ms,),
            ).fetchone()
            return [
                self._trend_bucket_payload(
                    row,
                    bucket_index=0,
                    bucket_start_epoch_ms=oldest_epoch_ms,
                    bucket_end_epoch_ms=newest_epoch_ms,
                    total_span_ms=0,
                )
            ]

        trend_rows = conn.execute(
            """
            SELECT
                CASE
                    WHEN event_epoch_ms >= ? THEN ?
                    ELSE CAST(((event_epoch_ms - ?) * ?) / ? AS INTEGER)
                END AS bucket_index,
                COUNT(*) AS total_count,
                SUM(CASE WHEN result = 'OK' THEN 1 ELSE 0 END) AS good_count,
                SUM(CASE WHEN result = 'NG' THEN 1 ELSE 0 END) AS bad_count,
                AVG(inference_ms) AS avg_inference_ms
            FROM inspection_records
            WHERE event_epoch_ms BETWEEN ? AND ?
            GROUP BY bucket_index
            ORDER BY bucket_index ASC
            """,
            (
                newest_epoch_ms,
                TREND_BUCKET_COUNT - 1,
                oldest_epoch_ms,
                TREND_BUCKET_COUNT,
                span_ms,
                oldest_epoch_ms,
                newest_epoch_ms,
            ),
        ).fetchall()
        rows_by_bucket = {safe_int(row["bucket_index"]): row for row in trend_rows}
        trend: list[dict[str, Any]] = []
        for bucket_index in range(TREND_BUCKET_COUNT):
            bucket_start_epoch_ms = oldest_epoch_ms + (span_ms * bucket_index) // TREND_BUCKET_COUNT
            bucket_end_epoch_ms = oldest_epoch_ms + (
                span_ms * (bucket_index + 1)
            ) // TREND_BUCKET_COUNT
            trend.append(
                self._trend_bucket_payload(
                    rows_by_bucket.get(bucket_index),
                    bucket_index=bucket_index,
                    bucket_start_epoch_ms=bucket_start_epoch_ms,
                    bucket_end_epoch_ms=bucket_end_epoch_ms,
                    total_span_ms=span_ms,
                )
            )
        return trend

    def _trend_bucket_payload(
        self,
        row: sqlite3.Row | None,
        *,
        bucket_index: int,
        bucket_start_epoch_ms: int,
        bucket_end_epoch_ms: int,
        total_span_ms: int,
    ) -> dict[str, Any]:
        total = safe_int(row["total_count"] if row else 0)
        good = safe_int(row["good_count"] if row else 0)
        return {
            "bucket": self._format_trend_bucket_label(bucket_start_epoch_ms, total_span_ms),
            "bucket_index": bucket_index,
            "bucket_start_epoch_ms": bucket_start_epoch_ms,
            "bucket_end_epoch_ms": bucket_end_epoch_ms,
            "total_count": total,
            "good_count": good,
            "bad_count": safe_int(row["bad_count"] if row else 0),
            "yield_rate": round((good / total) * 100, 2) if total else 0.0,
            "avg_inference_ms": round(safe_float(row["avg_inference_ms"] if row else 0.0), 2),
        }

    @staticmethod
    def _format_trend_bucket_label(epoch_ms: int, total_span_ms: int) -> str:
        local_time = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc).astimezone()
        if total_span_ms < 60 * 60 * 1000:
            return local_time.strftime("%H:%M:%S")
        if total_span_ms < 7 * 24 * 60 * 60 * 1000:
            return local_time.strftime("%m-%d %H:%M")
        return local_time.strftime("%Y-%m-%d")

    def _build_defect_summary(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT label, COUNT(*) AS total
            FROM (
                SELECT DISTINCT record_id, label
                FROM detections
            ) AS image_defects
            GROUP BY label
            ORDER BY total DESC, label ASC
            """
        ).fetchall()
        return [{"name": row["label"], "value": safe_int(row["total"])} for row in rows]

    def _fetch_detections(self, conn: sqlite3.Connection, record_id: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT label, confidence, x, y, w, h, normalized
            FROM detections
            WHERE record_id = ?
            ORDER BY confidence DESC, id ASC
            """,
            (record_id,),
        ).fetchall()
        detections: list[dict[str, Any]] = []
        for row in rows:
            detections.append(
                {
                    "label": row["label"],
                    "label_display": canonicalize_label(row["label"]),
                    "confidence": round(safe_float(row["confidence"]), 4),
                    "bbox": {
                        "x": safe_float(row["x"]),
                        "y": safe_float(row["y"]),
                        "w": safe_float(row["w"]),
                        "h": safe_float(row["h"]),
                        "normalized": bool(row["normalized"]),
                    },
                }
            )
        return detections

    def _top_labels(self, detections: list[dict[str, Any]]) -> list[str]:
        counts: dict[str, int] = {}
        for item in detections:
            label = chunked_label(item.get("label"))
            label = canonicalize_label(label)
            counts[label] = counts.get(label, 0) + 1
        return [label for label, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]]

    def _normalize_detections(
        self,
        payload: dict[str, Any],
    ) -> tuple[bool, bool, list[dict[str, Any]]]:
        raw_items = payload.get("detections")
        if not isinstance(raw_items, list):
            raw_items = payload.get("boxes")
        items = raw_items if isinstance(raw_items, list) else []
        had_raw_candidates = bool(items)
        candidates: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            label = chunked_label(
                raw.get("label") or raw.get("class_name") or raw.get("name") or raw.get("category")
            )
            label = canonicalize_label(label)
            confidence_value = raw.get("confidence")
            if confidence_value is None:
                confidence_value = raw.get("score")
            if confidence_value is None:
                confidence_value = raw.get("probability")
            confidence = safe_float(confidence_value)
            if confidence < getattr(self, "board_score_thresh", 0.2):
                continue
            is_normal = label.lower() in NORMAL_LABELS or label in NORMAL_LABELS
            bbox_raw = raw.get("bbox") or {}
            x = bbox_raw.get("x", raw.get("x"))
            y = bbox_raw.get("y", raw.get("y"))
            w = bbox_raw.get("w", raw.get("w"))
            h = bbox_raw.get("h", raw.get("h"))
            if w is None and raw.get("x2") is not None and x is not None:
                w = safe_float(raw.get("x2")) - safe_float(x)
            if h is None and raw.get("y2") is not None and y is not None:
                h = safe_float(raw.get("y2")) - safe_float(y)
            x = safe_float(x)
            y = safe_float(y)
            w = max(safe_float(w), 0.0)
            h = max(safe_float(h), 0.0)
            normalized = max(abs(x), abs(y), abs(w), abs(h)) <= 1.2
            candidates.append(
                {
                    "label": label,
                    "confidence": round(confidence, 4),
                    "bbox": {
                        "x": round(x, 4),
                        "y": round(y, 4),
                        "w": round(w, 4),
                        "h": round(h, 4),
                        "normalized": normalized,
                    },
                    "_is_normal": is_normal,
                }
            )
        if not candidates:
            return had_raw_candidates, False, []
        winner = max(
            candidates,
            key=lambda item: (
                safe_float(item.get("confidence")),
                0 if item.get("_is_normal") else 1,
            ),
        )
        normal_won = bool(winner.get("_is_normal"))
        if normal_won:
            return had_raw_candidates, True, []
        winner_label = winner["label"]
        detections: list[dict[str, Any]] = []
        for item in candidates:
            if item["label"] != winner_label:
                continue
            public_item = dict(item)
            public_item.pop("_is_normal", None)
            detections.append(public_item)
        return had_raw_candidates, False, detections

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        timestamp = str(payload.get("timestamp") or payload.get("ts") or utcnow_iso())
        frame_info = payload.get("frame") or {}
        width = safe_int(frame_info.get("width") or payload.get("width"), 1280)
        height = safe_int(frame_info.get("height") or payload.get("height"), 720)
        had_raw_candidates, normal_won, detections = self._normalize_detections(payload)
        if detections:
            result = "NG"
            defect_count = len(detections)
        elif normal_won or had_raw_candidates:
            result = "OK"
            defect_count = 0
        else:
            defect_count = safe_int(payload.get("defect_count"), 0)
            result = payload.get("result")
            if not result:
                result = "NG" if payload.get("is_ng") or defect_count > 0 else "OK"
        result = str(result).upper()
        if result == "OK":
            defect_count = 0
        elif defect_count <= 0:
            defect_count = 1
        inference_ms = round(safe_float(payload.get("inference_ms")), 2)
        board_inference_ms = round(safe_float(payload.get("board_inference_ms"), inference_ms), 2)
        board_roundtrip_ms = round(safe_float(payload.get("board_roundtrip_ms"), board_inference_ms), 2)
        pipeline_timing = dict(payload.get("pipeline_timing") or {})
        pipeline_timing.setdefault("board_inference_ms", board_inference_ms)
        pipeline_timing.setdefault("board_roundtrip_ms", board_roundtrip_ms)
        frame_id = str(payload.get("frame_id") or f"frame-{int(time.time() * 1000)}")
        event_time = parse_event_time(timestamp)
        if event_time is None:
            event_time = parse_legacy_circle_time(timestamp) or parse_legacy_circle_time(frame_id)
            if event_time is not None:
                timestamp = event_time.isoformat()
        event_epoch_ms = int(event_time.timestamp() * 1000) if event_time is not None else None
        model_name = str(payload.get("model_name") or self._state["device"]["model_name"])
        board_name = str(payload.get("board_name") or self._state["device"]["board_name"])
        device_state = str(payload.get("device_state") or "running")
        return {
            "timestamp": timestamp,
            "event_epoch_ms": event_epoch_ms,
            "frame_id": frame_id,
            "frame": {"width": width, "height": height},
            "detections": detections,
            "defect_count": defect_count,
            "circle_count": safe_int(payload.get("circle_count"), 0),
            "selected_circle": payload.get("selected_circle"),
            "target_circle": payload.get("target_circle"),
            "result": result,
            "inference_ms": inference_ms,
            "board_inference_ms": board_inference_ms,
            "board_roundtrip_ms": board_roundtrip_ms,
            "pipeline_timing": pipeline_timing,
            "trigger_epoch_ms": safe_int(payload.get("trigger_epoch_ms"), 0),
            "trigger_source": str(payload.get("trigger_source") or ""),
            "model_name": model_name,
            "board_name": board_name,
            "device_state": device_state,
            "notes": payload.get("notes") or "",
        }

    async def heartbeat(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        async with self._lock:
            self.last_device_seen_monotonic = time.monotonic()
            self._state["device"].update(
                {
                    "online": True,
                    "board_name": str(payload.get("board_name") or self._state["device"]["board_name"]),
                    "comm_state": str(payload.get("comm_state") or "connected"),
                    "model_name": str(payload.get("model_name") or self._state["device"]["model_name"]),
                    "last_seen_at": utcnow_iso(),
                    "stream_state": str(payload.get("stream_state") or "receiving"),
                    "circle_count": safe_int(payload.get("circle_count"), self._state["device"].get("circle_count", 0)),
                    "selected_circle": payload.get("selected_circle") or self._state["device"].get("selected_circle"),
                }
            )
            self._state["generated_at"] = utcnow_iso()
            return deepcopy(self._state)

    def _write_bytes_atomic(self, target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target.with_name(f".{target.name}.{time.time_ns()}.tmp")
        temp_path.write_bytes(data)
        temp_path.replace(target)

    def _annotate_result_frame(self, frame_bytes: bytes, payload: dict[str, Any]) -> bytes:
        try:
            with Image.open(io.BytesIO(frame_bytes)) as source:
                image = source.convert("RGB")
        except (OSError, UnidentifiedImageError):
            return frame_bytes

        width, height = image.size
        if width <= 0 or height <= 0:
            return frame_bytes

        draw = ImageDraw.Draw(image)
        font_size = max(12, min(24, int(round(min(width, height) * 0.04))))
        font, supports_chinese = annotation_font(font_size)
        line_width = max(2, min(5, int(round(min(width, height) / 240))))
        padding = max(3, line_width + 1)
        result = str(payload.get("result") or "OK").upper()
        detections = payload.get("detections") or []
        defect_count = safe_int(payload.get("defect_count"), len(detections))
        result_color = (232, 62, 78) if result == "NG" else (34, 181, 115)

        status_text = result
        if result == "NG":
            status_text = f"NG  {defect_count} defect{'s' if defect_count != 1 else ''}"
        status_box = draw.textbbox((0, 0), status_text, font=font)
        status_width = status_box[2] - status_box[0]
        status_height = status_box[3] - status_box[1]
        status_x = padding * 2
        status_y = padding * 2
        draw.rectangle(
            (
                status_x - padding,
                status_y - padding,
                status_x + status_width + padding,
                status_y + status_height + padding,
            ),
            fill=result_color,
        )
        draw.text((status_x, status_y), status_text, fill=(255, 255, 255), font=font)

        frame_info = payload.get("frame") or {}
        source_width = max(1, safe_int(frame_info.get("width"), width))
        source_height = max(1, safe_int(frame_info.get("height"), height))

        for index, detection in enumerate(detections, start=1):
            bbox = detection.get("bbox") or {}
            x = safe_float(bbox.get("x"))
            y = safe_float(bbox.get("y"))
            box_width = max(0.0, safe_float(bbox.get("w")))
            box_height = max(0.0, safe_float(bbox.get("h")))
            if bbox.get("normalized"):
                x1 = x * width
                y1 = y * height
                x2 = (x + box_width) * width
                y2 = (y + box_height) * height
            else:
                scale_x = width / source_width
                scale_y = height / source_height
                x1 = x * scale_x
                y1 = y * scale_y
                x2 = (x + box_width) * scale_x
                y2 = (y + box_height) * scale_y

            x1 = max(0, min(width - 1, int(round(x1))))
            y1 = max(0, min(height - 1, int(round(y1))))
            x2 = max(0, min(width - 1, int(round(x2))))
            y2 = max(0, min(height - 1, int(round(y2))))
            if x2 <= x1 or y2 <= y1:
                continue

            draw.rectangle((x1, y1, x2, y2), outline=result_color, width=line_width)
            label = str(detection.get("label") or f"Defect {index}")
            if not supports_chinese:
                label = ASCII_LABELS.get(label, f"Defect {index}")
            label_text = label
            label_box = draw.textbbox((0, 0), label_text, font=font)
            label_width = label_box[2] - label_box[0]
            label_height = label_box[3] - label_box[1]
            label_x = x1
            label_y = y1 - label_height - padding * 2
            if label_y < 0:
                label_y = y1
            label_right = min(width - 1, label_x + label_width + padding * 2)
            draw.rectangle(
                (label_x, label_y, label_right, min(height - 1, label_y + label_height + padding * 2)),
                fill=result_color,
            )
            draw.text(
                (label_x + padding, label_y + padding),
                label_text,
                fill=(255, 255, 255),
                font=font,
            )

        output = io.BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=False)
        return output.getvalue()

    async def update_live_frame(
        self,
        frame_bytes: bytes,
        payload: dict[str, Any] | None = None,
        return_snapshot: bool = False,
    ) -> dict[str, Any] | None:
        payload = payload or {}
        if (
            len(frame_bytes) < 4
            or not frame_bytes.startswith(b"\xff\xd8")
            or not frame_bytes.endswith(b"\xff\xd9")
        ):
            raise ValueError("Invalid live frame JPEG bytes.")

        async with self._live_frame_condition:
            self._live_frame_bytes = bytes(frame_bytes)
            self._live_frame_sequence += 1
            now = time.monotonic()
            if (
                not self.live_frame_path.exists()
                or (now - self._last_live_frame_disk_write_monotonic) >= self.live_frame_write_interval_seconds
            ):
                await asyncio.to_thread(self._write_bytes_atomic, self.live_frame_path, frame_bytes)
                self._last_live_frame_disk_write_monotonic = now
            self.last_device_seen_monotonic = time.monotonic()
            trigger_overlay = self._merge_trigger_overlay(payload)
            self._state["device"].update(
                {
                    "online": True,
                    "board_name": str(payload.get("board_name") or self._state["device"]["board_name"]),
                    "comm_state": str(payload.get("comm_state") or "connected"),
                    "model_name": str(payload.get("model_name") or self._state["device"]["model_name"]),
                    "last_seen_at": str(payload.get("timestamp") or utcnow_iso()),
                    "stream_state": "live",
                    "circle_count": safe_int(payload.get("circle_count"), 0),
                    "selected_circle": payload.get("selected_circle"),
                    "trigger_overlay": trigger_overlay,
                    "trigger_queue": payload.get("trigger_queue") or self._state["device"].get("trigger_queue"),
                }
            )
            self._state["generated_at"] = utcnow_iso()
            self._live_frame_condition.notify_all()
            if return_snapshot:
                return deepcopy(self._state)
            return None

    def _merge_trigger_overlay(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        now_ms = int(time.time() * 1000)
        current = self._state["device"].get("trigger_overlay")

        def active(overlay: Any) -> bool:
            if not isinstance(overlay, dict):
                return False
            return max(
                safe_int(overlay.get("expires_at_ms"), 0),
                safe_int(overlay.get("sent_until_ms"), 0),
            ) > now_ms

        current_overlay = dict(current) if active(current) else {}
        if "trigger_overlay" not in payload or payload.get("trigger_overlay") is None:
            return current_overlay or None

        incoming = payload.get("trigger_overlay")
        if not isinstance(incoming, dict):
            return current_overlay or None

        incoming_image = incoming.get("image_data")
        current_image = current_overlay.get("image_data")
        if incoming_image and incoming_image != current_image:
            merged = {
                "image_data": incoming_image,
                "expires_at_ms": safe_int(incoming.get("expires_at_ms"), 0),
                "sent_until_ms": safe_int(incoming.get("sent_until_ms"), 0),
            }
        else:
            merged = current_overlay
            if incoming_image:
                merged["image_data"] = incoming_image
            merged["expires_at_ms"] = max(
                safe_int(merged.get("expires_at_ms"), 0),
                safe_int(incoming.get("expires_at_ms"), 0),
            )
            merged["sent_until_ms"] = max(
                safe_int(merged.get("sent_until_ms"), 0),
                safe_int(incoming.get("sent_until_ms"), 0),
            )

        return merged if active(merged) else None

    async def get_live_state(self) -> dict[str, Any]:
        async with self._lock:
            device_state = deepcopy(self._state["device"])
        return {
            "device": device_state,
            "generated_at": utcnow_iso(),
            "uptime_seconds": int(time.time() - self.started_at),
        }

    async def wait_for_live_frame(
        self,
        last_sequence: int,
        timeout_seconds: float | None = None,
    ) -> tuple[int, bytes | None]:
        async with self._live_frame_condition:
            if self._live_frame_sequence <= last_sequence:
                wait_task = self._live_frame_condition.wait_for(
                    lambda: self._live_frame_sequence > last_sequence
                )
                try:
                    if timeout_seconds is None:
                        await wait_task
                    else:
                        await asyncio.wait_for(wait_task, timeout=max(0.05, timeout_seconds))
                except asyncio.TimeoutError:
                    return self._live_frame_sequence, None
            return self._live_frame_sequence, self._live_frame_bytes

    async def mark_stale_if_needed(self, timeout_seconds: int = 6) -> bool:
        async with self._lock:
            if not self._state["device"]["online"]:
                return False
            if self.last_device_seen_monotonic <= 0:
                return False
            if (time.monotonic() - self.last_device_seen_monotonic) < timeout_seconds:
                return False
            self._state["device"]["online"] = False
            self._state["device"]["comm_state"] = "timeout"
            self._state["device"]["stream_state"] = "stalled"
            self._state["generated_at"] = utcnow_iso()
            return True

    def _ingest_io(
        self,
        normalized: dict[str, Any],
        frame_bytes: bytes | None,
        ingest_started: float,
    ) -> tuple[int, dict[str, float]]:
        timing: dict[str, float] = {}
        if frame_bytes:
            image_started = time.monotonic()
            annotated_frame_bytes = self._annotate_result_frame(frame_bytes, normalized)
            self._write_bytes_atomic(self.latest_frame_path, annotated_frame_bytes)
            self._write_bytes_atomic(
                self.frames_dir / f"{normalized['frame_id']}.jpg",
                annotated_frame_bytes,
            )
            if normalized["result"] == "NG":
                self._write_bytes_atomic(
                    self.archive_dir / f"{normalized['frame_id']}.jpg",
                    annotated_frame_bytes,
                )
            timing["image_process_write_ms"] = round((time.monotonic() - image_started) * 1000.0, 2)

        database_started = time.monotonic()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO inspection_records (
                    frame_id, ts, event_epoch_ms, result, defect_count, inference_ms, width, height, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized["frame_id"],
                    normalized["timestamp"],
                    normalized["event_epoch_ms"],
                    normalized["result"],
                    normalized["defect_count"],
                    normalized["inference_ms"],
                    normalized["frame"]["width"],
                    normalized["frame"]["height"],
                    json.dumps(normalized, ensure_ascii=True),
                ),
            )
            record_id = safe_int(cursor.lastrowid)
            for item in normalized["detections"]:
                bbox = item["bbox"]
                conn.execute(
                    """
                    INSERT INTO detections (
                        record_id, label, confidence, x, y, w, h, normalized
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        item["label"],
                        item["confidence"],
                        bbox["x"],
                        bbox["y"],
                        bbox["w"],
                        bbox["h"],
                        1 if bbox["normalized"] else 0,
                    ),
                )
            conn.commit()
            timing["database_ms"] = round((time.monotonic() - database_started) * 1000.0, 2)
            timing["total_ms"] = round((time.monotonic() - ingest_started) * 1000.0, 2)
            pipeline_timing = normalized["pipeline_timing"]
            pipeline_timing["dashboard_ingest_ms"] = timing["total_ms"]
            trigger_epoch_ms = safe_int(normalized.get("trigger_epoch_ms"), 0)
            if trigger_epoch_ms > 0:
                pipeline_timing["trigger_to_dashboard_ms"] = round(
                    max(0.0, time.time() * 1000.0 - trigger_epoch_ms), 2
                )
            conn.execute(
                "UPDATE inspection_records SET payload_json = ? WHERE id = ?",
                (json.dumps(normalized, ensure_ascii=True), record_id),
            )
            conn.commit()
        return record_id, timing

    def _card_from_normalized(self, record_id: int, normalized: dict[str, Any]) -> dict[str, Any]:
        detections = deepcopy(normalized["detections"])
        return {
            "id": record_id,
            "frame_id": normalized["frame_id"],
            "timestamp": normalized["timestamp"],
            "result": normalized["result"],
            "defect_count": normalized["defect_count"],
            "inference_ms": normalized["inference_ms"],
            "board_inference_ms": normalized["board_inference_ms"],
            "board_roundtrip_ms": normalized["board_roundtrip_ms"],
            "pipeline_timing": deepcopy(normalized["pipeline_timing"]),
            "frame": deepcopy(normalized["frame"]),
            "detections": detections,
            "top_labels": self._top_labels(detections),
            "payload": deepcopy(normalized),
            "image_url": self._frame_url(normalized["frame_id"]),
        }

    def _update_incremental_state(self, normalized: dict[str, Any], record_id: int) -> None:
        self.last_device_seen_monotonic = time.monotonic()
        self._state["device"].update(
            {
                "online": True,
                "board_name": normalized["board_name"],
                "comm_state": "connected",
                "model_name": normalized["model_name"],
                "last_seen_at": normalized["timestamp"],
                "stream_state": "live",
                "circle_count": safe_int(
                    normalized.get("circle_count"), self._state["device"].get("circle_count", 0)
                ),
                "selected_circle": normalized.get("target_circle") or normalized.get("selected_circle"),
            }
        )

        summary = self._state["summary"]
        old_total = safe_int(summary.get("total_count"), 0)
        new_total = old_total + 1
        old_average = safe_float(summary.get("avg_inference_ms"), 0.0)
        good_count = safe_int(summary.get("good_count"), 0) + (1 if normalized["result"] == "OK" else 0)
        bad_count = safe_int(summary.get("bad_count"), 0) + (1 if normalized["result"] == "NG" else 0)
        self._state["summary"] = {
            "total_count": new_total,
            "good_count": good_count,
            "bad_count": bad_count,
            "yield_rate": round((good_count / new_total) * 100.0, 2),
            "avg_inference_ms": round(
                ((old_average * old_total) + normalized["inference_ms"]) / new_total, 2
            ),
        }

        card = self._card_from_normalized(record_id, normalized)
        self._state["latest_result"] = card
        self._state["recent_results"] = [card] + self._state["recent_results"][:2]
        record = {
            "id": record_id,
            "frame_id": normalized["frame_id"],
            "timestamp": normalized["timestamp"],
            "result": normalized["result"],
            "defect_count": normalized["defect_count"],
            "inference_ms": normalized["inference_ms"],
            "labels": ", ".join(card["top_labels"]) or "--",
            "width": normalized["frame"]["width"],
            "height": normalized["frame"]["height"],
            "image_url": card["image_url"],
        }
        self._state["history"]["records"] = [record] + self._state["history"]["records"][:49]

        defect_counts = {item["name"]: safe_int(item["value"]) for item in self._state["defect_summary"]}
        for label in unique_detection_labels(normalized["detections"]):
            defect_counts[label] = defect_counts.get(label, 0) + 1
        self._state["defect_summary"] = [
            {"name": name, "value": value}
            for name, value in sorted(defect_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        self._state["history"]["defect_distribution"] = deepcopy(self._state["defect_summary"][:8])
        self._state["generated_at"] = utcnow_iso()

    async def ingest(
        self,
        payload: dict[str, Any],
        frame_bytes: bytes | None = None,
    ) -> tuple[dict[str, Any], dict[str, float]]:
        ingest_started = time.monotonic()
        normalized = self._normalize_payload(payload)
        async with self._lock:
            record_id, server_timing = await asyncio.to_thread(
                self._ingest_io,
                normalized,
                frame_bytes,
                ingest_started,
            )
            self._update_incremental_state(normalized, record_id)
            return deepcopy(self._state), server_timing

    async def refresh_history_trend(self) -> dict[str, Any]:
        def load() -> list[dict[str, Any]]:
            with self._connect() as conn:
                return self._build_history_trend(conn)

        trend = await asyncio.to_thread(load)
        async with self._lock:
            self._state["history"]["trend"] = trend
            self._state["generated_at"] = utcnow_iso()
            return {
                "trend": deepcopy(trend),
                "generated_at": self._state["generated_at"],
            }

    async def refresh_analytics(self) -> dict[str, Any]:
        """Compatibility wrapper retained for storage-level callers and tests."""

        await self.refresh_history_trend()
        async with self._lock:
            return deepcopy(self._state)

    async def get_snapshot(self) -> dict[str, Any]:
        async with self._lock:
            snapshot = deepcopy(self._state)
        snapshot["uptime_seconds"] = int(time.time() - self.started_at)
        snapshot["generated_at"] = utcnow_iso()
        return snapshot
