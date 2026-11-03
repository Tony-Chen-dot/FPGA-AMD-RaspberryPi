# 树莓派多产线质检上位机（raspberry_pi）

一台树莓派作为产线 1～5 的上位机，统一提供监控、历史统计和 AI 分析；Zynq 作为多产线架构中的推理加速器。目前只接入一台摄像头，实际采集与分拣归属由根目录 `config.sh` 中的 `PRODUCTION_LINE_ID` 决定，其余产线显示“无信号”。各产线独立保存检测记录、图片、统计和 AI 对话。机械臂与气泵继续使用已验证的 UART 控制逻辑。

## 本组件在参赛项目中的位置

此目录全部是**运行在树莓派上的代码**；`vision/transport/` 是访问 Zynq 的客户端，`robot/` 是树莓派侧控制代码。交付名称统一为 `raspberry_pi`，整体放入总项目的 `src/raspberry_pi/`，不要只复制其中几个模块。

已按当前多产线版本整理，保留五条产线数据隔离、当前单摄像头配置、UART 控制和现有入口。Zynq 及其他硬件工程本次不处理。总项目目录与后续代码放置见 [整体目录说明](docs/submission_layout.md)。

导出命令：`python3 tools/export_raspberry_pi.py /目标总项目/src/raspberry_pi`，目标必须不存在。也可运行 `bash scripts/tools/package_project.sh` 生成独立目录和 ZIP。导出不携带 `.git`、虚拟环境、缓存、运行图片、数据库和本地环境文件；配置中的 DeepSeek Key 改为从环境读取。现场已校准的 `runtime/robot/servo_params.json` 和外部 `~/Database/vision-dashboard/` 数据请单独备份迁移，勿用默认参数覆盖现场校准值。

## 完整目录结构与文件用途

下面按当前项目实际内容列出目录，每行 `#` 后是该目录或文件的用途。所有路径都以本组件根目录 `raspberry_pi/` 为基准（开发仓库原名为 `FPGA`）。`__init__.py` 是 Python 包标记，不需要单独运行。

这棵树包括源码、脚本、测试、文档、随项目保存的前端库和当前已有的运行文件。`.venv/`、`__pycache__/`、`.DS_Store` 等安装或缓存产物不展开，见后面的“运行生成内容与外部数据”。

