# 双板仓库与目录对应

系统由两个独立仓库组成：

| 开发板 | 工程地址 | 主要内容 |
| --- | --- | --- |
| Zynq-7020 | https://github.com/huddddle/FPGA_AMD_Zynq | RTL、PS 推理、构建报告、上板文件、模型、海报与比赛指南 |
| 树莓派 | https://github.com/Tony-Chen-dot/FPGA-AMD-RaspberryPi | 相机采集、推理客户端、分拣控制、看板、语音及软件测试 |

树莓派软件保留根目录模块布局：`common/`、`vision/`、`robot/`、`dashboard/`、`voice/` 对应推荐结构的 `src/`；`tests/` 与 `sim/` 对应验证；`scripts/setup/` 与 `build/` 对应环境准备；`scripts/start/`、`scripts/stop/` 与 `board/` 对应运行部署；`data/`、`skill/`、`report/` 分别提供参考数据说明、可复用方法与报告。

Zynq 的推理服务端与树莓派的请求客户端分别保存在所属仓库。FPGA 的综合与时序报告集中在 Zynq 仓库 `build/reports/`，树莓派仓库的 `report/` 记录软件功能与验证。

下载本仓库后可直接在根目录运行安装和启动脚本。使用 `tools/export_raspberry_pi.py` 可生成包含源码、文档、许可和测试的独立副本；运行数据库、图片及标定参数单独迁移。
