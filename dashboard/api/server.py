from __future__ import annotations


import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from dashboard.storage.database import CANONICAL_DEFECT_LABELS
from common.production_lines import configured_line_id, LINE_IDS
from dashboard.services.production_lines import ProductionLines


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "web"

INTERFACE_DIR = Path(os.environ.get("DASHBOARD_INTERFACE_DIR", BASE_DIR)).expanduser().resolve()
DATA_DIR = Path(
    os.environ.get("DASHBOARD_DATA_DIR", str(Path.home() / "Database" / "vision-dashboard"))
).expanduser().resolve()
LIVE_STATE_INTERVAL_SECONDS = float(
    os.environ.get(
        "DASHBOARD_LIVE_STATE_INTERVAL_SECONDS",
        os.environ.get("DASHBOARD_LIVE_SNAPSHOT_INTERVAL_SECONDS", "0.08"),
    )
)
MJPEG_BOUNDARY = "frame"


lines = ProductionLines(DATA_DIR, configured_line_id())
storage = lines.store()


def resolve_line(line_id=None):
    try:
        return lines.resolve(line_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def capture_line(payload, line_id=None):
    if payload is not None and not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="数据必须是 JSON 对象")
    claimed = (payload or {}).get("line_id")
    number = resolve_line(line_id if line_id is not None else claimed)
    if claimed is not None and resolve_line(claimed) != number:
        raise HTTPException(status_code=409, detail="请求中的产线编号不一致")
    if number != lines.active_line_id:
        raise HTTPException(status_code=409, detail="该产线未连接摄像头，不能写入实时检测数据")
    return number
last_live_state_broadcast_monotonic = 0.0


async def broadcast_snapshot(snapshot: dict[str, Any] | None = None, line_id=None) -> None:
    number = resolve_line(line_id)
    payload = lines.decorate(snapshot, number) if snapshot is not None else await lines.snapshot(number)
    await lines.hubs[number].broadcast_message({"type": "snapshot", "payload": payload})


async def broadcast_live_state(line_id=None) -> None:
    number = resolve_line(line_id)
    await lines.hubs[number].broadcast_message({"type": "live_state", "payload": await lines.live_state(number)})


async def broadcast_result_update(snapshot: dict[str, Any], line_id=None) -> None:
    number = resolve_line(line_id)
    payload = lines.decorate(snapshot, number)
    keys = ("device", "summary", "latest_result", "recent_results", "defect_summary", "generated_at",
            "line_id", "line_name", "active_line_id", "camera_assigned")
    await lines.hubs[number].broadcast_message({"type": "result_update", "payload": {key: payload.get(key) for key in keys}})


async def mjpeg_frames(selected_storage) -> AsyncIterator[bytes]:
    sequence = 0
    while True:
        sequence, frame_bytes = await selected_storage.wait_for_live_frame(sequence, timeout_seconds=15.0)
        if frame_bytes is None:
            continue
        yield (
            f"--{MJPEG_BOUNDARY}\r\n"
            "Content-Type: image/jpeg\r\n"
            f"Content-Length: {len(frame_bytes)}\r\n"
            "Cache-Control: no-store\r\n"
            "\r\n"
        ).encode("ascii") + frame_bytes + b"\r\n"


async def monitor_device() -> None:
    while True:
        for number, selected_storage in lines.stores.items():
            if await selected_storage.mark_stale_if_needed():
                await broadcast_snapshot(line_id=number)
        await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(_: FastAPI):
    monitor_task = asyncio.create_task(monitor_device())
    yield
    monitor_task.cancel()