```text
raspberry_pi/
├── README.md  # 项目入口说明：目录、用途、安装启动、配置与数据位置
├── config.sh  # 现场配置：网络、相机、采集产线编号、机械臂和语音；加载时调用硬件预检
├── install.sh  # 一键安装入口，转交 scripts/setup/install_environment.sh
├── start_all.sh  # 一键启动全套系统，转交 scripts/start/system.sh
├── reset_database.sh  # 手动清理原数据库数据及所有产线 artifacts 目录内容
├── stop_all.sh  # 一键停止全套系统，转交 scripts/stop/system.sh
├── start_robot_debug.sh  # 一键启动机械臂调试页，默认端口 8088
├── stop_robot_debug.sh  # 一键停止机械臂调试后端并关闭串口连接
├── requirements.txt  # Python 依赖总入口，汇总 requirements/ 下的四份清单
├── .gitattributes  # Git 文件属性：Shell 脚本统一使用 LF 换行
├── .gitignore  # Git 忽略规则：环境、缓存、运行数据和数据库等不纳入版本管理
├── common/  # 公共基础模块
│   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   ├── paths.py  # 统一项目根目录、当前产线视觉数据和机械臂参数路径
│   └── production_lines.py  # 校验产线编号、生成隔离路径，并迁移原单产线数据
├── vision/  # 视觉采集、检测、上传与分拣调度
│   ├── capture/  # 相机与后台取帧
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   ├── frame_reader.py  # 后台持续取帧，向主流程提供最新一帧
│   │   └── hikrobot.py  # 海康 MVS 相机枚举、连接、图像读取和尺寸转换
│   ├── detection/  # 图像增强、圆检测和预览标注
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   ├── annotation.py  # 在预览图上绘制中心线、触发区域、圆与文字
│   │   ├── circles.py  # 圆候选生成、形状筛选、评分、排序和去重
│   │   ├── enhancement.py  # 图像增强参数、对比度增强、降噪和锐化
│   │   └── models.py  # 圆检测结果结构及标注用的椭圆比例常量
│   ├── transport/  # 板端推理和看板数据通信
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   └── inference_client.py  # 准备模型输入、请求板端推理、解析结果、上传看板图像和数据
│   ├── workers/  # 后台队列与任务数据
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   ├── fifo.py  # 有容量限制的先进先出队列，由单个消费者按顺序处理
│   │   └── tasks.py  # 触发任务、分拣任务的数据结构及时间/帧标识生成
│   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   └── pipeline.py  # 视觉主流程：相机、检测、触发、队列、动作调用及失败恢复
├── robot/  # 机械臂和气泵，共用已验证的 ASCII UART 控制逻辑
│   ├── actions/  # 生产分拣命令行入口
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   └── run_sequence.py  # 左右分拣、准备复位、故障恢复；默认演示，--live 才发指令
│   ├── control/  # 底层协议、参数与执行控制
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   ├── controller.py  # 串口连接/发送、关节与气泵动作、五阶段流程、停止和恢复
│   │   ├── hardware_lock.py  # 跨进程硬件互斥及参数文件访问锁
│   │   ├── parameters.py  # 默认姿态与时间、参数校验、原子保存和旧参数迁移
│   │   └── protocol.py  # 串口报文格式、舵机 ID、波特率、气泵 P 值和串口选择
│   ├── debug/  # 机械臂可视化调试页面
│   │   ├── static/  # 调试页面前端资源
│   │   │   ├── controls.css  # 机械臂调试页的布局、颜色和样式
│   │   │   └── controls.js  # 姿态、时间、串口、气泵和动作按钮的交互逻辑
│   │   ├── templates/  # 调试页面模板
│   │   │   └── index.html  # 调试页面的 HTML 结构
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   └── server.py  # 调试 HTTP 服务：页面、状态、连接、参数保存、动作和停止
│   ├── diagnostics/  # 机械臂通信检查
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   └── check_uart.py  # 检查 UART 能否打开；不发动作，也不扫描或确认舵机 ID
│   └── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
├── dashboard/  # 多产线看板、实时数据、存储与 AI 问答接口
│   ├── services/  # 产线数据与服务管理
│   │   ├── __init__.py  # Python 包标记
│   │   └── production_lines.py  # 五条产线的独立存储、AI 服务与实时消息通道
│   ├── api/  # 看板后端服务
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   ├── server.py  # HTTP API、设备数据接入、图像直播、历史查询及 AI 对话接口
│   │   └── websocket_hub.py  # 维护 WebSocket 客户端并广播实时状态
│   ├── storage/  # 检测记录与图像持久化
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   └── database.py  # SQLite 读写、统计、缺陷标签处理、图片保存与标注
│   ├── web/  # 检测看板前端，默认由 8000 端口服务提供
│   │   ├── css/  # 看板样式
│   │   │   └── dashboard.css  # 检测看板与 AI 对话界面的布局和样式
│   │   ├── js/  # 看板交互脚本
│   │   │   └── dashboard.js  # 实时预览、检测统计、历史记录和 AI 对话的页面逻辑
│   │   ├── vendor/  # 随项目保存的第三方前端库，页面无需从 CDN 加载这些库
│   │   │   ├── echarts.min.js  # ECharts：统计图表绘制
│   │   │   ├── gsap.min.js  # GSAP：界面动画
│   │   │   ├── marked.min.js  # Marked：把 Markdown 回答转换为 HTML
│   │   │   ├── pinia.iife.prod.js  # Pinia：前端状态管理
│   │   │   ├── purify.min.js  # DOMPurify：清理 Markdown 渲染后的 HTML
│   │   │   ├── vue-demi.iife.js  # Vue Demi：Vue 相关库的兼容层
│   │   │   └── vue.global.prod.js  # Vue：页面组件、响应式数据和界面更新
│   │   └── index.html  # 检测看板的 HTML 入口
│   └── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
├── voice/  # 语音助手与看板共用的 AI 问答能力
│   ├── context/  # 检测数据检索
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   └── inspection_context.py  # 查询检测数据库，整理模型回答所需的生产数据上下文
│   ├── dialogue/  # 大模型对话与历史
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   ├── history.py  # 会话和消息的 SQLite 保存、读取及删除
│   │   ├── model_client.py  # 组织模型请求、处理响应和分块上下文
│   │   └── prompts.py  # 铝片分拣业务背景、系统提示词及回答提示词
│   ├── speech/  # 音频输入输出
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   ├── recognition.py  # 录音和语音转文字
│   │   ├── synthesis.py  # 文字转语音及播放，包含不同合成后端的处理
│   │   └── wake_word.py  # 通过 Vosk 识别唤醒词
│   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   ├── config.py  # 从环境变量读取语音、模型服务和数据库配置
│   ├── main.py  # 后台语音循环：等待唤醒、听取问题、回答和播报
│   ├── service.py  # 共用问答服务：获取上下文、调用模型、保存对话
│   └── status.py  # 语音助手运行状态和控制台状态提示
├── scripts/  # 根目录一键入口背后的实现和辅助脚本
│   ├── check/  # 启动前硬件检查
│   │   ├── software.sh  # 无硬件软件回归、前端 URL 检查和 Shell 语法检查
│   │   └── hardware.sh  # 由 config.sh 加载，选择 UART 并执行相机与串口预检
│   ├── setup/  # 环境和硬件依赖安装
│   │   ├── configure_uart.sh  # 启用 UART、备份启动配置，并关闭串口登录控制台
│   │   ├── install_camera_sdk.sh  # 从提供的安装包或目录安装海康 MVS SDK
│   │   ├── install_dashboard.sh  # 将项目部署到 ~/Interface/FPGA，准备独立看板所需环境
│   │   ├── install_environment.sh  # 完整安装：系统依赖、UART、dialout、统一 .venv 和 Python 依赖
│   │   └── install_voice.sh  # 单独安装语音相关系统依赖和 Python 包
│   ├── start/  # 各服务启动实现
│   │   ├── dashboard.sh  # 启动 FastAPI 检测看板，默认端口 8000
│   │   ├── robot_debug.sh  # 后台启动机械臂调试服务，检查存活并记录 PID 与日志
│   │   ├── system.sh  # 总启动调度：加载配置、预检、机械臂准备、看板、视觉及可选语音
│   │   ├── vision.sh  # 启动视觉流程，传入相机、检测、通信和机械臂动作参数
│   │   ├── vision_only.sh  # 启动整套检测流程，但禁用机械臂预检、准备动作和结果分拣
│   │   └── voice.sh  # 按配置决定是否启动后台语音唤醒进程
│   ├── stop/  # 服务停止实现
│   │   ├── robot_debug.sh  # 识别本项目的调试进程，发送停止信号并等待其退出
│   │   └── system.sh  # 停止看板、视觉、语音和机械臂调试服务
│   └── tools/  # 监控、维护、打包和展示工具
│       ├── clear_camera_processes.sh  # 清理相机相关残留进程，并尝试 USB unbind/bind 复位
│       ├── monitor.sh  # 只读查看队列、机械臂、气泵、应用日志与内核消息
│       ├── open_kiosk.sh  # 用 Chromium/Chrome 全屏打开指定看板地址
│       ├── package_project.sh  # 生成 Desktop/fpga_transfer/ 下的项目副本和传输 ZIP
│       └── reset_dashboard.sh  # 删除看板数据库、检测图片和归档，供重建数据使用
├── requirements/  # 按功能拆分的 Python 依赖清单
│   ├── dashboard.txt  # 看板依赖：FastAPI、Uvicorn、图片处理和上传解析等
│   ├── robot.txt  # 机械臂串口依赖：pyserial
│   ├── vision.txt  # 视觉依赖：NumPy、OpenCV、HTTP 请求库
│   └── voice.txt  # 语音与模型客户端依赖：Vosk、合成引擎和 HTTP 请求库等
├── runtime/  # 运行数据，与源代码分开；缺失的子目录会由对应服务创建
│   ├── logs/  # 整套启动及预检输出的日志
│   │   ├── dashboard.log  # 检测看板后台输出
│   │   ├── vision.log  # 视觉流程与其调用的分拣动作输出
│   │   └── voice.log  # 后台语音助手输出
│   ├── robot/  # 机械臂参数、调试服务日志和进程记录；当前可为空
│   └── vision/  # 视觉流程生成的图片和状态记录
│       ├── artifacts/  # 预览图片及按流程保存的检测中间产物
│       │   └── live_annotated.jpg  # 最近保存的带标注预览图
│       └── logs/  # 视觉模块自身的日志
│           └── runtime_status.log  # 视觉运行状态记录
├── tools/  # 辅助 Python 工具
│   ├── export_raspberry_pi.py  # 导出树莓派代码及文件摘要清单
│   └── simulate_device.py  # 模拟设备心跳和检测结果，用于看板联调
├── tests/  # 自动化回归测试，不是生产启动入口
│   ├── integration_tests/  # 跨模块与入口测试
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   ├── test_entrypoints.py  # 验证从其他工作目录执行 CLI 帮助时仍可正确导入模块
│   │   ├── test_pipeline.py  # 验证图像链路、存储、队列、页面行为和现场配置约定
│   │   └── test_production_lines.py  # 验证产线隔离、无信号、历史迁移、图片/AI/实时消息归属
│   ├── robot_tests/  # 机械臂协议、动作、调试页和参数测试
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   ├── test_action_sequence.py  # 验证生产命令行、方向、准备/恢复动作和参数传递
│   │   ├── test_debug_http.py  # 验证调试 HTTP 接口、控制令牌、参数校验和错误响应
│   │   ├── test_debug_runtime.py  # 验证调试页共用控制器、连接行为、参数保存和气泵状态
│   │   ├── test_parameter_migration.py  # 验证旧位置参数迁移、已有参数保护及损坏文件处理
│   │   └── test_serial_controller.py  # 验证左右流程串口报文、气泵、停止、故障及参数校验
│   ├── vision_tests/  # 视觉结果处理与分拣联动测试
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   ├── test_defect_labels.py  # 验证板端与看板的缺陷阈值、类别筛选和 OK/NG 判定
│   │   └── test_sorting_actions.py  # 验证动作触发、左右映射、超时计算和失败恢复
│   ├── voice_tests/  # 语音与 AI 问答测试
│   │   ├── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
│   │   └── test_assistant.py  # 验证业务提示词、数据库上下文、对话持久化和看板问答呈现
│   └── __init__.py  # Python 包标记，使本目录可被导入；无独立启动功能
└── docs/  # 当前操作说明及历史资料
    ├── archive/  # 历史资料，只供追溯；当前启动与配置以本 README 为准
    │   ├── fpga_data_protocol_legacy.md  # 另一份历史板端接入说明，因内容不同而保留
    │   ├── previous_dashboard.md  # 旧版看板部署和使用说明
    │   ├── previous_handoff.md  # 原项目交接记录和历史问题说明
    │   ├── previous_readme.md  # 重排前的完整项目说明
    │   ├── previous_robot_control.md  # 旧版机械臂动作入口说明
    │   └── previous_voice_assistant.md  # 旧版语音助手说明
    ├── dashboard.md  # 检测看板启动、数据目录及辅助工具说明
    ├── fpga_data_protocol.md  # FPGA 板端数据接入协议和字段说明
    ├── submission_layout.md  # 总项目目录与其他设备代码放置规则
    ├── project_structure.md  # 模块职责与重排前后的路径对照
    ├── robot_control.md  # 串口、机械臂、气泵、五阶段动作与调试命令说明
    └── voice_assistant.md  # 语音与 AI 助手结构、配置和启动说明
```

