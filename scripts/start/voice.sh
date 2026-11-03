#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

case "${VOICE_WAKE_ENABLED:-0}" in
  1|true|TRUE|yes|YES|on|ON) ;;
  *)
    echo "Vosk 语音唤醒已关闭（VOICE_WAKE_ENABLED=${VOICE_WAKE_ENABLED:-0}），跳过语音助手进程。"
    exit 0
    ;;
esac

if [[ -d "${ROOT_DIR}/.venv" ]]; then
  source "${ROOT_DIR}/.venv/bin/activate"
else
  echo "未找到虚拟环境，请先运行 scripts/setup/install_environment.sh"
  exit 1
fi
export PYTHONNOUSERSITE=1

export DASHBOARD_DB_PATH="${DASHBOARD_DATA_DIR:-$HOME/Database/vision-dashboard}/lines/line_${PRODUCTION_LINE_ID:-1}/dashboard.sqlite3"
export DASHBOARD_URL="${DASHBOARD_URL:-http://172.20.10.12:8000}"
export VOICE_RECORD_DEVICE="${VOICE_RECORD_DEVICE:-plughw:3,0}"
export VOICE_WAKE_WORD="${VOICE_WAKE_WORD:-小助手}"
export VOICE_VOSK_MODEL_PATH="${VOICE_VOSK_MODEL_PATH:-$HOME/models/vosk-model-small-cn-0.22}"
export LLM_PROVIDER="${LLM_PROVIDER:-deepseek}"
export DEEPSEEK_BASE_URL="${DEEPSEEK_BASE_URL:-https://api.deepseek.com}"
export DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-flash}"

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "未设置 DEEPSEEK_API_KEY，无法启动 DeepSeek 联网语音助手。"
  exit 1
fi

cd "${ROOT_DIR}"
exec python -m voice.main
