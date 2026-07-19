---
round_name: R125
title: 热修复轮 — R124 遗留修复 + 文档同步
pm: 小谷
arch: 小开
dev: 爱泰
review: 小周
qa: 泰虾
ops: 小爱
created: 2026-07-19
status: drafting
---

# R125 工作计划

## 概述

R124 热修复轮，不做新功能。清理 3 个遗留修复项 + 同步协议文档。

## 步骤分解

### Step 1 — PM 需求审核

- 审核 R125 产品需求文档
- 确认范围：F-1/F-2/B-8 修复 + 文档更新

### Step 2 — Arch 技术方案

- 确认代码改动边界
- 确认死代码区间（L2950-L3042）不影响活跃函数
- 确认 `_find_archive` / `_fmt_ts` 为非死代码

### Step 3 — Dev 编码实现

- **修复 A**：删除 L2950-L3042（保留 `_find_archive` + `_fmt_ts`）
- **修复 B**：3 处补 `##archive`（L3689/L3727/L3743）
- **修复 C**：活跃版 `_archive_pipeline` 加 `_notify_pm`
- **更新 D**：inbox-message-protocol.md §1/4/7/8
- **更新 E**：TODO.md 版本号 + 闭环

### Step 4 — Review 代码审查

- 确认死代码已清 `grep -c def _handle_reject main.py` → 1
- 确认 `_find_archive` 未被删除
- 确认通知修复正确
- 审查文档更新完整性

### Step 5 — QA 测试验证

源码级验证：
- 代码重复检查
- 帮助命令完整性
- 归档通知路径
- 文档变更标记

### Step 6 — Ops 合并部署归档

- 推送 dev → review → main
- 更新 TODO.md 版本号
- 通知小爱部署

## 改动清单

| 文件 | 改动 | 行数 |
|:-----|:-----|:----:|
| `server/ws_server/main.py` | 删死代码 + 补 ##help + 加通知 | -92/+6 |
| `docs/inbox-message-protocol.md` | 更新 §1/4/7，新增 §7.7/7.8，刷新 §8 | ~+30 |
| `docs/TODO.md` | 版本号 + 闭环 | ~+5 |
| `docs/R125/R125-product-requirements.md` | 新增 | 新增 |
