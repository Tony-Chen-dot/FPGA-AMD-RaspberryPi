#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PID_FILE="${ROOT_DIR}/runtime/robot/server.pid"
LOG_FILE="${ROOT_DIR}/runtime/robot/server.log"
PORT="${SERVO_DASHBOARD_PORT:-8088}"
API_VERSION="servo-dashboard-ascii-uart-v1"

detect_host_ip() {
  local host_ip
  host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -z "${host_ip}" ]]; then
    host_ip="127.0.0.1"
  fi
  echo "${host_ip}"
}

mkdir -p "${ROOT_DIR}/runtime/robot"

PYTHON_BIN="/usr/bin/python3"
if [[ -d "${ROOT_DIR}/.venv" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python3"
fi
export PYTHONNOUSERSITE=1

if ! "${PYTHON_BIN}" -c "import serial" >/dev/null 2>&1; then
  echo "当前 Python 缺少 pyserial，请先执行 ./scripts/setup/install_environment.sh。" >&2
  exit 1
fi

stop_project_dashboard_processes() {
  local pid process_cwd process_command
  while read -r pid; do
    [[ -n "${pid}" ]] || continue
    process_cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
    process_command="$(tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null || true)"
    if [[ "${process_cwd}" == "${ROOT_DIR}" && "${process_command}" == *"robot/debug/server.py"* ]]; then
      echo "检测到旧机械臂调试后端，正在重启。PID: ${pid}"
      kill "${pid}" 2>/dev/null || true
      for _ in {1..50}; do
        if ! kill -0 "${pid}" 2>/dev/null; then
          break
        fi
        sleep 0.1
      done
      if kill -0 "${pid}" 2>/dev/null; then
        echo "无法停止旧机械臂调试后端。PID: ${pid}"
        return 1
      fi
    fi
  done < <(pgrep -f 'robot/debug/server.py' 2>/dev/null || true)
  rm -f "${PID_FILE}"
}

stop_project_dashboard_processes

cd "${ROOT_DIR}"
nohup "${PYTHON_BIN}" robot/debug/server.py --host 0.0.0.0 --port "${PORT}" --live --device "${ARM_SERIAL_PORT:-auto}" >"${LOG_FILE}" 2>&1 &
echo "$!" >"${PID_FILE}"

NEW_PID="$(cat "${PID_FILE}")"
READY=0
for _ in {1..50}; do
  if ! kill -0 "${NEW_PID}" 2>/dev/null; then
    echo "机械臂调试页面启动失败，日志如下："
    tail -n 30 "${LOG_FILE}" || true
    rm -f "${PID_FILE}"
    exit 1
  fi
  if "${PYTHON_BIN}" -c '
import json
import sys
import urllib.request

with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/state", timeout=0.2) as response:
    state = json.load(response)
raise SystemExit(0 if state.get("api_version") == sys.argv[2] else 1)
' "${PORT}" "${API_VERSION}" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.1
done

if [[ "${READY}" -ne 1 ]]; then
  echo "机械臂调试页面未能启动正确版本的后端，日志如下："
  tail -n 30 "${LOG_FILE}" || true
  kill "${NEW_PID}" 2>/dev/null || true
  rm -f "${PID_FILE}"
  exit 1
fi

echo "机械臂调试页面已启动。"
echo "PID: ${NEW_PID}"
echo "URL: http://$(detect_host_ip):${PORT}"
echo "Log: ${LOG_FILE}"
echo "Python: ${PYTHON_BIN}"
