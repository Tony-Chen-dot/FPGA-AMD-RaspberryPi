#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SHARED_VENV="${ROOT_DIR}/.venv"

if [[ -d "${SHARED_VENV}" ]]; then
  source "${SHARED_VENV}/bin/activate"
else
  echo "未找到虚拟环境，请先运行 ${ROOT_DIR}/scripts/setup/install_environment.sh"
  exit 1
fi
export PYTHONNOUSERSITE=1

if [[ -d "${HIKROBOT_SDK_PATH:-/opt/MVS}" ]]; then
  export MVCAM_SDK_PATH="${MVCAM_SDK_PATH:-${HIKROBOT_SDK_PATH:-/opt/MVS}}"
  export MVCAM_COMMON_RUNENV="${MVCAM_COMMON_RUNENV:-${MVCAM_SDK_PATH}/lib}"
  export MVCAM_SOFTWARE_LIBENV="${MVCAM_SOFTWARE_LIBENV:-${MVCAM_SDK_PATH}/lib}"
  export MVCAM_GENICAM_CLPROTOCOL="${MVCAM_GENICAM_CLPROTOCOL:-${MVCAM_COMMON_RUNENV}/CLProtocol}"
  export ALLUSERSPROFILE="${ALLUSERSPROFILE:-${MVCAM_SDK_PATH}/MVFG}"
  export LD_LIBRARY_PATH="${MVCAM_COMMON_RUNENV}/aarch64:${MVCAM_COMMON_RUNENV}/64:${LD_LIBRARY_PATH:-}"
fi

# 方案A：BOARD_SEND_RAW=1 时向板端发送原始 RGB888 字节流而非 JPEG；
# 默认 0 保持现有行为，开启前必须确认板端 /predict 已支持原始流接收。
if [[ "${BOARD_SEND_RAW:-0}" == "1" ]]; then
  export BOARD_SEND_RAW_FLAG="--board-send-raw"
else
  export BOARD_SEND_RAW_FLAG=""
fi

