#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

echo "1/4 安装系统依赖"
sudo apt update
sudo apt install -y \
  python3 \
  python3-venv \
  python3-pip \
  python3-dev \
  build-essential \
  pkg-config \
  alsa-utils \
  ffmpeg \
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
  libffi-dev \
  sqlite3 \
  chromium-browser \
  espeak-ng

echo "2/4 创建虚拟环境"
python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

echo "3/4 升级 pip"
python -m pip install --upgrade pip wheel setuptools

echo "4/4 安装 Python 依赖"
python -m pip install -r "${ROOT_DIR}/requirements/voice.txt"

if [ ! -d "${HOME}/models/vosk-model-small-cn-0.22" ]; then
  echo
  echo "提示：请手动下载 Vosk 中文模型并解压到 ${HOME}/models/vosk-model-small-cn-0.22"
  echo "模型下载后，语音助手才能完成语音转文字。"
fi

cat <<EOF

安装完成。

这个环境已经包含：
- SQLite 查询依赖
- 本地 Ollama 问答客户端依赖
- 唤醒词 + STT + TTS 语音链路依赖
- 树莓派语音播放和录音依赖

后续运行前建议检查：
1. 已设置 DEEPSEEK_API_KEY
2. 数据库位于 ~/Database/vision-dashboard/dashboard.sqlite3
3. Vosk 模型位于 ~/models/vosk-model-small-cn-0.22

EOF
