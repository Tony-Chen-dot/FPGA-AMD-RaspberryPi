#!/usr/bin/env bash
# ============================================================================

SITE_CONFIG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONNOUSERSITE=1

# 当前接入摄像头和进行检测/分拣的产线编号（1～5）；修改后重启整套程序。
# 看板按钮只切换查看对象，不改变实际采集归属。
export PRODUCTION_LINE_ID="1"
case "${PRODUCTION_LINE_ID}" in
  1|2|3|4|5) ;;
  *) echo "PRODUCTION_LINE_ID 必须为 1～5" >&2; return 1 2>/dev/null || exit 1 ;;
esac
# 树莓派现场部署配置文件
#
# 用法：
#   1. 改这个文件里的数值（不用改其它任何代码/脚本）
#   2. ./scripts/start/system.sh（启动脚本会自动 source 本文件并执行硬件预检）
#
# 这个文件只负责设置环境变量，本身不会启动任何程序，
# 也不会自己去改机械臂/气泵/检测算法的逻辑。
#
# 注意：这个文件当前受 Git 版本控制。请勿把真实 DEEPSEEK_API_KEY、口令
# 或其他敏感信息提交到仓库。现场必须临时填写时，只能保留为未提交修改；
# 提交前请执行 `git diff -- config.sh`，确认敏感值没有进入提交。
# ============================================================================

# ---------------------------------------------------------------------------
# 1. 网络地址 —— 每次换现场 / 换配对的 Zynq 板子都要确认这三项
# ---------------------------------------------------------------------------
# 树莓派的有线网卡名；可视化页面启动提示优先显示该接口当前的 IPv4 地址。
export WIRED_INTERFACE="${WIRED_INTERFACE:-eth0}"

# 旧配置字段保留给现场网络参数和兼容已有文档；页面访问地址不再直接使用它，
# 而是在下面读取 ${WIRED_INTERFACE} 的当前地址，避免网络变化后继续打印旧 IP。
PI_LAN_IP="172.20.10.2"

# 树莓派和 Zynq 用网线（eth0）直连时，树莓派这一端要配置的静态IP。
# 网段要和 ZYNQ_IP 在同一个 /24 网段里。
PI_ETH0_IP="192.168.10.120"
PI_ETH0_PREFIX="24"

# Zynq/SoC 板子当前真实的IP。
# 现场务必去 Zynq 终端执行 `ip addr`，看正在 up 的那个网口(一般是 eth1)的 inet 地址，
# 不要直接假设是默认值——现场很可能和练习时不一样。
ZYNQ_IP="192.168.10.111"

export DASHBOARD_INGEST_URL="http://127.0.0.1:8000/api/device/ingest"
export DASHBOARD_LIVE_FRAME_URL="http://127.0.0.1:8000/api/device/live_frame"
export BOARD_PREDICT_URL="http://${ZYNQ_IP}:8080/predict"

detect_wired_ipv4() {
  command -v ip >/dev/null 2>&1 || return 1
  ip -4 -o addr show dev "${WIRED_INTERFACE}" scope global 2>/dev/null |
    awk 'NR == 1 { sub("/.*", "", $4); print $4; exit }'
}

# 自动把 eth0 配置成上面写的静态IP并启用（幂等：已经配过就不会重复报错）。
# 如果你不想让这个文件自动改网络配置，把下面这一整块注释掉，自己手动执行 README 里的命令即可。
if command -v ip >/dev/null 2>&1; then
  if ! ip addr show eth0 2>/dev/null | grep -q "inet ${PI_ETH0_IP}/${PI_ETH0_PREFIX}"; then
    sudo ip addr add "${PI_ETH0_IP}/${PI_ETH0_PREFIX}" dev eth0 2>/dev/null
    sudo ip link set eth0 up 2>/dev/null
  fi
fi

CURRENT_WIRED_IP="$(detect_wired_ipv4 || true)"
if [[ -z "${CURRENT_WIRED_IP}" ]]; then
  CURRENT_WIRED_IP="127.0.0.1"
  echo "网络提示: ${WIRED_INTERFACE} 没有可用的全局 IPv4 地址，页面地址回退为 http://${CURRENT_WIRED_IP}:8000。" >&2
fi
export DASHBOARD_HOST_IP="${CURRENT_WIRED_IP}"
export DASHBOARD_URL="http://${DASHBOARD_HOST_IP}:8000"

# ---------------------------------------------------------------------------
# 2. DeepSeek 语音助手 Key —— 首次部署必填，之后一般不用改
# ---------------------------------------------------------------------------
export DEEPSEEK_API_KEY=""

# ---------------------------------------------------------------------------
# 3. 语音助手设备 —— 换了麦克风/喇叭型号，或者换了树莓派才需要改
# ---------------------------------------------------------------------------
export VOICE_RECORD_DEVICE="plughw:3,0"
export VOICE_PLAYBACK_DEVICE="plughw:CARD=vc4hdmi1,DEV=0"
export VOICE_WAKE_WORD="小助手"
# Vosk 持续唤醒开关：0=关闭（页面文字/浏览器语音仍可使用），1=启动后台语音助手
export VOICE_WAKE_ENABLED="0"

