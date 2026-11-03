# 机械臂与气泵

所有入口共用 `robot/control/controller.py`，不再加载旧 I²C 控制库或 USB 继电器驱动。

## 串口与动作

- UART：115200、8N1、无流控。树莓派物理引脚 8/10/9 对应 TX/RX/GND。
- 关节 ID：000～004；气泵控制通道：005。
- 指令：`#003P0722T1000!`。P 是协议位置值，不是角度；T 是运动毫秒数。
- 气泵 P 值：吸取 2500、释放 500、最后复位阶段 1500，按 Verilog 保留原行为。
- 五阶段：吸取 → 左/右转移 → 左/右下降 → 同姿态释放 → 复位。
- 每阶段先发关节与气泵指令，再等待 `wait_ms`。没有将 `move_ms` 再次加到等待时间上。
- 串口指令没有位置回读确认。停止发送五个关节 PDST，气泵保持原指令；恢复动作先释放气泵，再恢复关节。

默认串口由 `ARM_SERIAL_PORT` 指定；`auto` 时 Pi 5 使用 `/dev/ttyAMA0`，其他机型使用 `/dev/serial0`。配置文件加载时仍按原流程预检。

## 调试与参数

```bash
bash start_robot_debug.sh
bash stop_robot_debug.sh
```

页面地址为 `http://<树莓派IP>:8088`。可连接串口、调整姿态和时间、单步移动、执行左右完整流程、控制气泵与停止。没有导出参数模块；页面保存到 `runtime/robot/servo_params.json`，生产分拣读取同一份参数。

需要只看页面时：

```bash
python robot/debug/server.py --demo --host 127.0.0.1 --port 8088
```

## 生产命令行

```bash
python robot/actions/run_sequence.py --mode forward-left       # 演示指令
python robot/actions/run_sequence.py --mode forward-right      # 演示指令
python robot/actions/run_sequence.py --prepare-only --live     # 真实关节复位
python robot/actions/run_sequence.py --recover --live          # 真实释放气泵并复位
```

加 `--live` 才会实际发送串口命令。支持 `--device`、`--params`、`--disable-pump`，完整参数见 `--help`。旧 USB 继电器专用参数已移除。

升级旧目录时，新参数文件不存在才会从旧位置迁移经过校验的 UART 参数。已有新参数不会被覆盖；源文件也不会被删除。不同项目目录之间部署，需要单独复制已校准参数。
