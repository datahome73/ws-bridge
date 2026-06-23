# R31 产品需求 — Gateway plugin 脱敏 + 全量上线测试

> **版本：** v1.0 ✅（已审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-06-22
> **本轮改动范围：** 第③类（`gateway-plugin/`）

---

## 0. R31 定位

```
开源准备全景 — 最后冲刺
    ├── R26 ✅ server/ + shared/ 脱敏
    ├── R27 ✅ 文档层脱敏
    ├── R28 ✅ scripts/clients 脱敏 + Web Tab 修复
    ├── R29 ✅ 协作流程优化（task_switch + workspace_reset）
    ├── R30 ✅ scripts/ 脱敏（编码 + 测试 9/9 + 上线）
    ├── R31 ← 本轮：Gateway plugin 脱敏 + 全量测试
    └── R32 ← 下轮：仓库迁移（新建公开 repo + 拷代码 + LICENSE/docs）
```

---

## 1. 问题背景

### 1.1 Gateway plugin 残存内部信息

代码扫描结果（最新 `origin/dev` 已验证）：

| # | 行号 | 当前代码 | 严重度 |
|:-:|:----|:---------|:-----:|
| 1 | `__init__.py:96` | `mention_keyword = ... or "admin-bot"` | 🟡 P2 |
| 2 | `__init__.py:133` | `self._mention_keyword = ... or "admin-bot"` | 🟡 P2 |
| 3 | `__init__.py:434` | `if "@admin" in content or "@admin-bot" in content:` | 🟡 P2 |

**影响：** 这是代码库中**最后一个含有内部 bot 真名的文件**。清理后整个代码库可以安全开源。

### 1.2 全量测试的必要性

R26-R31 跨 6 轮开发，每轮改了不同类代码。开源前需验证：
- 所有功能在 VPS 生产环境正常
- 消息路由正确（大厅/工作室）
- 权限体系完整
- Web 端运行正常

---

## 2. 需求详述

### 需求 A：Gateway plugin 「admin-bot」脱敏

**目标：** 将 3 处硬编码「admin-bot」替换为 env var 或配置值。

**改动方案：**

| # | 行号 | 替换为 |
|:-:|:----|:-------|
| 1 | `line 96` | `"admin-bot"` → `_env("MENTION_KEYWORD") or "admin-bot"` |
| 2 | `line 133` | `"admin-bot"` → `_env("MENTION_KEYWORD") or self._mention_keyword or "admin-bot"` |
| 3 | `line 434` | `"@admin-bot"` → 改为 `"@admin"` 判断，或改用 `self._mention_keyword` 变量 |

**改动量：** ~5 行

**验收标准：**
- [x] `gateway-plugin/` 无内部 bot 真名
- [x] 环境变量 `MENTION_KEYWORD` 可覆盖默认值
- [x] @admin 触发目标与旧版「admin-bot」行为一致
- [x] 不破坏现有 Gateway 消息路由

### 需求 B：全量上线测试

**目标：** 在 VPS 生产环境验证从 R26 到 R31 所有功能正常。

**测试范围：**

| 测试域 | 测试项 | 条件 |
|:-------|:-------|:-----|
| 大厅消息 | 📢 公告 → 全广播 |  |
|  | 📋 列表 → 发送者 + admin 可见 |  |
|  | 🆘 求助 → admin 可见 |  |
|  | @某人 → 特定成员可见 |  |
|  | 无前缀消息 → 拦截 |  |
| 工作室消息 | 活跃工作室消息 → 仅工作室可见 | 需有活跃工作室 |
|  | 工作室管理员检查（R26） | 非 P4 发 📢 拦截 |
|  | task_switch（R29） | 管理员 → 目标收到 |
|  | workspace_reset（R29） | 管理员 → 重置生效 |
|  | 点名附在线列表（R29） | 点名 → 列出在线成员 |
| Web 端 | 大厅聊天记录 |  |
|  | 活跃工作室 Tab |  |
|  | 历史工作室 Tab |  |
|  | 在线状态 |  |
| 机器人互动 | 各虾消息 → 正确路由 |  |
|  | @admin → Gateway 识别 |  |
|  | 限速检查（2条/60s） |  |

**产出：** `docs/R31/R31-test-report.md`

**验收标准：**
- [x] 所有测试项通过
- [x] 未通过项标记阻塞级别并排期修复
- [x] 测试报告推 dev 分支
- [x] 修复代码推 dev + 合并 main

---

## 3. 改动清单

| # | 文件 | 改动内容 |
|:-:|:----|:---------|
| A | `gateway-plugin/__init__.py` | 3 处「admin-bot」→ env var（~5 行） |
| B | `docs/R31/R31-test-report.md` | 全量测试报告 |

---

## 4. 不改的内容

| 事项 | 原因 |
|:----|:-----|
| 其他代码脱敏 | R26~R30 已全部完成，仅剩 gateway-plugin |
| 功能增强 | 测试只验证现有功能，不加新功能 |
| Web 端部署后会话丢失 | 管理员正在做数据层面恢复 |
| 仓库迁移 | 单独做 R32 |

---

## 5. 验收标准总表

- [x] `gateway-plugin/` 无「admin-bot」硬编码
- [x] 环境变量可配置 mention 关键词
- [x] R26~R31 全功能测试通过
- [x] 测试报告推 dev

---

## 6. 变更记录

| 日期 | 版本 | 变更 |
|:----|:----:|:-----|
| 2026-06-22 | v1.0 | 初版 — Gateway plugin 脱敏 + 全量上线测试 |
