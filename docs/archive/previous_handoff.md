> 历史资料：保留当时的记录，目录和控制方式可能已过时。当前操作请以根目录 README.md 和 docs/project_structure.md 为准。

> 2026-10-25 更新：FPGA 副本的活动机械臂入口已切换到 `arm_control/serial_arm.py`，使用115200 ASCII UART，关节000～004、气泵005。当前部署及操作以 README 的“机械臂与气泵（众灵 ASCII UART）”章节和 pose_runner/README.md 为准。下文旧 I²C / USB继电器内容为历史记录，不再描述当前活动控制路径。

# Raspberry 项目交接说明

## 项目概况

本仓库是树莓派端的铝片视觉检测与机械分拣系统。树莓派负责海康相机取流、圆心触发、看板服务、机械臂与气泵控制；C5MB/SoC 板通过 HTTP 接口执行缺陷推理；检测结果存入 SQLite，并可由网页和 DeepSeek 语音/文字助手读取。

主要链路：

1. `circle-camera/main.py` 获取相机画面并检测圆。
2. 圆进入中心触发区后，`circle-camera/dashboard_transport.py` 裁剪并生成固定 300×300 三通道模型输入。
3. 图像发送至 `BOARD_PREDICT_URL`，返回 OK/NG 与缺陷信息。
4. 结果发送至 `vision-dashboard` 的 `/api/device/ingest`，由 SQLite 持久化并通过 WebSocket 更新页面。
5. `circle-camera/main.py` 根据 OK/NG 调用 `pose_runner/run_pose_sequence.py`，控制五轴机械臂与气泵完成左右分拣。
6. `voice-dashboard-assistant` 读取同一数据库，通过 DeepSeek 回答生产与质量问题。

## 关键目录与入口

- `run_all.sh`：生产模式统一启动入口，会加载 `site_config.sh` 并执行硬件预检。
- `run_exclude_robotarm.sh`：无机械臂调试入口；复用 `run_all.sh` 启动推理、看板、相机和其他非机械臂组件，并强制禁止舵机检查、启动定位及检测结果触发的分拣动作。
- `stop_all.sh`：停止整套生产服务。
- `site_config.sh`：网络、相机、推理、机械臂、气泵和语音参数；当前受 Git 跟踪。
- `vision-dashboard/`：FastAPI 看板、SQLite 存储、WebSocket 与静态页面。
- `circle-camera/`：相机取流、圆检测、C5MB 推理和分拣触发。
- `start_servo_dashboard.sh`：8088 机械臂与气泵现场调试入口。
- `servo_dashboard/`：四组姿态参数和手动动作调试页面。
- `pose_runner/`：Preparation、Forward、Left、Right 动作序列。
- `arm_control/`、`Arm_Lib/`：五个有效舵机的 I2C 控制与反馈校验。
- `pump_control/`：USB 串口继电器识别和气泵开关控制。
- `tests/`：硬件模拟和软件测试。

## 安装与运行

目标部署目录通常为 `/home/pi/raspberry`。

```bash
cd ~/raspberry
chmod +x install_all_on_pi.sh
./install_all_on_pi.sh
./run_all.sh
```

机械臂故障期间，只调试相机、板端推理、可视化页面及其他非机械臂组件：

```bash
cd ~/raspberry
chmod +x run_exclude_robotarm.sh
./run_exclude_robotarm.sh
```

该入口仍会检查海康相机和气泵 USB 设备，但不会访问机械臂 I2C，也不会执行任何机械臂或随分拣动作触发的气泵控制。停止方式仍为 `./stop_all.sh`。

机械臂与气泵调试：

```bash
cd ~/raspberry
./start_servo_dashboard.sh
```

调试页面默认地址为 `http://树莓派IP:8088`，日志位于 `servo_dashboard/data/server.log`。

停止生产服务：

```bash
cd ~/raspberry
./stop_all.sh
```

软件测试（使用模拟硬件，不应驱动真实机械臂或气泵）：

```bash
python -m unittest discover -s tests -v
```

## 当前配置与注意事项

- `PI_LAN_IP` 是历史兼容字段；启动时 `site_config.sh`、`run_all.sh` 和看板启动器现在实时读取 `eth0`（可由 `WIRED_INTERFACE` 覆盖）的当前全局 IPv4 地址作为页面提示地址。C5MB 地址仍由 `C5MB_IP` 配置，当前为 `172.16.68.110`。
- 当前海康相机序列号为 `DA3387962`。
- `DEEPSEEK_API_KEY` 已在现场配置文件中设置为本机未提交值；不要把真实 Key 内容复制到文档、日志或 Git 提交中。
- `VOICE_WAKE_ENABLED` 当前为 `0`。
- `BOARD_SCORE_THRESH` 当前默认 `0.2`，正常类和缺陷类候选均需达到该阈值才参与最终类别判定。
- `continuous_capture_cool_time` 当前默认 `2.0` 秒，由 `site_config.sh` 配置并经 `circle-camera/run_circle_camera.sh` 传入 `circle-camera/main.py`；它限制一次成功触发拍照/推理后到下一次触发之间的最短时间。
- `PUMP_SERIAL_PORT` 默认 `auto`，默认气泵 USB 身份为 VID `1a86`、PID `5523`。
- 仓库目前跟踪 `.venv`、日志、缓存和部分运行产物，仓库较臃肿；用户已明确暂不处理。

## 2026-08-20：`run_all.sh` 启动后的相机链路负载分析

### 结论

当前漏检风险不是单纯由 `run_all.sh` 多启动了一个服务造成，而是相机进程内的采集、全分辨率图像增强、圆检测和实时 JPEG 推流叠加竞争 CPU 与内存带宽；当单次圆检测耗时超过调度间隔时，现有实现会主动跳过中间待检测帧。`vision-dashboard` 本身通常不是首要瓶颈，语音唤醒当前关闭，不是当前负载来源。

本次只能基于仓库代码和 2026-08-16 的历史日志做静态分析，没有连接正在运行的树莓派，因此不能把问题直接定性为某个 CPU 百分比、内存不足或硬件丢帧。需要先按下面的现场命令补齐最新实测数据。

### 负载来源及优先级

