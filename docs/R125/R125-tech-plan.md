# R125 技术方案 — 热修复轮

> **起草人：** 📐 Arch（小开）
> **状态：** 📝 草稿
> **版本：** v1.0
> **基线：** dev `1496add`（R125 产品需求 + WORK_PLAN 已合并）

---

## 1. 问题概述

R125 定位为热修复轮，不做新功能。目标：

| # | 修复项 | 来源 | 类型 |
|:-:|:-------|:-----|:-----|
| A | 删除 L2950-L3041 死代码（旧版 `_handle_reject` + `_archive_pipeline` 重复定义） | R124 QA F-1 | 🐛 代码清理 |
| B | 3 处 `##help` 补齐 `##archive##R{N}` 命令说明 | R124 QA F-2 | 📖 帮助文档 |
| C | 活跃版 `_archive_pipeline` 补 `_notify_pm` 归档通知 | R124 QA B-8 | 🐛 Bug 修复 |
| D | 更新 `docs/inbox-message-protocol.md` 至 v3.1（覆盖 R124 新增功能） | TODO.md Phase 2 | 📖 文档同步 |
| E | 更新 `docs/TODO.md` 版本号 + R125 闭环 | 例行 | 📖 文档同步 |

---

## 2. 代码审计 — 实际行号确认

> 需求文档中的行号基于 R124 最终代码。以下使用 git HEAD `1496add` 的实际行号。

### 2.1 Fix A — 死代码区间

| 区间 | 行号 | 内容 | 操作 |
|:----|:----:|:-----|:----:|
| 旧版 `_handle_reject` | L2950-L2998 | 缺 `PS.COMPLETED` 守卫，使用字符串状态比较 | ❌ 删除 |
| 旧版 `_archive_pipeline` | L2999-L3041 | 有 `_notify_pm`（L3039），但即将被新版取代 | ❌ 删除 |
| 节标记 + 空行 | L2950, L2999, L3042 | 节对齐标记 | ❌ 一并删除 |
| `_find_archive` | L3044 | 被 `_handle_hash_status` 调用（`#1132`） | ✅ 保留 |
| `_fmt_ts` | L3060 | 被 `_handle_hash_status` 调用（`#1142`） | ✅ 保留 |

**验证命令：**
```bash
# 删除后搜索确认各函数仅 1 处定义
grep -n 'def _handle_reject' main.py    # 应仅剩 L3499
grep -n 'def _archive_pipeline' main.py # 应仅剩 L3839
grep -n 'def _find_archive' main.py     # 应仅剩 L3044
grep -n 'def _fmt_ts' main.py           # 应仅剩 L3060
```

**差分：** 删除 L2950-L3041（92 行，含旧版函数 + 节标记），净删 -92 行。

### 2.2 Fix B — ##help 补齐

| 位置 | 当前行号 | 当前内容 | 改动 |
|:-----|:--------:|:---------|:-----|
| Block 1（## 格式错误内联帮助） | L3689-L3694 | 列出 start/status/stop/advance/help | 补 `##archive##R{N}` 行 |
| Block 2（##help 命令回复） | L3727-L3732 | 同上 | 同 Block 1 |
| 未知命令回退 | L3743 | `可用: start / status / stop / advance / help` | 追加 `archive` |

**差分：** +3 行（每处 +1 行），格式与现有排版一致。

### 2.3 Fix C — 归档通知

| 函数 | 行号 | 现状 | 操作 |
|:-----|:----:|:-----|:-----|
| 旧版 `_archive_pipeline`（待删除） | L3000-L3041 | **有** `_notify_pm`（L3039） | 被 Fix A 删除 |
| 新版 `_archive_pipeline`（活跃） | L3839-L3888 | **缺** `_notify_pm`，try 块 L3880-L3886 仅 logger.info | ✅ 需添加 |

**添加位置：** 在新版 `_archive_pipeline` 的 try 块内，L3886 `logger.info(...)` 之后，L3887 `except` 之前。

```python
        # L3886 logger.info(...) 之后插入：
        await _notify_pm(ctx, len(ctx.steps), "archived",
                         f"📦 {round_name} 管线已完成并归档")
```

**差分：** +3 行。

### 2.4 Fix D — 协议文档

| 章节 | 当前内容 | 改动 |
|:-----|:---------|:-----|
| §1 概述（L16-L25） | R111→R115 功能表，5 项 | 追加 R124 4 项增强：驳回回退、##archive、##advance、自动归档 |
| §4 回复协议（L83-L101） | 仅提及 ACK/完成 | 补充 `退回 🔄` 协议说明 |
| §7.6 前缀规则（L331-L345） | 5 条规则表 | 表已有 `退回 🔄` 和 `##`，但需将 `##archive`/`##advance` 在 `##` 行中明确列出 |
| 新增 §7.7 驳回协议 | — | 退回触发条件、状态回退（Step 1/2→Step 1, Step 3+→Step 2）、PM 决策、stuck 机制 |
| 新增 §7.8 归档协议 | — | 自动归档（管线完成时）+ ##archive 命令 + 归档通知 |
| §8 全流程（现 §B 命令列表 L407-L412） | 缺 `##archive`、`##advance` | 补充至命令列表 |
| 版本/日期 | v3.0 / 2026-07-15 | → v3.1 / 2026-07-19 |
| 基线 | R111→R115 | → R111→R124 |

