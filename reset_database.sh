#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DASHBOARD_DATA_DIR:-${HOME}/Database/vision-dashboard}"
DASHBOARD_DB="${DATA_DIR}/dashboard.sqlite3"
AI_DB="${DASHBOARD_DB_PATH:-${DASHBOARD_DB}}"

remove_sqlite_database() {
    local db_path="$1"
    rm -f "${db_path}" "${db_path}-wal" "${db_path}-shm"
}

remove_sqlite_database "${DASHBOARD_DB}"
if [[ "${AI_DB}" != "${DASHBOARD_DB}" ]]; then
    remove_sqlite_database "${AI_DB}"
fi

rm -f "${DATA_DIR}/media/latest_frame.jpg"
rm -f "${DATA_DIR}/media/live_stream_frame.jpg"
rm -rf "${DATA_DIR}/media/frames"
rm -rf "${DATA_DIR}/archive"
rm -f "${DATA_DIR}/logs"/*.log 2>/dev/null || true

mkdir -p "${DATA_DIR}/media/frames" "${DATA_DIR}/archive" "${DATA_DIR}/logs"

# Clear every production line's artifacts, including hidden files and subfolders.
# Resolve from this script so ~/FPGA and other deployment locations both work.
# Keep the artifacts directories and leave logs/calibration parameters untouched.
for line_dir in "${ROOT_DIR}/runtime/vision"/line_*; do
    [[ -d "${line_dir}" && ! -L "${line_dir}" ]] || continue
    [[ "${line_dir##*/}" =~ ^line_[0-9]+$ ]] || continue
    artifacts_dir="${line_dir}/artifacts"
    [[ -d "${artifacts_dir}" && ! -L "${artifacts_dir}" ]] || continue
    find "${artifacts_dir}" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    echo "产线图片与检测产物已清空：${artifacts_dir}"
done

echo "检测记录、图片缓存和 AI 对话历史均已清空：${DATA_DIR}"
if [[ "${AI_DB}" != "${DASHBOARD_DB}" ]]; then
    echo "AI 对话数据库已清空：${AI_DB}"
fi
echo "请重启可视化页面后端以重新创建数据库并刷新统计。"