1. **最高优先级：海康相机先采满幅，再由树莓派缩小。** `hikrobot_camera.py` 强制使用完整传感器 ROI；历史日志显示每帧从 `3072x2048` 转为 Mono8，再缩放/补边到 `1280x720`。取流函数当前每帧重新分配约 6 MiB 的 SDK 转换缓冲区，随后还有 NumPy `.copy()` 和 `cv2.resize()`。按 `18 fps` 计算，仅完整 Mono8 帧数据就超过 108 MiB/s，尚未计入额外复制、缩放和 SDK 内部开销。
2. **最高优先级：`DETECTION_WIDTH=384` 没有覆盖最昂贵的预处理。** `detector.py` 先在 `1280x720` 图像上执行中值滤波、双边滤波、CLAHE、对比度调整和锐化，之后才缩小到 `384px` 宽运行 Canny、Hough 和五套轮廓掩码。因此当前 384 宽配置主要降低后半段检测量，并未降低全分辨率增强成本。
3. **高优先级：忙时跳过检测帧是当前调度的预期行为。** 相机读取线程只保存最新帧；检测线程只有一个。当上一次检测未完成时，`_maybe_submit_detection()` 直接返回，不排队中间帧。这样可以避免延迟无限累积，但实际检测帧率会低于配置的 `8 fps`，快速经过画面的圆可能恰好完全落在被跳过的帧中。
4. **中优先级：实时预览仍持续消耗 CPU。** 当前以 `15 fps` 把 `1280x720` 帧缩放到最多 `576x324`、JPEG 编码后通过本机 HTTP 发给看板。发送线程只保留最新帧，不会无限积压，这是正确的；但缩放和 JPEG 编码会与圆检测中的 OpenCV 运算并行竞争核心。看板每帧更新内存状态，默认每 2 秒才落一次实时图到磁盘，因此看板磁盘写入不是首要嫌疑。
5. **中优先级：OpenCV 并行度可能造成重叠抢核。** `OPENCV_THREADS=2` 是进程全局设置；圆检测线程和实时推流线程可以同时进入 OpenCV。两者重叠时可能占用多个核心并增加内存带宽压力。将其固定为 1 是否更好必须现场 A/B，因为单次检测也可能因此变慢。
6. **较低优先级：触发后的推理、入库和机械臂动作。** 这些工作已放在独立的单消费者线程中，平时不持续占用 CPU；但触发瞬间会增加 JPEG 编码、HTTP、SQLite/图片写盘和子进程启动开销，可能放大当时的延迟。动作队列已限制为 1，不会无限堆积。

### 历史日志能证明的范围

- 2026-08-16 日志中，相机配置为 `18 fps`，从 `20:02:49` 的 `frame=5` 到 `20:04:16` 的 `frame=1372`，主循环平均处理约 `15.71 fps`，比请求值低约 `12.7%`。
- 该日志来自当前性能优化之前的版本，当时实时推流也是 `18 fps`；它只能说明当时端到端取帧吞吐未达到请求值，不能证明 12.7% 全是海康相机硬件丢帧。
- 当前日志没有记录海康帧号、采集线程 FPS、主循环跳过的 sequence 数、圆检测耗时、检测忙跳过次数和实时推流实际发送 FPS，无法区分相机/USB 丢帧、主循环只取最新帧和检测线程主动跳帧。

### 树莓派现场基线采样

先保持现有参数运行 60 秒，并确保这段时间有圆盘经过：

```bash
cd ~/raspberry
./run_all.sh

# 另开终端。pidstat/iostat 来自 sysstat；没有时先只执行 mpstat、vmstat 和 ps。
pidstat -dur -p "$(pgrep -d, -f 'circle-camera/main.py|uvicorn backend.app:app')" 1 60
mpstat -P ALL 1 60
vmstat 1 60
iostat -xz 1 60
ps -eLo pid,tid,psr,pcpu,pmem,comm,args --sort=-pcpu | head -40
vcgencmd measure_temp
vcgencmd get_throttled
```

同时保留以下输出：

```bash
tail -n 300 ~/raspberry/logs/circle-camera.log
tail -n 300 ~/raspberry/circle-camera/logs/runtime_status.log
free -h
```

判断重点：是否所有核心长期接近满载；`circle-camera/main.py` 与 `uvicorn` 各占多少 CPU；`vmstat` 的 `si/so` 是否非零；磁盘 `%util`/`await` 是否异常；`get_throttled` 是否为非零；经过圆盘时负载、检测间隔和漏检是否同步恶化。温度降频、电源欠压或 swap 活动会使纯软件优化结果不稳定，必须先排除。

### 建议的改进顺序

1. **先补可观测性，再改参数。** 在相机读取层记录 SDK 帧号、采集成功/超时数和实际采集 FPS；在主循环记录 sequence 跳号；在检测层记录提交数、忙跳过数、完成数、平均/P95 检测耗时和实际检测 FPS；在实时预览层记录覆盖丢弃数与实际发送 FPS。目标是确认漏的是“采集帧”还是“检测机会”。
2. **先降低非关键预览负载。** 现场 A/B 将 `LIVE_PUSH_FPS` 从 `15` 临时降为 `8` 或 `10`，保持 `CAMERA_FPS=18`、`DETECTION_FPS=8` 不变。若漏检明显下降，说明 JPEG/HTTP 竞争是重要因素；页面流畅度下降但不会直接减少圆检测的目标帧率。
3. **拆分低分辨率检测与高分辨率触发图。** 应先缩小灰度图，再做用于圆定位的滤波、CLAHE、Hough 和轮廓检测；只有圆进入触发区时，才在对应的原始高分辨率帧上做高质量增强和 300x300 推理裁剪。这样能保留板端缺陷推理细节，同时把持续发生的圆检测计算量降到真正的 `384px` 级别。该改动需要用现场样图回归圆心坐标、半径、阈值缩放和漏检率。
4. **优先在相机端降采集像素量。** 查询该海康型号是否支持 2x2 Binning、Decimation 或保持视野的较小输出；能在相机端从 `3072x2048` 降采样，就不要每帧在树莓派上转换完整 6 MP 图像。直接缩小 ROI 会裁掉视野，只有现场确认圆盘路径都在 ROI 内才能使用。
5. **复用海康转换缓冲区。** 根据最大 Payload/输出尺寸预分配 SDK 解码和像素转换缓冲区，避免每帧创建 ctypes 数组；再用双缓冲或明确所有权的帧池减少不必要的全帧 `.copy()`。这是内存带宽和分配抖动优化，收益需用采集 FPS 与 CPU 实测确认。
6. **对 `OPENCV_THREADS=1/2` 做 A/B。** 每组至少运行 2 分钟，比较检测 P95 耗时、实际检测 FPS、总 CPU 和漏检率。不要只看平均 CPU：线程数降为 1 后若单次检测超过 125 ms，反而会让 `8 fps` 调度跳过更多帧。
7. **完成前述优化后再提高检测覆盖率。** 目标应是单次检测 P95 小于 125 ms，并让实际检测 FPS 接近配置的 `8 fps`。若圆盘在画面中的可见时间仍短，可在 CPU 有余量后提高 `DETECTION_FPS`，或增加一个每帧运行的廉价运动/边缘门控，仅在候选窗口调用完整圆验证；不建议先降低 `CAMERA_FPS`，因为这会直接减少快速目标的可见帧数。

### 建议验收指标

- 连续运行至少 10 分钟无温度降频、欠压和 swap in/out。
- 实际采集 FPS 稳定接近 `18 fps`，并能分别报告 SDK 丢帧与应用 sequence 跳帧。
- 圆检测 P95 耗时低于 `125 ms`，实际检测 FPS 接近 `8 fps`，忙跳过率有明确记录。
- 同一批、同一速度的圆盘至少重复 100 次，对比优化前后的圆检出率；不能只以页面是否流畅作为结论。
- 页面预览降帧不应影响触发图质量、C5MB 的 300x300 输入、OK/NG 后处理或机械臂动作时序。

