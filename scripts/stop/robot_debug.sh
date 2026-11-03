#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PID_FILE="${ROOT_DIR}/runtime/robot/server.pid"

stop_dashboard_pid() {
  local pid="$1"
  # The UART stays exclusively owned until runtime.close() finishes. Allow the
  # backend to cancel its worker and send joint-stop commands before returning.
  if ! kill -TERM "${pid}" 2>/dev/null; then
    if kill -0 "${pid}" 2>/dev/null; then
      echo "无法向机械臂调试后端发送停止信号。PID: ${pid}" >&2
      return 1
    fi
    return 0
  fi
  for _ in {1..80}; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done
  echo "机械臂调试后端在 8 秒内未退出，串口可能仍被占用。PID: ${pid}" >&2
  echo "未强制终止进程；请检查后端日志和硬件状态后重试。" >&2
  return 1
}

STOPPED=0
STOP_FAILED=0
while read -r PID; do
  [[ -n "${PID}" ]] || continue
  PROCESS_CWD="$(readlink -f "/proc/${PID}/cwd" 2>/dev/null || true)"
  PROCESS_COMMAND="$(tr '\0' ' ' <"/proc/${PID}/cmdline" 2>/dev/null || true)"
  if [[ "${PROCESS_CWD}" == "${ROOT_DIR}" && "${PROCESS_COMMAND}" == *"robot/debug/server.py"* ]]; then
    if stop_dashboard_pid "${PID}"; then
      echo "已停止机械臂调试页面。PID: ${PID}"
      STOPPED=1
    else
      STOP_FAILED=1
    fi
  fi
done < <(pgrep -f 'robot/debug/server.py' 2>/dev/null || true)

if [[ "${STOP_FAILED}" -ne 0 ]]; then
  exit 1
fi

rm -f "${PID_FILE}"

if [[ "${STOPPED}" -eq 0 ]]; then
  echo "机械臂调试页面没有运行。"
fi
