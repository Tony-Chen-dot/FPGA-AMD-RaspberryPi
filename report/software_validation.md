# 软件验证记录

日期：2026-11-04。环境：Windows 开发机上的 WSL Ubuntu，Python 3.11.18，测试依赖来自 `requirements/test.txt`；临时数据库位于 Windows 挂载的任务目录。相机、串口与推理接口使用软件测试替身。

| 检查 | 结果 |
| --- | --- |
| 完整 unittest 测试集 | 107 项：105 项通过、1 项失败、1 项因缺少 Node.js 跳过 |
| 跳过的前端图片 HTTP 用例补测 | 提供 Node.js 后通过；合计 106 项通过、1 项失败 |
| 新增源码导出用例 | 通过；导出包含小写首页、许可、文档、技能、验证入口，排除 Git 与运行目录 |
| 前端图片 URL 脚本 | 通过 |
| Shell 语法 | 根目录、`scripts/` 和 `sim/` 的脚本通过 `bash -n`；Git 属性固定 `.sh` 为 LF |

## 已知失败

`test_legacy_database_images_and_conversations_migrate_only_once` 在迁移后打开目标 SQLite 数据库时返回 `sqlite3.OperationalError: unable to open database file`。将修改前的 `80085c0` 版本导出到同一 WSL / Windows 挂载环境，单独执行该用例也出现相同错误。

该迁移代码在本次整理中保持原样。TODO：在目标树莓派 Linux 文件系统上复验旧数据迁移，并定位当前挂载环境的失败原因。新建数据的多产线隔离、HTTP 接口和其余测试已通过。

原始输出分别保存在本次任务工作目录的 `pi_linux_tests.log`、`pi_baseline_migration.log` 与 `pi_image_http.log`；对应测试源码在 `tests/integration_tests/`。本次验证侧重源码包、软件接口及脚本，不包含真实相机、机械臂或双板实测。
