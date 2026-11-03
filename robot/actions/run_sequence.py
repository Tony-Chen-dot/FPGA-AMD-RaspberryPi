#!/usr/bin/env python3
"""Production entry for the shared, field-tested ZL UART five-phase sequence."""
from __future__ import annotations

import argparse
import copy
import math
import os
from pathlib import Path
import signal
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from robot.control.controller import DEFAULTS, SETTINGS, Runtime, Cancelled, load_params, validate

DEFAULT_PARAMS_PATH = SETTINGS


def default_params():
    return copy.deepcopy(DEFAULTS)


def env_bool(name, default=False):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mode", choices=("forward-right", "forward-left"))
    group.add_argument("--prepare-only", action="store_true", help="仅发送 000～004 的复位姿态")
    group.add_argument("--recover", action="store_true", help="释放 005，等待后恢复关节姿态")
    parser.add_argument("--params", default=str(DEFAULT_PARAMS_PATH))
    parser.add_argument("--live", action="store_true", help="实际发送串口命令")
    parser.add_argument("--device", default=os.environ.get("ARM_SERIAL_PORT", "auto"))
    parser.add_argument("--disable-pump", action="store_true", default=env_bool("DISABLE_PUMP"))
    parser.add_argument("--time", type=int, help="覆盖全部阶段 T 与手动动作时间（不改等待）")
    parser.add_argument("--hold", type=float, help="覆盖吸取阶段发送后的等待秒数")
    parser.add_argument("--pump-before-seconds", type=float, help="覆盖下降阶段发送后的等待秒数")
    parser.add_argument("--pump-after-seconds", type=float, help="覆盖释放阶段发送后的等待秒数")
    parser.add_argument("--pump-release-wait", type=float, help="--pump-after-seconds 的兼容别名")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    runtime = None
    old_handlers = {}
    def interrupted(signum, _frame):
        if runtime is not None:
            try:
                runtime.stop()
            except Exception as exc:
                print(f"[ALARM] 停止指令失败: {exc}", flush=True)
        raise Cancelled(f"signal {signum}")
    try:
        params = load_params(Path(args.params).expanduser())
        if args.time is not None:
            params["manual_ms"] = args.time
            params["move_ms"] = [args.time] * 5
        for value, phase in ((args.hold, 0), (args.pump_before_seconds, 2),
                             (args.pump_release_wait, 3), (args.pump_after_seconds, 3)):
            if value is not None:
                if not math.isfinite(value) or not 0 <= value <= 60:
                    raise ValueError("等待秒数必须为 0～60 的有限数值")
                params["wait_ms"][phase] = round(value * 1000)
        params = validate(params)
        runtime = Runtime(demo=not args.live, settings_path=Path(args.params).expanduser(),
                          pump_enabled=not args.disable_pump)
        for signum in (signal.SIGTERM, signal.SIGINT):
            old_handlers[signum] = signal.signal(signum, interrupted)
        runtime.connect(args.device)
        if not args.live:
            print("DRY RUN: add --live to send commands.", flush=True)
        print(f"[ARM] UART {runtime.device} 115200 8N1; position feedback disabled", flush=True)
        if args.prepare_only:
            print(f"STEP move preparation: {tuple(params['poses']['reset'])}", flush=True)
            runtime.execute("move", params, pose="reset")
        elif args.recover:
            print("[ARM] recovery: release 005 then reset joints (no physical feedback)", flush=True)
            runtime.execute("recover", params)
        else:
            target = "right" if args.mode == "forward-right" else "left"
            print(f"MODE {args.mode}", flush=True)
            runtime.execute("sequence", params, target=target)
        print("DONE: commands sent and configured wait completed; no position readback", flush=True)
        return 0
    except (Cancelled, KeyboardInterrupt):
        print("[ARM] action cancelled; no automatic reset or pump release", flush=True)
        return 130
    except Exception as exc:
        print(f"[ALARM] UART action failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if runtime is not None:
            runtime.close()
        for signum, previous in old_handlers.items():
            signal.signal(signum, previous)


if __name__ == "__main__":
    raise SystemExit(main())
