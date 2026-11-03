# 目录与命名说明

本组件最终名称为 `raspberry_pi`，部署根目录是 `src/raspberry_pi/`。当前所有 Python 包均属于树莓派软件，Zynq 客户端也保留在这里。跨设备源码的放置规则见 [submission_layout.md](submission_layout.md)。

本次整理按“业务模块 → 子职责 → 具体文件”组织。Python 包、文件和 Shell 实现统一小写英文加下划线；网页资源用所属页面命名。根目录保留五个已使用的启动/安装命令，README.md 和 requirements.txt 保留常见约定名称。

## 一、视觉流程 vision

| 路径 | 职责 |
| --- | --- |
| `pipeline.py` | 串起采集、检测、上传、结果分拣与失败恢复 |
| `capture/hikrobot.py` | 海康 MVS 相机枚举、连接、取帧 |
| `capture/frame_reader.py` | 后台取最新帧，避免积压旧图像 |
| `detection/enhancement.py` | 灰度增强、降噪、锐化及增强参数 |
| `detection/models.py` | 圆检测结果的数据结构 |
| `detection/circles.py` | 圆候选检测、筛选、评分与去重 |
| `detection/annotation.py` | 预览图圆形、中心线、文字标注 |
| `transport/inference_client.py` | 板端请求、结果解析、看板图片与数据上传 |
| `workers/fifo.py` | 有容量限制的单消费者 FIFO 队列 |
| `workers/tasks.py` | 触发任务、动作任务与帧标识 |

图像处理算法、上传内容、触发条件、队列容量及 OK/NG 方向映射没有重写。调度器继续统一管理两条队列，避免拆分后各模块重复调度。

## 二、机械臂与气泵 robot

| 路径 | 职责 |
| --- | --- |
| `control/protocol.py` | `#000P1500T1000!` 格式、ID、波特率、气泵位置值、串口选择 |
| `control/parameters.py` | 六组姿态、五阶段时间、校验、原子保存与已有参数迁移 |
| `control/hardware_lock.py` | 跨进程互斥，避免生产程序和调试页同时操作 |
| `control/controller.py` | 串口连接/写入、关节与气泵执行、五阶段动作、停止与恢复 |
| `actions/run_sequence.py` | 生产分拣命令行入口 |
| `diagnostics/check_uart.py` | 只检查串口能否打开，不发送动作；不是舵机 ID 扫描 |
| `debug/server.py` | 调试页面 HTTP 接口与运行状态 |
| `debug/templates/index.html` | 调试页面结构 |
| `debug/static/controls.js`、`controls.css` | 调试交互和样式 |

气泵使用同一个 UART 的 ID 005，继续由控制器按相同阶段发送。没有另外保留 USB 气泵服务，也没有把气泵从动作顺序中拆出去。

## 三、检测看板 dashboard

| 路径 | 职责 |
| --- | --- |
| `api/server.py` | 看板接口、设备数据接入、直播、AI 对话接口 |
| `api/websocket_hub.py` | WebSocket 连接管理和广播 |
| `storage/database.py` | SQLite 记录、统计、图像保存与查询 |
| `web/index.html` | 检测看板页面 |
| `web/js/dashboard.js`、`web/css/dashboard.css` | 看板交互和样式 |
| `web/vendor/` | 原有离线前端库 |

当前接口、数据库与前端以新版多产线实现为准，数据和实时消息按产线隔离。本次目录整理不更改这些行为。

## 四、语音助手 voice

| 路径 | 职责 |
| --- | --- |
| `main.py` | 唤醒、听取问题、回答的主循环 |
| `service.py` | 看板与语音共用的问答服务 |
| `config.py`、`status.py` | 配置加载与运行状态 |
| `speech/wake_word.py` | 唤醒词识别 |
| `speech/recognition.py` | 语音转文字 |
| `speech/synthesis.py` | 文字转语音 |
| `context/inspection_context.py` | 查询检测数据库并整理问答上下文 |
| `dialogue/model_client.py` | 大模型请求与响应 |
| `dialogue/prompts.py` | 业务提示词 |
| `dialogue/history.py` | 对话历史持久化 |

