#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${ROOT_DIR}/runtime/logs"
mkdir -p "${LOG_DIR}"

detect_wired_ipv4() {
  command -v ip >/dev/null 2>&1 || return 1
  ip -4 -o addr show dev "${WIRED_INTERFACE:-eth0}" scope global 2>/dev/null |
    awk 'NR == 1 { sub("/.*", "", $4); print $4; exit }'
}

stop_stale_dashboard_processes() {
  local -a pids=()
  local -a survivors=()
  local pid

  mapfile -t pids < <(pgrep -f 'uvicorn dashboard[.]api[.]server:app' 2>/dev/null || true)
  if [[ "${#pids[@]}" -eq 0 ]]; then
    return 0
  fi

  echo "正在停止旧的可视化页面进程: ${pids[*]}"
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

  echo "旧看板进程未正常退出，正在强制终止: ${survivors[*]}" >&2
  kill -KILL "${survivors[@]}" 2>/dev/null || true
}

dashboard_health_ready() {
  if command -v curl >/dev/null 2>&1; then
    curl --fail --silent --show-error --max-time 1 \
      "http://127.0.0.1:8000/api/health" >/dev/null 2>&1
    return
  fi

  "${ROOT_DIR}/.venv/bin/python3" -c \
    'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=1).read()' \
    >/dev/null 2>&1
}

wait_for_dashboard() {
  local dashboard_pid="$1"
  local timeout_seconds="${DASHBOARD_STARTUP_TIMEOUT_SECONDS:-20}"
  local attempts=$((timeout_seconds * 5))

  for ((attempt = 1; attempt <= attempts; attempt += 1)); do
    if dashboard_health_ready; then
      echo "可视化页面健康检查通过: http://127.0.0.1:8000/api/health"
      return 0
    fi
    if ! kill -0 "${dashboard_pid}" 2>/dev/null; then
      echo "可视化页面进程已提前退出，日志如下：" >&2
      tail -n 80 "${LOG_DIR}/dashboard.log" >&2 || true
      return 1
    fi
    sleep 0.2
  done

  echo "可视化页面在 ${timeout_seconds}s 内未通过健康检查，日志如下：" >&2
  tail -n 80 "${LOG_DIR}/dashboard.log" >&2 || true
  kill -TERM "${dashboard_pid}" 2>/dev/null || true
  sleep 0.5
  kill -KILL "${dashboard_pid}" 2>/dev/null || true
  return 1
}

if [[ ! -d "${ROOT_DIR}/.venv" ]]; then
  echo "未找到 ${ROOT_DIR}/.venv，请先运行 ./scripts/setup/install_environment.sh"
  exit 1
fi

if [[ ! -f "${ROOT_DIR}/config.sh" ]]; then
  echo "未找到 ${ROOT_DIR}/config.sh，无法加载现场配置。"
  exit 1
fi
if [[ -x "${ROOT_DIR}/scripts/stop/robot_debug.sh" ]]; then
  echo "正在停止机械臂调试页面，避免与生产动作并发控制..."
  "${ROOT_DIR}/scripts/stop/robot_debug.sh"
fi

echo "正在加载现场配置并执行硬件预检..."
source "${ROOT_DIR}/config.sh"
LOG_DIR="${ROOT_DIR}/runtime/logs/line_${PRODUCTION_LINE_ID:-1}"
mkdir -p "${LOG_DIR}"

export PYTHONNOUSERSITE=1

HOST_IP="$(detect_wired_ipv4 || true)"
if [[ -z "${HOST_IP}" ]]; then
  HOST_IP="${DASHBOARD_HOST_IP:-127.0.0.1}"
fi
export DASHBOARD_HOST_IP="${HOST_IP}"
export DASHBOARD_URL="http://${DASHBOARD_HOST_IP}:8000"
export DASHBOARD_INGEST_URL="${DASHBOARD_INGEST_URL:-http://127.0.0.1:8000/api/device/ingest}"
export DASHBOARD_LIVE_FRAME_URL="${DASHBOARD_LIVE_FRAME_URL:-http://127.0.0.1:8000/api/device/live_frame}"
export BOARD_PREDICT_URL="${BOARD_PREDICT_URL:-http://172.16.68.110:8080/predict}"
export BOARD_SCORE_THRESH="${BOARD_SCORE_THRESH:-0.2}"