exec python3 "${ROOT_DIR}/vision/pipeline.py" \
  --project-dir "${ROOT_DIR}/runtime/vision/line_${PRODUCTION_LINE_ID:-1}" \
  --camera-source "${CAMERA_SOURCE:-auto}" \
  --camera-index "${CAMERA_INDEX:-0}" \
  --width "${CAMERA_WIDTH:-1280}" \
  --height "${CAMERA_HEIGHT:-720}" \
  --camera-fourcc "${CAMERA_FOURCC:-MJPG}" \
  --fps "${CAMERA_FPS:-24}" \
  --camera-brightness "${CAMERA_BRIGHTNESS:-0}" \
  --camera-contrast "${CAMERA_CONTRAST:-48}" \
  --camera-gamma "${CAMERA_GAMMA:-105}" \
  --camera-gain "${CAMERA_GAIN:-0}" \
  --camera-sharpness "${CAMERA_SHARPNESS:-6}" \
  --hikrobot-sdk-path "${HIKROBOT_SDK_PATH:-/opt/MVS}" \
  --hikrobot-camera-index "${HIKROBOT_CAMERA_INDEX:-0}" \
  --hikrobot-camera-serial "${HIKROBOT_CAMERA_SERIAL:-}" \
  --hikrobot-frame-timeout-ms "${HIKROBOT_FRAME_TIMEOUT_MS:-200}" \
  --live-push-fps "${LIVE_PUSH_FPS:-24}" \
  --detection-fps "${DETECTION_FPS:-8}" \
  --detection-width "${DETECTION_WIDTH:-384}" \
  --continuous-capture-cool-time "${continuous_capture_cool_time:-2.0}" \
  --center-threshold-px "${CENTER_THRESHOLD_PX:-14}" \
  --hough-min-dist "${HOUGH_MIN_DIST:-140}" \
  --hough-param1 "${HOUGH_PARAM1:-90}" \
  --hough-param2 "${HOUGH_PARAM2:-22}" \
  --min-radius "${MIN_RADIUS:-120}" \
  --max-radius "${MAX_RADIUS:-640}" \
  --min-circularity "${MIN_CIRCULARITY:-0.0}" \
  --min-edge-support "${MIN_EDGE_SUPPORT:-0.22}" \
  --min-contour-area-ratio "${MIN_CONTOUR_AREA_RATIO:-0.003}" \
  --max-contour-area-ratio "${MAX_CONTOUR_AREA_RATIO:-0.75}" \
  --min-fill-ratio "${MIN_FILL_RATIO:-0.22}" \
  --max-radial-error-ratio "${MAX_RADIAL_ERROR_RATIO:-0.42}" \
  --crop-min-area-ratio "${CROP_MIN_AREA_RATIO:-0.05}" \
  --center-reject-margin-px "${CENTER_REJECT_MARGIN_PX:-8}" \
  --max-candidates "${MAX_CANDIDATES:-6}" \
  --dashboard-ingest-url "${DASHBOARD_INGEST_URL:-http://127.0.0.1:8000/api/device/ingest}" \
  --dashboard-live-frame-url "${DASHBOARD_LIVE_FRAME_URL:-http://127.0.0.1:8000/api/device/live_frame}" \
  --board-predict-url "${BOARD_PREDICT_URL:-}" \
  --board-file-field "${BOARD_FILE_FIELD:-image_file}" \
  --board-score-thresh "${BOARD_SCORE_THRESH:-0.2}" \
  --board-request-timeout "${BOARD_REQUEST_TIMEOUT:-5.0}" \
  --board-input-size "${BOARD_INPUT_SIZE:-300}" \
  --board-jpeg-quality "${BOARD_JPEG_QUALITY:-85}" \
  ${BOARD_SEND_RAW_FLAG:-} \
  --trigger-queue-capacity "${TRIGGER_QUEUE_CAPACITY:-8}" \
  --artifact-mode "${ARTIFACT_MODE:-final}" \
  --request-timeout "${DASHBOARD_REQUEST_TIMEOUT:-3.0}" \
  --live-frame-request-timeout "${LIVE_FRAME_REQUEST_TIMEOUT:-0.25}" \
  --live-frame-width "${LIVE_FRAME_WIDTH:-1536}" \
  --live-frame-height "${LIVE_FRAME_HEIGHT:-1024}" \
  --live-frame-scale "${LIVE_FRAME_SCALE:-1.0}" \
  --live-frame-jpeg-quality "${LIVE_FRAME_JPEG_QUALITY:-85}" \
  --action-delay-seconds "${ACTION_DELAY_SECONDS:-10}" \
  --action-queue-capacity "${ACTION_QUEUE_CAPACITY:-3}" \
  --action-direction-mode "${ACTION_DIRECTION_MODE:-0}" \
  --action-timeout-seconds "${ACTION_TIMEOUT_SECONDS:-30}" \
  --action-python "${ACTION_PYTHON:-/usr/bin/python3}" \
  --action-params-path "${ACTION_PARAMS_PATH:-runtime/robot/servo_params.json}" \
  --pose-runner-path "${POSE_RUNNER_PATH:-robot/actions/run_sequence.py}" \
  ${ACTION_LIVE_FLAG:---action-live} \
  ${DISABLE_ARM_ACTION_FLAG:-} \
  --enhance-clahe-clip-limit "${ENHANCE_CLAHE_CLIP_LIMIT:-2.4}" \
  --enhance-clahe-grid-size "${ENHANCE_CLAHE_GRID_SIZE:-8}" \
  --enhance-contrast-gain "${ENHANCE_CONTRAST_GAIN:-1.15}" \
  --enhance-brightness-beta "${ENHANCE_BRIGHTNESS_BETA:--2}" \
  --enhance-detail-gain "${ENHANCE_DETAIL_GAIN:-0}" \
  --enhance-sharpen-sigma "${ENHANCE_SHARPEN_SIGMA:-1.0}" \
  --enhance-sharpen-amount "${ENHANCE_SHARPEN_AMOUNT:-0.55}" \
  --enhance-median-denoise-kernel "${ENHANCE_MEDIAN_DENOISE_KERNEL:-3}" \
  --enhance-gaussian-denoise-sigma "${ENHANCE_GAUSSIAN_DENOISE_SIGMA:-0}" \
  --enhance-bilateral-denoise-diameter "${ENHANCE_BILATERAL_DENOISE_DIAMETER:-3}" \
  --enhance-bilateral-denoise-sigma-color "${ENHANCE_BILATERAL_DENOISE_SIGMA_COLOR:-16}" \
  --enhance-bilateral-denoise-sigma-space "${ENHANCE_BILATERAL_DENOISE_SIGMA_SPACE:-16}" \
  --board-name "${CIRCLE_BOARD_NAME:-Zynq 多产线推理加速器}" \
  --model-name "${CIRCLE_MODEL_NAME:-Zynq 缺陷检测模型}" \
  ${SHOW_WINDOW_FLAG:---no-show-window}
