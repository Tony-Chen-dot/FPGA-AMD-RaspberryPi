#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

stop_process_pattern() {
  local pattern="$1"
  local label="$2"
  local -a pids=()
  local -a survivors=()
  local pid

  mapfile -t pids < <(pgrep -f "${pattern}" 2>/dev/null || true)
  if [[ "${#pids[@]}" -eq 0 ]]; then
    return 0
  fi

  kill -TERM "${pids[@]}" 2>/dev/null || true
  for _ in {1..30}; do
    survivors=()
    for pid in "${pids[@]}"; do
      if kill -0 "${pid}" 2>/dev/null; then
        survivors+=("${pid}")
      fi
    done
    if [[ "${#survivors[@]}" -eq 0 ]]; then
      return 0
    fi
    sleep 0.1
  done

  echo "${label}未正常退出，强制终止 PID: ${survivors[*]}" >&2
  kill -KILL "${survivors[@]}" 2>/dev/null || true
}

stop_process_pattern 'uvicorn dashboard[.]api[.]server:app' "可视化页面"
pkill -f "python -m voice.main" || true
pkill -f "vision/pipeline.py" || true
if [[ -x "${ROOT_DIR}/scripts/stop/robot_debug.sh" ]]; then
  "${ROOT_DIR}/scripts/stop/robot_debug.sh"
fi

echo "已停止可视化页面、机械臂调试页面、语音助手和圆检测采集。"