## 验证记录

- 2026-08-18：在 Windows Python 3.13.12 下执行 `python -m unittest discover -s tests -v`，68 项测试全部通过。
- 上述测试使用 mock/dry-run 路径，没有对真实机械臂、气泵或相机发送命令。
- 2026-08-18：历史日志显示看板和相机实时帧接口曾正常返回 HTTP 200；曾发生旧相机序列号 `DB1164307` 与现场设备 `DA3387962` 不匹配，当前配置已改为后者。
- 2026-08-18：历史语音日志显示因未配置 `DEEPSEEK_API_KEY` 而未启动。
- 2026-08-19：后处理定向测试 10 项全部通过，覆盖正常胜出、缺陷胜出、同分缺陷优先、`0.2` 阈值边界、低分过滤和显式 NG 兼容。
- 2026-08-19：在 Windows Python 3.13.12 下执行完整 `python -m unittest discover -s tests -v`，扩充后的 75 项测试全部通过；使用 mock/dry-run 路径，未操作现场硬件。
- 2026-08-19：对 `run_exclude_robotarm.sh` 完成静态链路核对，确认禁用标志依次覆盖 `site_config.sh` 的舵机检查、`run_all.sh` 的 Preparation 动作和 `circle-camera/main.py` 的运行期分拣入口；`git diff --check` 通过。当前 Windows 的 `bash` 指向没有可用发行版的 WSL，未能执行 `bash -n`，且未在现场启动相机、推理服务或任何硬件。
- 2026-08-20：用户要求启动输出使用当前有线网卡地址。根因是 `site_config.sh` 固定导出旧 `PI_LAN_IP`，`run_all.sh` 又只在地址为空时保留默认值。对应修改：新增 `detect_wired_ipv4`，从 `eth0`（或 `WIRED_INTERFACE`）读取当前 IPv4；`DASHBOARD_URL` 和 `DASHBOARD_HOST_IP` 改为启动时动态生成；看板启动器同步使用同一来源。无可用有线 IPv4 时回退 `127.0.0.1` 并输出提示。未修改 `DASHBOARD_INGEST_URL`（仍为本机回环）或 `BOARD_PREDICT_URL`（仍指向 C5MB）。
- 2026-08-20：完成 `run_all.sh`、相机 SDK 取流、圆检测、实时预览上传和看板入库链路的静态负载审计。解析 2026-08-16 历史运行日志得到旧版本主循环约 `15.71 fps`（请求 `18 fps`）；由于未连接树莓派且现有日志缺少分层丢帧与检测耗时指标，本轮没有声称获得当前 CPU/内存/温度实测值。仅更新 `HANDOFF.md`，未修改生产代码或现场参数。
- 2026-08-21：将连续拍照冷却时间从 `main.py` 的固定默认值解耦为 `site_config.sh` 的 `continuous_capture_cool_time`。启动脚本通过 `--continuous-capture-cool-time` 传入，`main.py` 内部统一使用 `args.continuous_capture_cool_time`；保留旧 `--trigger-cooldown-seconds` 作为兼容别名。当前配置为 `2.0` 秒，修改后需重启 `./run_all.sh`。

### 2026-08-20：调整可视化页面文案和缺陷类别展示

- 用户决策：删除核心指标右上角副标题“让评委第一眼就看到系统确实在稳定工作”；页面缺陷类别只显示“脏污 / 折皱 / 针孔 / 擦伤”。
- 对应修改：删除 `vision-dashboard/static/index.html` 核心指标副标题内容；在 `vision-dashboard/static/js/app.js` 的页面计算属性中过滤“划痕”；将页面脚本查询版本更新为 `20260820a`，避免浏览器继续使用旧缓存。未修改后端 `CANONICAL_DEFECT_LABELS`、模型类别映射或历史数据，因此推理接入仍兼容五类标准标签。
- 验证方式：修改后检查页面源码和前端计算属性，确认目标文案不存在、展示列表过滤“划痕”；需同步到树莓派并刷新浏览器验证实际页面。

## 用户决策与修改记录

### 2026-08-18：配置文件安全声明

- 用户决策：只修正 `site_config.sh` 已被 `.gitignore` 忽略这一错误声明。
- 用户决策：暂不清理 `.venv`、日志、缓存或其他导致仓库臃肿的非致命问题。
- 对应修改：更新根 `README.md` 和 `site_config.sh` 文件头，明确 `site_config.sh` 当前受 Git 跟踪，禁止提交真实 DeepSeek Key、口令或其他敏感信息；现场临时填写只能保留为未提交修改，并建议提交前检查差异。由于脚本直接设置 Key，文档没有声称预先设置的同名环境变量可以覆盖它。
- 未做事项：没有改变 `site_config.sh` 的 Git 跟踪状态，没有新增根 `.gitignore`，没有删除或取消跟踪任何环境和运行产物。

### 2026-08-18：建立持续交接记录

- 用户决策：在项目根目录维护 `HANDOFF.md`，记录每次决策和对应修改，方便后续 AI 快速上手。
- 对应修改：创建本文件；后续工程修改必须同步补充“用户决策与修改记录”、验证结果、已知问题和下一步建议。

### 2026-08-18：8088 调试程序梳理

- 用户决策：仅分析 `start_servo_dashboard.sh` 对机械臂、气泵、VID/PID 自动识别和失败保护的实现，不修改相关控制代码。
- 对应修改：未修改调试程序源码；分析结论由本次对话交付。

### 2026-08-18：补充 DeepSeek Key

- 用户说明：`DEEPSEEK_API_KEY` 为空是此前忘记填写，不是希望禁用 DeepSeek。
- 用户决策：将用户提供的真实 Key 写入 `site_config.sh`，供现场语音和网页 AI 使用。
- 对应修改：已写入 Key，但仅作为本机未提交配置保留；本文件不记录 Key 原文，后续提交必须排除 `site_config.sh` 中的敏感差异。

### 2026-08-19：修正正常类后处理判定

- 用户确认：训练集清单、XML 类别、类别顺序、正常框标注、现场输入分布、类别平衡以及板卡新模型部署不存在已列出的风险，本轮聚焦树莓派后处理。
- 用户决策：正常类与缺陷类先统一应用置信度阈值，再进行全局最高分判定；默认阈值为 `0.2`，正常与缺陷完全同分时缺陷优先。
- 对应修改：`circle-camera/dashboard_transport.py` 和 `vision-dashboard/backend/storage.py` 均先保留正常候选参与全局决策。正常获胜输出 `OK`、空检测列表和零缺陷；缺陷获胜只保留达到阈值的获胜缺陷类别。存在原始候选但全部低于阈值时输出 `OK`，没有候选列表时继续兼容明确传入的 `OK/NG`。
- 配置位置：根目录 `site_config.sh` 的 `BOARD_SCORE_THRESH="0.2"`；`run_all.sh`、相机独立启动和看板后端的无配置默认值均同步为 `0.2`。
- 说明：该逻辑是“阈值过滤 + 全局类别决策 + 获胜同类框保留”，不是根据边界框 IoU 执行的 NMS。

