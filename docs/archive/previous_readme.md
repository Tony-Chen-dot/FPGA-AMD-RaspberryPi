> 历史资料：保留当时的记录，目录和控制方式可能已过时。当前操作请以根目录 readme.md 和 docs/project_structure.md 为准。

# Raspberry

这是树莓派端的整套项目目录，里面包含三部分：

- `vision-dashboard`：可视化页面和数据库后端
- `voice-dashboard-assistant`：连续待机 AI 语音助手，联网调用 DeepSeek，并结合数据库内容回答后再语音播报
- `circle-camera`：树莓派摄像头圆检测、实时预览推送、图像增强处理、命中中心后图片和 JSON 上报

为了方便老师直接复线项目，当前这份文档已经主动去掉了不必要的检查步骤，没有再单独要求检查 `ollama`、`vosk`、`piper_voices`、麦克风型号、默认树莓派 IP、数据库文件是否存在这一类前置项，而是直接保留实际安装、启动、停止和重置项目所需要的操作命令。

当前这套代码已经整理成统一安装、统一启动的形式，默认使用：

- 默认可视化页面地址：`http://172.20.10.12:8000`
- 默认数据库路径：`$HOME/Database/vision-dashboard/dashboard.sqlite3`
- 默认唤醒词：`小助手`
- 默认语音播放设备：`plughw:CARD=vc4hdmi1,DEV=0`
- 默认 DeepSeek 接口地址：`https://api.deepseek.com`

当前页面顶部新增“AI 分拣助手”视图：左侧保留历史会话，中间完成网页对话，右侧提供本次对话的快速定位，最右侧提供六个快捷提问按钮。网页和连续待机语音入口共用铝片智能分拣专用提示词，并在每次提问前读取 `~/Database/vision-dashboard/dashboard.sqlite3` 中的全部检测记录与缺陷明细；数据量过大时会自动分片后汇总，避免只依据最近几条记录回答。

## AI 快捷提问与生产工艺背景

AI 页面最右侧新增六个常用入口：

1. `当前良率`：查询 OK 数、总检测数、良率计算公式和数据时间范围。
2. `缺陷排行`：查询数量最多的缺陷、各类数量、比例和统计口径。
3. `近期异常`：分析最近有效数据中的缺陷变化和异常集中时段。
4. `问题排查`：按照数据证据、可能工序和现场检查方法生成不超过三项排查建议。
5. `工艺优化`：从熔铸、轧制、退火清洗、矫直分切、冲裁和输送环节寻找需要核查的工艺点。
6. `识别可靠性`：检查各类缺陷的置信度分布和低置信度记录。

点击按钮后，问题会写入当前对话输入框并自动聚焦，但不会立即发送。这样可以先修改问题和时间范围，也避免误触后触发一次需要读取全库数据的模型调用。

需要直接进入 AI 页面时，可以打开 `http://树莓派IP:8000/?view=assistant`；不带 `view` 参数时仍然默认显示比赛主看板。

AI 的生产背景按工业铝板带或薄片经轧制、精整、切片或圆片冲裁后进入视觉分拣工位来设置。典型路线为：

1. 铝液熔炼与合金化。
2. 精炼、除气和过滤。
3. 半连续铸锭、均匀化与热轧，或者采用连续铸轧路线形成带卷。
4. 多道次冷轧控制厚度、板形和表面。
5. 中间退火或成品退火、脱脂清洗、干燥和矫直。
6. 分切、定尺剪切或圆片冲裁、去毛刺、堆叠和输送。
7. 机器视觉检测、数据库记录、AI 分析和机械分拣。

提示词会把脏污、折皱、划痕、针孔和擦伤映射到可能相关的工序，但这些映射只用于形成排查假设。数据库没有记录合金牌号、厚度、炉次、卷号、轧机张力、退火曲线和模具编号时，AI 不得把某个工序写成已经确定的根因。

## 目录结构

- `vision-dashboard/`：页面主程序和数据库后端
- `voice-dashboard-assistant/`：语音助手源码
- `circle-camera/`：摄像头取流、圆检测、触发上传
- `pump_control/`：USB-TTL 气泵控制代码和串口配置
- `.venv/`：整个项目共用的 Python 虚拟环境
- `install_all_on_pi.sh`：整套安装脚本
- `install_hikrobot_mvs_on_pi.sh`：海康工业相机 MVS SDK 安装脚本
- `run_all.sh`：整套启动脚本
- `stop_all.sh`：整套关闭脚本
- `reset_database.sh`：清空数据库和缓存

