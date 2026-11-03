#!/usr/bin/env bash
# 仅配置 GPIO14/15 UART；复用已实机验证的 test/setup.sh 配置步骤。
set -euo pipefail
if [[ -r /proc/device-tree/model ]] && grep -q 'Raspberry Pi' /proc/device-tree/model; then
  if [[ -e /boot/firmware/config.txt ]]; then
    boot_dir=/boot/firmware
  elif [[ -e /boot/config.txt ]]; then
    boot_dir=/boot
  else
    echo '找不到启动配置；请按当前系统文档手动启用 UART。' >&2
    exit 1
  fi
  # 启动配置变更前备份。重复运行不会重复追加。
  sudo python3 - "$boot_dir" <<'PY'
import pathlib, re, shutil, sys, datetime
root=pathlib.Path(sys.argv[1])
model=pathlib.Path('/proc/device-tree/model').read_text()
is_pi5='Raspberry Pi 5' in model
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
config=root/'config.txt'
cmdline=root/'cmdline.txt'
if not cmdline.exists():
    raise SystemExit('缺少 cmdline.txt，未修改 UART；请按系统文档配置。')
text=config.read_text()
start='# BEGIN servo-debug UART'
end='# END servo-debug UART'
text=re.sub(r'\n?# BEGIN servo-debug UART.*?# END servo-debug UART\n?', '\n', text, flags=re.S)
block='\n'+start+'\n[all]\nenable_uart=1\n'
if is_pi5:
    block+='dtoverlay=uart0-pi5\n'
block+=end+'\n'
new=text.rstrip()+block
old_cmd=cmdline.read_text()
# 从 GPIO UART 移除登录控制台，保留 console=tty1 等屏幕控制台。
ports={'serial0','ttyAMA0'} if is_pi5 else {'serial0','ttyAMA0','ttyS0'}
parts=[p for p in old_cmd.split() if not (p.startswith('console=') and p[8:].split(',')[0] in ports)]
new_cmd=' '.join(parts)+'\n'
for file, old, new_data in ((config, config.read_text(), new), (cmdline,old_cmd,new_cmd)):
    if old != new_data:
        backup=file.with_name(file.name+'.servo-debug-backup-'+stamp)
        shutil.copy2(file,backup)
        file.write_text(new_data)
        print('已修改',file,'；备份',backup)
print('GPIO UART：'+('/dev/ttyAMA0 (Pi 5)' if is_pi5 else '/dev/serial0'))
PY
  # 禁止同一 UART 上的串口登录服务，避免登录提示混入舵机命令。
  if command -v systemctl >/dev/null; then
    if grep -q 'Raspberry Pi 5' /proc/device-tree/model; then
      uart_units=(serial-getty@ttyAMA0.service)
    else
      uart_units=(serial-getty@serial0.service serial-getty@ttyAMA0.service serial-getty@ttyS0.service)
    fi
    for unit in "${uart_units[@]}"; do
      sudo systemctl disable --now "$unit" || echo "提示：未禁用 $unit，请检查是否存在。"
    done
  fi
  echo 'UART 配置完成。首次修改后请执行 sudo reboot，再启动 ./scripts/start/system.sh 或 ./scripts/start/robot_debug.sh。'
else
  echo '未检测到树莓派，不修改启动配置；使用指定的 ARM_SERIAL_PORT 或演示模式。'
fi