app = FastAPI(title="树莓派多产线质检上位机 · Zynq 推理加速", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health(line_id: int | None = None) -> JSONResponse:
    storage = lines.store(resolve_line(line_id))
    return JSONResponse(
        {
            "ok": True,
            "interface_dir": str(INTERFACE_DIR),
            "data_dir": str(storage.data_root),
            "data_root": str(DATA_DIR),
            "active_line_id": lines.active_line_id,
            "latest_frame_exists": storage.latest_frame_path.exists(),
            "live_frame_exists": storage.live_frame_path.exists(),
        }
    )


@app.get("/api/lines")
async def production_lines() -> JSONResponse:
    return JSONResponse({"active_line_id": lines.active_line_id,
                         "lines": [{"id": number, "name": f"产线 {number}",
                                    "camera_assigned": number == lines.active_line_id}
                                   for number in LINE_IDS]})


@app.get("/api/state")
async def state(line_id: int | None = None) -> JSONResponse:
    return JSONResponse(await lines.snapshot(resolve_line(line_id)))


@app.get("/api/history/trend")
async def history_trend(line_id: int | None = None) -> JSONResponse:
    return JSONResponse(await lines.store(resolve_line(line_id)).refresh_history_trend())


@app.get("/api/assistant/status")
async def assistant_status(line_id: int | None = None) -> JSONResponse:
    assistant_service = lines.assistant(resolve_line(line_id))
    config = assistant_service.config
    return JSONResponse(
        {
            "ok": True,
            "wake_word": config.wake_word,
            "llm_provider": config.llm_provider,
            "model": config.deepseek_model,
            "llm_configured": bool(config.deepseek_api_key),
            "tts_provider": config.tts_provider,
            "database": assistant_service.database_status(),
            "pipeline": [
                {"key": "wake", "label": "语音唤醒", "state": "ready"},
                {"key": "stt", "label": "语音转文字", "state": "ready"},
                {
                    "key": "llm",
                    "label": "数据约束推理",
                    "state": "ready" if config.deepseek_api_key else "needs_key",
                },
                {"key": "tts", "label": "文字转语音", "state": "ready"},
            ],
        }
    )


@app.get("/api/assistant/conversations")
async def assistant_conversations(line_id: int | None = None) -> JSONResponse:
    assistant_service = lines.assistant(resolve_line(line_id))
    conversations = await run_in_threadpool(assistant_service.list_conversations)
    return JSONResponse({"conversations": conversations})


@app.post("/api/assistant/conversations")
async def create_assistant_conversation(payload: dict[str, Any] | None = None, line_id: int | None = None) -> JSONResponse:
    assistant_service = lines.assistant(resolve_line(line_id))
    title = str((payload or {}).get("title") or "新对话")
    conversation = await run_in_threadpool(assistant_service.create_conversation, title)
    return JSONResponse({"conversation": conversation}, status_code=201)


@app.get("/api/assistant/conversations/{conversation_id}")
async def get_assistant_conversation(conversation_id: str, line_id: int | None = None) -> JSONResponse:
    assistant_service = lines.assistant(resolve_line(line_id))
    conversation = await run_in_threadpool(assistant_service.get_conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return JSONResponse({"conversation": conversation})


@app.delete("/api/assistant/conversations/{conversation_id}")
async def delete_assistant_conversation(conversation_id: str, line_id: int | None = None) -> JSONResponse:
    assistant_service = lines.assistant(resolve_line(line_id))
    deleted = await run_in_threadpool(assistant_service.delete_conversation, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="对话不存在")
    return JSONResponse({"ok": True})


@app.post("/api/assistant/chat")
async def assistant_chat(payload: dict[str, Any], line_id: int | None = None) -> JSONResponse:
    assistant_service = lines.assistant(resolve_line(line_id))
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    if len(message) > 20000:
        raise HTTPException(status_code=413, detail="消息长度不能超过 20000 个字符")
    conversation_id = payload.get("conversation_id")
    if conversation_id is not None:
        conversation_id = str(conversation_id)
    try:
        result = await run_in_threadpool(
            assistant_service.chat,
            message,
            conversation_id,
            bool(payload.get("speak", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse(result)


@app.get("/api/device/schema")
async def device_schema() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "supported_defects": CANONICAL_DEFECT_LABELS,
            "endpoints": {
                "heartbeat": {"method": "POST", "path": "/api/device/heartbeat"},
                "result_only": {"method": "POST", "path": "/api/device/result"},
                "frame_and_result": {"method": "POST", "path": "/api/device/ingest"},
            },
            "multipart_fields": ["payload", "frame"],
            "payload_example": {
                "timestamp": "2026-05-26T20:00:00+08:00",
                "frame_id": "arm-000123",
                "model_name": "Vision-Defect-Model",
                "board_name": "Zynq 多产线推理加速器",
                "line_id": lines.active_line_id,
                "inference_ms": 18.4,
                "frame": {"width": 1280, "height": 720},
                "result": "NG",
                "defect_count": 1,
                "detections": [
                    {
                        "label": "脏污",
                        "confidence": 0.96,
                        "bbox": {"x": 0.42, "y": 0.35, "w": 0.11, "h": 0.09},
                    }
                ],
            },
        }
    )


@app.get("/api/frame/latest")
async def latest_frame(line_id: int | None = None) -> FileResponse:
    storage = lines.store(resolve_line(line_id))
    if not storage.latest_frame_path.exists():
        raise HTTPException(status_code=404, detail="No frame uploaded yet.")
    return FileResponse(storage.latest_frame_path)


@app.get("/api/stream.mjpg")
async def mjpeg_stream(line_id: int | None = None) -> StreamingResponse:
    number = resolve_line(line_id)
    if number != lines.active_line_id:
        raise HTTPException(status_code=409, detail="该产线无信号")
    return StreamingResponse(
        mjpeg_frames(lines.store(number)),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/frame/{frame_id}")
async def frame_by_id(frame_id: str, line_id: int | None = None) -> FileResponse:
    storage = lines.store(resolve_line(line_id))
    frame_path = storage.frames_dir / f"{frame_id}.jpg"
    if not frame_path.exists():
        frame_path = storage.archive_dir / f"{frame_id}.jpg"
        if not frame_path.exists():
            raise HTTPException(status_code=404, detail="Frame not found.")
    return FileResponse(frame_path)


@app.post("/api/device/heartbeat")
async def heartbeat(payload: dict[str, Any] | None = None, line_id: int | None = None) -> JSONResponse:
    number = capture_line(payload, line_id)
    storage = lines.store(number)
    snapshot = await storage.heartbeat(payload)
    await broadcast_snapshot(snapshot, number)
    return JSONResponse({"ok": True})


@app.post("/api/device/result")
async def ingest_result(payload: dict[str, Any], line_id: int | None = None) -> JSONResponse:
    number = capture_line(payload, line_id)
    storage = lines.store(number)
    started = time.monotonic()
    payload = {**payload, "line_id": number}
    snapshot, server_timing = await storage.ingest(payload, frame_bytes=None)
    await broadcast_result_update(snapshot, number)
    server_timing["total_ms"] = round((time.monotonic() - started) * 1000.0, 2)
    return JSONResponse(
        {"ok": True, "latest_result": snapshot["latest_result"], "server_timing_ms": server_timing}
    )


@app.post("/api/device/ingest")
async def ingest_packet(
    payload: str = Form(...),
    frame: UploadFile | None = File(default=None),
    line_id: int | None = None,
) -> JSONResponse:
    started = time.monotonic()
    try:
        payload_data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid payload JSON: {exc}") from exc
    number = capture_line(payload_data, line_id)
    storage = lines.store(number)
    payload_data = {**payload_data, "line_id": number}
    frame_bytes = await frame.read() if frame else None
    snapshot, server_timing = await storage.ingest(payload_data, frame_bytes=frame_bytes)
    broadcast_started = time.monotonic()
    await broadcast_result_update(snapshot, number)
    server_timing["websocket_broadcast_ms"] = round((time.monotonic() - broadcast_started) * 1000.0, 2)
    server_timing["total_ms"] = round((time.monotonic() - started) * 1000.0, 2)
    return JSONResponse(
        {"ok": True, "latest_result": snapshot["latest_result"], "server_timing_ms": server_timing}
    )


@app.post("/api/device/live_frame")
async def ingest_live_frame(
    frame: UploadFile = File(...),
    payload: str | None = Form(default=None),
    line_id: int | None = None,
) -> JSONResponse:
    global last_live_state_broadcast_monotonic

    payload_data: dict[str, Any] | None = None
    if payload:
        try:
            payload_data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid payload JSON: {exc}") from exc
    number = capture_line(payload_data, line_id)
    storage = lines.store(number)
    frame_bytes = await frame.read()
    try:
        await storage.update_live_frame(frame_bytes, payload=payload_data, return_snapshot=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    now = time.monotonic()
    if (now - last_live_state_broadcast_monotonic) >= LIVE_STATE_INTERVAL_SECONDS:
        last_live_state_broadcast_monotonic = now
        await broadcast_live_state(number)
    return JSONResponse({"ok": True, "live_frame_updated": True})


@app.websocket("/ws/dashboard")
async def dashboard_socket(websocket: WebSocket, line_id: int | None = None) -> None:
    try:
        number = lines.resolve(line_id)
    except ValueError:
        await websocket.close(code=1008)
        return
    hub = lines.hubs[number]
    await hub.connect(websocket)
    try:
        await websocket.send_json({"type": "snapshot", "payload": await lines.snapshot(number)})
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)
