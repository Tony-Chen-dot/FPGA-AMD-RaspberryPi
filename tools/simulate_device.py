from __future__ import annotations

import argparse
import io
import json
import random
import time
from datetime import datetime, timezone
from urllib import request

from PIL import Image, ImageDraw


DEFECT_TYPES = ["脏污", "折皱", "划痕", "针孔", "擦伤"]


def build_frame(index: int, defects: list[dict]) -> bytes:
    image = Image.new("RGB", (1280, 720), "#091A2B")
    draw = ImageDraw.Draw(image)
    draw.rectangle((86, 136, 1194, 584), outline="#36E8FF", width=3)
    draw.text((106, 86), "ARM BOARD CAMERA FEED", fill="#36E8FF")
    belt_x = 160 + (index * 24) % 760
    draw.rounded_rectangle((belt_x, 252, belt_x + 240, 470), radius=24, fill="#CAD4E5", outline="#EEF7FF")
    draw.rectangle((belt_x + 36, 296, belt_x + 204, 426), outline="#4A5975", width=4)
    for defect in defects:
        x = defect["bbox"]["x"] * 1280
        y = defect["bbox"]["y"] * 720
        w = defect["bbox"]["w"] * 1280
        h = defect["bbox"]["h"] * 720
        draw.rectangle((x, y, x + w, y + h), outline="#FF5B6E", width=5)
        draw.text((x, max(0, y - 18)), defect["label"], fill="#FF5B6E")
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=88)
    return stream.getvalue()


def multipart_encode(fields: dict[str, str], file_name: str, file_bytes: bytes) -> tuple[bytes, str]:
    boundary = f"----codexboundary{int(time.time() * 1000)}"
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
            f'Content-Disposition: form-data; name="frame"; filename="{file_name}"\r\n'.encode(),
            b"Content-Type: image/jpeg\r\n\r\n",
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), boundary


def post_ingest(server: str, payload: dict, frame_bytes: bytes) -> None:
    body, boundary = multipart_encode({"payload": json.dumps(payload, ensure_ascii=True)}, "frame.jpg", frame_bytes)
    req = request.Request(
        f"{server.rstrip('/')}/api/device/ingest",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with request.urlopen(req, timeout=5) as response:
        response.read()


def generate_payload(index: int) -> tuple[dict, bytes]:
    defect_count = random.choices([0, 1, 2], weights=[0.55, 0.32, 0.13])[0]
    defects = []
    for _ in range(defect_count):
        x = random.uniform(0.24, 0.68)
        y = random.uniform(0.34, 0.54)
        w = random.uniform(0.06, 0.14)
        h = random.uniform(0.04, 0.12)
        defects.append(
            {
                "label": random.choice(DEFECT_TYPES),
                "confidence": round(random.uniform(0.82, 0.98), 3),
                "bbox": {"x": x, "y": y, "w": w, "h": h},
            }
        )
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frame_id": f"demo-{index:05d}",
        "model_name": "DefectNet-Demo",
        "board_name": "FPGA-ARM Demo Board",
        "inference_ms": round(random.uniform(14.0, 28.0), 2),
        "frame": {"width": 1280, "height": 720},
        "detections": defects,
        "defect_count": defect_count,
        "result": "NG" if defect_count else "OK",
    }
    frame = build_frame(index, defects)
    return payload, frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Push demo frames/results to the dashboard backend.")
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="FastAPI server address")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between frames")
    args = parser.parse_args()

    index = 1
    while True:
        payload, frame_bytes = generate_payload(index)
        post_ingest(args.server, payload, frame_bytes)
        print(f"pushed {payload['frame_id']} {payload['result']} defects={payload['defect_count']}")
        index += 1
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