### 2026-08-19：新增无机械臂调试入口

- 用户决策：机械臂故障期间需要继续运行并调试机械臂以外的推理和可视化流程；新增根目录脚本 `run_exclude_robotarm.sh`，不修改其他业务代码。
- 对应修改：新脚本强制导出 `DISABLE_ARM_ACTION_FLAG="--disable-arm-action"` 后复用 `run_all.sh`。由现有保护逻辑跳过 S1-S5 ID/PING 检查、启动时 Preparation 移动，以及圆检测结果触发的机械臂与气泵分拣序列；相机预检、气泵 USB 识别、看板、相机采集、板端推理和已启用的语音助手保持原流程。
- 运行方式：首次同步到树莓派后执行 `chmod +x run_exclude_robotarm.sh`，之后使用 `./run_exclude_robotarm.sh` 启动，使用 `./stop_all.sh` 停止。
- 约束：该模式不会单独驱动气泵；若气泵 USB 设备缺失或权限不正确，现有非机械臂硬件预检仍会阻止启动。

## 已知问题

- 新后处理尚需在树莓派现场用同一张正常图复核：板卡原始结果中 `zheng_chang` 全局最高时，树莓派最终结果必须为 `OK`，页面不显示正常框。
- **高优先级：8088 调试页前后端 API 版本不一致。** `start_servo_dashboard.sh` 和 `servo_dashboard/app.py` 使用 `servo-dashboard-five-axis-pump-v4`，但 `servo_dashboard/static/app.js` 仍期待 `servo-dashboard-five-axis-pump-v3`。页面加载 `/api/state` 时会报告版本不匹配；当前前端仍会绑定操作按钮，因此在修复并现场复核前，不应依赖页面显示状态或进行真实动作调试。本轮用户要求只梳理、不修改控制代码，所以未修复。
- `site_config.sh` 是受跟踪文件，并已包含本机真实 Key 的未提交修改；提交时必须排除该敏感差异，目前以文档警告规避。
- `.venv`、`.pyc`、日志和运行图片等大量文件受 Git 跟踪，增加仓库体积和无效差异；按用户决定暂缓处理。
- 根目录没有统一 `.gitignore`，仅 `vision-dashboard/` 下存在局部规则；按用户决定暂缓处理。
- 调试页面通过 HTTP 暴露在 `0.0.0.0:8088`，控制接口没有鉴权；应只在可信局域网使用。
- 机械臂与气泵的真实联调仍依赖树莓派 I2C、舵机反馈、USB 串口权限和现场机构安全空间，Windows 测试不能替代现场验证。
- `run_exclude_robotarm.sh` 仅绕过机械臂相关控制，未改变生产入口 `run_all.sh`；恢复机械臂后仍应先完成 I2C/舵机检查，再使用生产入口。
- 页面提示地址依赖 `eth0` 当前存在全局 IPv4；如果通过无线访问，应使用 `ip -4 -o addr show dev wlan0` 查到的无线地址，或临时设置 `WIRED_INTERFACE=wlan0` 后启动。
- **高优先级：相机链路缺少分层负载和丢帧指标。** 当前只能看到主循环累计 frame，无法区分 SDK 取流丢帧、只保留最新帧造成的 sequence 跳帧和检测线程忙时主动跳过。没有这些指标前，调低分辨率或线程数只能算经验性试验。
- **高优先级：圆检测缩放发生在全分辨率增强之后。** `DETECTION_WIDTH=384` 尚未降低中值/双边滤波、CLAHE 和锐化的全分辨率成本；这是当前最值得优先改造的软件路径。
- 海康取流使用完整 `3072x2048` 传感器画面，再在树莓派转 Mono8 并缩放到 `1280x720`，每帧还有动态转换缓冲区分配与复制。现场应先确认相机端 Binning/Decimation 能否在保持视野的条件下降采样。
- `continuous_capture_cool_time` 只控制“成功进入触发队列后的下一次触发间隔”，不会提高圆检测帧率，也不会改变机械臂启动延迟；若仍漏检，还需分别检查 `DETECTION_FPS`、检测忙跳过和相机/CPU 负载。

## 建议的后续步骤

1. 先按“树莓派现场基线采样”采集 60 秒 CPU、线程、内存、I/O、温度和降频数据，并补充相机/检测分层指标；这是定位漏帧来源的第一优先级。
2. 在其他参数不变的情况下，仅将 `LIVE_PUSH_FPS` 从 `15` A/B 为 `10`、`8`，用同一批至少 100 个圆盘比较实际检测率和检测耗时。
3. 将圆定位改为先缩放后增强，触发后再从对应原始帧生成高质量推理裁剪；完成样图与现场坐标回归后再部署。
4. 调研海康相机端 Binning/Decimation，并复用 SDK 转换缓冲区，减少完整 6 MP 帧的 CPU 与内存带宽开销。
5. 将修改同步到树莓派后重启整套程序，用同一张正常图对照板卡原始 JSON、树莓派最终 JSON 和页面结果。
6. 先统一 8088 调试页前后端 API 版本并补充覆盖该一致性的测试，修复前不要进行真实页面动作调试。
7. 修复后在树莓派现场执行 `./start_servo_dashboard.sh`，确认五个舵机 ID 均返回 `218 (0xDA)`，并核对气泵枚举结果。
8. 先在机械臂周围清场，再依次测试 Preparation、Forward、Left、Right，最后测试完整 Left/Right 气泵流程。
9. 启用 AI 时确保真实 DeepSeek Key 始终留在未提交差异中。
10. 用户将来同意后，再单独规划仓库瘦身和忽略规则，不与功能修改混做。

### 2026-08-20：低 CPU 手动加载近 12 小时趋势

