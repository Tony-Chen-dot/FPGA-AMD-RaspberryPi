#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SHARED_VENV="${ROOT_DIR}/.venv"
PYTHON_BIN=""

detect_host_ip() {
  command -v ip >/dev/null 2>&1 || return 1
  ip -4 -o addr show dev "${WIRED_INTERFACE:-eth0}" scope global 2>/dev/null |
    awk 'NR == 1 { sub("/.*", "", $4); print $4; exit }'
}

if [[ -x "${SHARED_VENV}/bin/python3" ]]; then
  PYTHON_BIN="${SHARED_VENV}/bin/python3"
else
  echo "未找到可执行的虚拟环境 Python 3，请先运行顶层 ./scripts/setup/install_environment.sh" >&2
  exit 1
fi
export PYTHONNOUSERSITE=1

if ! "${PYTHON_BIN}" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "虚拟环境 Python 无法导入 fastapi/uvicorn: ${PYTHON_BIN}" >&2
  echo "请在项目根目录重新运行 ./scripts/setup/install_environment.sh" >&2
  exit 1
fi

export DASHBOARD_INTERFACE_DIR="${ROOT_DIR}/dashboard"
export DASHBOARD_DATA_DIR="${DASHBOARD_DATA_DIR:-${HOME}/Database/vision-dashboard}"

HOST_IP="$(detect_host_ip || true)"
if [[ -z "${HOST_IP}" ]]; then
  HOST_IP="${DASHBOARD_HOST_IP:-127.0.0.1}"
fi
echo "可视化页面: http://${HOST_IP}:${PORT:-8000}"

cd "${ROOT_DIR}"
exec "${PYTHON_BIN}" -m uvicorn dashboard.api.server:app --host 0.0.0.0 --port "${PORT:-8000}"
