#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LINE_ID="${1:-${PRODUCTION_LINE_ID:-1}}"
case "${LINE_ID}" in 1|2|3|4|5) ;; *) echo "产线编号必须为 1～5" >&2; exit 1 ;; esac
APP_LOG="${ROOT_DIR}/runtime/logs/line_${LINE_ID}/vision.log"
DASHBOARD_LOG="${ROOT_DIR}/runtime/robot/server.log"
HISTORY_LINES="${MONITOR_HISTORY_LINES:-20}"
CHILD_PIDS=()

cleanup() {
  local pid
  trap - INT TERM EXIT
  for pid in "${CHILD_PIDS[@]}"; do
    pkill -TERM -P "${pid}" 2>/dev/null || true
    kill "${pid}" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

now() {
  date '+%H:%M:%S'
}

find_arm_node() {
  local candidate="${ARM_SERIAL_PORT:-auto}" resolved
  if [[ "${candidate}" == "auto" ]]; then
    if [[ -r /proc/device-tree/model ]] && grep -q 'Raspberry Pi 5' /proc/device-tree/model; then
      candidate="/dev/ttyAMA0"
    else
      candidate="/dev/serial0"
    fi
  fi
  if [[ -e "${candidate}" ]]; then
    resolved="$(readlink -f "${candidate}" 2>/dev/null || true)"
    printf '%s->%s (pump ID 005)\n' "${candidate}" "${resolved}"
  else
    printf '%s missing\n' "${candidate}"
  fi
}

watch_process_state() {
  local previous="" current camera action dashboard pump
  while true; do
    camera="$(pgrep -d, -f 'vision/pipeline.py' 2>/dev/null || true)"
    action="$(pgrep -d, -f 'robot/actions/run_sequence.py' 2>/dev/null || true)"
    dashboard="$(pgrep -d, -f 'robot/debug/server.py' 2>/dev/null || true)"
    pump="$(find_arm_node)"
    current="camera=${camera:-off} action=${action:-idle} dashboard8088=${dashboard:-off} arm_uart=${pump}"
    if [[ "${current}" != "${previous}" ]]; then
      printf '%s [PROC] %s\n' "$(now)" "${current}"
      previous="${current}"
    fi
    sleep 1
  done
}

filter_application_events() {
  awk '
    function emit(tag, text) {
      sub(/^.*\[(QUEUE|ARM|PUMP|ALARM)\][[:space:]]*/, "", text)
      printf "%s [%s] %s\n", strftime("%H:%M:%S"), tag, text
      fflush()
    }
    /\[QUEUE\]/ { emit("QUEUE", $0); next }
    /\[ARM\]/ { emit("ARM", $0); next }
    /\[PUMP\]/ { emit("PUMP", $0); next }
    /\[ALARM\]/ { emit("ALARM", $0); next }
    /STEP move|TX #[0-9][0-9][0-9]/ { emit("ARM", $0); next }
    /发送失败|串口连接失败|串口发送排空超时|机械臂动作失败|机械臂安全恢复失败/ {
      emit("ALARM", $0)
    }
  '
}

watch_application_logs() {
  tail -n "${HISTORY_LINES}" -F "${APP_LOG}" "${DASHBOARD_LOG}" 2>/dev/null |
    filter_application_events
}

watch_kernel_usb() {
  if ! journalctl -k -n 0 --no-pager >/dev/null 2>&1; then
    printf '%s [ALARM] 无权读取内核日志；应用日志监视继续。可使用 sudo ./scripts/tools/monitor.sh。\n' "$(now)"
    return 0
  fi
  journalctl -k -f -n 0 -o short-iso --no-pager 2>/dev/null |
    awk '
      {
        lower = tolower($0)
        if (lower ~ /usb/ || lower ~ /ch341/ || lower ~ /ttyusb/ || lower ~ /xhci/) {
          if (lower ~ /1a86/ || lower ~ /5523/ || lower ~ /ch341/ ||
              lower ~ /ttyusb/ || lower ~ /emi/ || lower ~ /disconnect/ || lower ~ /-19/) {
            printf "%s [USB] %s\n", strftime("%H:%M:%S"), $0
            fflush()
          }
        }
      }
    '
}

printf '%s [MONITOR] 只读监视已启动；Ctrl+C 仅停止本脚本。\n' "$(now)"
printf '%s [MONITOR] action FIFO total capacity=%s\n' "$(now)" "${ACTION_QUEUE_CAPACITY:-3}"

watch_application_logs &
CHILD_PIDS+=("$!")
watch_kernel_usb &
CHILD_PIDS+=("$!")
watch_process_state &
CHILD_PIDS+=("$!")

wait