## 安装教程

当前部署方式是：从 Windows 将桌面的整个 `raspberry` 文件夹复制到树莓派的 `/home/pi/raspberry`。**注意：Windows 没有 Linux 的"可执行权限"概念，`scp` 复制过去的 `.sh` 脚本可能缺少可执行权限（运行时报 `Permission denied`），所以每次部署后都要在树莓派上重新执行一次 `chmod +x`。**

在 Windows PowerShell 执行：

```powershell
scp -r "C:\Users\huddd\Desktop\raspberry" pi@172.20.10.12:/home/pi/
```

- `-r` 表示连同子目录一起递归复制；复制完成后项目目录应为 `/home/pi/raspberry`。
- 页面启动提示默认使用树莓派 `eth0` 的当前有线 IPv4 地址；更换网络后不需要手动改页面地址，启动脚本会自动重新读取。查看结果可执行 `ip -4 -o addr show dev eth0`。

然后到树莓派终端（提示符是 `pi@raspberrypi`）执行：

```bash
cd ~/raspberry && \
chmod +x install_all_on_pi.sh && \
./install_all_on_pi.sh
```

- `install_all_on_pi.sh` 启动后会自动给项目中其余 `.sh` 脚本添加执行权限，所以这里只需要手动给安装脚本本身添加权限。
- `install_all_on_pi.sh` 会自动完成：

1. 安装系统依赖
2. 创建统一虚拟环境 `~/raspberry/.venv`
3. 安装可视化页面依赖
4. 安装语音助手依赖
5. 安装圆检测与摄像头依赖
6. 让三个子项目共用同一个 `.venv`

## 海康工业相机安装

如果你使用的是海康 USB 工业相机，例如 `Hikrobot MV-CU060-10UC`，当前仓库已经改成支持通过海康 `MVS SDK` 取流，不再依赖 `/dev/video0` 这种 UVC 视频节点。

如果你已经把海康安装包目录放进了 `~/raspberry/MVS_STD_V3`，并且里面有 `MVS-3.0.1_aarch64_20251113.deb`，直接执行：

```bash
cd ~/raspberry && \
chmod +x install_hikrobot_mvs_on_pi.sh && \
./install_hikrobot_mvs_on_pi.sh ~/raspberry/MVS_STD_V3
```

如果你想手动安装，也可以直接执行：

```bash
cd ~/raspberry/MVS_STD_V3 && \
sudo dpkg -i MVS-3.0.1_aarch64_20251113.deb && \
sudo apt-get install -f -y
```

安装完成后，建议检查：

```bash
ls /opt/MVS && \
find /opt/MVS -name 'MvCameraControl_class.py'
```

如果以上命令有输出，就说明 MVS SDK 已经安装成功。

## 启动整套程序（推荐：用 site_config.sh 一次性配置）

现场部署 / 换环境时，只需要改一个文件：项目根目录下的 `site_config.sh`。它把网络 IP、DeepSeek Key、机械臂动作时间、气泵参数、摄像头来源等所有容易变的东西集中放在一起，改完之后：

```bash
cd ~/raspberry
nano site_config.sh
```

按文件里的注释填好数值，保存退出，然后执行：

```bash
cd ~/raspberry
./run_all.sh
```

`run_all.sh` 会自动加载 `site_config.sh`，并在机械臂动作和后台服务启动前检查气泵与海康相机。相机序列号不一致时会打印配置值和现场枚举结果并停止启动。

需要实时观察机械臂动作 FIFO、UART 发送、005 气泵指令和串口故障时，另开一个终端运行：

```bash
cd ~/raspberry
chmod +x monitor.sh
./monitor.sh
```

该脚本只读取应用日志、进程状态和内核 USB 事件，不会打开串口，也不会与 `run_all.sh` 争用硬件。按 `Ctrl+C` 只停止监视；若提示无权读取内核日志，可改用 `sudo ./monitor.sh`。

`site_config.sh` 当前受 Git 版本控制，用于保存项目默认现场配置。请勿把真实 DeepSeek Key、口令或其他敏感信息提交到仓库；现场必须临时填写真实 Key 时，只能保留为该设备上的未提交修改，并在每次提交前用 `git diff -- site_config.sh` 检查、确认敏感值没有进入提交。当前脚本会直接设置 `DEEPSEEK_API_KEY`，不能假设启动前设置的同名环境变量一定会覆盖它。当前暂不调整该文件的跟踪状态。

