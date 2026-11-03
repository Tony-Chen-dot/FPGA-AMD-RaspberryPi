#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Skip the arm preflight, startup positioning, and result-triggered sorting.
export DISABLE_ARM_ACTION_FLAG="--disable-arm-action"

echo "正在以无机械臂模式启动推理和可视化调试..."
echo "机械臂ID检查、Preparation移动和检测结果触发的分拣动作均已禁用。"

exec "${ROOT_DIR}/scripts/start/system.sh"