- 用户决策：近 12 小时检测趋势只在用户点击标题右侧“显示趋势”按钮后读取和渲染；后续点击“刷新趋势”才显示新的检测记录，入库和 WebSocket 实时结果均不得自动触发趋势查询。
- 根因：圆检测触发链路此前把 `20260820_191230_932407` 这类文件名时间写入 `inspection_records.ts`。普通历史记录和总数不需要解析该字段，仍能显示；趋势 SQL 使用 `datetime(ts)` 过滤不可解析时间，因此这些记录被全部排除。代码不存在“必须累计满 12 小时才显示”的条件。
- 对应修改：`circle-camera/main.py` 现在将入库时间生成 UTC ISO 8601，文件/帧 ID 继续使用紧凑时间。`vision-dashboard/backend/storage.py` 新增 `event_epoch_ms` 和索引；启动时从旧紧凑 `ts` 或 `circle-...` 帧 ID 按树莓派本地时区回填已知旧记录，未知异常时间不改动。趋势统计改为索引范围查询最新记录向前 12 小时，不再对整张 `inspection_records` 表执行 `datetime(ts)`。
- 对应修改：新增 `GET /api/history/trend`；删除每次检测入库后的自动统计调度。历史视图新增按钮、加载中禁用状态、首次打开提示、单点显示及无动画 ECharts 渲染；数据只有在手动请求成功后才显示。静态 CSS/JS 缓存版本分别更新为 `20260820d` 和 `20260820b`。
- 验证：Windows Python 3.13.12 下 `test_latency_pipeline.py` 20 项和 `test_circle_camera_action.py` 6 项均通过；包含旧时间回填、趋势范围索引、有效/无效时间隔离和 UTC 帧标识测试。`py_compile`、`node --check vision-dashboard/static/js/app.js` 与 `git diff --check` 通过。上述验证未连接真实树莓派或硬件；部署后第一次启动会执行旧记录回填，应在历史页点击“显示趋势”确认实际数据库结果。

### 2026-08-20：全周期十等分趋势与图片级缺陷排行

- 用户决策：趋势范围改为数据库全部有效 `event_epoch_ms` 记录的最早至最新时间，按该跨度固定等分为 10 个时间桶；折线显示每桶总检测图片数，红色柱显示同桶不良图片数，二者共用同一个从 0 开始的整数 Y 轴。趋势仍只在用户点击“显示趋势/刷新趋势”时查询，入库和 WebSocket 不自动刷新。
- 边界口径：前 9 个桶采用左闭右开，最后一个桶包含最新记录；空桶补 0。没有有效时间记录时返回空数组；所有有效记录时间相同时返回一个数据点。趋势只查询数据库时间和计数，不读取或检查图片文件，无法恢复时间的异常旧记录不参与趋势。
- 对应修改：`vision-dashboard/backend/storage.py` 使用 `idx_inspection_records_event_epoch` 取得全库时间边界，并通过 `bucket_index` 聚合后补齐 10 桶。`history.trend` 保留原计数字段，并新增 `bucket_index`、`bucket_start_epoch_ms`、`bucket_end_epoch_ms`。历史页标题改为“全周期检测趋势”；ECharts 关闭动画和面积填充，红色不良柱设为低层，青色总数折线及圆点设为高层，提示框显示每桶完整起止时间。
- 缺陷统计口径：SQL 明确先对 `(record_id, label)` 去重再计数；实时增量通过 `unique_detection_labels()` 对当前图片的标签集合去重。同一张图片中的 5 个针孔框只为针孔排行增加 1，初始加载、WebSocket 增量、概览分布和历史排行使用同一图片级口径。
- 现场只读基准：树莓派数据库当时共有 182 条有效时间记录，时间范围为本地 `2026-08-20 20:14:07` 至 `20:39:14`。针孔为 492 个框、106 张图片；擦伤为 167 个框、35 张图片；折皱为 25 个框、14 张图片；脏污为 39 个框、13 张图片。页面排行应显示图片数 `106/35/14/13`，不能显示框数。
- 验证：Windows Python 3.13.12 下完整 `unittest discover -s tests` 共 81 项全部通过；新增覆盖 10 桶边界、空桶、异常时间、单时间点、框/图片计数和重载一致性。`py_compile`、`node --check`、`git diff --check` 均通过。使用 `D:\CodexCache\raspberry_trend-visual_2026-08-20_225311` 中的模拟接口，通过无头 Chrome 完成 1440px 桌面和 500px 窄屏渲染检查，柱线层级、10 个标签、按钮和排行均正常。尚未将本轮修改部署至真实树莓派。

### 2026-08-21：趋势按钮 404 部署遗漏修复

- 现场现象：历史页点击“显示趋势”后按钮仍保持原文且图表为空；树莓派本机 `curl http://127.0.0.1:8000/api/history/trend` 返回 `404 Not Found`，Uvicorn 日志也记录该路由 404，因此不是十等分查询过大或 ECharts 卡死。
- 根因：树莓派上的 `storage.py`、`index.html`、`app.js` 与本地修改版 SHA-256 完全一致，但 `/home/pi/raspberry/vision-dashboard/backend/app.py` 仍是旧版，未注册 `GET /api/history/trend`。远端旧文件与本地目标文件的差异仅为计划内的趋势路由和移除自动统计调度，没有远端独有改动。
- 处理：从 `C:\Users\huddd\Desktop\raspberry\vision-dashboard\backend\app.py` 上传到对应树莓派路径，并只重启 Uvicorn 看板进程；圆检测进程保持运行，不调用 `run_all.sh`，避免机械臂重新执行 Preparation。
- 后续核对：接口修复后远端 `index.html` 和 `app.js` 又被检出停留在上一版，导致页面仍显示“近 12 小时检测趋势”，且缺少最终的时间段提示、整数 Y 轴和折线高层级配置。对比未发现远端独有修改，同步本地目标版两个前端文件，静态文件同步不需要重启圆检测或机械臂。
- 现场验证：`GET /api/history/trend` 返回 HTTP 200、10 个时间桶，合计 234 条有效记录和 212 条不良记录；树莓派本机查询约 4 ms，电脑经局域网访问约 298 ms。无头 Chrome 实际进入历史页并点击按钮后，按钮由“显示趋势”变为“刷新趋势”，ECharts 生成 `669x360` 非空画布；证明图表数据查询、按钮事件和绘图链路均已打通。
- ECharts 稳定性防护：未手动读取趋势时不创建空的 `bar/line` 系列，仅显示加载提示；成功获取数据后再创建柱线系列。浏览器隔离测试确认 `Cannot read properties of undefined (reading 'type')` 来自右侧“缺陷类型排行”；仅改为整配置替换仍会复现，最终根因是 Vue 把保存在响应式 `data` 中的 ECharts 类实例包装成 Proxy，破坏其内部状态访问。三个图表实例现均使用 Vue `markRaw()` 保留原始对象，右侧排行同时保留 `setOption(option, true)`。JS 缓存版本更新为 `20260821c`。
- 最终现场验收：部署期间曾出现外部启停流程将 `storage.py` 回退到旧的 12 小时聚合版，导致临时只返回 3 个自然小时桶；逐行比对无远端独有修改后重新同步本地目标版，并仅重启看板 Uvicorn。稳定观察 10 秒后仍只有 PID `4055` 监听 8000；真实接口返回 10 桶、267 条有效记录和 241 条不良记录。无头 Chrome 实际点击后画布为 `669x360`，红柱与总数折线各 10 点，Y 轴从 0 开始且只用整数分度，折线 `z=3` 高于柱状 `z=1`，浏览器控制台 0 异常。本地 81 项 Python 测试、`node --check` 和 `git diff --check` 全部通过。

### 2026-08-21：文件精简候选审计（未删除）