## 五、部署与运行管理

- `scripts/setup/`：统一环境安装、UART 配置、MVS SDK 安装、单独语音/看板安装。
- `scripts/check/`：相机和机械臂串口预检。
- `scripts/start/`：整套、视觉、看板、语音、机械臂调试及禁用机械臂启动。
- `scripts/stop/`：整套和机械臂调试停止。
- `scripts/tools/`：只读监控、数据库清理、相机进程清理、全屏浏览器、传输打包。清理脚本保留原用途，不在正常启动时自动执行。
- `config.sh`：现场设置；原设置值保留。
- `requirements/`：按业务拆分依赖，`requirements.txt` 汇总。
- `runtime/`：运行时生成的内容，与源码分离。

`common/paths.py` 统一项目根目录、机械臂参数和当前产线视觉运行目录，减少代码搬迁后依赖当前工作目录的问题。

## 旧新路径对照

| 旧路径 | 新路径 |
| --- | --- |
| `circle-camera/main.py` | `vision/pipeline.py` |
| `circle-camera/detector.py` | `vision/detection/` 下的增强、检测、标注等模块 |
| `circle-camera/hikrobot_camera.py` | `vision/capture/hikrobot.py` |
| `circle-camera/dashboard_transport.py` | `vision/transport/inference_client.py` |
| `arm_control/serial_arm.py` | `robot/control/` 下的协议、参数、控制器 |
| `pose_runner/run_pose_sequence.py` | `robot/actions/run_sequence.py` |
| `arm_control/check_servo_ids.py` | `robot/diagnostics/check_uart.py` |
| `servo_dashboard/` | `robot/debug/`，参数移入 `runtime/robot/` |
| `vision-dashboard/backend/` | `dashboard/api/`、`dashboard/storage/` |
| `vision-dashboard/static/` | `dashboard/web/` |
| `voice-dashboard-assistant/app/` | `voice/` 的各职责模块 |
| `site_config.sh` | `config.sh`，预检实现在 `scripts/check/hardware.sh` |
| `logs/` | `runtime/logs/` |
| `monitor.sh` | `scripts/tools/monitor.sh` |
| `run_exclude_robotarm.sh` | `scripts/start/vision_only.sh` |
| `HANDOFF.md` 与旧长篇说明 | `docs/archive/` 历史资料 |

## 已删除与保留的边界

已删除 `Arm_Lib/`、旧 `dofbot_i2c.py`、旧二进制 `servo_protocol.py`、`arm_motion.py`、USB 继电器 `pump_control/` 以及两份对应测试。清除了生产路径的旧继电器专用退出码、重连反馈超时计算和命令行参数。

保留历史参数识别与一次性迁移，以保护树莓派上已经校准的 UART 参数。这些代码不会驱动旧硬件。原有的两份板端接入说明内容不同，分别放入当前文档与历史文档，未当成重复文件丢弃。

依赖中原来同时固定 `requests==2.32.3` 和 `requests==2.32.4`，汇总安装会冲突；本次统一为视觉模块原先使用的 `2.32.4`。其他依赖版本不变。测试中遗留的检测帧率期望 `8` 改为现场配置本来就有的 `12`，未调整实际帧率。

## 多产线扩展

- `common/production_lines.py`：产线编号 1～5 校验、隔离路径，以及原单产线数据的一次性迁移。
- `dashboard/services/production_lines.py`：五份独立存储、五条实时消息通道、按产线加载的 AI 服务。
- `config.sh`：`PRODUCTION_LINE_ID` 指定唯一摄像头实际所属产线，`ZYNQ_IP` 替代原 `C5MB_IP` 名称，IP 数值保持不变。
- 页面按钮只切换查看对象；未配置摄像头的产线明确显示“无信号”，历史数据与 AI 对话仍按产线隔离。
- 检测数据库位于 `DASHBOARD_DATA_DIR/lines/line_N/`，拍照产物位于 `runtime/vision/line_N/`，启动日志位于 `runtime/logs/line_N/`。机械臂校准参数仍属于同一套物理机械臂。
