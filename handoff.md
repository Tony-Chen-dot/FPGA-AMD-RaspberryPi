# 树莓派 仓库交接

更新日期：2026-11-04。本次任务为双板开源仓库整理，用户已确认维护本仓库的 `handoff.md`。

## 工程与入口

- 架构：根目录模块布局；采集/HTTP 客户端/UART/看板/语音。
- 安装、构建、启动与依赖见 `readme.md`、`build/readme.md`、`board/readme.md`。
- 两仓库地址与分工见首页；比赛指南和海报集中在 Zynq 的 `report/materials/`。

## 本次修改

- 重写首页并增加双板互链，简化内部流程措辞，将缺件整理为 TODO。
- 文件名统一小写，更新链接与工具入口；保留扩展名和 Git 隐藏文件的点号。
- 补充目录对照、许可说明、技能与协作记录。

## 验证与下一步

Linux 测试 107 项：合计 106 项通过，1 项旧数据库迁移失败；该失败在原版 `80085c0` 的同环境可复现。新增导出、图片 HTTP 与 URL 检查、Shell 语法检查通过，详见 `report/software_validation.md`。本次未操作真实硬件，目标树莓派上旧数据迁移复验为后续事项。

后续继续整理可使用 `grill-with-docs` 与 `handoff` 技能，路径为 `C:/Users/huddd/.codex/skills/<name>/SKILL.md`；行为变更按 `tdd` 验证。工作中间文件放在 `D:/CodexCache` 的独立任务时间目录。
