# 环境准备

树莓派代码使用 Python 运行。根目录 `install.sh` 调用 `scripts/setup/install_environment.sh`，安装系统包、配置 UART 与 dialout、创建 `.venv` 并安装 `requirements.txt`。各功能依赖位于 `requirements/`；离线软件测试使用 `requirements/test.txt`。

完整安装、海康 SDK 安装与启动步骤见[首页](../readme.md)。海康安装脚本面向 Linux ARM64；厂商 SDK 与语音模型由使用者另行准备。

FPGA 由 Vivado 2022.2 构建，脚本与资源/时序报告位于 [Zynq 仓库 build/](https://github.com/huddddle/FPGA_AMD_Zynq/tree/main/build)。

TODO：补充实物树莓派型号、系统镜像版本、完整依赖安装结果及镜像获取说明。