- 用户决策：先列出大小、用途、CPU 影响和删除风险，由用户明确选择后再删除；本轮不删任何候选文件。
- 桌面工程共 `6536` 个文件、`487.37 MiB`；`.venv` 为 `347.18 MiB/5680` 个文件，`.git` 为 `136.83 MiB/690` 个文件，二者占总体积约 `99.3%`。删除 `.venv` 会使树莓派依赖和启动脚本失效；删除 `.git` 会丢失版本历史，均为高风险且不建议。
- 低风险候选：工程级 `__pycache__/*.pyc` 共 `1.21 MiB/69` 个，4 个 `.DS_Store` 共 `0.03 MiB`，`circle-camera/artifacts/live_annotated.jpg` 为 `0.12 MiB`。都不降低稳态 CPU；删缓存只会让下次启动重新生成，删调试图会丢失当前样图。
- 有条件候选：根 `logs` 和 `circle-camera/logs` 合计约 `0.10 MiB`，删除不降 CPU 且会丢失排障证据；`tests` 为 `0.34 MiB/27` 个文件，不参与生产 CPU，但删除会丢失 81 项回归验证，不建议。`echarts.min.js` 为 `0.99 MiB`，是趋势和排行绘图核心，不能删除。
- CPU 只能按进程采样，不能归因到静态文件。生产运行快照中圆检测约 `58.6% CPU/147 MiB RSS`，看板约 `2.7% CPU/103 MiB RSS`；仅保留看板时约 `0.5% CPU/99 MiB RSS`。删除 `.venv`、缓存、日志或 Git 历史不会降低这些进程的稳态 CPU。

### 2026-08-21：机械臂 FIFO 执行审计

- 实际是两个独立的单消费者 FIFO。推理触发队列配置为 `8` 个等待位，因此最多是 `1` 个正在推理加 `8` 个等待；第 10 个触发会记录“推理队列过载”并拒绝。这不是机械臂动作队列的容量。
- 动作队列在代码中固定 `capacity=1`，最多只容纳 `1` 个正在计时/执行的动作和 `1` 个等待动作。第二张图的推理结果在第一个动作未完成时会进入唯一等待位；如果这时第三张图又完成推理，其结果已入库且页面会显示 OK/NG，但机械臂动作会被明确跳过，日志为“机械臂忙碌，跳过本次动作 | depth=1/1”。
- 每个动作的期限是自己的“原始检测时刻 + `ACTION_DELAY_SECONDS`”。第一个动作完成后，如果第二张的期限尚未到，动作线程只等剩余时间；如果期限已过，第二个动作立即执行，不会再额外等完整延时。动作线程在延时睡眠期间也算“正在处理”。
- 桌面工程 `site_config.sh` 的延时是 `5s`，但树莓派 `2026-08-21 10:22` 实际进程与日志使用 `3.3s`，说明现场配置或启动环境与桌面工程不一致。现场姿态参数的三段运动是 `400+800+800 ms`，气泵停留是 `0.1+0.1+0.3s`，再加每段 `0.05s` 稳定余量，理论动作主体约 `2.65s`，另有进程启动和硬件通信开销。
- 动作最长允许 `15s`；失败后在同一动作线程内同步执行“关泵并回 preparation”恢复，恢复最长又可占用 `15s`。恢复期间仍只有一个等待位，其他新动作会继续被跳过。

### 2026-08-21：Left/Right 后气泵偶发不释放的诊断（未改控制代码）

- 用户要求：本轮先排查并给出由用户在树莓派执行的采集命令，同时使用专业术语和大白话解释；不修改机械臂、气泵或串口控制代码。
- 内核证据：气泵 CH341/CH340 设备 `1a86:5523` 反复出现 `USB disconnect`、`failed to send control message: -19`和重新枚举，节点在 `ttyUSB2 -> ttyUSB1 -> ttyUSB2 -> ttyUSB1` 之间变化。`-19` 是 `ENODEV`，表示内核认为设备已不存在。这不是普通 CPU 调度抢占或 Python 串口写入被“打断一半”的典型表现，优先怀疑 USB 供电瞬降、机械臂运动牵拉/接触不良、电机或继电器电磁干扰、USB 集线器/线缆问题，或设备自身复位。`throttled=0x0` 只说明 SoC 未记录整机欠压/降频，不能排除某个 USB 端口的瞬态掉压或 EMI。
- 为什么现象显示在 Left/Right 之后：`run_pick_place_sequence()` 的顺序固定为“开泵 -> 到 Forward -> 到 Left/Right -> 停留 -> 发送关泵 -> 回 Preparation”。如果 USB 在前两段机械臂运动期间掉线，关泵命令是后续第一个使用该串口的操作，因此失败在 Left/Right 到位后才暴露；这不等于 Left/Right 分支漏写了关泵命令。
- 当前软件局限：`PumpController` 在动作开始时只解析并打开一次串口，中途重新枚举后原文件描述符已失效；关泵失败时没有关闭旧句柄、按 VID/PID 重新查找、等待 udev 重建节点或重试 OFF 命令。新枚举节点即使又由 `/dev/serial/by-id/...` 指向，旧的已打开句柄也不会自动连到新设备。
- 协议局限：当前 `A0 01 00 A1` 协议没有设备 ACK/状态回读；`write()==4` 加 `flush()` 只能证明主机串口栈接受了 4 字节，不能证明继电器已执行。如果在写入后紧接着掉线，软件甚至可能认为成功，而继电器仍保持吸取状态。
- 日志可观测性缺口：动作子进程使用 `capture_output=True`，但发生 `CalledProcessError` 时主进程只记录异常摘要，没有写出子进程已捕获的 stdout/stderr。因此当前 `circle-camera.log` 可能只显示动作失败，看不到底层 `SerialException`/`OSError`。
- 安全结论：软件重连和 OFF 重试只能缓解问题，不能在 USB 持续断开时保证释放。如果“通信失效时仍持续吸取”可能损坏机构或伤人，最终需要常开型断电释放回路、硬件看门狗或独立泄压/急停等硬件失效安全设计。
- 待采集：将内核 USB 日志与 `circle-camera.log` 的动作时间线对齐；记录 USB 拓扑、当前 by-id/by-path 指向、udev 属性、设备电源策略和串口占用者。再根据时间线决定是先处理供电/布线/EMI，还是同时增加串口重连、OFF 重试和完整子进程日志。
- 现场证据更新：`14:42:25` 开始 `forward-left`，`14:42:26.083448` 内核明确记录 `usb usb1-port2: disabled by hub (EMI?), re-enabling...`，紧接着 CH341 从 `ttyUSB0` 断开并在约 0.46 秒后重新枚举为 `ttyUSB1`，`14:42:28` 动作子进程以状态 1 失败，`14:42:30` 安全恢复成功。时间线已形成直接因果链，主因优先级为 USB EMI/物理链路不稳定，不是 CPU 调度打断串口字节。
- 掉线并非只发生在 Left/Right：同一次采集中 `14:39:55` 和 `14:42:18` 也发生断开/重枚举，其中 `14:42:18` 早于该次动作 7 秒。Left/Right 运动可能增大干扰或牵拉概率，而关泵命令位于该动作之后，所以现象集中在该阶段暴露。
- 电源策略：当前 CH341 的 `power/control=on`，因此可排除 USB autosuspend 作为这次掉线的直接原因。USB 描述符声明 `MxPwr=480mA`，接近 USB 2.0 单端口 500mA 上限；这是设备声明值而非实测值，但提高了局部 5V 供电裕量不足的嫌疑。`throttled=0x0` 仍不能排除 USB 支路瞬态掉压。
- 串口占用复核：再次检查时 PID `2858` 已退出，`/dev/ttyUSB*` 没有占用者；当时只看到生产圆检测 PID `3626` 和一个 `run_pose_sequence.py --recover` 恢复进程 PID `3742`，8088 PID 文件为空。因此目前没有证据证明生产故障由两个常驻程序同时争用串口造成；即使曾有进程竞争，也不能解释内核明确的 `disabled by hub (EMI?)` 和 USB 重枚举。
- 8088 调试日志复核：Right 序列在目标位明确执行了 `PUMP off: A0 01 00 A1` 两次，中间间隔 `0.100s`，随后才移动回 Preparation。该次 `/api/sequence` 返回 500 的直接原因是回程时的 `Arm_serial_servo_write6 I2C error`，不是该日志中的关泵调用失败。气泵 USB/EMI 掉线与机械臂 I2C 回程失败是两个独立故障，不能用后者否定前者。
- 安全恢复含义：生产动作失败后启动的独立恢复进程能够完成恢复，说明 CH341 重新枚举后，新进程可以通过稳定路径重新打开当前节点并补发 OFF；原动作进程中已经失效的旧串口文件描述符不会自动绑定到新节点。
- 版本一致性风险：树莓派现场 `server.log` 包含“两次目标位 OFF”和 `PUMP shutdown off skipped: two target off commands sent`，但桌面工程当前 `pose_runner/run_pose_sequence.py` 的已知实现与该日志不完全一致。继续设计软件修复前必须先核对远端 `pose_runner/run_pose_sequence.py`、`pump_control/serial_pump.py` 和 `servo_dashboard/app.py` 的哈希及相关代码片段，避免以桌面旧版本推断现场行为。