if [[ "${DISABLE_ARM_ACTION_FLAG:-}" != "--disable-arm-action" ]]; then
  PREPARE_ARGS=(
    --prepare-only
    --params "${ACTION_PARAMS_PATH:-runtime/robot/servo_params.json}"
  )
  if [[ "${ACTION_LIVE_FLAG:---action-live}" != "--no-action-live" ]]; then
    PREPARE_ARGS+=(--live)
  fi
  echo "正在将机械臂移动到 preparation 状态..."
  if ! PREPARE_OUTPUT="$(
    cd "${ROOT_DIR}"
    "${ACTION_PYTHON:-/usr/bin/python3}" robot/actions/run_sequence.py "${PREPARE_ARGS[@]}" 2>&1
  )"; then
    echo "机械臂准备失败: 复位指令发送或等待失败。" >&2
    echo "底层执行信息:" >&2
    printf '%s\n' "${PREPARE_OUTPUT}" >&2
    exit 1
  fi

  printf '%s\n' "${PREPARE_OUTPUT}" >"${LOG_DIR}/robot_prepare.log"
  echo "机械臂准备指令及设定等待已完成（UART 无位置回读，未验证实际到位）。"
fi

stop_stale_dashboard_processes

(
  cd "${ROOT_DIR}"
  exec ./scripts/start/dashboard.sh
) >"${LOG_DIR}/dashboard.log" 2>&1 &
DASHBOARD_PID=$!

if ! wait_for_dashboard "${DASHBOARD_PID}"; then
  echo "整套程序未启动：可视化页面不可用。" >&2
  exit 1
fi

(
  cd "${ROOT_DIR}"
  source "${ROOT_DIR}/.venv/bin/activate"
  exec ./scripts/start/vision.sh
) >"${LOG_DIR}/vision.log" 2>&1 &

case "${VOICE_WAKE_ENABLED:-0}" in
  1|true|TRUE|yes|YES|on|ON)
    (
      cd "${ROOT_DIR}"
      exec ./scripts/start/voice.sh
    ) >"${LOG_DIR}/voice.log" 2>&1 &
    VOICE_WAKE_STATUS="已启动"
    ;;
  *)
    VOICE_WAKE_STATUS="已关闭（不启动 Vosk 后台进程）"
    ;;
esac

cat <<EOF
已启动整套程序。

- 可视化页面: ${DASHBOARD_URL}
- 当前采集产线: ${PRODUCTION_LINE_ID:-1}
- Zynq 推理接口: ${BOARD_PREDICT_URL}
- 本机入库接口: ${DASHBOARD_INGEST_URL}
- 页面日志: ${LOG_DIR}/dashboard.log
- 圆检测日志: ${LOG_DIR}/vision.log
- 语音助手日志: ${LOG_DIR}/voice.log
- 默认唤醒词: 小助手
- 数据库路径: ${DASHBOARD_DATA_DIR:-$HOME/Database/vision-dashboard}/lines/line_${PRODUCTION_LINE_ID:-1}/dashboard.sqlite3
- 摄像头采集帧率: ${CAMERA_FPS:-18}
- 页面预览推流帧率: ${LIVE_PUSH_FPS:-15}
- 圆检测目标帧率: ${DETECTION_FPS:-8}
- 圆检测输入最大宽度: ${DETECTION_WIDTH:-384}
- 连续拍照冷却时间: ${continuous_capture_cool_time:-2.0}s
- 机械臂启动状态: preparation
- 机械臂动作延迟 t0: ${ACTION_DELAY_SECONDS:-10}s
- 机械臂动作 FIFO: 总在途 ${ACTION_QUEUE_CAPACITY:-3}（包含正在执行）
- 五阶段运动与等待时间: runtime/robot/servo_params.json（由 8088 调试页设置）
- 机械臂方向映射: ${ACTION_DIRECTION_MODE:-0}（0=NG左/OK右，1=NG右/OK左）
- 机械臂/气泵总线: ${ARM_SERIAL_PORT:-auto}，115200 8N1，气泵 ID 005
- 海康相机序列号: ${HIKROBOT_CAMERA_SERIAL:---}
- 联网模型: ${DEEPSEEK_MODEL:-deepseek-v4-flash}
- 关键词来源: 用户语音转写 + 检测数据库全库内容
- AI 语音助手实时状态: ${VOICE_WAKE_STATUS}

EOF