## 各模块怎样配合

```text
start_all.sh → scripts/start/system.sh
  ├─ 加载根目录 config.sh → scripts/check/hardware.sh 执行相机与串口预检
  ├─ robot/actions/run_sequence.py 执行机械臂准备动作（启用机械臂时）
  ├─ dashboard/api/server.py 提供检测看板、数据接口和 AI 问答接口
  ├─ vision/pipeline.py 采集 → 增强/圆检测 → Zynq 推理 → 上传当前产线看板
  │                                      └─ OK/NG → 分拣动作 → UART 机械臂与气泵
  └─ voice/main.py 按配置启用后台语音唤醒与问答

start_robot_debug.sh → robot/debug/server.py → robot/control/controller.py
生产分拣命令行入口 ────────────────────────────┘ 共用同一控制器和参数文件
```

`dashboard/` 是检测看板；`robot/debug/` 是机械臂调试页，两者用途和端口不同。气泵使用同一 UART 上的 ID 005，与五个关节的阶段动作一起执行。

## 产线配置与页面切换

### 实时视频尺寸

在 `config.sh` 中设置 `LIVE_FRAME_SCALE`，修改后重启采集程序（整套启动可执行 `bash stop_all.sh` 后再执行 `bash start_all.sh`）。

```bash
export LIVE_FRAME_WIDTH="1536"
export LIVE_FRAME_HEIGHT="1024"
export LIVE_FRAME_SCALE="1.0"
export LIVE_FRAME_JPEG_QUALITY="85"
```

