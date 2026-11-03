from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests


LABEL_CN = {
    "ca_shang": "擦伤",
    "cashang": "擦伤",
    "zang_wu": "脏污",
    "zangwu": "脏污",
    "zhe_zhou": "折皱",
    "zhezhou": "折皱",
    "zhen_kong": "针孔",
    "zhenkong": "针孔",
    "zheng_chang": "正常",
    "zhengchang": "正常",
    "scratch": "擦伤",
    "stain": "脏污",
    "dirty": "脏污",
    "wrinkle": "折皱",
    "fold": "折皱",
    "pinhole": "针孔",
    "normal": "正常",
}
NORMAL_LABELS = {"zheng_chang", "zhengchang", "normal", "ok", "good", "正常", "良品"}


@dataclass
class TransportResult:
    mode: str
    ok: bool
    detail: str
    response_payload: dict[str, Any] | None = None
    timing_ms: dict[str, float] = field(default_factory=dict)
    artifact_image_bytes: bytes | None = None
    artifact_payload: dict[str, Any] | None = None


@dataclass
class BoardInferenceResult:
    result: str
    detections: list[dict[str, Any]]
    defect_count: int
    inference_ms: float
    roundtrip_ms: float
    raw_payload: dict[str, Any] | None = None
    response_image_bytes: bytes | None = None
    detail: str = ""


