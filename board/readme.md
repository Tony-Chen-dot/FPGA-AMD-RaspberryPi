# 树莓派上板与双板联调

1. 使用普通用户通过 SSH 登录 ARM64 树莓派 Linux，按[首页](../readme.md)安装依赖与相机 SDK。
2. 根据相机实物填写 `config.sh` 的类型与序列号，将树莓派和 Zynq 以太网配置到同一子网。
3. 按 [Zynq 运行说明](https://github.com/huddddle/FPGA_AMD_Zynq/blob/main/board/readme.md)启动 8080 推理服务，确认 `/health` 返回正常。
4. 连接 UART：物理引脚 8/TX、10/RX 与控制板交叉连接，9/GND 共地；核对供电、电平、舵机控制板协议和气泵接口。
5. 启动机械臂调试页并标定姿态/等待时间；保存 `runtime/robot/servo_params.json`，再运行整套服务。
6. 在 8000 看板检查相机预览、缺陷类别、当前产线历史记录，以及 OK/NG 对应的机械臂动作。

## 数据保存

- 标定参数：`runtime/robot/servo_params.json`。
- 数据库与图片：`~/Database/vision-dashboard/lines/line_N/`，或 `DASHBOARD_DATA_DIR` 下的同名子目录。
- 运行日志：`runtime/logs/line_N/` 和 `runtime/vision/line_N/logs/`。

## 已有运行文件

`evidence/previous_runtime/` 保存仓库原先跟踪的日志和预览图片，作为历史运行资料；文件内容与原仓库一致，原路径为 `runtime/` 下的对应相对路径。

## TODO

- 补充树莓派、相机、UART 控制板型号和系统版本。
- 补充接线照片、标定参数示例、完整双板联调记录。
- 用带时间戳的采集、HTTP 请求、结果与动作完成日志统计整机时延和分拣成功率。