预览读取海康相机未补边的完整画面，先等比例适配上述尺寸上限，再将宽、高分别乘以 `LIVE_FRAME_SCALE`；不裁剪、不补黑边、不放大较小的源图。3:2 相机画面与网页的 3:2 视频区域匹配。

以 1536×1024 源图为例：`1.0` 输出 1536×1024，`0.75` 输出 1152×768，`0.5` 输出 768×512。系数控制的是宽、高，总像素数按系数的平方变化；JPEG 压缩质量独立由 `LIVE_FRAME_JPEG_QUALITY` 控制。有效范围为 `0 < LIVE_FRAME_SCALE <= 1`，0、负数、超过 1 和非有限数值会报错。

圆检测继续使用原来的 1280×720 处理图及检测参数，预览缩放系数不改变检测、中心触发或 Zynq 输入。实际推送性能需在设备上观察，降低系数可减少 JPEG 编码和传输负载。

`CAMERA_FPS=24` 与 `LIVE_PUSH_FPS=24` 分别设置采集和实时推送目标帧率；实际帧率受曝光时间、设备和网络性能影响。右上角触发截图使用触发检测对应的未补边原始画面，3:2 源图缩为 480×320 显示。`BOARD_INPUT_SIZE=320` 仍表示单独发送给 Zynq 的 320×320 正方形推理图，不是实时视频或右上角截图的尺寸。

