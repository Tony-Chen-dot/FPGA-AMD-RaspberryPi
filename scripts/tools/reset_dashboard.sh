#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${DASHBOARD_DATA_DIR:-${HOME}/Database/vision-dashboard}"

rm -f "${DATA_DIR}/dashboard.sqlite3"
rm -f "${DATA_DIR}/media/latest_frame.jpg"
rm -rf "${DATA_DIR}/media/frames"
rm -rf "${DATA_DIR}/archive"

mkdir -p "${DATA_DIR}/media/frames" "${DATA_DIR}/archive" "${DATA_DIR}/logs"

echo "已清空数据目录：${DATA_DIR}"
echo "下次启动服务后会自动重建数据库。"
