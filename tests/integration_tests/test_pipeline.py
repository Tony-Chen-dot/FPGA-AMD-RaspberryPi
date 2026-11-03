from __future__ import annotations

import asyncio
import base64
from concurrent.futures import Future
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CIRCLE_CAMERA_DIR = PROJECT_ROOT / "vision"
VISION_BACKEND_DIR = PROJECT_ROOT / "dashboard" / "storage"
if str(CIRCLE_CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CIRCLE_CAMERA_DIR))

from vision.transport.inference_client import BoardInferenceResult, DashboardTransport
from vision.detection.circles import FrameEnhancer, EnhancementConfig, _resize_for_detection, annotate_frame
from vision.capture.hikrobot import HikrobotCameraCapture
from vision.capture.frame_reader import LatestFrameReader

MAIN_SPEC = importlib.util.spec_from_file_location(
    "circle_camera_latency_main",
    CIRCLE_CAMERA_DIR / "pipeline.py",
)
assert MAIN_SPEC is not None and MAIN_SPEC.loader is not None
main_module = importlib.util.module_from_spec(MAIN_SPEC)
sys.modules[MAIN_SPEC.name] = main_module
MAIN_SPEC.loader.exec_module(main_module)


STORAGE_SPEC = importlib.util.spec_from_file_location(
    "vision_dashboard_storage_latency_test",
    VISION_BACKEND_DIR / "database.py",
)
assert STORAGE_SPEC is not None and STORAGE_SPEC.loader is not None
storage_module = importlib.util.module_from_spec(STORAGE_SPEC)
STORAGE_SPEC.loader.exec_module(storage_module)