### 产线归属

在根目录 `config.sh` 中设置：

```bash
export PRODUCTION_LINE_ID="1"  # 1～5：当前摄像头、检测、分拣实际所属的产线
ZYNQ_IP="192.168.10.111"       # 原 C5MB 板卡，统一称为 Zynq 推理加速器
```

修改产线编号后，执行 `bash stop_all.sh` 和 `bash start_all.sh` 重新加载。看板上方的“产线 1～5”按钮只切换浏览对象，不改变摄像头归属；选择哪一条，主看板、历史统计、图片、趋势图与 AI 对话就读取哪一条的数据。切换会保留当前功能视图，不同浏览器可分别查看不同产线。

目前只有配置指定的产线可接收实时采集，其他产线显示“无信号”，不会套用当前摄像头画面或实时结果。有历史数据的离线产线仍可查看自己的历史记录。后台写入接口会校验 `line_id`，拒绝将当前摄像头的数据写入其他产线。

检测数据目录：

```text
~/Database/vision-dashboard/
└── lines/
    ├── line_1/
    ├── line_2/
    ├── line_3/
    ├── line_4/
    └── line_5/
        # 每条产线目录内都有独立的 dashboard.sqlite3、media/、archive/、logs/

raspberry_pi/runtime/vision/line_1/artifacts/  # 产线1的拍照结果 JPG、JSON
raspberry_pi/runtime/vision/line_1/logs/       # 产线1的视觉状态日志
raspberry_pi/runtime/logs/line_1/             # 产线1的启动、看板、视觉、语音和预检日志
# 其他产线使用对应的 line_2～line_5；只有实际启动的产线生成采集日志和图片。
```

`DASHBOARD_DATA_DIR` 可覆盖数据库根目录，产线子目录仍由程序统一生成。后台语音助手读取当前配置产线的数据库；看板 AI 读取页面所选产线的数据库，会话和上下文不会跨产线混用。

