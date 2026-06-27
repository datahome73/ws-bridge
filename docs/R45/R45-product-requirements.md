# R45 产品需求 — 管线自动触发修复 + 测试标签前缀兼容

> **版本：** v0.3（草稿，待项目负责人审核）
> **状态：** 📋 草稿（基于实战发现重写）
> **产品经理：** 🧐 PM
> **日期：** 2026-06-27
> **本轮改动范围：** 仅第①类（服务器代码 `server/handler.py`）

---

## 1. 问题背景

### 1.1 R44 修复已验证通过，但触发依赖本地文件系统

R44 的三处修复（`_can_broadcast` _admin 放开、`_check_command_permission` 白名单、`_cmd_pipeline_start` 自动收集成员+默认 step2）**均已在生产环境验证通过**。

`!pipeline_start R45` 通过原始 WS 直连 `_admin` 频道的完整调用链：

```
PM 直连 WS → _admin 频道
  → _can_broadcast() ✅（member 准入放开）
  → _check_command_permission() ✅（白名单放行）
  → _cmd_pipeline_start() ✅（函数被调用）
  → WORK_PLAN.md 检查 → ❌ 文件不存在
```

**最后一步暴露了根本问题：** `_cmd_pipeline_start()` 使用 `os.path.exists(f"docs/{round_name}/WORK_PLAN.md")` 检查本地文件系统。但：

| 分支 | 预期 | 实际 |
|:-----|:-----|:------|
| **dev** | 有 R45 文档 | ✅ 已提交 `docs/R45/WORK_PLAN.md` |
| **main** | 有 R45 文档 | 🟡 合并了但生产容器需要重新部署才生效 |
| **生产容器文件系统** | 有 R45 文档 | ❌ 容器内没有 dev 分支的新文档 |

### 1.2 设计缺陷

```
当前设计（❌）：
  !pipeline_start R45
    → 查本地 docs/R45/WORK_PLAN.md → 仅限本地文件系统
    → 生产容器 = main 分支代码 → 没有 dev 的新文档
    → 每次启动管线都要部署 → 与「自动化」理念背道而驰

期望设计（✅）：
  !pipeline_start R45
    → 从 GitHub dev 分支读取 WORK_PLAN.md（raw URL）
    → 不依赖本地文件系统 → 不需要部署
    → PM 推 dev 后即时可用
```

### 1.3 测试标签与前缀匹配冲突（F-4）

此问题依然存在且在 R45 验证中影响更大——验证过程中需要使用 `[R45测试] 📢` 等带标签的消息。

详细描述同上版需求文档 §1.2（未变更）。

### 1.4 可用基础

| 已有能力 | 状态 | 说明 |
|:---------|:----:|:------|
| `!pipeline_start` 命令（F-12+F-13 修复） | ✅ | 权限绕过和成员填充已就位 |
| `_admin` 频道 | ✅ | 常驻，PM 可直连 WS 触发 |
| GitHub raw URL（公共仓库） | ✅ | `https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/...` 无需认证 |
| `_classify_lobby_message()` | ✅ | handler.py 中前缀分类函数 |
| `PREFIX_ANNOUNCE / CHECKIN / HELP` | ✅ | 前缀常量定义 |

---

## 2. 预期体验

### 2.1 改进后 — 管线启动

```
PM(直连 WS _admin) → 发「!pipeline_start R45」
  ↓
_cmd_pipeline_start() 执行：
  ① 从 GitHub 公共仓库 dev 分支获取 WORK_PLAN.md
  ② 获取成功 → 继续管线启动
  ③ 获取失败（404/网络不通）→ 返回「❌ 无法从远程获取 WORK_PLAN.md」
  ↓
创建工作室 → 收集成员 → 点名 arch-bot → 创建 Step Task
  ↓
PM 收到：「🚀 R45 管线已启动 / Step: step2 → arch / ...」
```

### 2.2 F-4 修复后

同 v0.1 描述（不变）。

---

## 3. 需求详述

### 方向 A — 工作区文档读取来源改为 GitHub dev 分支 🔴 P1

将 `_cmd_pipeline_start()` 中的 WORK_PLAN.md 检查从本地文件系统改为从 GitHub dev 分支的 raw URL 读取。

#### 具体需求

| # | 需求 | 优先级 |
|:-:|:-----|:------:|
| A-1 | `!pipeline_start R{N}` 时，从 `https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{R{N}}/WORK_PLAN.md` 获取文档 | 🔴 P1 |
| A-2 | HTTP 200（文档存在）→ 继续管线启动流程，无需写本地临时文件 | 🔴 P1 |
| A-3 | HTTP 404 或网络不可达 → 返回「❌ 无法从远程仓库获取 WORK_PLAN.md，请确认文档已推送到 dev 分支」 | 🟡 P2 |
| A-4 | 旧行为（本地 `os.path.exists` 检查）保留为 fallback：GitHub 远程获取失败时回退本地检查 | 🟢 P3 |
| A-5 | 仅对 `!pipeline_start` 有效，不影响其他 `!` 命令 | 🟢 P3 |
| A-6 | 网络请求超时 5s，避免因网络问题长时间阻塞管线启动 | 🟡 P2 |