class ImagePipelineTests(unittest.TestCase):
    def test_trigger_thumbnail_encodes_unpadded_three_by_two_frame(self) -> None:
        app = object.__new__(main_module.CircleCameraApp)
        source = np.full((1024, 1536), 127, np.uint8)
        data_url = app._encode_trigger_snapshot(source)
        image = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1])))
        self.assertEqual(image.size, (480, 320))
        pixels = np.asarray(image)
        self.assertTrue(np.all(pixels[:, 0] > 120))
        self.assertTrue(np.all(pixels[:, -1] > 120))

    def test_trigger_overlay_uses_matching_raw_frame_without_changing_inference(self) -> None:
        app = object.__new__(main_module.CircleCameraApp)
        enhanced = np.zeros((720, 1280), np.uint8)
        raw = np.full((1024, 1536), 127, np.uint8)
        future = Future()
        future.set_result((["circle"], enhanced, enhanced))
        app.detection_future = future
        app.detection_preview_frame = raw
        app.detection_lock = threading.Lock()
        app.should_trigger = Mock(return_value=True)
        app.save_trigger_bundle = Mock(return_value=True)
        app._arm_trigger_overlay = Mock()
        app.print_status = Mock()
        app._poll_detection_result()
        self.assertIs(app._arm_trigger_overlay.call_args.args[0], raw)
        self.assertIs(app.save_trigger_bundle.call_args.args[0], enhanced)
        self.assertIs(app.save_trigger_bundle.call_args.args[1], enhanced)
        self.assertIsNone(app.detection_preview_frame)

    def test_preview_preserves_sensor_view_and_detection_input(self) -> None:
        capture = object.__new__(HikrobotCameraCapture)
        capture.width, capture.height = 1280, 720
        source = np.full((1024, 1536), 127, dtype=np.uint8)
        with patch.object(capture, "read_native", return_value=(True, source)):
            ok, detection, preview = capture.read_with_preview()
        self.assertTrue(ok)
        self.assertEqual(detection.shape, (720, 1280))
        self.assertTrue(np.all(detection[:, :100] == 0))
        np.testing.assert_array_equal(detection, capture._resize_to_output(source))
        np.testing.assert_array_equal(preview, source)

    def test_preview_scale_controls_dimensions_without_padding_or_upscaling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for scale, shape in ((1.0, (1024, 1536)), (0.75, (768, 1152)), (0.5, (512, 768))):
                with self.subTest(scale=scale):
                    transport = DashboardTransport(Path(directory), live_frame_scale=scale)
                    preview = transport._prepare_live_frame(np.full((1024, 1536), 127, np.uint8))
                    self.assertEqual(preview.shape, shape)
                    self.assertTrue(np.all(preview == 127))
                    # A higher-resolution sensor fits the same bounds first.
                    self.assertEqual(transport._prepare_live_frame(np.full((2048, 3072), 127, np.uint8)).shape, shape)
                    transport.close()
            transport = DashboardTransport(Path(directory))
            self.assertEqual(transport._prepare_live_frame(np.zeros((240, 320), np.uint8)).shape, (240, 320))
            transport.close()

    def test_preview_scale_rejects_invalid_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for scale in (0, -0.1, 1.1, float("nan"), float("inf")):
                with self.subTest(scale=scale), self.assertRaises(ValueError):
                    DashboardTransport(Path(directory), live_frame_scale=scale)

    def test_frame_reader_keeps_preview_paired_with_detection(self) -> None:
        class Camera:
            available = True

            def read_with_preview(self):
                if not self.available:
                    return False, None, None
                self.available = False
                return True, np.full((720, 1280), 23, np.uint8), np.full((1024, 1536), 42, np.uint8)

        reader = LatestFrameReader(Camera())
        reader.start()
        try:
            sequence, detection, preview = reader.get_latest_with_preview(0, timeout_seconds=1)
            self.assertEqual(sequence, 1)
            self.assertEqual(detection.shape, (720, 1280))
            self.assertEqual(preview.shape, (1024, 1536))
            self.assertEqual(int(detection[0, 0]), 23)
            self.assertEqual(int(preview[0, 0]), 42)
        finally:
            reader.stop()

    def test_monochrome_enhancer_keeps_single_channel(self) -> None:
        source = np.zeros((720, 1280), dtype=np.uint8)
        enhancer = FrameEnhancer(
            EnhancementConfig(
                median_denoise_kernel=0,
                bilateral_denoise_diameter=0,
                sharpen_amount=0,
            )
        )

        enhanced, normalized = enhancer.enhance(source)

        self.assertEqual(enhanced.shape, source.shape)
        self.assertEqual(normalized.shape, source.shape)
        self.assertEqual(enhanced.ndim, 2)
        self.assertEqual(normalized.ndim, 2)

    def test_detection_resize_preserves_full_frame_coverage(self) -> None:
        source = np.zeros((720, 1280), dtype=np.uint8)
        resized, scale = _resize_for_detection(source, max_width=384)

        self.assertEqual(resized.shape, (216, 384))
        self.assertAlmostEqual(scale, 0.3)

    def test_gray_annotation_converts_only_for_overlay_drawing(self) -> None:
        source = np.zeros((120, 160), dtype=np.uint8)

        annotated = annotate_frame(source, [], center_threshold_px=10)

        self.assertEqual(annotated.shape, (120, 160, 3))

    def test_hikrobot_output_resize_keeps_mono_frames_mono(self) -> None:
        capture = object.__new__(HikrobotCameraCapture)
        capture.width = 1280
        capture.height = 720

        output = capture._resize_to_output(np.zeros((2048, 3072), dtype=np.uint8))

        self.assertEqual(output.shape, (720, 1280))
        self.assertEqual(output.ndim, 2)

    def test_board_input_is_strict_300_square_three_channel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transport = DashboardTransport(Path(directory), board_input_size=300, board_jpeg_quality=85)
            image, resize_info = transport._prepare_model_input(np.zeros((417, 231), dtype=np.uint8))
            transport.close()

        self.assertEqual(image.shape, (300, 300, 3))
        self.assertTrue(resize_info["applied"])

    def test_formal_export_creates_no_png_or_raw_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = DashboardTransport(root, board_input_size=300, board_jpeg_quality=85)
            result = transport.export_gray_payload(
                np.zeros((480, 640), dtype=np.uint8),
                {
                    "timestamp": "test",
                    "frame_id": "frame-test",
                    "frame": {"width": 640, "height": 480},
                    "all_circles": [{"x": 320, "y": 240, "radius": 120}],
                    "selected_circle": {"x": 320, "y": 240, "radius": 120},
                    "pipeline_timing": {"queue_wait_ms": 1.0},
                },
            )
            transport.close()

            self.assertTrue(result.ok)
            self.assertIsNotNone(result.artifact_image_bytes)
            self.assertEqual(list(root.rglob("*.png")), [])
            self.assertEqual(list(root.rglob("*.raw")), [])
            self.assertEqual(list(root.iterdir()), [])

    def _board_export_metadata(self) -> dict:
        return {
            "timestamp": "test",
            "frame_id": "frame-test",
            "frame": {"width": 640, "height": 480},
            "all_circles": [{"x": 320, "y": 240, "radius": 120}],
            "selected_circle": {"x": 320, "y": 240, "radius": 120},
            "pipeline_timing": {"queue_wait_ms": 1.0},
        }

    def test_board_raw_mode_sends_uncompressed_rgb888_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transport = DashboardTransport(
                Path(directory),
                board_input_size=300,
                board_jpeg_quality=85,
                board_send_raw=True,
                board_predict_url="http://127.0.0.1:9/predict",
            )
            board_result = BoardInferenceResult(
                result="OK", detections=[], defect_count=0, inference_ms=1.0, roundtrip_ms=1.5
            )
            with patch.object(transport, "_infer_on_board", return_value=board_result) as infer:
                result = transport.export_gray_payload(
                    np.zeros((480, 640), dtype=np.uint8), self._board_export_metadata()
                )
            transport.close()

        infer.assert_called_once()
        sent_bytes, width, height = infer.call_args.args
        self.assertEqual((width, height), (300, 300))
        self.assertTrue(infer.call_args.kwargs.get("raw"))
        # 全零输入 → 原始 RGB888 字节也全为零；JPEG 编码永远不可能得到这种字节流。
        self.assertEqual(len(sent_bytes), 300 * 300 * 3)
        self.assertEqual(sent_bytes, bytes(300 * 300 * 3))
        # 看板/归档仍拿到 JPEG（分流），元数据声明与实际一致。
        self.assertTrue(result.artifact_image_bytes.startswith(b"\xff\xd8"))
        self.assertEqual(result.artifact_payload["model_input"]["dtype"], "uint8")

    def test_board_jpeg_mode_keeps_compressed_payload_for_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transport = DashboardTransport(
                Path(directory),
                board_input_size=300,
                board_jpeg_quality=85,
                board_predict_url="http://127.0.0.1:9/predict",
            )
            board_result = BoardInferenceResult(
                result="NG", detections=[], defect_count=1, inference_ms=2.0, roundtrip_ms=2.5
            )
            with patch.object(transport, "_infer_on_board", return_value=board_result) as infer:
                result = transport.export_gray_payload(
                    np.full((480, 640), 127, dtype=np.uint8), self._board_export_metadata()
                )
            transport.close()

        sent_bytes = infer.call_args.args[0]
        self.assertFalse(infer.call_args.kwargs.get("raw"))
        self.assertTrue(sent_bytes.startswith(b"\xff\xd8"))
        self.assertTrue(result.artifact_image_bytes.startswith(b"\xff\xd8"))

    def test_infer_on_board_raw_posts_octet_stream_content_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transport = DashboardTransport(
                Path(directory), board_predict_url="http://192.168.10.111:8080/predict"
            )
            fake_response = Mock()
            fake_response.content = json.dumps(
                {"result": "OK", "detections": [], "inference_ms": 2.0}
            ).encode("utf-8")
            fake_response.headers = {}
            transport._request_session.post = Mock(return_value=fake_response)

            payload_bytes = bytes(range(256)) * 2
            result = transport._infer_on_board(payload_bytes, 300, 300, raw=True)
            transport.close()

        files = transport._request_session.post.call_args.kwargs["files"]
        filename, content, content_type = files["image_file"]
        self.assertEqual(filename, "image_file.raw")
        self.assertEqual(content_type, "application/octet-stream")
        self.assertEqual(content, payload_bytes)
        self.assertEqual(result.result, "OK")


