# 树莓派端设计说明

## 目标与系统分工

系统用于铝片表面擦伤、脏污、褶皱、针孔及正常类别的检测与分拣。树莓派负责采集、触发、网络请求、看板、数据保存和 UART 控制；Zynq-7020 负责 PS + PL 推理。分工使相机与业务页面独立于 FPGA 加速实现。

## 数据流

`vision/pipeline.py` 读取相机画面，以降采样图执行圆检测，用对应的原始帧生成推理输入。采集、推理与动作使用容量受限的队列，避免机械臂等待阻塞预览。`vision/transport/inference_client.py` 向 Zynq 上传图片，解析结果后更新本地看板并提交分拣任务。

`robot/control/` 实现 115200、8N1 ASCII UART 报文、五阶段动作、气泵、超时和恢复。生产流程与 8088 调试页共用参数文件，并通过进程互斥避免同时操作硬件。

`dashboard/` 使用 FastAPI、SQLite 和 WebSocket 提供实时状态与历史查询。产线 1～5 分别保存图片、检测记录及 AI 对话，当前一台相机只写入配置指定的产线。`voice/` 从所选产线记录构建问答上下文，并可接入录音、识别与语音合成。

## 验证与工程取舍

软件测试验证图像预处理、缺陷标签、动作顺序、参数迁移、产线隔离和页面图片地址。测试结果见 [software_validation.md](software_validation.md)。FPGA 资源与推理计时由 [Zynq 设计报告](https://github.com/huddddle/FPGA_AMD_Zynq/blob/main/report/design_report.md) 提供。

复现步骤见[首页](../readme.md)，接线与联调见 [board/](../board/readme.md)。海康 SDK、模型服务与语音模型按设备和功能选择配置。

## TODO

- 补充具体硬件型号、操作系统镜像与可迁移的标定样例。
- 测量触发到分拣完成的时延分布、成功率、连续运行时间与失败恢复情况。
- 归档原始开发协作对话及优化前后的同条件对比数据。