首次升级：如果原单产线数据库存在且目标产线数据库尚未建立，程序会用 SQLite 备份机制将原数据库、图片和对话复制到首次启用的产线，原数据保留供回退；迁移标记保证之后改产线编号不会再次复制到另一条产线。原 `runtime/vision/artifacts/`、`logs/` 会迁到首次启用产线的运行目录。若原数据属于某条具体产线，请在第一次启动新版前设置好编号。

## 常见修改应该找哪里

| 想修改的内容 | 主要文件或目录 |
| --- | --- |
| 采集产线编号、Zynq/树莓派网络地址、相机、串口、分拣方向、语音现场设置 | 根目录 `config.sh` |
| 已校准的机械臂姿态和时间 | 在 8088 调试页修改，保存到 `runtime/robot/servo_params.json` |
| 串口报文、舵机 ID、气泵控制值 | `robot/control/protocol.py` |
| 机械臂和气泵执行顺序、停止与恢复 | `robot/control/controller.py` |
| 图像增强、圆检测、预览标注 | `vision/detection/` |
| FPGA 推理请求和结果处理 | `vision/transport/inference_client.py` |
| 检测看板界面 | `dashboard/web/` |
| 机械臂调试界面 | `robot/debug/templates/`、`robot/debug/static/` |
| 模型业务提示词和问答上下文 | `voice/dialogue/prompts.py`、`voice/context/inspection_context.py` |
| 安装和服务启动过程 | `scripts/setup/`、`scripts/start/` |

## 树莓派常用命令

在项目根目录执行：

```bash
bash install.sh            # 一键配置环境和 UART
# 首次配置串口或 dialout 后，按安装提示重启树莓派
bash start_all.sh          # 启动整套系统
bash stop_all.sh           # 停止整套系统
bash start_robot_debug.sh  # 单独启动机械臂调试页
bash stop_robot_debug.sh   # 停止机械臂调试页
```

根目录这五个文件只是稳定入口，实际脚本分别在 `scripts/setup/`、`scripts/start/`、`scripts/stop/`。全套启动会先关闭机械臂调试后端，再做相机与 UART 预检，随后执行机械臂准备动作、启动检测看板、视觉流程和按配置启用的语音进程。

检测看板：`http://<树莓派IP>:8000`；机械臂调试：`http://<树莓派IP>:8088`。使用当前 SSH 地址时，可访问 `http://172.20.10.2:8000` 或 `http://172.20.10.2:8088`。

```bash
bash scripts/start/vision_only.sh   # 原“不运行机械臂”的整套启动方式
bash scripts/tools/monitor.sh 1     # 查看产线1的队列、机械臂、气泵与内核日志
```

## 运行生成内容与外部数据

以下文件可能在安装、首次保存参数或启动服务后才出现；它们没有提前全部放进源码目录树。

| 位置 | 内容与生成方式 |
| --- | --- |
| `.venv/` | `install.sh` 在目标树莓派创建的统一 Python 环境；包含解释器入口及安装的依赖包 |
| `__pycache__/`、`*.pyc` | Python 自动生成的字节码缓存，不是业务源码 |
| `.DS_Store` | macOS 文件管理器生成的显示信息，不参与程序运行 |
| `runtime/robot/servo_params.json` | 调试页保存的姿态和时间；生产动作与调试页共用 |
| `runtime/robot/servo_params.json.lock` | 参数读写和迁移时使用的文件锁 |
| `runtime/robot/server.pid` | 调试服务启动脚本记录的进程号 |
| `runtime/robot/server.log` | 调试服务的控制台输出和错误日志 |
| `runtime/robot/*.legacy-angles-*.bak` | 识别到旧角度格式并迁移时生成的原参数备份 |
| `runtime/logs/line_N/robot_uart_check.log` | UART 预检成功后的检查输出 |
| `runtime/logs/line_N/robot_prepare.log` | 全套启动时机械臂准备动作的执行输出 |
| `runtime/vision/line_N/artifacts/` | 当前产线最近预览图和视觉流程保存的中间图片/数据，内容随运行变化 |
| `/tmp/raspberry-arm-pump.lock` | 默认的跨进程机械臂/气泵操作锁；可由环境变量覆盖 |
| `~/Database/vision-dashboard/lines/line_N/dashboard.sqlite3` | 第 N 条产线的检测数据库和 AI 会话/消息 |
| `~/Database/vision-dashboard/lines/line_N/media/` | 检测图片、最近结果图、实时帧和历史帧 |
| `~/Database/vision-dashboard/lines/line_N/archive/` | 看板数据归档目录 |
| `~/Database/vision-dashboard/lines/line_N/logs/` | 看板数据目录下的日志目录 |
| `~/models/vosk-model-small-cn-0.22/` | 默认 Vosk 中文语音识别模型目录 |
| `~/piper_voices/` | 默认 Piper 语音模型目录 |
| `/opt/MVS/` | 默认海康 MVS SDK 安装位置 |
| `~/Desktop/fpga_transfer/` | 按时间生成的 `raspberry_pi/` 干净副本与 `raspberry_pi.zip` |