### 2026-08-21：三任务动作 FIFO、气泵反馈重连与只读监视

- 用户决策：机械臂动作 FIFO 按“总在途量”扩容到 `3`，即最多 `1` 个执行中和 `2` 个等待；第 4 个结果完成推理和入库，但动作明确拒绝。现场来料间隔小于 2 秒，分拣工位可以挡停或停止传送带；容量 3 只吸收短时突发，不作为长期吞吐不足的替代方案。
- 动作调度：新增 `ACTION_QUEUE_CAPACITY=3` 和 `--action-queue-capacity`。`BoundedFifoWorker` 使用加锁的 `in_flight` 计数执行原子容量判断，动作继续由单消费者严格 FIFO 串行执行。每个任务分配运行期 `A001` 形式的 `action_id`，日志新增 `[QUEUE] IN/OUT/DONE/FAIL/DROP`，包含完整 `frame_id`、总在途量、等待数、排队时间、目标时刻滞后和动作耗时。任务仍按自己的原始触发时刻加 `ACTION_DELAY_SECONDS` 计算期限，出队时已过期则立即执行。
- 用户提供并确认的第 1 路继电器协议：开并反馈发送原始字节 `A0 01 03 A4`，期望 `A0 01 01 A2`；关并反馈发送 `A0 01 02 A3`，期望 `A0 01 00 A1`；查询发送 `A0 01 05 A6`，接受 ON/OFF 状态帧。第四字节按前三字节之和的低 8 位校验；发送的是四个二进制字节，不是 ASCII 十六进制字符串。
- 气泵状态确认：`PumpController` 现在为每次 STARTUP_OFF、ON、OFF 操作清理旧输入、发送反馈命令并读取完整四字节状态帧；校验帧头 `A0`、通道 `01`、状态 `00/01` 和校验字节。默认反馈超时 `0.5s`。脏字节可跳过，分段响应可拼接；无反馈、错误状态、错误校验、串口异常和 USB 消失均视为失败。
- 气泵重连：首次失败后最多执行 `2` 次重连。每次关闭旧句柄，按 VID/PID `1a86:5523` 等待唯一设备重新枚举（默认每次最长 `2.0s`），打开新节点后先查询；查询已经达到目标状态则成功，否则重发带反馈命令。配置项为 `PUMP_FEEDBACK_TIMEOUT_SECONDS`、`PUMP_RECONNECT_ATTEMPTS` 和 `PUMP_RECONNECT_TIMEOUT_SECONDS`。
- 动作超时：生产外层的动态动作超时预算现在除三段运动、停留和进程开销外，还包含 STARTUP_OFF、ON、目标位 OFF 三次状态操作各自的反馈与两次重连最坏耗时，避免默认 `15s` 在保护流程完成前杀掉动作子进程。
- 失败策略：STARTUP_OFF 或 ON 最终无法确认时以退出码 `21` 阻止机械臂进入 Forward。目标位 OFF 最终无法确认时，按用户决定完成释放等待并返回 Preparation，然后以退出码 `20` 标记动作失败；生产外层识别该退出码后不再启动第二轮恢复，保证不会突破“首次 + 两次重连”的上限。下一动作会重新从 STARTUP_OFF 确认开始。已确认 OFF 时上下文关闭只关闭串口句柄，不重复发送 shutdown OFF。
- 实时日志：生产动作子进程不再 `capture_output`，机械臂步骤、气泵发送/接收、重连和底层 I2C/串口错误会实时继承到 `logs/circle-camera.log`，不再只留下 `CalledProcessError` 摘要。
- 新增根目录 `monitor.sh`：该脚本只读取 `logs/circle-camera.log`、8088 `server.log`、进程状态、udev 节点和内核 USB 事件，不打开串口、不访问 I2C、不获取硬件锁。终端精简显示 `[QUEUE]`、`[ARM]`、`[PUMP]`、`[USB]`、`[ALARM]`、`[PROC]`；PID/串口节点只在变化时打印。`Ctrl+C` 只终止监视脚本及其 `tail/awk/journalctl` 子进程；无内核日志权限时降级为应用日志监视，可用 `sudo ./monitor.sh` 获取完整 USB 事件。
- 配置与文档：`pump_control/pump_config.json` 默认端口改为 `auto` 并记录反馈/重连参数；根 README 和 `pose_runner/README.md` 已同步反馈协议、FIFO 参数和监视命令。`run_all.sh` 启动摘要会显示动作总容量。
- 验证：Windows Python 3.13.12 下完整 `unittest discover -s tests -v` 共 93 项全部通过，覆盖协议字节与校验、正常反馈、分段和脏数据、错误通道/校验/无响应、重枚举后查询、严格两次重连、OFF 失败只回程一次、OFF 与 Preparation 同时失败、动作总容量 3、FIFO 顺序和监视脚本只读约束。Python 源码直接编译检查和 `git diff --check` 通过。当前 Windows 的 `bash` 指向未安装发行版的 WSL，无法执行 `bash -n`；部署到树莓派后须先运行 `bash -n monitor.sh circle-camera/run_circle_camera.sh run_all.sh site_config.sh`。
- 部署前风险：此前树莓派现场存在带“双 OFF”逻辑的远端版本，与当时桌面工程不一致。上传前必须先比对远端三个核心文件并确认没有需要保留的现场独有修改；部署后首次测试必须清场，并同时运行 `sudo ./monitor.sh` 观察反馈帧和 USB `EMI?` 事件。软件重连不能替代短屏蔽线、磁环、线束隔离、可靠供电或硬件失效安全。