### 2.5 Fix E — TODO.md

| 字段 | 当前 | 改为 |
|:----|:-----|:-----|
| 版本号 | v2.72 | v2.73 |
| Phase 2 异常处理 | `🔲 异常处理机制完善：跳步、驳回回退、超时自动换人` | `✅ 驳回回退（R124）+ 热修复（R125）` |
| Phase 2 协议文档 | `🔲 **更新 inbox-message-protocol.md**` | `✅ **更新 inbox-message-protocol.md** — R124 热修复已闭环` |

---

## 3. 改动清单汇总

| 文件 | 改动 | 预估行数 |
|:-----|:------|:--------:|
| `server/ws_server/main.py` | Fix A（-92）+ Fix B（+3）+ Fix C（+3）= **净 -86 行** | -92/+6 |
| `docs/inbox-message-protocol.md` | Fix D：§1/4/7/8 更新，新增 §7.7/§7.8，版本号 v3.0→v3.1 | ~+35 行 |
| `docs/TODO.md` | Fix E：版本号 v2.72→v2.73，Phase 2 项标记 ✅，新增 R125 闭环记录 | ~+10 行 |

---

## 4. 侧效应分析

| 变动 | 侧效应 | 风险等级 |
|:-----|:-------|:--------:|
| Fix A 删除旧版 `_handle_reject` | 所有 reject 逻辑走 L3499 新版（带 `PS.COMPLETED` 守卫），功能不变 | 🟢 低 |
| Fix A 删除旧版 `_archive_pipeline` | 旧版的 `_notify_pm`（L3039）被删除，但 Fix C 给新版补上，通知功能不变 | 🟢 低 |
| Fix B 加 `##archive` 到帮助 | 纯文本改动，不影响逻辑 | 🟢 低 |
| Fix C 加 `_notify_pm` | 归档成功时新增通知，不影响归档逻辑本身 | 🟢 低 |
| 文档更新 | 无运行时影响 | 🟢 低 |

**无风险项：** 所有改动均为纯代码清理 + 文档更新，不修改活跃函数逻辑。

---

## 5. 不做事项

| 排除项 | 理由 |
|:-------|:------|
| ❌ TDD RED-GREEN-REFACTOR | 代码清理 + 文档更新，改动极小 |
| ❌ Step 测试环境构建 | 代码清理不影响逻辑 |
| ❌ 新增任意功能 | R125 定位为纯热修复 |
| ❌ ESLint/Pylint 清理 | 积攒到代码治理轮次 |

---

## 6. 验收检查表

| # | 验收项 | 验证方式 | 优先级 |
|:-:|:-------|:---------|:-----:|
| A-1 | `_handle_reject` 仅剩 1 处定义（L3499） | `grep -c "def _handle_reject" main.py` == 1 | 🟢 P0 |
| A-2 | `_archive_pipeline` 仅剩 1 处定义（L3839） | `grep -c "def _archive_pipeline" main.py` == 1 | 🟢 P0 |
| A-3 | `_find_archive` / `_fmt_ts` 未被删除 | `grep "def _find_archive" main.py` + `grep "def _fmt_ts" main.py` 各有 1 处 | 🟢 P0 |
| A-4 | `##status` 仍可查归档管线 | `_handle_hash_status` 调用 `_find_archive` 路径不变 | 🟡 P1 |
| A-5 | 节标记对齐无断裂 | 删除区间前后 # ═══ 节标记连续 | 🔵 P2 |
| B-1 | Block 1（L3689-3695）含 `##archive` | grep `##archive` 在 L3690-3695 区间 | 🟢 P0 |
| B-2 | Block 2（L3727-3733）含 `##archive` | grep `##archive` 在 L3728-3733 区间 | 🟢 P0 |
| B-3 | 未知命令回退（L3743+）含 `archive` | 可用命令列表含 `archive` | 🟢 P0 |
| B-4 | 排版风格一致 | `##archive##R{N}` 使用 `` ` 包裹，`\\n` 换行符统一 | 🔵 P2 |
| C-1 | `_archive_pipeline` 成功分支调用 `_notify_pm` | L3886 后存在 `await _notify_pm(...)` | 🟢 P0 |
| C-2 | PM 收到归档通知 | 归档后 PM 收到「📦 R{N} 管线已完成并归档」 | 🟢 P0 |
| C-3 | 写入失败不调 `_notify_pm` | `except` 块内无 `_notify_pm` | 🟡 P1 |
| D-1~D-7 | 协议文档更新 | 见需求文档 §3 D 验收项 | 🟢 P0 |
| E-1~E-3 | TODO.md 更新 | 版本号 + 闭环 + Phase 2 项标记 | 🟢 P0 |

---

## 7. 执行顺序

| 步骤 | 操作 | 依赖 |
|:----:|:-----|:-----|
| 1 | Fix A：删除 L2950-L3041（保留 L3043+ 的 `_find_archive` 和 `_fmt_ts`） | — |
| 2 | Fix B：3 处补 `##archive` | — |
| 3 | Fix C：活跃版 `_archive_pipeline` L3886 后加 `_notify_pm` | Fix A 先删旧版，避免编译期函数名重复 |
| 4 | Fix D：更新 `docs/inbox-message-protocol.md` | — |
| 5 | Fix E：更新 `docs/TODO.md` | — |
| 6 | 全量验证：执行验收检查表 | 1-5 完成 |
