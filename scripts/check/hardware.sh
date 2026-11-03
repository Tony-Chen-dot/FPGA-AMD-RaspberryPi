#!/usr/bin/env bash
# Sourced by config.sh after environment settings are loaded.
configure_arm_serial_port() {
  if [[ "${ARM_SERIAL_PORT}" == "auto" ]]; then
    if [[ -r /proc/device-tree/model ]] && grep -q 'Raspberry Pi 5' /proc/device-tree/model; then
      export ARM_SERIAL_PORT="/dev/ttyAMA0"
    else
      export ARM_SERIAL_PORT="/dev/serial0"
    fi
  fi
}

validate_arm_uart() {
  local python_bin="${ACTION_PYTHON:-/usr/bin/python3}"
  local arm_check_output
  local arm_check_log="${SITE_CONFIG_ROOT}/runtime/logs/line_${PRODUCTION_LINE_ID:-1}/robot_uart_check.log"

  if [[ "${DISABLE_ARM_ACTION_FLAG:-}" == "--disable-arm-action" ]]; then
    export ARM_UART_CHECK_RESULT="SKIPPED"
    echo "机械臂串口预检: 已通过 --disable-arm-action 跳过。"
    return 0
  fi
  if [[ ! -x "${python_bin}" ]]; then
    echo "机械臂串口预检失败: 未找到 Python ${python_bin}。" >&2
    return 1
  fi

  if ! arm_check_output="$(
    "${python_bin}" "${SITE_CONFIG_ROOT}/robot/diagnostics/check_uart.py" 2>&1
  )"; then
    echo "机械臂串口预检失败: 无法独占打开指定 UART。" >&2
    echo "底层检查信息:" >&2
    printf '%s\n' "${arm_check_output}" >&2
    echo "请检查 ARM_SERIAL_PORT、UART 配置、dialout 权限，以及是否有其他程序占用串口。" >&2
    return 1
  fi

  mkdir -p "$(dirname "${arm_check_log}")"
  printf '%s\n' "${arm_check_output}" >"${arm_check_log}"
  export ARM_UART_CHECK_RESULT="PASS"
  echo "机械臂串口预检通过: 端口可打开；未发送动作，也未验证舵机 ID 或位置。"
}

validate_hikrobot_camera() {
  local camera_source="${CAMERA_SOURCE:-auto}"
  local expected_serial="${HIKROBOT_CAMERA_SERIAL:-}"
  local python_bin="${SITE_CONFIG_ROOT}/.venv/bin/python3"
  local camera_output matching_line

  if [[ "${camera_source}" == "v4l2" ]]; then
    echo "海康相机检查: CAMERA_SOURCE=v4l2，已跳过。"
    return 0
  fi

  if [[ ! -x "${python_bin}" ]]; then
    echo "海康相机检查失败: 未找到 ${python_bin}，请先运行 ./scripts/setup/install_environment.sh。" >&2
    return 1
  fi
  if [[ -z "${expected_serial}" ]]; then
    echo "海康相机检查失败: HIKROBOT_CAMERA_SERIAL 为空，请在 config.sh 中填写目标相机序列号。" >&2
    return 1
  fi

  if ! camera_output="$(
    "${python_bin}" "${SITE_CONFIG_ROOT}/vision/pipeline.py" \
      --hikrobot-sdk-path "${HIKROBOT_SDK_PATH}" \
      --list-hikrobot-cameras 2>&1
  )"; then
    echo "海康相机检查失败: 无法枚举海康相机。" >&2
    printf '%s\n' "${camera_output}" >&2
    echo "请检查USB连接、MVS SDK和 ${HIKROBOT_SDK_PATH}。" >&2
    return 1
  fi

  if [[ -z "${camera_output}" || "${camera_output}" == *"未发现海康相机"* ]]; then
    echo "海康相机检查失败: 未发现海康相机，配置序列号为 ${expected_serial}。" >&2
    printf '%s\n' "${camera_output}" >&2
    return 1
  fi

  matching_line="$(printf '%s\n' "${camera_output}" | grep -F "serial=${expected_serial} " | head -n 1 || true)"
  if [[ -z "${matching_line}" ]]; then
    echo "海康相机检查失败: 配置序列号 ${expected_serial} 与现场设备不一致。" >&2
    echo "现场检测结果:" >&2
    printf '%s\n' "${camera_output}" >&2
    echo "请修改 config.sh 中的 HIKROBOT_CAMERA_SERIAL 后重新运行 ./scripts/start/system.sh。" >&2
    return 1
  fi

  echo "海康相机检查通过: ${matching_line}"
}

if ! validate_hikrobot_camera; then
  return 1 2>/dev/null || exit 1
fi

if ! configure_arm_serial_port; then
  return 1 2>/dev/null || exit 1
fi

if ! validate_arm_uart; then
  return 1 2>/dev/null || exit 1
fi

echo "config.sh 已生效，当前关键配置："
echo "  DASHBOARD_URL       = ${DASHBOARD_URL}"
echo "  BOARD_PREDICT_URL   = ${BOARD_PREDICT_URL}"
echo "  ACTION_DELAY_SECONDS= ${ACTION_DELAY_SECONDS}"
echo "  ACTION_QUEUE_CAPACITY = ${ACTION_QUEUE_CAPACITY}（总在途）"
echo "  continuous_capture_cool_time = ${continuous_capture_cool_time}"
echo "  ARM_SERIAL_PORT     = ${ARM_SERIAL_PORT} (115200 8N1)"
echo "  PUMP_BUS_ID         = 005 (DISABLE_PUMP=${DISABLE_PUMP:-0})"
echo "  HIKROBOT_SERIAL     = ${HIKROBOT_CAMERA_SERIAL}"
echo "  ARM_ACTIVE_IDS      = 000,001,002,003,004"
echo "  ARM_UART_CHECK      = ${ARM_UART_CHECK_RESULT}"
echo "  DEEPSEEK_API_KEY    = $([ -n "${DEEPSEEK_API_KEY}" ] && echo '已设置' || echo '【未设置，语音助手无法启动】')"