### 2026-08-21：看板残留进程与虚拟环境入口修复

- 现场现象：`run_all.sh` 打印“已启动整套程序”和 `http://172.16.68.111:8000`，但 `ss` 未发现 8000 监听，本机 `curl http://127.0.0.1:8000/` 连接失败。PID `3077` 的命令行仍显示 Uvicorn，但其工作目录和日志文件均为 `(deleted)`，只保留旧 WebSocket 连接，不再监听端口。
- 根因：Windows 工作区设置 `core.symlinks=false`，受 Git 跟踪的 `.venv/bin/python` 和 `.venv/bin/python3.11` 被检出为仅含 `python3` 的 7 字节普通文件，并在部署时覆盖树莓派虚拟环境入口。Bash 将该文件当作脚本执行，丢弃 `-m uvicorn ...` 的启动参数；原 `run_all.sh` 又没有检查进程和端口是否就绪，因此产生假成功输出。
- 业务代码排除：使用仍有效的 `/home/pi/raspberry/.venv/bin/python3` 在临时端口 8010 启动当前 `backend.app`，FastAPI 启动和关闭均正常，说明页面代码、趋势接口和 SQLite 数据库不是此次无法访问的根因。
- 对应修改：`vision-dashboard/scripts/start_dashboard.sh` 不再依赖 PATH 中的 `python`，而是选择并显式执行共享或局部虚拟环境的 `bin/python3`；启动前验证该解释器能导入 `fastapi` 和 `uvicorn`，失败时给出重装提示。
- 对应修改：`run_all.sh` 启动看板前查找并终止旧 Uvicorn；普通 `SIGTERM` 等待 3 秒仍不退出时使用 `SIGKILL` 清除。启动后最多等待 `DASHBOARD_STARTUP_TIMEOUT_SECONDS`（默认 20 秒），仅当 `GET /api/health` 成功后才启动圆检测并打印整套程序已启动；进程提前退出或超时会打印最近 80 行看板日志并返回失败。
- 对应修改：`stop_all.sh` 对看板使用同样的 TERM 后 KILL 收尾，专门处理目录已删除但进程未退出的残留实例。`install_all_on_pi.sh` 在执行 `python3 -m venv` 前删除可能被 Windows 还原成普通文本的三个 Python 入口，并在继续安装前验证新 `bin/python3` 可执行。
- 部署约束：不要从 Windows 上传整个 `.venv` 目录。首次部署本修复后，先在机械臂和气泵无动作的安全状态执行 `./stop_all.sh`，再修复 `.venv/bin/python*` 链接或运行 `./install_all_on_pi.sh`，最后执行 `./run_all.sh`。正常启动必须出现“可视化页面健康检查通过”，且 `curl http://127.0.0.1:8000/api/health` 返回成功。
- 机械臂预检补充：`source site_config.sh` 会再次执行相机、气泵和 S1-S5 全套预检，不只是加载变量。现场首次只有 S1 报 `Errno 121`、同轮 S2-S5 正常，随后连续检查全部通过，符合首次 I2C 事务瞬时 NACK；当前每个舵机只 PING 一次，尚未增加失败重试。本次看板修复没有修改机械臂检查策略。

### 2026-08-21：8088 全动作有限恢复状态机

- 用户决策：8088 上位机调试页面的全部机械臂动作都启用有限恢复，不只保护 Full Sequence 最后的 Preparation；代码保持精简，只清理本链路中的重复字段、临时变量和魔法数字，不清理无关模块。
- 底层异常传播：工程内 `Arm_Lib.Arm_serial_set_torque()` 不再吞掉 I2C 写异常，而是抛出 `IOError`。六轴同步写原本已抛出异常；S1-S5 读回失败仍返回 `None`，由上层位置验证统一判为失败。
- 单段运动闭环：8088 强制 `verify_moves=True`，每个 Preparation、Forward、Left、Right 段均执行“写目标姿态 -> 等待运动完成 -> 读取 S1-S5 -> 校验误差不超过 ±8°”。每段最多 3 次（首次加 2 次恢复）；重试前关闭旧 SMBus、等待 0.2 秒、重建 `Arm_Device`、PING S1-S5 并重新开启扭矩，然后重发同一目标。生产 `run_all.sh` 的默认低负载策略未被强制改变。
- 安全恢复：单步或 Full Sequence 任一阶段最终失败后，先通过气泵反馈协议确认 OFF，再尝试返回并读回验证 Preparation。SMBus 关闭时同步清除最后已验证姿态，避免旧缓存将一次失败恢复误判为已归位。原操作即使安全恢复成功仍返回失败，不会假报动作完成。
- FAULT 规则：气泵 OFF 无法确认或 Preparation 恢复失败时记录 `arm_fault` 并锁定 Forward、Left、Right、Full Sequence 和 Pump ON；Pump OFF 与 Preparation 恢复入口保留。FAULT 状态下点击 Preparation 会执行完整的“确认泵 OFF + I2C 重建/PING/扭矩恢复 + Preparation 位置验证”，成功后才解除锁定。
- 前端与接口：API 版本更新为 `servo-dashboard-five-axis-pump-v5`。`GET /api/state` 增加 `arm_fault`、`arm_recovery_attempts=2`、`arm_position_verification=true`；错误响应携带 `arm_fault`。页面显示 `Connected · ARM FAULT` 并按上述规则禁用危险按钮，安全恢复后重新启用。
- 验证：机械臂/I2C/8088 定向测试 27 项全部通过；完整测试 101 项中 100 项通过。唯一失败是既有 `site_config.sh` 使用 `DETECTION_FPS="12"`，而旧测试 `test_camera_and_voice_performance_defaults_are_explicit` 仍硬编码要求 `8`，与本次修改无关，未擅自更改现场帧率。`node --check`、Python 源码编译和 `git diff --check` 均通过。
- 尚未验证：Windows 本地没有真实 Dofbot、I2C 和气泵硬件，尚未执行实机运动。部署后必须清空机械臂工作区，确保 `run_all.sh` 已停止，再启动 8088；依次测试单步 Forward/Left/Right、Preparation、左右 Full Sequence，并在可控条件下模拟一次 I2C 短暂中断，核对重连、位置读回、安全归位和 FAULT 锁定日志。