def multipart_encode(
    fields: dict[str, str],
    file_field_name: str,
    file_name: str,
    file_bytes: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    boundary = f"----circleboundary{int(time.time() * 1000)}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{file_field_name}"; filename="{file_name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), boundary


class DashboardTransport:
    def __init__(
        self,
        artifacts_dir: Path,
        ingest_endpoint_url: str | None = None,
        live_frame_endpoint_url: str | None = None,
        request_timeout: float = 3.0,
        live_frame_request_timeout: float = 0.35,
        live_frame_width: int = 1536,
        live_frame_height: int = 1024,
        live_frame_jpeg_quality: int = 85,
        crop_min_area_ratio: float = 0.05,
        board_predict_url: str | None = None,
        board_file_field: str = "image_file",
        board_score_thresh: float = 0.2,
        board_request_timeout: float | None = None,
        board_input_size: int = 300,
        board_jpeg_quality: int = 85,
        board_send_raw: bool = False,
        live_frame_scale: float = 1.0,
    ) -> None:
        self.artifacts_dir = artifacts_dir
        self.ingest_endpoint_url = ingest_endpoint_url
        self.live_frame_endpoint_url = live_frame_endpoint_url
        self.request_timeout = request_timeout
        self.live_frame_request_timeout = max(0.05, float(live_frame_request_timeout))
        self.live_frame_width = max(0, int(live_frame_width))
        self.live_frame_height = max(0, int(live_frame_height))
        self.live_frame_scale = float(live_frame_scale)
        if not math.isfinite(self.live_frame_scale) or not 0 < self.live_frame_scale <= 1:
            raise ValueError("LIVE_FRAME_SCALE 必须大于 0 且不超过 1")
        self.live_frame_jpeg_quality = max(35, min(95, int(live_frame_jpeg_quality)))
        self.crop_min_area_ratio = max(0.0, min(1.0, float(crop_min_area_ratio)))
        self.board_predict_url = (board_predict_url or "").strip()
        self.board_file_field = (board_file_field or "image_file").strip() or "image_file"
        self.board_score_thresh = max(0.0, float(board_score_thresh))
        self.board_input_size = max(32, int(board_input_size))
        self.board_jpeg_quality = max(35, min(95, int(board_jpeg_quality)))
        self.board_send_raw = bool(board_send_raw)
        self.board_request_timeout = (
            max(0.2, float(board_request_timeout))
            if board_request_timeout is not None
            else max(0.2, float(request_timeout))
        )
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._live_frame_condition = threading.Condition()
        self._live_frame_pending: tuple[Any, str] | None = None
        self._live_frame_stop = False
        self._live_frame_last_error: str | None = None
        self._live_frame_thread: threading.Thread | None = None
        self._request_session = requests.Session()
        self._live_session = requests.Session()

        if self.live_frame_endpoint_url:
            self._live_frame_thread = threading.Thread(
                target=self._live_frame_worker,
                name="dashboard-live-frame-uploader",
                daemon=True,
            )
            self._live_frame_thread.start()

    def send_live_frame(self, annotated_frame, payload: dict[str, Any]) -> TransportResult:
        if not self.live_frame_endpoint_url:
            return TransportResult(mode="live-frame", ok=False, detail="未配置实时预览上传接口")

        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._live_frame_condition:
            # 只保留最新一帧，避免网络抖动时排队越积越多。
            self._live_frame_pending = (annotated_frame, payload_json)
            self._live_frame_condition.notify()

        return TransportResult(mode="live-frame", ok=True, detail="实时预览帧已加入发送队列")

    def consume_live_frame_error(self) -> str | None:
        with self._live_frame_condition:
            error = self._live_frame_last_error
            self._live_frame_last_error = None
            return error

    def close(self) -> None:
        with self._live_frame_condition:
            self._live_frame_stop = True
            self._live_frame_condition.notify_all()
        if self._live_frame_thread is not None:
            self._live_frame_thread.join(timeout=1.0)
        self._request_session.close()
        self._live_session.close()

    def _reset_session(self, live: bool = False) -> None:
        if live:
            self._live_session.close()
            self._live_session = requests.Session()
        else:
            self._request_session.close()
            self._request_session = requests.Session()

    def _live_frame_worker(self) -> None:
        while True:
            with self._live_frame_condition:
                while self._live_frame_pending is None and not self._live_frame_stop:
                    self._live_frame_condition.wait()
                if self._live_frame_stop and self._live_frame_pending is None:
                    return
                pending = self._live_frame_pending
                self._live_frame_pending = None

            if pending is None:
                continue

            annotated_frame, payload_json = pending
            result = self._send_live_frame_now(annotated_frame, payload_json)
            if not result.ok:
                with self._live_frame_condition:
                    self._live_frame_last_error = result.detail

    def _send_live_frame_now(self, annotated_frame, payload_json: str) -> TransportResult:
        import cv2

        prepared = self._prepare_live_frame(annotated_frame)
        ok, encoded = cv2.imencode(
            ".jpg",
            prepared,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.live_frame_jpeg_quality],
        )
        if not ok:
            return TransportResult(mode="live-frame", ok=False, detail="实时预览帧 JPEG 编码失败")

        try:
            response = self._live_session.post(
                self.live_frame_endpoint_url,
                data={"payload": payload_json},
                files={"frame": ("live_annotated.jpg", encoded.tobytes(), "image/jpeg")},
                timeout=(0.1, self.live_frame_request_timeout),
            )
            response.raise_for_status()
            return TransportResult(mode="live-frame", ok=True, detail=f"实时预览已发送到 {self.live_frame_endpoint_url}")
        except Exception as exc:
            self._reset_session(live=True)
            return TransportResult(mode="live-frame", ok=False, detail=f"实时预览发送失败: {exc}")

    def _prepare_live_frame(self, annotated_frame):
        import cv2

        height, width = annotated_frame.shape[:2]
        # Fit within the preview bounds, then scale both dimensions. Never pad,
        # crop, or upscale; detection continues to use its separate input.
        scale = 1.0
        if self.live_frame_width > 0 and self.live_frame_height > 0:
            scale = min(1.0, self.live_frame_width / width, self.live_frame_height / height)
        scale *= self.live_frame_scale
        if scale == 1.0:
            return annotated_frame
        resized_width = max(1, int(round(width * scale)))
        resized_height = max(1, int(round(height * scale)))
        return cv2.resize(annotated_frame, (resized_width, resized_height), interpolation=cv2.INTER_AREA)

    def export_gray_payload(self, gray_image, metadata: dict[str, Any]) -> TransportResult:
        import cv2

        timing_ms = dict(metadata.get("pipeline_timing") or {})
        preprocess_started = time.monotonic()
        crop_circle = self._select_crop_circle(metadata)
        cropped_gray, crop_info = self._crop_target_square(gray_image, crop_circle)
        model_input_rgb, resize_info = self._prepare_model_input(cropped_gray)
        tensor_height, tensor_width = model_input_rgb.shape[:2]
        tensor_shape = [1, 3, int(tensor_height), int(tensor_width)]
        ok, encoded = cv2.imencode(
            ".jpg",
            cv2.cvtColor(model_input_rgb, cv2.COLOR_RGB2BGR),
            [int(cv2.IMWRITE_JPEG_QUALITY), self.board_jpeg_quality],
        )
        if not ok:
            return TransportResult(
                mode="http-multipart",
                ok=False,
                detail="模型输入图 JPEG 编码失败",
                timing_ms=timing_ms,
            )
        model_input_jpeg = encoded.tobytes()
        timing_ms["preprocess_encode_ms"] = round((time.monotonic() - preprocess_started) * 1000.0, 2)

        payload_body = {
            "line_id": metadata.get("line_id"),
            "timestamp": metadata.get("timestamp"),
            "frame_id": metadata.get("frame_id"),
            "trigger_epoch_ms": metadata.get("trigger_epoch_ms"),
            "board_name": metadata.get("board_name"),
            "model_name": metadata.get("model_name"),
            "result": metadata.get("result"),
            "defect_count": metadata.get("defect_count", 0),
            "frame": {"width": int(tensor_width), "height": int(tensor_height), "channels": 3},
            "source_frame": metadata.get("frame"),
            "notes": metadata.get("notes", ""),
            "target_circle": metadata.get("selected_circle"),
            "crop_circle": crop_circle,
            "all_circles": metadata.get("all_circles"),
            "trigger_source": "circle_monitor",
            "gray_payload": True,
            "crop_min_area_ratio": self.crop_min_area_ratio,
            "model_input": {
                "tensor_shape": tensor_shape,
                "layout": "NCHW",
                "dtype": "uint8",
                "image_shape": [3, int(tensor_height), int(tensor_width)],
                "color_space": "RGB",
                "source": "grayscale replicated to 3 RGB channels",
                "crop_mode": "largest_circle_square_with_padding",
                "crop_info": crop_info,
                "resize_mode": "fixed_square",
                "resize_info": resize_info,
            },
            "pipeline_timing": timing_ms,
        }

        response_payload: dict[str, Any] | None = None
        dashboard_frame_bytes = model_input_jpeg
        dashboard_frame_name = "model_input_3ch.jpg"
        board_detail = ""

        if self.board_predict_url:
            try:
                if self.board_send_raw:
                    # 方案A：向板端发送无压缩的原始 RGB888 字节流（HWC 交错序，
                    # 320×320×3=307200 字节），板端免去 JPEG 解码。看板/归档仍使用
                    # 上面的 model_input_jpeg，不受影响。
                    board_input_bytes = model_input_rgb.tobytes()
                    board_result = self._infer_on_board(
                        board_input_bytes, int(tensor_width), int(tensor_height), raw=True
                    )
                else:
                    board_result = self._infer_on_board(model_input_jpeg, int(tensor_width), int(tensor_height))
            except Exception as exc:
                self._reset_session()
                return TransportResult(
                    mode="board-predict",
                    ok=False,
                    detail=f"板端推理失败: {type(exc).__name__}: {exc}",
                    timing_ms=timing_ms,
                    artifact_image_bytes=model_input_jpeg,
                    artifact_payload=payload_body,
                )

            timing_ms["board_inference_ms"] = round(board_result.inference_ms, 2)
            timing_ms["board_roundtrip_ms"] = round(board_result.roundtrip_ms, 2)

            payload_body.update(
                {
                    "result": board_result.result,
                    "defect_count": board_result.defect_count,
                    "detections": board_result.detections,
                    "inference_ms": board_result.inference_ms,
                    "board_inference_ms": board_result.inference_ms,
                    "board_roundtrip_ms": board_result.roundtrip_ms,
                    "board_predict_url": self.board_predict_url,
                    "board_response": board_result.raw_payload,
                    "notes": (
                        str(payload_body.get("notes") or "")
                        + f" board_result={board_result.result} defects={board_result.defect_count}"
                    ).strip(),
                }
            )
            response_payload = {
                "result": board_result.result,
                "defect_count": board_result.defect_count,
                "detections": board_result.detections,
                "board": board_result.raw_payload,
                "pipeline_timing": timing_ms,
            }
            if board_result.response_image_bytes:
                dashboard_frame_bytes = board_result.response_image_bytes
                dashboard_frame_name = "board_result.jpg"
            board_detail = (
                f"板端判定={board_result.result} 缺陷数={board_result.defect_count} "
                f"纯推理={board_result.inference_ms:.1f}ms 往返={board_result.roundtrip_ms:.1f}ms"
            )

        if not self.ingest_endpoint_url:
            detail = board_detail or "未配置触发图上传接口"
            return TransportResult(
                mode="board-predict" if self.board_predict_url else "file",
                ok=True,
                detail=detail,
                response_payload=response_payload,
                timing_ms=timing_ms,
                artifact_image_bytes=dashboard_frame_bytes,
                artifact_payload=payload_body,
            )

        dashboard_started = time.monotonic()
        try:
            response = self._request_session.post(
                self.ingest_endpoint_url,
                data={"payload": json.dumps(payload_body, ensure_ascii=False)},
                files={"frame": (dashboard_frame_name, dashboard_frame_bytes, "image/jpeg")},
                timeout=(0.2, self.request_timeout),
            )
            response.raise_for_status()
            timing_ms["dashboard_roundtrip_ms"] = round((time.monotonic() - dashboard_started) * 1000.0, 2)
            dashboard_response_payload = self._decode_response_payload(response.content)
            server_timing = (dashboard_response_payload or {}).get("server_timing_ms")
            if isinstance(server_timing, dict):
                timing_ms["dashboard_ingest_ms"] = round(
                    self._safe_float(server_timing.get("total_ms"), timing_ms["dashboard_roundtrip_ms"]), 2
                )
            if response_payload is None:
                response_payload = dashboard_response_payload
            elif dashboard_response_payload is not None:
                response_payload["dashboard"] = dashboard_response_payload
            detail = f"已按 multipart/form-data 发送到 {self.ingest_endpoint_url}"
            if board_detail:
                detail = f"{board_detail} | {detail}"
            return TransportResult(
                mode="http-multipart",
                ok=True,
                detail=detail,
                response_payload=response_payload,
                timing_ms=timing_ms,
                artifact_image_bytes=dashboard_frame_bytes,
                artifact_payload=payload_body,
            )
        except Exception as exc:
            timing_ms["dashboard_roundtrip_ms"] = round((time.monotonic() - dashboard_started) * 1000.0, 2)
            self._reset_session()
            return TransportResult(
                mode="http-multipart",
                ok=False,
                detail=f"HTTP multipart 发送失败: {exc}",
                response_payload=response_payload,
                timing_ms=timing_ms,
                artifact_image_bytes=dashboard_frame_bytes,
                artifact_payload=payload_body,
            )

    def _infer_on_board(
        self,
        image_bytes: bytes,
        frame_width: int,
        frame_height: int,
        *,
        raw: bool = False,
    ) -> BoardInferenceResult:
        start = time.monotonic()
        filename = "image_file.raw" if raw else "image_file.jpg"
        content_type = "application/octet-stream" if raw else "image/jpeg"
        response = self._request_session.post(
            self.board_predict_url,
            files={self.board_file_field: (filename, image_bytes, content_type)},
            timeout=(0.5, self.board_request_timeout),
        )
        response.raise_for_status()
        response_body = response.content
        headers = response.headers
        elapsed_ms = (time.monotonic() - start) * 1000.0

        payload = self._decode_response_payload(response_body)
        if payload is not None:
            return self._board_result_from_payload(payload, frame_width, frame_height, elapsed_ms)

        has_defect_header = headers.get("X-Has-Defect")
        if has_defect_header is not None:
            return self._board_result_from_header(
                has_defect_header,
                elapsed_ms,
                response_body if self._looks_like_image(headers.get("Content-Type", ""), response_body) else None,
            )

        content_type = headers.get("Content-Type", "")
        raise ValueError(f"板端返回既不是 JSON，也没有 X-Has-Defect 响应头(Content-Type={content_type})")

    def _board_result_from_header(
        self,
        has_defect_header: str,
        inference_ms: float,
        response_image_bytes: bytes | None,
    ) -> BoardInferenceResult:
        normalized = str(has_defect_header).strip().lower()
        has_defect = normalized in {"1", "true", "yes", "y", "ng", "defect", "bad"}
        result = "NG" if has_defect else "OK"
        return BoardInferenceResult(
            result=result,
            detections=[],
            defect_count=1 if has_defect else 0,
            inference_ms=round(inference_ms, 2),
            roundtrip_ms=round(inference_ms, 2),
            raw_payload={"x_has_defect": has_defect_header},
            response_image_bytes=response_image_bytes,
            detail="image-header",
        )

    def _board_result_from_payload(
        self,
        payload: dict[str, Any],
        frame_width: int,
        frame_height: int,
        inference_ms: float,
    ) -> BoardInferenceResult:
        items: list[Any] = []
        result_value = payload.get("result")
        if isinstance(result_value, list):
            items = result_value
        elif isinstance(payload.get("detections"), list):
            items = payload["detections"]
        elif isinstance(payload.get("boxes"), list):
            items = payload["boxes"]

        had_raw_candidates = bool(items)
        candidates: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            det = self._normalize_board_detection(raw, frame_width, frame_height)
            if det is not None:
                candidates.append(det)
        selected = self._select_highest_confidence_class(candidates)
        normal_won = bool(selected and selected[0].get("_is_normal"))
        detections: list[dict[str, Any]] = []
        if selected and not normal_won:
            for item in selected:
                public_item = dict(item)
                public_item.pop("_is_normal", None)
                detections.append(public_item)

        if detections:
            result = "NG"
        elif normal_won or had_raw_candidates:
            result = "OK"
        elif isinstance(result_value, str) and result_value.strip().upper() in {"OK", "NG"}:
            result = result_value.strip().upper()
        else:
            result = "OK"

        if detections:
            defect_count = len(detections)
        elif result == "OK":
            defect_count = 0
        else:
            defect_count = max(1, self._safe_int(payload.get("defect_count"), 1))

        payload_inference_ms = self._safe_float(payload.get("inference_ms"), inference_ms)
        return BoardInferenceResult(
            result=result,
            detections=detections,
            defect_count=defect_count,
            inference_ms=round(payload_inference_ms, 2),
            roundtrip_ms=round(inference_ms, 2),
            raw_payload=payload,
            detail="json",
        )

    def _normalize_board_detection(
        self,
        raw: dict[str, Any],
        frame_width: int,
        frame_height: int,
    ) -> dict[str, Any] | None:
        raw_label = str(
            raw.get("class_name")
            or raw.get("label")
            or raw.get("name")
            or raw.get("category")
            or ""
        ).strip()
        if not raw_label:
            return None

        score = self._safe_float(raw.get("score", raw.get("confidence", raw.get("probability"))), 0.0)
        if score < self.board_score_thresh:
            return None

        normalized_label_key = raw_label.lower()
        is_normal = normalized_label_key in NORMAL_LABELS or raw_label in NORMAL_LABELS

        bbox = self._board_bbox(raw, frame_width, frame_height)
        if bbox is None:
            return None

        label = LABEL_CN.get(normalized_label_key, LABEL_CN.get(raw_label, raw_label))
        return {
            "label": label,
            "confidence": round(score, 4),
            "bbox": bbox,
            "_is_normal": is_normal,
        }

    def _select_highest_confidence_class(
        self,
        detections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not detections:
            return []
        # Defects win exact normal/defect score ties; otherwise max() keeps response order.
        winner = max(
            detections,
            key=lambda item: (
                self._safe_float(item.get("confidence")),
                0 if item.get("_is_normal") else 1,
            ),
        )
        winner_label = str(winner.get("label") or "")
        return [item for item in detections if str(item.get("label") or "") == winner_label]

    def _board_bbox(self, raw: dict[str, Any], frame_width: int, frame_height: int) -> dict[str, float] | None:
        loc = raw.get("loc")
        if isinstance(loc, (list, tuple)) and len(loc) >= 4:
            x1 = self._safe_float(loc[0])
            y1 = self._safe_float(loc[1])
            x2 = self._safe_float(loc[2])
            y2 = self._safe_float(loc[3])
            x = x1
            y = y1
            w = max(0.0, x2 - x1)
            h = max(0.0, y2 - y1)
        else:
            bbox_raw = raw.get("bbox") if isinstance(raw.get("bbox"), dict) else {}
            x = self._safe_float(bbox_raw.get("x", raw.get("x")))
            y = self._safe_float(bbox_raw.get("y", raw.get("y")))
            w_value = bbox_raw.get("w", raw.get("w"))
            h_value = bbox_raw.get("h", raw.get("h"))
            if w_value is None and raw.get("x2") is not None:
                w_value = self._safe_float(raw.get("x2")) - x
            if h_value is None and raw.get("y2") is not None:
                h_value = self._safe_float(raw.get("y2")) - y
            w = max(0.0, self._safe_float(w_value))
            h = max(0.0, self._safe_float(h_value))

        if frame_width <= 0 or frame_height <= 0:
            return None
        if max(abs(x), abs(y), abs(w), abs(h)) > 1.2:
            x = x / frame_width
            y = y / frame_height
            w = w / frame_width
            h = h / frame_height
        return {
            "x": round(max(0.0, min(1.0, x)), 4),
            "y": round(max(0.0, min(1.0, y)), 4),
            "w": round(max(0.0, min(1.0, w)), 4),
            "h": round(max(0.0, min(1.0, h)), 4),
        }

    def _looks_like_image(self, content_type: str, response_body: bytes) -> bool:
        lower_type = (content_type or "").lower()
        return (
            lower_type.startswith("image/")
            or response_body.startswith(b"\xff\xd8")
            or response_body.startswith(b"\x89PNG\r\n\x1a\n")
        )

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _decode_response_payload(self, response_body: bytes) -> dict[str, Any] | None:
        if not response_body:
            return None
        try:
            decoded = response_body.decode("utf-8")
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _select_crop_circle(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
        all_circles = metadata.get("all_circles") or []
        valid_circles = [circle for circle in all_circles if isinstance(circle, dict)]
        frame_info = metadata.get("frame") or metadata.get("frame_size") or {}
        frame_width = int(frame_info.get("width") or 0)
        frame_height = int(frame_info.get("height") or 0)
        frame_area = frame_width * frame_height
        if valid_circles and frame_area > 0:
            qualified_circles = []
            for circle in valid_circles:
                radius = max(0.0, float(circle.get("radius") or 0.0))
                circle_area_ratio = (math.pi * radius * radius) / frame_area
                if circle_area_ratio >= self.crop_min_area_ratio:
                    qualified_circles.append(circle)
            if qualified_circles:
                return qualified_circles[0]
        selected_circle = metadata.get("selected_circle")
        return selected_circle if isinstance(selected_circle, dict) else None

    def _crop_target_square(self, gray_image, selected_circle: dict[str, Any] | None):
        import numpy as np

        source_height, source_width = gray_image.shape[:2]
        if not selected_circle:
            crop_info = {
                "mode": "full_frame_square",
                "source_width": int(source_width),
                "source_height": int(source_height),
            }
            return gray_image, crop_info

        center_x = int(round(selected_circle.get("x", source_width / 2)))
        center_y = int(round(selected_circle.get("y", source_height / 2)))
        radius = max(1, int(round(selected_circle.get("radius", min(source_width, source_height) / 4))))

        padding_scale = 1.35
        extra_padding_px = 12
        half_extent = max(int(round(radius * padding_scale)), radius + extra_padding_px)
        side = half_extent * 2
        x1 = center_x - half_extent
        y1 = center_y - half_extent
        x2 = center_x + half_extent
        y2 = center_y + half_extent

        src_x1 = max(0, x1)
        src_y1 = max(0, y1)
        src_x2 = min(source_width, x2)
        src_y2 = min(source_height, y2)

        crop = np.zeros((side, side), dtype=gray_image.dtype)
        dst_x1 = src_x1 - x1
        dst_y1 = src_y1 - y1
        dst_x2 = dst_x1 + (src_x2 - src_x1)
        dst_y2 = dst_y1 + (src_y2 - src_y1)
        crop[dst_y1:dst_y2, dst_x1:dst_x2] = gray_image[src_y1:src_y2, src_x1:src_x2]

        crop_info = {
            "mode": "largest_circle_square_with_padding",
            "source_width": int(source_width),
            "source_height": int(source_height),
            "center_x": int(center_x),
            "center_y": int(center_y),
            "radius": int(radius),
            "padding_scale": padding_scale,
            "extra_padding_px": extra_padding_px,
            "square_size": int(side),
            "source_box": {
                "x1": int(src_x1),
                "y1": int(src_y1),
                "x2": int(src_x2),
                "y2": int(src_y2),
            },
            "padding": {
                "left": int(dst_x1),
                "top": int(dst_y1),
                "right": int(side - dst_x2),
                "bottom": int(side - dst_y2),
            },
        }
        return crop, crop_info

    def _prepare_model_input(self, gray_image):
        import cv2

        source_height, source_width = gray_image.shape[:2]
        resized = cv2.resize(
            gray_image,
            (self.board_input_size, self.board_input_size),
            interpolation=cv2.INTER_AREA,
        )
        model_input_rgb = cv2.cvtColor(resized, cv2.COLOR_GRAY2RGB)

        resize_info = {
            "source_width": int(source_width),
            "source_height": int(source_height),
            "output_width": self.board_input_size,
            "output_height": self.board_input_size,
            "applied": source_width != self.board_input_size or source_height != self.board_input_size,
        }
        return model_input_rgb, resize_info