现场需要调整参数时直接修改 `site_config.sh`，保存后重新运行：

```bash
./run_all.sh
```

### site_config.sh 变量说明

| 变量 | 作用 | 什么时候需要改 |
|---|---|---|
| `PI_LAN_IP` | 历史兼容字段；页面访问地址现在由启动脚本实时读取 `eth0` 的 IPv4，不再直接使用此值 | 通常不用改；如需指定其他接口，临时设置 `WIRED_INTERFACE` |
| `WIRED_INTERFACE` | 启动时用于显示页面地址的网卡名，默认 `eth0` | 需要临时使用其他网卡（例如 `wlan0`）时 |
| `PI_ETH0_IP` | 树莓派和 AC550 网线直连时，树莓派侧的静态IP（脚本会自动配置到 `eth0`） | 一般不用改，换网段才需要 |
| `C5MB_IP` | C5MB/SoC 板子当前真实IP，本次固定为 `172.16.68.110`；更换板卡后用 `ip addr` 复核 | **每次换现场 / 换 C5MB 板子都要确认** |
| `DEEPSEEK_API_KEY` | 语音助手调用 DeepSeek 用的 key，不填语音助手无法启动 | 首次部署必填，之后一般不用改 |
| `VOICE_RECORD_DEVICE` | 麦克风 ALSA 设备名 | 换麦克风型号/换树莓派才需要 |
| `VOICE_PLAYBACK_DEVICE` | 播放设备 ALSA 设备名 | 换喇叭/换 HDMI 输出才需要 |
| `VOICE_WAKE_WORD` | 语音唤醒词 | 想换唤醒词才需要 |
| `VOICE_WAKE_ENABLED` | 是否启动 Vosk 持续语音唤醒，`0`=关闭，`1`=开启 | 树莓派 CPU 紧张或不需要语音唤醒时保持 `0` |
| `ACTION_DELAY_SECONDS` | 命中中心后延迟多久才让机械臂动作 | **现场装好机械臂后大概率要微调** |
| `ACTION_QUEUE_CAPACITY` | 机械臂动作总在途容量，默认 `3`，包含执行中和等待中 | 工位物理缓存数量变化时调整，不能替代传送带挡停 |
| `continuous_capture_cool_time` | 圆形检测触发拍照/推理后，允许下一次拍照前等待的冷却时间（秒），当前默认 `2.0` | 连续工件间隔较短、出现漏拍或需要避免重复触发时调整；修改后必须重启程序 |
| `BOARD_SCORE_THRESH` | 板卡正常/缺陷候选参与最终类别判定的最低置信度，默认 `0.2` | 正常误报或缺陷漏检需要重新权衡时 |
| `ACTION_DIRECTION_MODE` | 0=NG左/OK右，1=相反 | 机械臂摆放方向变了才需要 |
| `ACTION_HOLD_SECONDS` | 机械臂到达 Forward 后的停留时间，默认 `0.2` 秒 | 需要更稳的吸取动作时可微调 |
| `PUMP_BEFORE_SECONDS` | 到达 Left/Right 后气泵继续开启的时间，默认 `0.1` 秒 | 调整放料位置稳定时间时 |
| `PUMP_AFTER_SECONDS` | 关泵后到返回 Preparation 前的释放等待，默认 `0.7` 秒 | 工件被回程连带时优先增大 |
| `ARM_VERIFY_MOVES` | `0`=生产动作不逐段回读 5 个舵机位置；`1`=诊断模式逐段校验并允许重试 | 默认保持 `0`，仅排障时临时开启 |
| `ARM_SETTLE_SECONDS` | 每段设定运动时间结束后的机械稳定余量，默认 `0.05` 秒 | 机械惯性明显时小幅增加 |
| `ACTION_TIMEOUT_SECONDS` | 单次动作超时下限；程序还会按三段运动及停留总时长自动放宽 | 一般不用改 |
| `PUMP_SERIAL_PORT` | 气泵USB转串口设备路径 | 换气泵驱动板/换USB口才需要确认 |
| `PUMP_BAUDRATE` | USB继电器串口波特率，默认 `9600`（8N1） | 换继电器型号且说明书要求不同波特率时 |
| `PUMP_RELEASE_WAIT_SECONDS` | 手动 Stop Pump 时的机械缓冲时间，完整分拣流程使用 `PUMP_AFTER_SECONDS` | 单独调试气泵按钮时 |
| `PUMP_FEEDBACK_TIMEOUT_SECONDS` | 等待继电器四字节状态反馈的超时，默认 `0.5` 秒 | 正常反馈偶发超时时小幅调整 |
| `PUMP_RECONNECT_ATTEMPTS` | 首次失败后的 USB 重连次数，默认 `2` | 一般不用改 |
| `PUMP_RECONNECT_TIMEOUT_SECONDS` | 每次等待 CH341 重新枚举的最长时间，默认 `2.0` 秒 | USB 重枚举明显偏慢时调整 |
| `DISABLE_PUMP` | 只测试机械臂动作、不测试气泵（默认注释掉，不禁用） | 气泵硬件还没接好，先单独调试机械臂时 |
| `CAMERA_SOURCE` | `hikrobot`（海康工业相机）或 `v4l2`（普通UVC摄像头） | 换摄像头类型才需要改 |
| `HIKROBOT_CAMERA_SERIAL` | 海康相机序列号；启动时会与 MVS 枚举结果严格比对 | 换相机才需要改 |
| `LIVE_PUSH_FPS` | 页面 MJPEG 推流帧率，当前默认 `15` | 页面预览需要更流畅或需要进一步降负载时调整 |
| `DETECTION_FPS` | 圆检测提交帧率，当前默认 `8` | 现场输送速度变化时调整 |
| `DETECTION_WIDTH` | 圆检测输入最大宽度，当前默认 `384`；整幅画面等比例缩放，不裁剪视野 | 检测精度不足时可恢复到 `448` |

