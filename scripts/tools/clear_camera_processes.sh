#!/usr/bin/env bash
# 清理占着摄像头 USB 接口不放的残留进程（vision/pipeline.py 崩溃残留、
# 或海康 MVS SDK 自带的 MVOperateCamera 等测试工具退出时没释放接口），
# 并尝试软件复位相机所在的 USB 接口，效果上相当于自动拔插一次。
set -uo pipefail

PATTERN='vision/pipeline[.]py|mvcamera|mvoperatecamera'

echo "===1. 查找残留进程==="
mapfile -t pids < <(pgrep -fi "$PATTERN" || true)

if [ "${#pids[@]}" -eq 0 ]; then
    echo "没有找到残留进程，摄像头接口目前是干净的。"
else
    echo "找到 ${#pids[@]} 个残留进程（下面表格第一列 PID 就是要杀的进程编号）："
    ps -o pid,ppid,etime,cmd -p "$(IFS=,; echo "${pids[*]}")"

    echo "===2. 逐个杀掉==="
    for pid in "${pids[@]}"; do
        echo "kill -9 ${pid}"
        kill -9 "${pid}" 2>/dev/null || true
    done

    sleep 2

    echo "===3. 再次确认==="
    remaining=$(pgrep -fi "$PATTERN" || true)
    if [ -z "${remaining}" ]; then
        echo "已确认杀干净，没有残留进程了。"
    else
        echo "警告：仍有进程没杀掉，PID: ${remaining}，需要手动排查（可能是权限不够，试试 sudo 运行本脚本）。"
    fi
fi

echo "===4. 尝试软件复位海康相机所在的 USB 接口（相当于自动拔插一次）==="
hik_path=""
for product_file in /sys/bus/usb/devices/*/product; do
    [ -f "${product_file}" ] || continue
    if grep -qiE "hikrobot|MV-CU|Hikvision" "${product_file}" 2>/dev/null; then
        hik_path=$(basename "$(dirname "${product_file}")")
        break
    fi
done

if [ -z "${hik_path}" ]; then
    echo "没有在 /sys/bus/usb/devices 下找到海康相机，跳过软件复位（也可能相机本来就没接上）。"
else
    echo "找到海康相机的 USB 路径：${hik_path}，尝试 unbind/bind 复位..."
    echo "${hik_path}" | sudo tee /sys/bus/usb/drivers/usb/unbind >/dev/null
    sleep 1
    echo "${hik_path}" | sudo tee /sys/bus/usb/drivers/usb/bind >/dev/null
    echo "软件复位命令已执行。"
fi

echo "===完成==="
echo "如果软件复位之后启动程序还是打不开摄像头，最保险的做法仍然是把海康相机 USB 线物理拔一次再插回去。"
