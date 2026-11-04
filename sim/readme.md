# 软件验证

验证入口是 `verify.sh`，调用 `scripts/check/software.sh`：运行 `tests/` 中的单元和接口测试、前端图片 URL 检查及 Shell 语法检查。相机、串口和推理服务使用软件测试替身；完整环境为 Linux / WSL、Python 3.10+、Node.js 及 `requirements/test.txt`。

安装和执行命令见[首页的软件验证步骤](../readme.md)。验证结果记录在 [software_validation.md](../report/software_validation.md)。RTL 验证位于 [Zynq 仓库 sim/](https://github.com/huddddle/FPGA_AMD_Zynq/tree/main/sim)。
