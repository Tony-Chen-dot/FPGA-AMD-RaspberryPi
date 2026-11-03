#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_INTERFACE="${HOME}/Interface/FPGA"
TARGET_DATA="${HOME}/Database/vision-dashboard"
TARGET_VENV="${TARGET_INTERFACE}/.venv"

mkdir -p "${HOME}/Interface" "${HOME}/Database"
mkdir -p "${TARGET_DATA}/media" "${TARGET_DATA}/archive" "${TARGET_DATA}/logs"

rsync -a \
  --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude 'desktop-output/' \
  --exclude 'package/' \
  --exclude 'runtime/logs/' \
  --exclude 'runtime/vision/' \
  --exclude 'runtime/robot/*.log' \
  --exclude 'runtime/robot/*.pid' \
  --exclude 'runtime/robot/*.lock' \
  --exclude '__pycache__/' \
  --exclude '.DS_Store' \
  "${SOURCE_DIR}/" "${TARGET_INTERFACE}/"

python3 -m venv "${TARGET_VENV}"
source "${TARGET_VENV}/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "${TARGET_INTERFACE}/requirements/dashboard.txt" -r "${TARGET_INTERFACE}/requirements/voice.txt"

cat <<EOF

安装完成。
项目目录：${TARGET_INTERFACE}
数据目录：${TARGET_DATA}

启动命令：
  cd "${TARGET_INTERFACE}"
  ./scripts/start/dashboard.sh

演示数据命令（另开一个终端）：
  cd "${TARGET_INTERFACE}"
  ./.venv/bin/python ./tools/simulate_device.py --server http://172.20.10.12:8000

浏览器打开：
  http://172.20.10.12:8000

EOF
