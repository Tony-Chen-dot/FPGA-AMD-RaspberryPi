#!/usr/bin/env python3
"""UART preflight entry: check UART availability without moving hardware.

The field-tested movement protocol has no acknowledgement; this is not an ID scan.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from robot.control.controller import Runtime
from robot.control.hardware_lock import hardware_operation_lock


def main():
    runtime = None
    try:
        runtime = Runtime(demo=False)
        with hardware_operation_lock():
            runtime.connect()
            print(f"ARM UART CHECK PASS: {runtime.device} 115200 8N1; "
                  "port opened only, no ID/position response verified, no commands sent", flush=True)
        return 0
    except Exception as exc:
        print(f"ARM UART CHECK FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