更细的图像增强、圆检测阈值参数（`ENHANCE_*`、`CENTER_THRESHOLD_PX`、`MIN_RADIUS` 等）平时不需要改，只有画面效果或检测效果明显不对时才需要微调。生产模式下建议直接写入 `site_config.sh`；单项调试脚本仍可在 `source site_config.sh` 后临时 `export`。

启动成功后会同时运行：

1. 可视化页面后端
2. 树莓派摄像头圆检测与实时推流程序
3. 按 `VOICE_WAKE_ENABLED` 决定是否启动 AI 语音助手连续待机程序

终端会输出：

- 可视化页面地址
- 页面日志路径
- 圆检测日志路径
- 语音助手日志路径
- 默认唤醒词
- 数据库路径
- 联网模型
- 关键词来源
- AI 语音助手实时状态

页面会直接显示 `circle-camera` 推送的实时摄像头画面，并带圆检测标注。海康黑白相机在采集和圆检测链路中保持单通道，只有板端模型要求时才转换为三通道输入；圆检测使用整幅画面等比例缩小后的图像，不改变摄像头覆盖范围。当圆进入中心阈值后，系统仍会保持原有功能：

1. 保存命中时刻图片
2. 保存 JSON 元数据
3. 向 `vision-dashboard` 的 `/api/device/ingest` 发送检测后的图片和 JSON
4. 页面数据库照常入库，语音助手照常读取数据库回答

## 页面地址

浏览器打开：