class DashboardStorageTests(unittest.TestCase):
    def test_empty_database_has_no_trend_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = storage_module.DashboardStorage(Path(directory))
            with storage._connect() as conn:
                trend = storage._build_history_trend(conn)

        self.assertEqual(trend, [])

    def test_full_history_trend_uses_ten_equal_buckets_with_zero_fill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = storage_module.DashboardStorage(Path(directory))
            oldest_epoch_ms = 1_700_000_000_000
            span_ms = 100_000
            records = [
                ("oldest", oldest_epoch_ms, "OK"),
                ("boundary-1", oldest_epoch_ms + 10_000, "NG"),
                ("middle", oldest_epoch_ms + 50_000, "OK"),
                ("newest", oldest_epoch_ms + span_ms, "NG"),
            ]
            with storage._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO inspection_records (
                        frame_id, ts, event_epoch_ms, result, defect_count,
                        inference_ms, width, height, payload_json
                    )
                    VALUES (?, ?, ?, ?, 0, 0, 80, 80, '{}')
                    """,
                    [
                        (frame_id, "2026-08-20T12:00:00+00:00", epoch_ms, result)
                        for frame_id, epoch_ms, result in records
                    ],
                )
                conn.commit()
                trend = storage._build_history_trend(conn)

        self.assertEqual(len(trend), 10)
        self.assertEqual([item["bucket_index"] for item in trend], list(range(10)))
        self.assertEqual([item["total_count"] for item in trend], [1, 1, 0, 0, 0, 1, 0, 0, 0, 1])
        self.assertEqual([item["bad_count"] for item in trend], [0, 1, 0, 0, 0, 0, 0, 0, 0, 1])
        self.assertEqual(sum(item["total_count"] for item in trend), len(records))
        self.assertEqual(trend[0]["bucket_start_epoch_ms"], oldest_epoch_ms)
        self.assertEqual(trend[-1]["bucket_end_epoch_ms"], oldest_epoch_ms + span_ms)
        self.assertTrue(all(item["bad_count"] <= item["total_count"] for item in trend))

    def test_invalid_timestamp_does_not_hide_valid_trend_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = storage_module.DashboardStorage(Path(directory))
            output = io.BytesIO()
            Image.new("RGB", (80, 80), color=(96, 96, 96)).save(output, format="JPEG")

            async def ingest_and_refresh() -> dict:
                await storage.ingest(
                    {
                        "frame_id": "valid-time",
                        "timestamp": "2026-08-20T12:00:00+08:00",
                        "result": "OK",
                        "frame": {"width": 80, "height": 80},
                    },
                    output.getvalue(),
                )
                await storage.ingest(
                    {
                        "frame_id": "invalid-time",
                        "timestamp": "not-a-timestamp",
                        "result": "NG",
                        "frame": {"width": 80, "height": 80},
                    },
                    output.getvalue(),
                )
                return await storage.refresh_analytics()

            snapshot = asyncio.run(ingest_and_refresh())

        self.assertEqual(len(snapshot["history"]["trend"]), 1)
        self.assertEqual(snapshot["history"]["trend"][0]["total_count"], 1)
        self.assertEqual(
            snapshot["history"]["trend"][0]["bucket_start_epoch_ms"],
            snapshot["history"]["trend"][0]["bucket_end_epoch_ms"],
        )

    def test_defect_summary_counts_each_label_once_per_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = storage_module.DashboardStorage(root)
            pinhole_boxes = [
                {
                    "label": "针孔",
                    "confidence": 0.9,
                    "bbox": {"x": index * 0.1, "y": 0.1, "w": 0.05, "h": 0.05},
                }
                for index in range(5)
            ]

            snapshot, _ = asyncio.run(
                storage.ingest(
                    {
                        "frame_id": "five-pinholes-one-image",
                        "timestamp": "2026-08-20T12:00:00+08:00",
                        "result": "NG",
                        "detections": pinhole_boxes,
                        "frame": {"width": 300, "height": 300},
                    }
                )
            )
            with storage._connect() as conn:
                counts = conn.execute(
                    """
                    SELECT COUNT(*) AS box_count, COUNT(DISTINCT record_id) AS image_count
                    FROM detections
                    WHERE label = '针孔'
                    """
                ).fetchone()
            reloaded_snapshot = asyncio.run(storage_module.DashboardStorage(root).get_snapshot())

        self.assertEqual(counts["box_count"], 5)
        self.assertEqual(counts["image_count"], 1)
        self.assertEqual(snapshot["defect_summary"], [{"name": "针孔", "value": 1}])
        self.assertEqual(reloaded_snapshot["defect_summary"], [{"name": "针孔", "value": 1}])
        self.assertEqual(
            reloaded_snapshot["history"]["defect_distribution"],
            [{"name": "针孔", "value": 1}],
        )

    def test_legacy_circle_timestamp_is_backfilled_for_trend_queries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = storage_module.DashboardStorage(root)
            with storage._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO inspection_records (
                        frame_id, ts, result, defect_count, inference_ms, width, height, payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "circle-20260820_191230_932407",
                        "20260820_191230_932407",
                        "NG",
                        1,
                        21.5,
                        80,
                        80,
                        "{}",
                    ),
                )
                conn.commit()

            migrated = storage_module.DashboardStorage(root)
            snapshot = asyncio.run(migrated.refresh_analytics())
            with migrated._connect() as conn:
                row = conn.execute(
                    "SELECT ts, event_epoch_ms FROM inspection_records WHERE frame_id = ?",
                    ("circle-20260820_191230_932407",),
                ).fetchone()

        self.assertIsNotNone(row)
        self.assertTrue(str(row["ts"]).endswith("+00:00"))
        self.assertGreater(int(row["event_epoch_ms"]), 0)
        self.assertEqual(len(snapshot["history"]["trend"]), 1)
        self.assertEqual(snapshot["history"]["trend"][0]["bad_count"], 1)

    def test_event_epoch_index_supports_trend_range_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = storage_module.DashboardStorage(Path(directory))
            with storage._connect() as conn:
                query_plan = conn.execute(
                    "EXPLAIN QUERY PLAN "
                    "SELECT result FROM inspection_records WHERE event_epoch_ms BETWEEN ? AND ?",
                    (1, 2),
                ).fetchall()

        details = " ".join(str(row[3]) for row in query_plan)
        self.assertIn("idx_inspection_records_event_epoch", details)

    def test_annotated_defect_label_omits_confidence_text(self) -> None:
        storage = object.__new__(storage_module.DashboardStorage)
        output = io.BytesIO()
        Image.new("RGB", (300, 300), color=(96, 96, 96)).save(output, format="JPEG")
        payload = {
            "result": "NG",
            "defect_count": 1,
            "frame": {"width": 300, "height": 300},
            "detections": [
                {
                    "label": "擦伤",
                    "confidence": 0.952,
                    "bbox": {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3, "normalized": True},
                }
            ],
        }

        font_patch = patch.object(
            storage_module,
            "annotation_font",
            return_value=(storage_module.ImageFont.load_default(), True),
        )
        draw_patch = patch.object(storage_module.ImageDraw, "Draw")
        with font_patch, draw_patch as draw_factory:
            draw_factory.return_value.textbbox.return_value = (0, 0, 80, 20)
            storage._annotate_result_frame(output.getvalue(), payload)

        drawn_text = [call.args[1] for call in draw_factory.return_value.text.call_args_list]
        self.assertEqual(drawn_text[-1], "擦伤")
        self.assertNotIn("%", drawn_text[-1])

    def test_ingest_returns_server_timing_and_wal_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = storage_module.DashboardStorage(Path(directory))
            output = io.BytesIO()
            Image.new("RGB", (300, 300), color=(96, 96, 96)).save(output, format="JPEG")
            snapshot, server_timing = asyncio.run(
                storage.ingest(
                    {
                        "frame_id": "frame-1",
                        "timestamp": "2026-08-17T12:00:00+08:00",
                        "result": "OK",
                        "inference_ms": 500,
                        "board_inference_ms": 500,
                        "board_roundtrip_ms": 620,
                        "frame": {"width": 300, "height": 300},
                        "pipeline_timing": {"queue_wait_ms": 2},
                    },
                    output.getvalue(),
                )
            )
            with storage._connect() as conn:
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

        self.assertEqual(journal_mode.lower(), "wal")
        self.assertEqual(snapshot["latest_result"]["frame_id"], "frame-1")
        self.assertIn("total_ms", server_timing)
        self.assertEqual(snapshot["latest_result"]["pipeline_timing"]["board_roundtrip_ms"], 620)

    def test_circle_monitor_results_remain_visible_after_storage_reload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            storage = storage_module.DashboardStorage(data_root)
            output = io.BytesIO()
            Image.new("RGB", (300, 300), color=(96, 96, 96)).save(output, format="JPEG")
            frame_bytes = output.getvalue()

            async def ingest_results() -> None:
                for index in range(4):
                    await storage.ingest(
                        {
                            "frame_id": f"circle-{index}",
                            "timestamp": f"2026-08-18T12:00:0{index}+08:00",
                            "result": "OK",
                            "trigger_source": "circle_monitor",
                            "frame": {"width": 300, "height": 300},
                        },
                        frame_bytes,
                    )

            asyncio.run(ingest_results())
            reloaded = storage_module.DashboardStorage(data_root)
            snapshot = asyncio.run(reloaded.get_snapshot())

        self.assertEqual(
            [item["frame_id"] for item in snapshot["recent_results"]],
            ["circle-3", "circle-2", "circle-1"],
        )
        self.assertTrue(all(item["image_url"] for item in snapshot["recent_results"]))
        self.assertEqual(snapshot["latest_result"]["payload"]["trigger_source"], "circle_monitor")

    def test_live_overlay_survives_frames_that_omit_overlay_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = storage_module.DashboardStorage(Path(directory))
            output = io.BytesIO()
            Image.new("RGB", (80, 80), color=(96, 96, 96)).save(output, format="JPEG")
            frame_bytes = output.getvalue()
            visible_until_ms = int(time.time() * 1000) + 1500

            async def update_frames() -> dict:
                await storage.update_live_frame(
                    frame_bytes,
                    {
                        "trigger_overlay": {
                            "image_data": "data:image/jpeg;base64,preview",
                            "expires_at_ms": visible_until_ms,
                            "sent_until_ms": 0,
                        }
                    },
                )
                await storage.update_live_frame(frame_bytes, {})
                return await storage.get_live_state()

            live_state = asyncio.run(update_frames())

        self.assertEqual(
            live_state["device"]["trigger_overlay"]["image_data"],
            "data:image/jpeg;base64,preview",
        )

    def test_expired_live_overlay_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = storage_module.DashboardStorage(Path(directory))
            output = io.BytesIO()
            Image.new("RGB", (80, 80), color=(96, 96, 96)).save(output, format="JPEG")

            asyncio.run(
                storage.update_live_frame(
                    output.getvalue(),
                    {
                        "trigger_overlay": {
                            "image_data": "data:image/jpeg;base64,expired",
                            "expires_at_ms": int(time.time() * 1000) - 1,
                            "sent_until_ms": 0,
                        }
                    },
                )
            )
            live_state = asyncio.run(storage.get_live_state())

        self.assertIsNone(live_state["device"]["trigger_overlay"])

    def test_trigger_overlay_duration_is_one_and_a_half_seconds(self) -> None:
        self.assertEqual(main_module.TRIGGER_OVERLAY_DURATION_MS, 1500)

    def test_frontend_overlay_timing_uses_the_server_clock(self) -> None:
        app_script = (PROJECT_ROOT / "dashboard" / "web" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("snapshotReceivedAtMs", app_script)
        self.assertIn("estimatedServerNowMs", app_script)
        self.assertIn("Number(overlay.expires_at_ms || 0) > this.estimatedServerNowMs", app_script)

    def test_frontend_trend_uses_shared_axis_and_draws_line_above_bars(self) -> None:
        app_script = (PROJECT_ROOT / "dashboard" / "web" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )
        index_html = (PROJECT_ROOT / "dashboard" / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("全周期检测趋势", index_html)
        self.assertIn('ref="trendChartEl"', index_html)
        self.assertRegex(
            app_script,
            r'name: "不良数",\s+type: "bar",\s+yAxisIndex: 0,\s+z: 1',
        )
        self.assertRegex(
            app_script,
            r'name: "总检测数",\s+type: "line",\s+yAxisIndex: 0,\s+z: 3',
        )
        self.assertIn("const trendSeries = hasTrend ? [", app_script)
        self.assertIn("series: trendSeries", app_script)
        self.assertIn("const { createApp, markRaw, nextTick } = Vue", app_script)
        self.assertEqual(app_script.count("markRaw(echarts.init("), 3)
        self.assertRegex(
            app_script,
            r"this\.yieldChart\.setOption\(\{[\s\S]+?\n\s+\}, true\);",
        )
        self.assertNotIn('areaStyle: { color: "rgba(60,240,255,0.16)" }', app_script)
        self.assertEqual(app_script.count('requestJson("/api/history/trend")'), 1)


class QueueIsolationTests(unittest.TestCase):
    def test_eight_jobs_finish_in_fifo_order(self) -> None:
        completed: list[int] = []
        worker = main_module.BoundedFifoWorker(
            "fifo-test",
            8,
            completed.append,
            lambda _name, exc: self.fail(str(exc)),
        )
        for index in range(8):
            self.assertTrue(worker.submit(index))
        worker.queue.join()
        worker.close()
        self.assertEqual(completed, list(range(8)))

    def test_action_wait_does_not_block_inference_worker(self) -> None:
        action_release = threading.Event()
        inference_done = threading.Event()
        action_worker = main_module.BoundedFifoWorker(
            "action-test",
            8,
            lambda _item: action_release.wait(1.0),
            lambda _name, exc: self.fail(str(exc)),
        )
        inference_worker = main_module.BoundedFifoWorker(
            "inference-test",
            8,
            lambda _item: inference_done.set(),
            lambda _name, exc: self.fail(str(exc)),
        )
        self.assertTrue(action_worker.submit("wait-five-seconds"))
        self.assertTrue(inference_worker.submit("next-sample"))
        self.assertTrue(inference_done.wait(0.5))
        action_release.set()
        action_worker.queue.join()
        inference_worker.queue.join()
        action_worker.close()
        inference_worker.close()

    def test_action_capacity_three_counts_active_plus_waiting(self) -> None:
        started = threading.Event()
        release = threading.Event()
        completed: list[int] = []

        def handle(item: int) -> None:
            started.set()
            release.wait(1.0)
            completed.append(item)

        worker = main_module.BoundedFifoWorker(
            "action-capacity-test",
            3,
            handle,
            lambda _name, exc: self.fail(str(exc)),
            capacity_includes_active=True,
        )
        self.assertTrue(worker.submit(1))
        self.assertTrue(started.wait(0.5))
        self.assertTrue(worker.submit(2))
        self.assertTrue(worker.submit(3))
        self.assertFalse(worker.submit(4))
        self.assertEqual(worker.active, 1)
        self.assertEqual(worker.depth, 2)
        self.assertEqual(worker.in_flight, 3)

        release.set()
        worker.queue.join()
        worker.close()
        self.assertEqual(completed, [1, 2, 3])
        self.assertEqual(worker.in_flight, 0)


class CompetitionConfigTests(unittest.TestCase):
    def test_local_dashboard_and_board_urls_are_not_mixed(self) -> None:
        config = (PROJECT_ROOT / "config.sh").read_text(encoding="utf-8")
        self.assertIn('DASHBOARD_INGEST_URL="http://127.0.0.1:8000/api/device/ingest"', config)
        self.assertIn('DASHBOARD_LIVE_FRAME_URL="http://127.0.0.1:8000/api/device/live_frame"', config)
        self.assertIn('BOARD_PREDICT_URL="http://${ZYNQ_IP}:8080/predict"', config)
        checks = (PROJECT_ROOT / "scripts/check/hardware.sh").read_text(encoding="utf-8")
        self.assertIn('robot/diagnostics/check_uart.py', checks)
        self.assertIn('ARM_ACTIVE_IDS      = 000,001,002,003,004', checks)
        self.assertIn('ARM_SERIAL_PORT="${ARM_SERIAL_PORT:-auto}"', config)
        self.assertIn('(115200 8N1)', checks)

    def test_camera_and_voice_performance_defaults_are_explicit(self) -> None:
        config = (PROJECT_ROOT / "config.sh").read_text(encoding="utf-8")
        self.assertIn('VOICE_WAKE_ENABLED="0"', config)
        self.assertIn('LIVE_PUSH_FPS="24"', config)
        self.assertIn('CAMERA_FPS="24"', config)
        self.assertIn('DETECTION_FPS="12"', config)
        self.assertIn('DETECTION_WIDTH="384"', config)
        self.assertIn('ACTION_QUEUE_CAPACITY="3"', config)

    def test_monitor_is_read_only_and_shows_hardware_categories(self) -> None:
        monitor = (PROJECT_ROOT / "scripts/tools/monitor.sh").read_text(encoding="utf-8")
        self.assertIn('emit("QUEUE"', monitor)
        self.assertIn('emit("ARM"', monitor)
        self.assertIn('emit("PUMP"', monitor)
        self.assertIn('[USB]', monitor)
        self.assertIn('[ALARM]', monitor)
        self.assertIn("tail -n", monitor)
        self.assertIn("journalctl -k -f", monitor)
        self.assertNotIn("run_pose_sequence.py --", monitor)
        self.assertNotIn("i2ctransfer", monitor)


if __name__ == "__main__":
    unittest.main()