表中的 N 为产线编号 1～5。数据库根目录和模型目录可由相应环境变量覆盖，具体以 `config.sh` 与各模块配置为准。SQLite 运行时还可能在数据库旁生成 `-wal`、`-shm` 辅助文件。

### 配置加载与参数迁移

- `config.sh` 位于项目最上层，集中保存网络、相机、分拣方向和语音设置。加载它会调用 `scripts/check/hardware.sh` 执行预检。
- 在原项目目录覆盖升级时，若新参数不存在、旧 `servo_dashboard/data/servo_params.json` 存在，会校验并迁移其中的 UART 参数；旧文件保留，新文件已有内容时不会被覆盖。
- 部署到新目录时，请把树莓派上已调好的参数一并复制到 `runtime/robot/servo_params.json`。尚未保存参数且没有可迁移文件时，控制器使用代码里的默认姿态和时间。
- `.gitignore` 忽略整个 `runtime/`，因此只传 Git 源码不会自动带上已校准参数。

### 维护脚本的区别

`monitor.sh` 只读日志和运行状态；`clear_camera_processes.sh` 会终止匹配的相机进程，并尝试重置相机 USB 接口。它们都位于 `scripts/tools/`。

`scripts/tools/reset_dashboard.sh` 保持原样。`reset_database.sh` 已移至项目根目录，运行 `bash reset_database.sh` 会额外清空本项目 `runtime/vision/line_N/artifacts/` 中的全部内容（包括隐藏文件和子目录），保留 artifacts 目录及产线日志、机械臂参数。数据库清理范围保持原样，不会自动清理新增的 `lines/line_N/` 数据库。原清理范围：`reset_dashboard.sh` 删除旧看板数据库、检测图片和归档；`reset_database.sh` 清理范围更广，还处理 SQLite 辅助文件、实时图像、数据日志以及另行配置的 AI 数据库。默认 AI 对话和检测记录在同一个数据库内，所以删除看板数据库也会删除其中的对话记录。这些清理工具仅在需要清空时手动执行，不属于正常启动步骤。

`package_project.sh` 打包时排除虚拟环境、缓存、视觉运行目录和日志/PID/锁文件；已有的机械臂参数 JSON 会随项目复制。历史资料保存在 `docs/archive/`，仅供追溯，当前命令以本 README 为准。

## 开发验证

在具备依赖的 Python 环境中运行：

```bash
python -m pip install httpx  # 运行新增接口集成测试时需要
python -m unittest discover -s tests -t .
python robot/debug/server.py --demo --host 127.0.0.1 --port 8088
```

演示调试页不访问串口。机械臂串口、动作与气泵细节见 [机械臂说明](docs/robot_control.md)；其他模块见 [检测看板](docs/dashboard.md)、[语音助手](docs/voice_assistant.md)、[板端数据协议](docs/fpga_data_protocol.md)。

## 开发电脑上的软件验证

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements/test.txt
# 另需 Node.js 执行已有的前端图片 URL 检查
bash scripts/check/software.sh
```

验证使用模拟串口与临时数据，不运行 config.sh，也不启动真实相机和机械臂。可通过 TEST_PYTHON 指定其他测试解释器。
