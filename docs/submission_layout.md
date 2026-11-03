# 总项目目录与树莓派代码归属

依据 2026 AMD 选题指南 §3.3.5，本项目采用 src、sim、build、board、data、skill、report 顶层目录。下图是完整工程的放置约定，Zynq 和其他硬件目录是后续规划，不代表已提供相关代码。

```text
aluminum_sorting/
├── README.md
├── src/
│   ├── raspberry_pi/          # 当前这整份树莓派代码，可独立部署
│   │   ├── config.sh          # 现场网络、产线、相机和串口配置
│   │   ├── install.sh
│   │   ├── start_all.sh
│   │   ├── stop_all.sh
│   │   ├── start_robot_debug.sh
│   │   ├── stop_robot_debug.sh
│   │   ├── common/            # 路径、产线编号和数据隔离
│   │   ├── vision/            # 采集、圆检测、Zynq 请求客户端、分拣调度
│   │   ├── robot/             # 树莓派 UART 控制与调试网页
│   │   ├── dashboard/         # 多产线看板、服务、存储和前端资源
│   │   ├── voice/             # 语音与 AI 问答
│   │   ├── scripts/           # 树莓派安装、启动、检查、维护脚本
│   │   ├── requirements/     # 分模块依赖及 test.txt
│   │   ├── requirements.txt
│   │   ├── tests/             # 树莓派回归测试，不必再复制到 sim
│   │   ├── tools/             # 模拟设备与干净导出工具
│   │   ├── docs/              # 树莓派部署、接口、控制与目录说明
│   │   └── runtime/           # 部署后自动生成，不包含在源码导出包
│   ├── zynq/                  # 后续：只放真正运行/实现于 Zynq 的工程
│   │   ├── ps/                # Linux/裸机程序、推理 HTTP 服务、驱动调用
│   │   ├── pl/                # RTL/HLS、Block Design Tcl、约束及 IP 源码
│   │   └── model/             # 模型/权重、转换脚本、版本与来源说明
│   └── control_fpga/          # 后续：若控制板是独立器件，放其 RTL/固件
├── sim/                       # 统一验证入口、软件测试结果和 RTL testbench
│   ├── verify_raspberry_pi.sh
│   └── raspberry_pi/          # 树莓派软件验证结果
├── build/                     # 后续：Vivado/Vitis/HLS 构建脚本与报告
│   ├── zynq/
│   └── control_fpga/
├── board/                     # 后续：烧录/启动、接线、器件信息与实测输出
│   ├── raspberry_pi/          # 版本/环境、校准参数样本、现场验证记录
│   ├── zynq/                  # .bit/.xsa/.hwh、板端启动与测试输出
│   └── control_fpga/
├── data/                      # 后续：测试输入、人工标签与黄金参考结果
├── skill/                     # 可复用流程：范围、用法、失效条件和验证结果
└── report/                    # 后续：整体设计报告、大模型协作记录、性能对比
```

## 其他代码怎么放

按“在哪个设备执行/综合”划分，不能按名字里有没有 FPGA/Zynq 划分。树莓派访问推理服务的 Python 客户端仍留在 `raspberry_pi/vision/transport/`；Zynq 上接收图片并运行推理的服务端放 `zynq/ps/`。控制机械臂的树莓派 UART 程序仍留在 `raspberry_pi/robot/`；若 UART 解码/PWM 是另一块 FPGA 的逻辑，放 `control_fpga/`；若是 Zynq 自身 PL 的逻辑，放 `zynq/pl/`，不要重复存两份。

已有 Vivado/Vitis 工程先整体放入所属设备目录，保留其相对引用；确认可重建后，再把可复现构建入口放入 `build/<device>/` 并引用源文件。不要只搬单个 .v 文件而丢失 .xdc、IP 配置、BD 或初始化数据。没有的硬件子目录不必创建。模型较大时可提供合法下载/转换脚本与校验值。

## 树莓派部署与目录对照

把整个 `raspberry_pi/` 复制到树莓派任意位置，例如 `~/raspberry_pi/`；在里面执行 `bash install.sh`，配置 `config.sh` 后运行 `bash start_all.sh`。这些脚本为树莓派 Linux 现场部署设计，不在开发电脑上启动硬件。原 `install_dashboard.sh` 的独立看板安装位置 `~/Interface/FPGA` 为兼容已有部署保留，名称不影响组件归属。

| 指南推荐项 | 本次已整理的位置 |
| --- | --- |
| src | src/raspberry_pi 完整软件组件 |
| sim | 总目录验证入口调用 src/raspberry_pi/tests，不复制测试源码 |
| build | 树莓派环境安装在组件 scripts/setup；FPGA 构建由后续工程补充 |
| board | 树莓派启动在组件 scripts/start；真实硬件与校准证据后续归档 |
| data | 当前不附模拟为真实的测试数据 |
| skill | 总项目的树莓派导出/验证流程 |
| report | 当前软件验证记录；整体报告和原始协作记录后续汇总 |

现场数据库默认在 `~/Database/vision-dashboard/lines/line_N/`，可能由 DASHBOARD_DATA_DIR 覆盖；它不属于源码。标定参数 `runtime/robot/servo_params.json` 应单独备份后迁移。导出不带运行数据，不代表这些数据已被删除；开发仓库与现场数据均保留。

源码目录使用小写英文和下划线，README.md 延续指南示例命名。是否满足器件、综合、上板、性能及开源要求，必须由后续真实工程和证据确认，目录齐全本身不是达标证明。