#### 实现说明

```python
# 当前代码（handler.py:1092-1096）：
import os as _r42os
work_plan_path = f"docs/{round_name}/WORK_PLAN.md"
if not _r42os.path.exists(work_plan_path):
    return f"❌ {round_name} 未找到 WORK_PLAN.md，请先完成 Step A/B"

# 修改后：
import urllib.request
remote_url = f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/WORK_PLAN.md"
try:
    with urllib.request.urlopen(remote_url, timeout=5) as resp:
        if resp.status != 200:
            raise Exception(f"HTTP {resp.status}")
except Exception:
    # fallback: 本地文件系统
    import os as _r42os
    work_plan_path = f"docs/{round_name}/WORK_PLAN.md"
    if not _r42os.path.exists(work_plan_path):
        return f"❌ {round_name} 未找到 WORK_PLAN.md（远程+本地均不存在）"
```

> 技术方案（具体实现——urllib / aiohttp / 异步 HTTP 请求）由架构师决定。

### 方向 B — 测试标签前缀兼容（F-4 修复） 🟢 P3

同 v0.1 描述（修复 `_classify_lobby_message()` 前缀匹配，使 `[R{N}测试] 📢` 能被识别为 announce）。无变更。

---

## 4. 架构原则

### 4.1 GitHub 公共仓库可用性

ws-bridge 是 MIT 开源项目，public 仓库，raw.githubusercontent.com 无需认证即可访问。生产容器需要具备出站 HTTPS 能力（当前已具备——R43 看门狗使用了公共网络）。

### 4.2 纯服务端系统层

方向 A 和方向 B 的全部逻辑均在 `handler.py` 的服务端系统层完成，不涉及 AI/LLM 判断，不占用 token。

### 4.3 向后兼容

- 本地 `os.path.exists` 作为方向 A 的 fallback 保留，不影响本地开发环境
- F-4 修复：无测试标签的消息行为不变；测试标签在后（`📢 [R45测试]`）行为不变
- 其他 `!` 命令不受影响

---

## 5. 验收标准

### 方向 A — GitHub dev 分支读取 WORK_PLAN.md

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| A-1 | `!pipeline_start R45` 成功从 GitHub dev 获取 WORK_PLAN.md，返回启动成功 | 🔴 P1 |
| A-2 | 对不存在的轮次（如 `!pipeline_start R999`）返回远程获取失败错误 | 🟡 P2 |
| A-3 | 网络断开场景下 fallback 到本地文件系统检查，不静默失败 | 🟢 P3 |
| A-4 | 网络请求超时 < 5s，不阻塞管线启动流程 | 🟡 P2 |

### 方向 B — 测试标签前缀兼容（F-4）

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| B-1 | `[R45测试] 📢 xxx` 在 lobby 中被标记为 'announce' | 🟢 P3 |
| B-2 | `[R45测试] 📋 @xxx` 在 lobby 中被标记为 'checkin' | 🟢 P3 |
| B-3 | `[R45测试] 🆘 xxx` 在 lobby 中被标记为 'help' | 🟢 P3 |
| B-4 | `[R45测试] @arch-bot xxx` 在 lobby 中被标记为 'mention' | 🟢 P3 |
| B-5 | `📢 [R45测试] xxx` 继续正常工作（不退化） | 🟢 P3 |
| B-6 | 无测试标签的消息分类不受影响（回归通过） | 🟢 P3 |

---

## 6. 不纳入本轮需求

| 事项 | 原因 |
|:-----|:------|
| Gateway 侧 `_admin` 路由（send_message 可达性） | 下轮（R46）方向，本轮先确保 WS 直连可用 |
| F-3 P3 角色体系 | 独立功能轮 |
| F-9 Web 端 Tab 加载空白 | 🔴 P0 但待定位 |
| 生产容器部署流程自动化 | 运维问题，不在此功能轮处理 |

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v0.1 | 2026-06-27 | 初稿 — R44 实战验证 + F-4 测试标签修复 |
| v0.3 | 2026-06-27 | 🔄 重写：实战发现 `!pipeline_start` 依赖本地文件系统（生产容器无 dev 文档），新增方向 A（改为 GitHub dev 分支读取）。Phase V 验证推迟到 R46。实现在本轮并行完成 |
