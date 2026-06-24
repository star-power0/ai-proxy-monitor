# Changelog

## 0.2.0 - 2026-06-21

- 重构数据架构：ccswitch 只负责站点导入，分组/倍率/余额全部来自站点实时数据。
- 站点按 host 聚合，同一 host 下多条 ccswitch 记录合并为一个站点。
- 改为父子卡片展示：站点层显示余额和整体状态，分组层显示倍率和价格。
- 状态判定改为保守状态机：online / unknown / error，不乱判离线。
- 探明 New API 系列站点的 `/api/pricing` 接口结构（含 group_ratio、usable_group）。
- 探明当前 ccswitch key 对余额接口返回未授权，确认余额需通过网页登录态抓取。
- 确认下一步方向：分组/倍率/余额全部改为网页抓取。
- 新增 HANDOFF.md 项目交接文档。

## 0.1.0 - 2026-06-21

- 新建 ai-proxy-monitor 项目，技术栈 Python + FastAPI + 原生 HTML/CSS/JS。
- 接入 ccswitch 本地 SQLite 数据库，读取 23 条 provider 记录。
- 实现基础健康检测（API 探测 /api/token/prices、/api/user/self、/v1/models）。
- 实现 Web 面板：总数、正常数、异常数、卡片展示、异常置顶、手动刷新。
- 检测历史写入 data/history.jsonl。
