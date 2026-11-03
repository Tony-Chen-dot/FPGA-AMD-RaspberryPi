#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

echo "为项目中的其他脚本添加执行权限"
find "${ROOT_DIR}" \
  -path "${VENV_DIR}" -prune -o \
  -type f -name '*.sh' ! -path "${ROOT_DIR}/scripts/setup/install_environment.sh" \
  -exec chmod +x {} +

echo "1/4 安装系统依赖"
sudo apt update
sudo apt install -y \
  python3 \
  python3-venv \
  python3-pip \
  python3-dev \
  python3-serial \
  build-essential \
  pkg-config \
  alsa-utils \
  ffmpeg \
  sqlite3 \
  chromium-browser \
  espeak-ng \
  libavformat-dev \
  libavcodec-dev \
  libavdevice-dev \
  libavutil-dev \
  libavfilter-dev \
  libswscale-dev \
  libswresample-dev \
  libopus-dev \
  libvpx-dev \
  libjpeg-dev \
  libopenjp2-7 \
  libopenblas-dev \
  libssl-dev \
  libffi-dev

echo "2/4 配置机械臂 UART 与串口权限"
bash "${ROOT_DIR}/scripts/setup/configure_uart.sh"
sudo usermod -aG dialout "${USER}"

echo "3/4 创建统一 Python 虚拟环境并安装依赖"
cd "${ROOT_DIR}"
# Windows 检出受跟踪的 Linux 符号链接时，可能将它们还原成内容仅为
# "python3" 或 "/usr/bin/python3" 的普通文本文件。先删除这些入口，
# 再由 Linux venv 重新创建正确的可执行文件/符号链接。
if [[ -d "${VENV_DIR}/bin" ]]; then
  rm -f "${VENV_DIR}/bin/python" "${VENV_DIR}/bin/python3" "${VENV_DIR}/bin/python3.11"
fi
python3 -m venv --system-site-packages "${VENV_DIR}"
if [[ ! -x "${VENV_DIR}/bin/python3" ]] || ! "${VENV_DIR}/bin/python3" -c 'import sys' >/dev/null 2>&1; then
  echo "虚拟环境 Python 入口创建失败: ${VENV_DIR}/bin/python3" >&2
  exit 1
fi
source "${VENV_DIR}/bin/activate"
export PYTHONNOUSERSITE=1
# mediapipe is not used by this project and its old 0.10.9 release forces
# protobuf<4, which conflicts with Piper's onnxruntime dependency.
pip uninstall -y mediapipe mediapipe-nightly >/dev/null 2>&1 || true
pip install --upgrade pip
pip install -r "${ROOT_DIR}/requirements.txt"
pip check

echo "检查 Python 硬件库导入"
python - <<'PY'
import serial
print("ok: serial is importable")
PY

echo "4/4 完成安装"
deactivate
echo "安装完成：./start_all.sh 启动全套程序；./start_robot_debug.sh 启动机械臂调试。"
echo "运行日志位于 runtime/logs。首次配置 UART 或 dialout 后请 sudo reboot。"
