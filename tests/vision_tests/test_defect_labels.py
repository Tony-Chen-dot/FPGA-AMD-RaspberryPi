from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CIRCLE_CAMERA_DIR = PROJECT_ROOT / "vision"
VISION_BACKEND_DIR = PROJECT_ROOT / "dashboard" / "storage"
if str(CIRCLE_CAMERA_DIR) not in sys.path:
    sys.path.insert(0, str(CIRCLE_CAMERA_DIR))

from vision.transport.inference_client import DashboardTransport


STORAGE_SPEC = importlib.util.spec_from_file_location(
    "vision_dashboard_storage_filter_test",
    VISION_BACKEND_DIR / "database.py",
)
assert STORAGE_SPEC is not None and STORAGE_SPEC.loader is not None
storage_module = importlib.util.module_from_spec(STORAGE_SPEC)
STORAGE_SPEC.loader.exec_module(storage_module)


def board_box(label: str, score: float, x: float) -> dict:
    return {
        "class_name": label,
        "score": score,
        "loc": [x, 10, x + 20, 30],
    }


def dashboard_box(label: str, confidence: float, x: float) -> dict:
    return {
        "label": label,
        "confidence": confidence,
        "bbox": {"x": x, "y": 0.1, "w": 0.1, "h": 0.1},
    }


class BoardDefectClassFilterTests(unittest.TestCase):
    def make_transport(self, directory: str) -> DashboardTransport:
        return DashboardTransport(
            artifacts_dir=Path(directory),
            board_score_thresh=0.2,
        )

    def infer(self, detections: list[dict]) -> object:
        with tempfile.TemporaryDirectory() as directory:
            transport = self.make_transport(directory)
            return transport._board_result_from_payload(
                {"result": detections},
                frame_width=100,
                frame_height=100,
                inference_ms=5.0,
            )

    def test_higher_normal_score_returns_ok_and_hides_normal_box(self) -> None:
        result = self.infer(
            [
                board_box("zheng_chang", 0.91, 10),
                board_box("zhe_zhou", 0.28, 40),
            ]
        )

        self.assertEqual(result.result, "OK")
        self.assertEqual(result.defect_count, 0)
        self.assertEqual(result.detections, [])

    def test_higher_defect_score_keeps_only_threshold_passing_winner_boxes(self) -> None:
        result = self.infer(
            [
                board_box("zhe_zhou", 0.92, 10),
                board_box("zheng_chang", 0.90, 40),
                board_box("zhe_zhou", 0.20, 70),
                board_box("zhe_zhou", 0.19, 5),
                board_box("zhen_kong", 0.80, 35),
            ]
        )

        self.assertEqual([item["label"] for item in result.detections], ["折皱", "折皱"])
        self.assertEqual([item["confidence"] for item in result.detections], [0.92, 0.2])
        self.assertEqual(result.defect_count, 2)
        self.assertEqual(result.result, "NG")

    def test_defect_wins_exact_tie_with_normal(self) -> None:
        result = self.infer(
            [
                board_box("zheng_chang", 0.90, 10),
                board_box("zhe_zhou", 0.90, 40),
            ]
        )

        self.assertEqual([item["label"] for item in result.detections], ["折皱"])
        self.assertEqual(result.result, "NG")

    def test_equal_defect_confidence_uses_first_returned_class(self) -> None:
        result = self.infer(
            [
                board_box("zhe_zhou", 0.9, 10),
                board_box("zhen_kong", 0.9, 40),
                board_box("zhe_zhou", 0.2, 70),
            ]
        )

        self.assertEqual([item["label"] for item in result.detections], ["折皱", "折皱"])

    def test_all_candidates_below_threshold_return_ok(self) -> None:
        result = self.infer(
            [
                board_box("zheng_chang", 0.19, 10),
                board_box("zhe_zhou", 0.19, 40),
            ]
        )

        self.assertEqual(result.result, "OK")
        self.assertEqual(result.defect_count, 0)
        self.assertEqual(result.detections, [])

    def test_explicit_ng_without_detection_list_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transport = self.make_transport(directory)
            result = transport._board_result_from_payload(
                {"result": "NG", "defect_count": 1},
                frame_width=100,
                frame_height=100,
                inference_ms=5.0,
            )

        self.assertEqual(result.result, "NG")
        self.assertEqual(result.defect_count, 1)
        self.assertEqual(result.detections, [])


class DashboardDefectClassFilterTests(unittest.TestCase):
    def make_storage(self):
        storage = object.__new__(storage_module.DashboardStorage)
        storage._state = {"device": {"model_name": "test", "board_name": "test"}}
        storage.board_score_thresh = 0.2
        return storage

    def test_direct_ingest_higher_normal_score_returns_ok(self) -> None:
        storage = self.make_storage()
        normalized = storage._normalize_payload(
            {
                "result": "NG",
                "defect_count": 2,
                "detections": [
                    dashboard_box("zheng_chang", 0.91, 0.1),
                    dashboard_box("折皱", 0.28, 0.4),
                ],
            }
        )

        self.assertEqual(normalized["detections"], [])
        self.assertEqual(normalized["defect_count"], 0)
        self.assertEqual(normalized["result"], "OK")

    def test_direct_ingest_applies_threshold_and_winner_class_filter(self) -> None:
        storage = self.make_storage()
        normalized = storage._normalize_payload(
            {
                "result": "OK",
                "defect_count": 5,
                "detections": [
                    dashboard_box("擦伤", 0.95, 0.1),
                    dashboard_box("脏污", 0.90, 0.4),
                    dashboard_box("正常", 0.92, 0.5),
                    dashboard_box("擦伤", 0.20, 0.7),
                    dashboard_box("擦伤", 0.19, 0.8),
                ],
            }
        )

        self.assertEqual([item["label"] for item in normalized["detections"]], ["擦伤", "擦伤"])
        self.assertEqual([item["confidence"] for item in normalized["detections"]], [0.95, 0.2])
        self.assertEqual(normalized["defect_count"], 2)
        self.assertEqual(normalized["result"], "NG")

    def test_direct_ingest_all_low_candidates_return_ok(self) -> None:
        storage = self.make_storage()
        normalized = storage._normalize_payload(
            {
                "result": "NG",
                "defect_count": 2,
                "detections": [
                    dashboard_box("正常", 0.19, 0.1),
                    dashboard_box("折皱", 0.19, 0.4),
                ],
            }
        )

        self.assertEqual(normalized["detections"], [])
        self.assertEqual(normalized["defect_count"], 0)
        self.assertEqual(normalized["result"], "OK")

    def test_direct_ingest_explicit_ng_without_candidates_is_preserved(self) -> None:
        storage = self.make_storage()
        normalized = storage._normalize_payload({"result": "NG", "defect_count": 1})

        self.assertEqual(normalized["detections"], [])
        self.assertEqual(normalized["defect_count"], 1)
        self.assertEqual(normalized["result"], "NG")


if __name__ == "__main__":
    unittest.main()