# ---------------------------------------------------------------------------
# 4. 机械臂动作时间参数 —— 现场把机械臂/相机/圆盘轨道摆好之后，大概率要微调
# ---------------------------------------------------------------------------
# 检测到圆盘命中中心之后，等待多少秒再让机械臂开始动作（给圆盘留出到位/稳定的时间）
export ACTION_DELAY_SECONDS="3.5"
# 圆形检测触发拍照/推理后的连续拍照冷却时间（秒）；修改后重启 ./scripts/start/system.sh 生效
export continuous_capture_cool_time="1.0"
# Zynq 单次推理约 15 秒，读取响应超时设为 30 秒；与机械臂动作超时独立。
export BOARD_REQUEST_TIMEOUT="30.0"
# 发给 Zynq 推理的正方形图像边长（像素），不改变相机采集或看板预览尺寸。
export BOARD_INPUT_SIZE="320"
export BOARD_JPEG_QUALITY="85"
# 发送给 Zynq 的推理输入图格式开关（方案A）：
#   0 = 现有行为，发送 JPEG 压缩图（image/jpeg）；
#   1 = 发送无压缩原始 RGB888 字节流（320×320×3=307200 字节，HWC 交错序，
#       application/octet-stream，字段名仍为 image_file）。
# 开启前必须确认板端 /predict 已支持原始流接收（按 Content-Type 区分），
# 否则板端会把原始字节当 JPEG 解码导致推理失败；双端需同版本切换。
export BOARD_SEND_RAW="0"
# 板卡候选框置信度阈值：低于该值的正常/缺陷候选都不参与最终类别判定。
export BOARD_SCORE_THRESH="0.2"
export CAMERA_FPS="24"
export LIVE_PUSH_FPS="24"
# 网页预览：原始视野等比例缩放，不补黑边；与圆检测输入尺寸独立。
export LIVE_FRAME_WIDTH="1536"
export LIVE_FRAME_HEIGHT="1024"
# 宽、高缩放系数，0 < 值 <= 1。1=1536×1024，0.5=768×512（总像素为 1/4）。
# 先适配上述尺寸上限再乘系数，不放大小尺寸源图；0/负数/大于1会报错。
export LIVE_FRAME_SCALE="1.0"
export LIVE_FRAME_JPEG_QUALITY="85"
export DETECTION_FPS="12"
# 黑白相机进入圆检测前的最大宽度，384 相比原 448 可减少约 26% 像素量
export DETECTION_WIDTH="384"
# 限制 OpenCV 内部线程，避免圆检测和其他进程同时抢满树莓派 CPU
export OPENCV_THREADS="2"
export TRIGGER_QUEUE_CAPACITY="8"
# 机械臂动作总在途容量（包含正在执行的动作）；3 = 1 个执行中 + 2 个等待。
export ACTION_QUEUE_CAPACITY="3"
export ARTIFACT_MODE="final"
# 0 = NG走左边/OK走右边；1 = 相反。机械臂摆放方向变了才需要改。
export ACTION_DIRECTION_MODE="0"
# 五阶段 P/T 参数和发送后等待时间由 8088 串口调试页面设置，
# 并保存到 runtime/robot/servo_params.json，生产分拣读取同一组参数。
# UART 运动命令没有应答；这里不再使用旧 I2C 位置回读或额外稳定时间。
# 单次机械臂+气泵动作序列的超时时间（秒），超时视为本次动作失败
export ACTION_TIMEOUT_SECONDS="30"

# ---------------------------------------------------------------------------
# 5. 机械臂串口 —— 物理引脚 8/TX、9/GND、10/RX
# ---------------------------------------------------------------------------
# auto：Pi 5 使用 /dev/ttyAMA0，其余型号使用 /dev/serial0。
# 也可在启动前 export ARM_SERIAL_PORT=/dev/... 指定已验证的端口。
export ARM_SERIAL_PORT="${ARM_SERIAL_PORT:-auto}"
# 115200、8N1；关节 ID 000～004，气泵 ID 005，共用一条 ASCII 总线。
# 若仅测试关节、跳过全部 005 命令，取消下一行注释：
# export DISABLE_PUMP="1"

# ---------------------------------------------------------------------------
# 6. 摄像头来源 —— 换摄像头型号/换了另一台海康相机才需要改
# ---------------------------------------------------------------------------
export CAMERA_SOURCE="hikrobot"       # 普通UVC摄像头改成 "v4l2"
export HIKROBOT_SDK_PATH="${HIKROBOT_SDK_PATH:-/opt/MVS}"
export HIKROBOT_CAMERA_SERIAL="DB1164307"

# ---------------------------------------------------------------------------
# 更细的图像增强 / 圆检测阈值参数（ENHANCE_*、HOUGH_*、MIN_RADIUS 等）
# 平时不需要改，只有画面效果或检测效果明显不对时才需要微调。
# 具体变量名和含义见 README.md「摄像头与圆检测参数微调」章节，
# 完整生产启动以本文件为准；单项调试时可以 source 后再临时 export 覆盖。
# ---------------------------------------------------------------------------

source "${SITE_CONFIG_ROOT}/scripts/check/hardware.sh"