[http://172.20.10.12:8000](http://172.20.10.12:8000)

## 机械臂与气泵（众灵 ASCII UART）

本副本已经切换为 `test` 中实机验证的串口方案。关节 ID 为 `000～004`，气泵为同一总线上的 `005`；115200、8N1。旧 I²C 和 USB 继电器代码保留作历史参考，生产与调试入口均不再导入它们。

在树莓派进入本项目文件夹：

```bash
# 已安装整套环境且 test 串口可用时，无需重新配置 UART
./start_servo_dashboard.sh
# 首次安装整套环境才执行：./install_all_on_pi.sh
# 只需补充 UART 配置：bash configure_arm_uart.sh（首次修改后重启）
```

浏览器打开 `http://树莓派IP:8088`。启动不自动运动；页面支持六组姿态、左右五阶段完整流程、005吸取/释放/复位、时序调节、发送日志及停止。滑块为 P0500～P2500，不能使用旧机械臂的角度值。参数自动保存到 `servo_dashboard/data/servo_params.json`，生产 `run_all.sh` 读取同一文件；无参数导出功能。

气泵吸取 `#005P2500Txxxx!`，释放 `#005P0500Txxxx!`，完整流程最终按 Verilog 发 `P1500`。P1500 仅表示最近发送值，不伪装成气泵已关闭。`DISABLE_PUMP=1` 会跳过005，保留五关节动作。

`ARM_SERIAL_PORT=auto` 自动选择：Pi 5 `/dev/ttyAMA0`，其他树莓派 `/dev/serial0`。如需覆盖，先 `export ARM_SERIAL_PORT=/dev/你的设备` 再启动；调试页也可切换串口。物理引脚仍为 8/TX、9/GND、10/RX，继续使用已经测试成功的接口与供电。

整套启动 `./run_all.sh` 保留原准备动作、NG/OK分支映射、失败恢复和动作队列。默认 `ACTION_DIRECTION_MODE=0` 仍为 **NG左、OK右**，不是按 FPGA 注释重新定义检测结果。完整机械动作改为吸取→转移→下降→释放→复位。检测失败恢复仍由原相机流程调用 `--recover`：发送005释放，等待后让五关节复位；这是原整套流程保留的恢复行为。

预检仅确认串口可打开，不发送查询或运动，不声称舵机 ID 在线。所有完成提示均表示指令发送和等待结束，没有位置回读。`run_all.sh` 会先停止8088以释放串口；同一时间只运行一套机械臂控制程序。

旧角度格式参数首次读取会备份后替换为新的 FPGA 默认参数；损坏的新格式会报错。若在树莓派的 `test/settings.json` 中调好了姿态，可先停止控制程序，再复制该文件到本项目的 `servo_dashboard/data/servo_params.json`；格式相同。

详细指令与动作表见 [pose_runner/readme.md](pose_runner/readme.md)。每次上传新版后重新执行 `./start_servo_dashboard.sh` 会停止本工程旧后端并检查新接口版本。

## 查看圆检测和视频流实时日志

如果你想看圆检测和视频流实时日志，可以执行：

```bash
tail -f ~/raspberry/logs/circle-camera.log
```

## 常用 export 命令

下面这些命令用于更换设备、接口地址或模型。其中网络地址、DeepSeek Key、机械臂动作时间、气泵参数、摄像头来源这几项，现在**推荐直接改 `site_config.sh`**（见上面「启动整套程序」一节），不用每次手动 `export`；下面这些命令主要用于临时调试、或者调整 `site_config.sh` 里没有覆盖的细节参数（TTS、图像增强、圆检测阈值等），只需要在启动前执行一次即可。

### 1. 更换数据库路径和页面地址

```bash
export DASHBOARD_DB_PATH="$HOME/Database/vision-dashboard/dashboard.sqlite3"
# 正常启动时会自动使用 eth0 当前 IPv4；仅临时覆盖时再手动设置：
# export WIRED_INTERFACE="wlan0"
```

### 2. 更换摄像头与圆检测参数

如果是普通 UVC 摄像头：

```bash
export CAMERA_SOURCE="v4l2"
export CAMERA_INDEX="0"
export CAMERA_WIDTH="1280"
export CAMERA_HEIGHT="720"
export CAMERA_FPS="18"
export CAMERA_BRIGHTNESS="0"
export CAMERA_CONTRAST="48"
export CAMERA_GAMMA="105"
export CAMERA_GAIN="0"
export CAMERA_SHARPNESS="6"
export LIVE_PUSH_FPS="18"
export DETECTION_FPS="8"
export LIVE_FRAME_WIDTH="576"
export LIVE_FRAME_HEIGHT="324"
export LIVE_FRAME_JPEG_QUALITY="55"
export CENTER_THRESHOLD_PX="10"
export MIN_RADIUS="25"
export MAX_RADIUS="260"
export MIN_CIRCULARITY="0.78"
export MIN_EDGE_SUPPORT="0.35"
export CROP_MIN_AREA_RATIO="0.05"
export SHOW_WINDOW_FLAG="--no-show-window"
```

如果是海康工业相机：

```bash
export CAMERA_SOURCE="hikrobot"
export HIKROBOT_SDK_PATH="/opt/MVS"
export HIKROBOT_CAMERA_INDEX="0"
export HIKROBOT_CAMERA_SERIAL="DA3387962"
export HIKROBOT_FRAME_TIMEOUT_MS="200"
export CAMERA_WIDTH="1280"
export CAMERA_HEIGHT="720"
export CAMERA_FPS="18"
export LIVE_PUSH_FPS="18"
export DETECTION_FPS="8"
export LIVE_FRAME_WIDTH="576"
export LIVE_FRAME_HEIGHT="324"
export LIVE_FRAME_JPEG_QUALITY="55"
export CENTER_THRESHOLD_PX="10"
export MIN_RADIUS="25"
export MAX_RADIUS="260"
export MIN_CIRCULARITY="0.78"
export MIN_EDGE_SUPPORT="0.35"
export CROP_MIN_AREA_RATIO="0.05"
export SHOW_WINDOW_FLAG="--no-show-window"
```

如果你只接了一台海康相机，`HIKROBOT_CAMERA_INDEX="0"` 一般就够了。  
如果你想确认当前海康 SDK 能看到哪些相机，可以执行：

```bash
cd ~/raspberry/circle-camera
python3 main.py --camera-source hikrobot --hikrobot-sdk-path /opt/MVS --list-hikrobot-cameras
```

其中 `CROP_MIN_AREA_RATIO` 表示裁剪和目标圆筛选时，忽略掉"面积占整帧比例"小于该阈值的圆。默认 `0.05` 表示忽略小于整张画面 5% 的圆；如果你想放宽或收紧，可以在启动前改成例如 `export CROP_MIN_AREA_RATIO="0.03"` 或 `export CROP_MIN_AREA_RATIO="0.08"`。

当前 `circle-camera` 在 `CAMERA_SOURCE="v4l2"` 时会优先通过 `v4l2-ctl` 设置摄像头硬件参数；在 `CAMERA_SOURCE="hikrobot"` 时，会自动切换到海康 MVS SDK 取流，跳过这些 V4L2 专用控制，不影响后续圆检测、页面实时视频流、触发截图和上传逻辑。

### 3. 更换传输路径（网络地址）

树莓派和 C5MB/SoC 板子用网线直连时需要分配有线 IP，并把上传地址指向板子的真实 IP。**这一步现在由 `site_config.sh` 自动完成**（改 `PI_ETH0_IP`/`C5MB_IP` 两个变量，`source` 时会自动执行下面等价的操作），这里保留手动做法，供不想用 `site_config.sh` 或需要临时调试时参考：

```bash
sudo ip addr add 172.16.68.12/23 dev eth0
sudo ip link set eth0 up
export BOARD_PREDICT_URL="http://172.16.68.110:8080/predict"
export DASHBOARD_INGEST_URL="http://172.20.10.12:8000/api/device/ingest"
```

本次 C5MB 地址固定为 `172.16.68.110/23`。更换板卡或镜像后，仍应去 C5MB 终端执行 `ip addr` 复核；端口固定是 `8080`、路径固定是 `/predict`。

验证时采用

```bash
ip addr
```

会输出eth0处的代码

### 4. 摄像头画面调整

当前代码已经加入图像增强链路：先做中值滤波去除椒盐类噪点，再做双边滤波降低颗粒噪声并尽量保留边缘，随后进行 CLAHE 局部对比度增强、亮度/对比度调整、细节增强和锐化。常用参数如下：

```bash
export ENHANCE_CLAHE_CLIP_LIMIT="2.6"
export ENHANCE_CLAHE_GRID_SIZE="8"
export ENHANCE_CONTRAST_GAIN="1.18"
export ENHANCE_BRIGHTNESS_BETA="-6"
export ENHANCE_DETAIL_GAIN="0.12"
export ENHANCE_SHARPEN_SIGMA="1.1"
export ENHANCE_SHARPEN_AMOUNT="0.82"
export ENHANCE_MEDIAN_DENOISE_KERNEL="3"
export ENHANCE_GAUSSIAN_DENOISE_SIGMA="0"
export ENHANCE_BILATERAL_DENOISE_DIAMETER="5"
export ENHANCE_BILATERAL_DENOISE_SIGMA_COLOR="28"
export ENHANCE_BILATERAL_DENOISE_SIGMA_SPACE="28"
```

如果画面过暗，可以先提高软件亮度：

```bash
export ENHANCE_BRIGHTNESS_BETA="0"
```

如果希望画面更加接近训练画面，可以提高相机对比度和软件对比度：

```bash
export CAMERA_CONTRAST="55"
export ENHANCE_CONTRAST_GAIN="1.25"
```

如果画面噪点比较明显，可以适当提高降噪参数：

```bash
export ENHANCE_MEDIAN_DENOISE_KERNEL="5"
export ENHANCE_BILATERAL_DENOISE_DIAMETER="7"
```

如果画面细节被抹得太平，可以把降噪调轻：

```bash
export ENHANCE_MEDIAN_DENOISE_KERNEL="3"
export ENHANCE_BILATERAL_DENOISE_DIAMETER="3"
```

### 5. 更换 DeepSeek API

```bash
export LLM_PROVIDER="deepseek"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_API_KEY="你的 deepseek key"
export DEEPSEEK_MODEL="deepseek-v4-flash"
export DEEPSEEK_TIMEOUT_SECONDS="180"
export DEEPSEEK_MAX_TOKENS="2048"
```

### 6. 更换语音唤醒词和录音参数

```bash
export VOICE_WAKE_WORD="小助手"
export VOICE_RECORD_DEVICE="plughw:3,0"
export VOICE_SAMPLE_RATE="16000"
export VOICE_QUESTION_SECONDS="5"
export VOICE_WAKE_REARM_DELAY="1.2"
```

### 7. 更换屏幕喇叭或其它播放设备

如果你改了屏幕输出口或者改用别的喇叭，可以调整播放设备：

```bash
export VOICE_PLAYBACK_DEVICE="plughw:CARD=vc4hdmi1,DEV=0"
```

如果你切到另一个 HDMI 或声卡，只需要把这里替换成你实际要用的 ALSA 设备名。

### 8. 更换 TTS 方案

默认优先级是：`piper -> edge-tts -> espeak-ng`

如果你想强制指定：

```bash
export TTS_PROVIDER="piper"
export PIPER_VOICE_ZH="zh_CN-huayan-medium"
export PIPER_VOICE_EN="en_US-lessac-medium"
export PIPER_DATA_DIR="$HOME/piper_voices"
export TTS_SPEED="0.92"
```

如果你想临时改成 `edge-tts`：

```bash
export TTS_PROVIDER="edge"
```

如果你想临时改成 `espeak-ng`：

```bash
export TTS_PROVIDER="espeak"
```

### 9. 一次性常用启动示例

现在推荐用 `site_config.sh` 代替下面这一长串手动 `export`：

```bash
cd ~/raspberry
./run_all.sh
```

如果不想用 `site_config.sh`，也可以手动执行等价的一次性示例（仅供参考/临时调试）：

```bash
export DEEPSEEK_API_KEY="你的 deepseek key"
export VOICE_PLAYBACK_DEVICE="plughw:CARD=vc4hdmi1,DEV=0"
export TTS_PROVIDER="piper"
export PIPER_DATA_DIR="$HOME/piper_voices"
export CAMERA_FPS="15"
export LIVE_PUSH_FPS="18"
export DETECTION_FPS="8"
export LIVE_FRAME_WIDTH="576"
export LIVE_FRAME_HEIGHT="324"
export LIVE_FRAME_JPEG_QUALITY="55"
export CAMERA_CONTRAST="48"
export CAMERA_SHARPNESS="6"
export ENHANCE_CONTRAST_GAIN="1.18"
export ENHANCE_BRIGHTNESS_BETA="-6"
cd ~/raspberry
./run_all.sh
```

## 停止程序

如果你是通过 `./run_all.sh` 启动的，推荐直接执行：

```bash
cd ~/raspberry
./stop_all.sh
```

如果你想手动关闭，也可以执行下面三条命令：

```bash
pkill -f "uvicorn backend.app:app"
pkill -f "circle-camera/main.py"
pkill -f "python -m app.main"
```

如果你想确认是否已经停止，可以执行：

```bash
ps aux | grep -E "uvicorn backend.app:app|circle-camera/main.py|python -m app.main"
```

**注意**：`stop_all.sh` 报告"已停止"不代表进程真的清空了，务必用上面这条 `ps aux` 命令亲自确认一遍，现场遇到过 `stop_all.sh` 声称成功、但 `circle-camera/main.py` 进程仍占着摄像头 USB 接口的情况，导致新启动的程序打不开摄像头。

## 清空数据库和缓存

如果你想把所有检测记录、图片缓存、统计数据全部清空，执行：

```bash
cd ~/raspberry
chmod +x reset_database.sh
./reset_database.sh
```

这个脚本会清空：

1. `dashboard.sqlite3`
2. 最新帧图片缓存
3. 实时流图片缓存
4. 历史帧缓存
5. 归档图片
6. 日志缓存

清空后如果要继续使用，重新启动整套程序：

```bash
cd ~/raspberry
./run_all.sh
```

## 重新启动程序

如果你改了 `site_config.sh`，建议这样重新启动：

```bash
cd ~/raspberry
./stop_all.sh
./run_all.sh
```

## 说明

`pip install -r requirements.txt` 只能安装 Python 库，像 `ffmpeg`、`sqlite3`、`espeak-ng` 这些系统程序仍然需要通过 `apt` 安装。顶层 `install_all_on_pi.sh` 已经把这些内容封装好了，正常使用时直接运行它即可。

## 操作手册

### 1. 项目目标

当前整合后的 `~/raspberry` 已经把原来的 `vision-dashboard`、`voice-dashboard-assistant` 和 `pi_circle_fpga` 的核心能力缝合为一套程序，目标是：

1. 页面实时显示树莓派摄像头画面
2. 实时显示圆检测结果
3. MJPEG 实时推流帧率默认设置为 `15fps`，后台圆检测默认 `8fps`，圆检测输入为整幅画面等比例缩放后的 `384px` 宽图像；三者可以分别通过 `LIVE_PUSH_FPS`、`DETECTION_FPS` 和 `DETECTION_WIDTH` 调整
4. 当圆进入中心区域时，自动保存触发图片
5. 自动保存对应 JSON
6. 仍按原有接口把检测后的图片和 JSON 发给可视化后端
7. 数据继续入原数据库，语音助手继续基于数据库回答

### 2. 一键安装

```bash
cd ~/raspberry
chmod +x install_all_on_pi.sh
./install_all_on_pi.sh
```

### 3. 配置RJ45网口

这一步现在由 `site_config.sh` 自动完成（见上面「启动整套程序」一节），手动做法：

```bash
sudo ip addr add 172.16.68.12/23 dev eth0
sudo ip link set eth0 up
export BOARD_PREDICT_URL="http://172.16.68.110:8080/predict"
```

验证时执行 `ip addr`，确认输出里 `eth0` 那一行的 `inet` 地址符合预期。

### 4. 一键启动

```bash
cd ~/raspberry
chmod +x run_all.sh stop_all.sh
./run_all.sh
```

### 5. 一键关闭

```bash
cd ~/raspberry
./stop_all.sh
```

### 6. 默认工作方式

1. `circle-camera` 从树莓派摄像头读取画面
2. 程序先把原始摄像头画面推送给 `vision-dashboard`，保证视频低延迟
3. 后台线程独立执行圆检测和图像增强
4. 按 `LIVE_PUSH_FPS` 设置把实时画面发给 `vision-dashboard`
5. 页面显示实时画面，并用叠层显示后台检测圆数量、触发小图和发送状态
6. 命中中心时，把检测图片和 JSON 继续发给 `/api/device/ingest`
7. 模型输入图裁剪时优先以当前画面检测到的最大圆为基准，避免针孔、小杂圆影响裁剪区域
8. `vision-dashboard` 写入数据库并更新页面
9. `voice-dashboard-assistant` 继续读取数据库内容进行语音回答

### 7. 关键日志

```bash
tail -f ~/raspberry/logs/vision-dashboard.log
tail -f ~/raspberry/logs/circle-camera.log
tail -f ~/raspberry/logs/voice-dashboard-assistant.log
```

## 语音助手（AI）相关内容

如果你想看语音转写、关键词、匹配到的标签、AI 返回内容，可以执行：

```bash
tail -f ~/raspberry/logs/voice-dashboard-assistant.log
```

如果你只想单独启动语音助手，不启动页面，可以执行：

```bash
export DEEPSEEK_API_KEY="你的 deepseek key"
cd ~/raspberry
./voice-dashboard-assistant/scripts/start_voice_assistant.sh
```

## 本次串口集成验证（2026-10-25）

本地回归共106项，105通过；唯一失败沿用原项目既有的测试/配置不一致：测试期望DETECTION_FPS=8，实际配置为12，本次没有修改现场帧率。已核对与test相同的左右30条指令、005气泵、停止、故障传播、CLI、页面API、参数迁移与保存，并通过pySerial+伪终端验证发送字节。看板和语音源码逐文件保持一致，相机仅修改机械臂动作/恢复的超时适配。尚未在树莓派上运行这次全套集成。
