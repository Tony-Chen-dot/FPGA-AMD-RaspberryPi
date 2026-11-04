> 历史资料：保留当时的记录，目录和控制方式可能已过时。当前操作请以根目录 readme.md 和 docs/project_structure.md 为准。

# 智能质检比赛可视化系统

这是一个面向树莓派部署的比赛展示项目，采用：

- 前端展示：`Vue 3 + Pinia + ECharts + GSAP`
- 页面结构：`比赛主看板 + 历史统计视图`
- 浏览器实时视频：`MJPEG`
- 实时业务数据：`WebSocket`
- 后端服务：`FastAPI`
- 数据目录：`~/Database/vision-dashboard`
- 界面目录：`~/Interface/vision-dashboard`

## 为什么我把 FPGA/ARM 到树莓派 的通信定成 RJ45 + HTTP/WebSocket

为了提高现场成功率，我把系统拆成两段：

1. `FPGA/ARM 板卡 -> 树莓派 FastAPI`
   - 通过 RJ45 以太网连接
   - 使用 `HTTP multipart` 上传最新帧
   - 使用结构化 JSON 一起上报推理结果
   - 实时预览帧以 JPEG 上传，后端不再额外解码和转码

2. `树莓派 FastAPI -> 浏览器页面`
   - 使用 `MJPEG` 直接输出实时 JPEG 帧
   - 使用 `WebSocket` 推送统计数字、最近 3 次检测、历史趋势和设备状态

这样做的好处是：

- 保留浏览器端低延迟视频体验
- 降低板端实现难度
- 推理框样式由前端 `Canvas` 叠加，比赛展示更好看
- 后续替换模型或板端语言时，前端基本不用动

## 目录说明

- `backend/`：FastAPI 后端、SQLite 数据逻辑、MJPEG 输出
- `static/`：前端页面
- `scripts/mock_device.py`：模拟板端推送数据，便于演示
- `scripts/install_to_pi.sh`：拷贝到树莓派后的安装脚本
- `scripts/start_dashboard.sh`：启动脚本
- `scripts/open_kiosk.sh`：树莓派比赛展示全屏脚本
- `scripts/reset_dashboard_data.sh`：清空演示数据，比赛前建议执行一次
- `scripts/package_for_transfer.sh`：生成桌面交付包

## 在树莓派上的推荐部署步骤

1. 把整个项目文件夹拷到树莓派。
2. 在树莓派上执行：

```bash
cd ~/你传过去的文件夹/vision-dashboard
chmod +x scripts/*.sh
./scripts/install_to_pi.sh
```

3. 启动服务：

```bash
cd ~/Interface/vision-dashboard
./scripts/start_dashboard.sh
```

4. 浏览器打开：

```text
http://172.20.10.12:8000
```

5. 如果你想先演示而不是立刻接板子，再开一个终端运行：

```bash
cd ~/Interface/vision-dashboard
./.venv/bin/python ./scripts/mock_device.py --server http://172.20.10.12:8000
```

6. 比赛展示时，如果树莓派安装了 Chromium，可以直接全屏打开：

```bash
cd ~/Interface/vision-dashboard
./scripts/open_kiosk.sh
```

## 板端上报协议

推荐让 ARM 处理器向树莓派发送 `multipart/form-data` 到：

```text
POST /api/device/ingest
```

字段：

- `payload`：JSON 字符串
- `frame`：JPEG 文件

示例 `payload`：

```json
{
  "timestamp": "2026-05-26T12:00:00+00:00",
  "frame_id": "arm-000321",
  "model_name": "DefectNet-Edge",
  "board_name": "Zynq ARM Board",
  "inference_ms": 18.7,
  "frame": { "width": 1280, "height": 720 },
  "result": "NG",
  "defect_count": 2,
  "detections": [
    {
      "label": "Scratch",
      "confidence": 0.96,
      "bbox": { "x": 0.31, "y": 0.42, "w": 0.11, "h": 0.07 }
    }
  ]
}
```

接收端先用 `BOARD_SCORE_THRESH`（默认 `0.2`）过滤正常类和缺陷类候选，再执行全局最高置信度类别判定。正常类获胜时结果为 `OK` 且不显示正常框；缺陷类获胜时结果为 `NG`，只展示该缺陷类别中达到阈值的框。正常与缺陷完全同分时缺陷优先，两个缺陷类别同分时以返回列表中的第一类为准。这是类别决策，不是基于 IoU 的 NMS。

## 你的原始目录想法是否可行

可行，但我做了一个小调整：

- `~/Interface/vision-dashboard`：放整套界面和后端程序
- `~/Database/vision-dashboard`：放数据库、最新帧、归档图片、日志

这样比把所有内容直接平铺在 `~/Database` 更清晰，也更方便以后扩展。
