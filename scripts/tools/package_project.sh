#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXPORT_DIR="${1:-${HOME}/Desktop/fpga_transfer/$(date +%Y%m%d_%H%M%S)}"
mkdir -p "${EXPORT_DIR}"
EXPORT_DIR="$(cd "${EXPORT_DIR}" && pwd)"
if [[ -e "${EXPORT_DIR}/raspberry_pi.zip" ]]; then
  echo "归档已存在，请选择新的输出目录: ${EXPORT_DIR}" >&2
  exit 1
fi
python3 "${ROOT_DIR}/tools/export_raspberry_pi.py" "${EXPORT_DIR}/raspberry_pi"
cd "${EXPORT_DIR}"
zip -qr raspberry_pi.zip raspberry_pi
echo "树莓派代码：${EXPORT_DIR}/raspberry_pi"
echo "归档文件：${EXPORT_DIR}/raspberry_pi.zip"
