> 历史资料：保留当时的记录，目录和控制方式可能已过时。当前操作请以根目录 readme.md 和 docs/project_structure.md 为准。

# 生产机械臂动作入口

生产相机继续调用 `robot/actions/run_sequence.py`，业务分拣方向、队列、触发延迟和错误恢复入口保留。机械动作与8088页面共用 `robot/control/controller.py`，来自已实机成功的 `test/servo_debug.py`，不依赖上级 test 文件夹。

```bash
# 在 FPGA 项目根目录操作；不加 --live 为演示
python3 robot/actions/run_sequence.py --mode forward-left
python3 robot/actions/run_sequence.py --mode forward-right --live
python3 robot/actions/run_sequence.py --prepare-only --live
python3 robot/actions/run_sequence.py --recover --live
```

参数文件默认 `runtime/robot/servo_params.json`，可用 `--params PATH` 指定。启动时的 `--prepare-only` 只让000～004到复位姿态，不更改005。恢复 `--recover` 在气泵启用时发005释放，等待后复位五关节；正常分拣失败后的恢复触发机制由原相机程序保留。

`ARM_SERIAL_PORT=auto` 在Pi5使用 `/dev/ttyAMA0`，其他树莓派使用 `/dev/serial0`；也可指定已测试的 `/dev/...`。固定115200、8N1，无流控。005共享该串口，不需要旧USB继电器，也不使用其A0协议、VID/PID或状态反馈。`DISABLE_PUMP=1` 或 `--disable-pump` 跳过005所有指令。

## 正常流程

| Phase | 000～004 的 P 值 | 005 P | T(ms) | 发送完后的等待(ms) |
|---|---|---:|---:|---:|
| 0 吸取 | 1500,1223,1722,0722,1500 | 2500 | 1000 | 1500 |
| 1 左转移 | 0967,1500,1722,0722,1500 | 2500 | 1000 | 1000 |
| 1 右转移 | 2033,1500,1722,0722,1500 | 2500 | 1000 | 1000 |
| 2 左下降 | 0967,1033,1622,0822,1500 | 2500 | 0500 | 500 |
| 2 右下降 | 2033,1033,1622,0822,1500 | 2500 | 0500 | 500 |
| 3 释放 | 重复本分支下降姿态 | 0500 | 0500 | 500 |
| 4 复位 | 1500,1500,1500,1500,1500 | 1500 | 1000 | 1000 |

每个分支执行5阶段，每阶段按000→005顺序发送六条独立ASCII指令；总共30条，无换行/校验和，例如 `#003P0722T1000!`。等待时间与T不叠加；Phase4等待来自原Verilog实际使用的RESET_WAIT_MS。P1500不等同于确认气泵关闭，按原代码保留。

新参数格式（与test/settings.json一致）：`poses`包含pickup、left_transfer、right_transfer、left_drop、right_drop、reset，各为五个整数；`manual_ms`为单步时间；`move_ms`与`wait_ms`分别为五阶段列表。旧角度参数无法直接转换为新机械臂位置，首次遇到旧格式时备份后改用FPGA默认值；无效新参数不用于运动。

## 运行边界

- 启动/连接/预检不发送运动。正常全套run_all仍保留显式的启动复位步骤。
- 串口独占打开，沿用 `/tmp/raspberry-arm-pump.lock`，生产动作与调试不可同时抢占硬件。
- 仅发送，不读位置；“DONE”表示命令及等待完成，不是位置反馈。
- Ctrl+C/SIGTERM尽力停止关节，气泵不随停止自动释放；最终依实际模块状态判断。
- 活动路径不再使用 Arm_Lib、dofbot_i2c 或 pump_control.serial_pump。它们保留为旧协议参考，不用于本机械臂。
- 相机异常仍触发原有恢复入口；UART故障不使用旧USB继电器特有的20/21返回码。
