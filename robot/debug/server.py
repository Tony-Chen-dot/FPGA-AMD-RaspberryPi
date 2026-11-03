#!/usr/bin/env python3
"""8088 调试入口：页面与生产动作共用经过 test 实机验证的 ASCII UART 核心。"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from robot.control.controller import Runtime, API_VERSION, suggested_port
from common.paths import ROBOT_PARAMS_PATH

APP_DIR = Path(__file__).resolve().parent
PARAMS_PATH = ROBOT_PARAMS_PATH

def handler_for(runtime):
    token = secrets.token_hex(24)
    page = (APP_DIR / "templates/index.html").read_text(encoding="utf-8").replace("__STYLE__", (APP_DIR / "static/controls.css").read_text(encoding="utf-8")).replace("__JS__", (APP_DIR / "static/controls.js").read_text(encoding="utf-8").replace("__TOKEN__", token)).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, body, status=200, html=False):
            data = body if html else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.path == "/":
                self.respond(page, html=True)
            elif self.path == "/api/state":
                self.respond({**runtime.snapshot(), "api_version": API_VERSION, "arm_position_verification": False})
            else:
                self.respond({"ok": False, "error": "不存在"}, 404)

        def do_POST(self):
            if self.headers.get("X-Control-Token") != token:
                self.respond({"ok": False, "error": "请刷新调试页面后重试"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32768:
                    raise ValueError("请求大小无效")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("请求必须为对象")
                if self.path == "/api/connect":
                    runtime.connect(body.get("device"))
                elif self.path == "/api/settings":
                    runtime.save(body.get("params"))
                elif self.path == "/api/action":
                    runtime.start(body.get("action"), body.get("params"), body.get("target", "right"), body.get("pose"))
                elif self.path == "/api/stop":
                    runtime.stop()
                else:
                    self.respond({"ok": False, "error": "不存在"}, 404)
                    return
                self.respond({"ok": True})
            except (ValueError, TypeError, KeyError) as exc:
                self.respond({"ok": False, "error": str(exc)}, 400)
            except Exception as exc:
                self.respond({"ok": False, "error": str(exc)}, 500)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="使用真实串口")
    mode.add_argument("--demo", action="store_true", help="演示模式，不访问硬件")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--device", default=os.environ.get("ARM_SERIAL_PORT", "auto"))
    parser.add_argument("--params", type=Path, default=PARAMS_PATH)
    args = parser.parse_args()
    pump_enabled = os.environ.get("DISABLE_PUMP", "0").strip().lower() not in {"1", "true", "yes", "on"}
    runtime = Runtime(demo=not args.live, settings_path=args.params, pump_enabled=pump_enabled)
    if args.live:
        try:
            runtime.connect(suggested_port() if args.device == "auto" else args.device)
        except (ValueError, OSError, RuntimeError) as exc:
            print(f"串口连接失败，可在页面修正设备后重连：{exc}", flush=True)
    try:
        server = ThreadingHTTPServer((args.host, args.port), handler_for(runtime))
    except OSError:
        runtime.close()
        raise
    print(f"SERVO_DASHBOARD {API_VERSION} {'LIVE' if args.live else 'DEMO'} http://{args.host}:{args.port}", flush=True)
    print("启动不移动机械臂；共享生产参数：" + str(args.params), flush=True)
    def terminate(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        runtime.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
