#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  echo "请不要直接用 root 运行，使用普通用户执行即可，脚本会在需要时调用 sudo。"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="${ROOT_DIR}/.tmp_hikrobot_mvs_install"

if [[ $# -lt 1 ]]; then
  cat <<'EOF'
用法：
  ./scripts/setup/install_camera_sdk.sh /path/to/MVS_xxx_aarch64.deb
  ./scripts/setup/install_camera_sdk.sh /path/to/MVS_xxx(Linux ARM).zip
  ./scripts/setup/install_camera_sdk.sh /path/to/MVS_STD_V3

说明：
1. 先准备海康机器人 MVS 的 Linux ARM64 安装包。
2. 可以直接传 `.deb`，也可以传官方 `.zip`，或者传包含 `.deb/.tar.gz` 的目录。
3. 再执行本脚本完成安装。

示例：
  ./scripts/setup/install_camera_sdk.sh ~/raspberry/MVS_STD_V3
  ./scripts/setup/install_camera_sdk.sh ~/Downloads/MVS-3.0.1_aarch64_20251113.deb
EOF
  exit 1
fi

INPUT_PATH="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$1")"

if [[ ! -e "${INPUT_PATH}" ]]; then
  echo "未找到安装包或目录：${INPUT_PATH}"
  exit 1
fi

ARCH="$(uname -m)"
if [[ "${ARCH}" != "aarch64" ]]; then
  echo "当前系统架构是 ${ARCH}，这个脚本只针对 ARM64 / aarch64 的树莓派。"
  exit 1
fi

if ! command -v unzip >/dev/null 2>&1; then
  echo "缺少 unzip，正在安装。"
  sudo apt-get update
  sudo apt-get install -y unzip
fi

rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}"

DEB_PATH=""
ZIP_PATH=""
INNER_TAR=""

if [[ -d "${INPUT_PATH}" ]]; then
  DEB_PATH="$(find "${INPUT_PATH}" -maxdepth 2 -type f -iname '*aarch64*.deb' | head -n 1)"
  ZIP_PATH="$(find "${INPUT_PATH}" -maxdepth 2 -type f -iname '*.zip' | head -n 1)"
  INNER_TAR="$(find "${INPUT_PATH}" -maxdepth 2 -type f \( -iname '*aarch64*.tar.gz' -o -iname '*arm64*.tar.gz' \) | head -n 1)"
elif [[ "${INPUT_PATH}" == *.deb ]]; then
  DEB_PATH="${INPUT_PATH}"
elif [[ "${INPUT_PATH}" == *.zip ]]; then
  ZIP_PATH="${INPUT_PATH}"
elif [[ "${INPUT_PATH}" == *.tar.gz ]]; then
  INNER_TAR="${INPUT_PATH}"
fi

if [[ -n "${DEB_PATH}" ]]; then
  echo "正在安装 deb：${DEB_PATH}"
  sudo dpkg -i "${DEB_PATH}" || true
  sudo apt-get install -f -y
elif [[ -n "${ZIP_PATH}" ]]; then
  echo "正在解压 zip：${ZIP_PATH}"
  unzip -q "${ZIP_PATH}" -d "${WORK_DIR}"
  INNER_TAR="$(find "${WORK_DIR}" -type f \( -iname '*aarch64*.tar.gz' -o -iname '*arm64*.tar.gz' \) | head -n 1)"
  if [[ -z "${INNER_TAR}" ]]; then
    echo "在 zip 包内没有找到 aarch64/arm64 的 tar.gz 安装包。"
    echo "请确认你下载的是海康 MVS 的 Linux ARM64 版本。"
    exit 1
  fi

  EXTRACT_DIR="${WORK_DIR}/mvs_aarch64"
  mkdir -p "${EXTRACT_DIR}"

  echo "正在解压 ARM64 安装包：${INNER_TAR}"
  tar -xzf "${INNER_TAR}" -C "${EXTRACT_DIR}"

  SETUP_SH="$(find "${EXTRACT_DIR}" -type f -name 'setup.sh' | head -n 1)"
  if [[ -z "${SETUP_SH}" ]]; then
    echo "没有找到 setup.sh，无法继续安装。"
    exit 1
  fi

  SETUP_DIR="$(cd "$(dirname "${SETUP_SH}")" && pwd)"
  echo "准备运行安装程序：${SETUP_SH}"
  (
    cd "${SETUP_DIR}"
    sudo ./setup.sh
  )
elif [[ -n "${INNER_TAR}" ]]; then
  EXTRACT_DIR="${WORK_DIR}/mvs_aarch64"
  mkdir -p "${EXTRACT_DIR}"
  echo "正在解压 ARM64 安装包：${INNER_TAR}"
  tar -xzf "${INNER_TAR}" -C "${EXTRACT_DIR}"
  SETUP_SH="$(find "${EXTRACT_DIR}" -type f -name 'setup.sh' | head -n 1)"
  if [[ -z "${SETUP_SH}" ]]; then
    echo "没有找到 setup.sh，无法继续安装。"
    exit 1
  fi
  SETUP_DIR="$(cd "$(dirname "${SETUP_SH}")" && pwd)"
  echo "准备运行安装程序：${SETUP_SH}"
  (
    cd "${SETUP_DIR}"
    sudo ./setup.sh
  )
else
  echo "没有找到可安装的海康 ARM64 包。"
  echo "请确认目录里至少有以下其中一种："
  echo "  *aarch64*.deb"
  echo "  *aarch64*.tar.gz"
  echo "  *.zip"
  exit 1
fi

if [[ ! -d /opt/MVS ]]; then
  echo "安装脚本已执行，但没有发现 /opt/MVS，请检查安装输出是否报错。"
  exit 1
fi

cat <<'EOF'

MVS SDK 安装完成。

建议追加到 ~/.bashrc：
  export MVCAM_SDK_PATH="/opt/MVS"
  export MVCAM_COMMON_RUNENV="/opt/MVS/lib"
  export MVCAM_SOFTWARE_LIBENV="/opt/MVS/lib"
  export MVCAM_GENICAM_CLPROTOCOL="/opt/MVS/lib/CLProtocol"
  export ALLUSERSPROFILE="/opt/MVS/MVFG"
  export LD_LIBRARY_PATH="/opt/MVS/lib/aarch64:/opt/MVS/lib/64:${LD_LIBRARY_PATH:-}"

追加后执行：
  source ~/.bashrc

可以这样检查是否安装成功：
  ls /opt/MVS
  ls /opt/MVS/bin
  find /opt/MVS -name 'MvCameraControl_class.py'

如果要打开官方客户端：
  cd /opt/MVS/bin
  ./MVS.sh
EOF
