# 树莓派工程目录

| 目录或文件 | 用途 |
| --- | --- |
| `config.sh` | 网络、相机、采集产线、串口、动作与语音配置；加载时执行硬件预检 |
| `install.sh`、`start_all.sh`、`stop_all.sh` | 安装、启动和停止入口 |
| `start_robot_debug.sh`、`stop_robot_debug.sh` | 机械臂调试服务入口 |
| `common/` | 路径、产线编号、数据隔离与旧数据迁移 |
| `vision/` | 相机、图像增强、圆检测、推理请求、任务队列与分拣调度 |
| `robot/` | UART 协议、姿态参数、动作执行、硬件互斥与调试页面 |
| `dashboard/` | FastAPI 服务、SQLite 存储、实时消息和前端页面 |
| `voice/` | 检测记录检索、模型问答、语音识别和播报 |
| `scripts/` | 安装、预检、服务启动/停止及维护工具 |
| `requirements/` | 视觉、看板、控制、语音与软件测试的 Python 依赖 |
| `tests/`、`sim/` | 测试源码和统一验证入口 |
| `tools/` | 模拟设备和可迁移源码导出 |
| `build/`、`board/`、`data/` | 环境准备、上板联调与测试数据说明 |
| `skill/`、`report/` | 技能包、设计说明、协作记录与验证结果 |
| `runtime/` | 运行后生成的日志、图片和机械臂参数，由 Git 忽略 |

历史文档保留在 `docs/archive/`；当前部署方式以[首页](../readme.md)和模块文档为准。`reset_database.sh` 与 `scripts/tools/reset_dashboard.sh` 是手动清理工具，运行前确认数据库范围并备份，不属于部署必需步骤。
