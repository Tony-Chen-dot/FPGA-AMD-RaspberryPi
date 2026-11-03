#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://127.0.0.1:8000}"

if command -v chromium-browser >/dev/null 2>&1; then
  exec chromium-browser --kiosk --disable-infobars "${URL}"
fi

if command -v chromium >/dev/null 2>&1; then
  exec chromium --kiosk --disable-infobars "${URL}"
fi

if command -v google-chrome >/dev/null 2>&1; then
  exec google-chrome --kiosk --disable-infobars "${URL}"
fi

echo "未找到 Chromium/Chrome，请手动打开：${URL}"
exit 1
