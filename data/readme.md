# 测试输入与参考结果

软件测试在 `tests/` 内生成固定图像、串口报文和临时数据库：检测类别筛选见 `tests/vision_tests/`，动作报文和参数迁移见 `tests/robot_tests/`，产线隔离及图片访问见 `tests/integration_tests/`。

这些输入用于软件回归。硬件推理固定图片与参考张量位于 [Zynq 仓库 data/](https://github.com/huddddle/FPGA_AMD_Zynq/tree/main/data)。原仓库的预览图和运行日志保存在 `board/evidence/previous_runtime/`。

TODO：整理可公开的相机输入样例、人工标签、预期分拣结果和完整联调日志，并记录设备、版本和采集条件。
