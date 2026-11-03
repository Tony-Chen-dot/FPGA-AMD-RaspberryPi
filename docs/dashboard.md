# 树莓派多产线质检上位机

主入口是 `dashboard/api/server.py`，使用 FastAPI；网页位于 `dashboard/web/`，SQLite 与图片逻辑位于 `dashboard/storage/database.py`。

安装统一环境后，从项目根目录执行：

```bash
bash scripts/start/dashboard.sh
```

默认端口 8000。生产环境通常直接用根目录 `start_all.sh` 启动，会加载现场配置并连接视觉采集流程。

原有实时预览、检测结果、缺陷统计、历史记录、设备接入、WebSocket 更新、AI 问答和对话历史功能均保留。原 API 地址与数据库结构不变；数据按产线分别存放在 `~/Database/vision-dashboard/lines/line_1/` 到 `line_5/`，每条产线包含独立 SQLite 数据库、图片和归档。可以用 `DASHBOARD_DATA_DIR` 覆盖它们共同的根目录。

辅助命令：

```bash
python tools/simulate_device.py --help
bash scripts/tools/open_kiosk.sh http://127.0.0.1:8000
```

这两份脚本仍针对旧单产线路径，不会自动删除新增的各产线数据。`reset_dashboard.sh` 只负责原看板数据清理，`reset_database.sh` 还包含对话历史清理；两者都在 `scripts/tools/`，仅在需要清空时手动执行。

## 多产线浏览与单摄像头采集

`config.sh` 的 `PRODUCTION_LINE_ID=1` 指定当前摄像头与分拣所属产线，范围 1～5。页面的五个产线按钮只切换查看对象，其余产线显示“无信号”，但自己的历史数据仍然可读。树莓派为多产线上位机，Zynq 为推理加速器；当前演示只有一条采集通道，没有模拟其他产线信号。

API 通过 `line_id` 查询参数区分查看对象，例如 `/api/state?line_id=2`、`/api/history/trend?line_id=2`、`/api/assistant/conversations?line_id=2`、`/ws/dashboard?line_id=2`。返回的图片 URL 已带对应编号，后端不会把一条产线的图片转给另一条。写入包可以带 `line_id`，必须与当前配置的采集产线一致；省略时归当前采集产线。

首次升级的历史迁移与导出路径见根目录 README.md“产线配置与页面切换”。
