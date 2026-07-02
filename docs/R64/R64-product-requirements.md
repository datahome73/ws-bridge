# R64 产品需求 — Gateway 多触发词支持 🎯

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-02
> **本轮改动范围：** `gateway-plugin/__init__.py`（纯 gateway 层改动）
> **参考：** R63 实战暴露、TODO.md v2.30 F-21、「@arch 无法触发 arch bot」R63 Step 3 经验

---

## 1. 问题背景

### 1.1 单触发词 → 多角色点名断裂

ws-bridge 的每个 bot 容器通过 Gateway 插件连接，配置了 `mention_keyword` 作为**唯一触发词**：

| Bot | 角色 | 当前 mention_keyword | 问题 |
|:---|:----|:---------------------|:----|
| 🟣 Dev bot | dev | `爱泰` | `@dev` 点名不触发 |
| 🔵 Arch bot | arch | `小开` | `@arch` 点名不触发 |
| 🟢 Review bot | review | `小周` | `@review` 点名不触发 |
| 🟡 Admin bot | admin | `小爱` | `@admin` 点名不触发 |
| 🟠 QA bot | qa | TG 通道（无 Gateway mention_keyword） | PM 需通过 TG DM 点名，`@qa` 无法直接触发 |
| 🔴 PM | PM | Hermes Agent（无 Gateway mention_keyword） | `@PM` 点名由 handler.py 解析，不经过 Gateway 触发链 |

**R63 实战暴露的断裂场景：**

```
工作室消息：@arch 到你了——编写技术方案
         ↓
小开（mention_keyword="小开"）❌ 「小开」不在内容中 → 静默丢弃
         ↓
管线静默停摆 → PM 不得不二次发送 @小开 点名
```

### 1.2 Gateway 侧触发链分析

```python
# gateway-plugin/__init__.py 当前触发逻辑

# L133 — 初始化（单值字符串）
self._mention_keyword = extra.get("mention_keyword") or "admin-bot"

# L359 — 触发检查（单值）
if self._mention_keyword not in content:  # ❌ "arch" not in "@小开" → 静默
    return

# L367 — 前缀剥离（单值）
if text.startswith(self._mention_keyword):  # ✅ 仅对一值生效
    text = text[len(self._mention_keyword):].strip()

# L434 — 频道路由（单值 @mention 检查）
if "@admin" in content or f"@{self._mention_keyword}" in content:
    return "lobby"
```

**四个消费点全部是单值匹配**，共 4 处需改造：

| # | 位置 | 代码 | 当前行为 | 改造后 |
|:-:|:-----|:-----|:---------|:-------|
| 1 | L133 | `self._mention_keyword =` | 单字符串 | 解析分号分割为 `list[str]` |
| 2 | L359 | `if self._mention_keyword not in content` | 单值 `not in` | `if not any(kw in content for kw in self._mention_keywords)` |
| 3 | L367 | `if text.startswith(self._mention_keyword)` | 单值 `startswith` | 遍历 `_mention_keywords`，任一切前缀 |
| 4 | L434 | `f"@{self._mention_keyword}" in content` | 单值 | 遍历 `_mention_keywords` 任一匹配 |

### 1.3 为什么是现在修？

| 原因 | 说明 |
|:----|:------|
| 🔴 **R63 实测暴露** | 多轮点名师「@arch」「@dev」点名发现 bot 不响应，PM 被迫二次发送 bot 名点名 |
| 🟡 **管线效率瓶颈** | 每轮 Step 交接 PM 需记住每个 bot 的精确触发词，用角色名点名更方便 |
| 🟢 **改动量小** | 单文件 4 处改动，~20 行净增，零风险 |
| 🟢 **向下兼容** | 现有 `mention_keyword: "小开"` 配置 → 分割后仍为 `["小开"]` → 行为零变化 |
| 🔗 **配合 R63 Agent Card** | Agent Card schema 已含 `trigger_preference.mention_keyword`，Gateway 支持多触发词后角色名可以作为标准触发词 |

---

## 2. 功能需求

### 设计原则

> **最小改动原则：** 只改消费点，不改 `SeededConfig` 种子配置格式（保持 `mention_keyword` 字段名不变）。
> **向下兼容：** 现有单值配置零改动，行为零变化。
> **分隔符统一：** 使用 `;`（分号）作为多值分隔符，与日常使用习惯一致。

---

### 方向 A（核心）：`mention_keyword` 多值支持 🔴 P0

**目标：** 各 bot 的 `mention_keyword` 配置可写为 `"小开;arch"`，`@小开` 或 `@arch` 均可触发。

#### A1 — 初始化解析：单字符串 → 列表

**位置：** `__init__.py` ~L133（`__init__` 方法）

```python
# 当前
self._mention_keyword = extra.get("mention_keyword") or _env("MENTION_KEYWORD") or "admin-bot"

# 改造后
_raw = extra.get("mention_keyword") or _env("MENTION_KEYWORD") or "admin-bot"
self._mention_keywords = [k.strip() for k in _raw.split(";") if k.strip()]
self._mention_keyword = self._mention_keywords[0]  # 保留兼容引用
```

**注意：** `_mention_keyword` 保留为 `_mention_keywords[0]`（首个值），供第三方引用需要单一值的场景使用。但**新代码统一用 `_mention_keywords`（列表）**。

> **为什么保留 `_mention_keyword`？** 登录日志（L144 `"agent=%s url=%s role=%s mention=%s"`）、调试输出可能引用此字段。

#### A2 — 触发检查：单值 `not in` → 列表 `any()`

**位置：** `__init__.py` ~L359

```python
# 当前
if self._mention_keyword not in content:
    logger.warning("[WSBridge] Silent: no mention keyword '%s'", self._mention_keyword)
    return

# 改造后
if not any(kw in content for kw in self._mention_keywords):
    logger.warning(
        "[WSBridge] Silent: no mention keyword in '%s'",
        self._mention_keywords,
    )
    return
```

#### A3 — 前缀剥离：单值 `startswith` → 遍历列表（长词优先）

**位置：** `__init__.py` ~L367

```python
# 改造后
text = content
# 长词优先匹配（避免 "小" 覆盖 "小开"）
for kw in sorted(self._mention_keywords, key=len, reverse=True):
    if text.startswith(kw):
        text = text[len(kw):].strip()
        break
```

**行为说明：**
- 按长度降序排列触发词列表（短词排在后面，避免 `"小"` 误剥 `"小开"`）
- 先匹配前缀，剥离后 `break`
- 剥离后内容保留后续字符

#### A4 — 频道路由：单值插值 → 遍历

**位置：** `__init__.py` ~L434

```python
# 当前
if "@admin" in content or f"@{self._mention_keyword}" in content:
    return "lobby"

# 改造后
if "@admin" in content:
    return "lobby"
for kw in self._mention_keywords:
    if f"@{kw}" in content:
        return "lobby"
```

#### A5 — 高频词去重（可选优化）

如果 `_mention_keywords` 长度超过 10 时，触发检查的 `any(kw in content for kw in ...)` 可能带来性能压力。但当前各 bot 各配 2 个词 → 总长不超过 6，**不需要优化**。

---

### 方向 B（建议）：配置更新 🟡 P2

**目标：** 各 Gateway bot 自查自调，将自身 `mention_keyword` 更新为「bot 名 + 角色名」双触发词（如 `"bot名;角色名"`）。

**这是各 bot 的自主配置行为，非代码层改动。** 部署新版 Gateway 插件后，各 bot 自行修改各自容器的 `config.yaml` 中 `mention_keyword` 配置（或环境变量 `MENTION_KEYWORD`），重启容器生效。

> **管线调度说明：** PM 在 `!pipeline_start` 启动工作室后，先开一个「配置通知晨会」——在工作室中逐个 @通知 各 Gateway bot 告知需调整的触发词配置。确认全部就绪后，再继续后续 Step（方案设计 → 编码 → 审查 → 测试）。具体 bot 名称和角色对应关系不下沉到需求文档，由 PM 在工作室通知中传达。

---

### 方向 C（辅助）：顺手修复 🟢 P3

| # | 位置 | 问题 | 操作 |
|:-:|:-----|:-----|:-----|
| C1 | `__init__.py` L65-98 `seeded_config()` | `mention_keyword` 种子配置不影响 `SeededConfig` | 不做破坏性修改，仅保留兼容 |
| C2 | `__init__.py` L144 | 初始化日志打印单值 | 改为打印 `self._mention_keywords` 列表 |
| C3 | `__init__.py` L361 | Silent 日志单值 | 改为打印列表 |

---

## 3. 验收标准

### 🎯 3.1 方向 A（多触发词）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 单值 `mention_keyword: "小开"` → `["小开"]` | 零行为变化 | 单元测试 `split(";")` |
| ✅-2 | 多值 `mention_keyword: "小开;arch"` → `["小开", "arch"]` | 两个词均生效 | 单元测试 |
| ✅-3 | 前后空格被 trim：`" 小开 ; arch "` → `["小开", "arch"]` | 健壮解析 | 单元测试 |
| ✅-4 | `@角色名 收到` → 角色名匹配 → 对应 bot 触发 | bot 回复 | 实测 |
| ✅-5 | `@角色英文名 收到` → 英文角色名匹配 → 对应 bot 触发 | bot 回复 | 实测 |
| ✅-6 | 另一角色的英文名触发另一 bot | 对应 bot 回复 | 实测 |
| ✅-7 | 内容不含任何 trigger keyword → 静默不触发 | 不回复、日志 silent | 实测 |
| ✅-8 | 前缀剥离：`bot名 收到` → 剥离 bot 名 → 处理 `收到` | 消息去掉触发词前缀 | 实测 |
| ✅-9 | 前缀剥离：`角色名 内容` → 剥离角色名 → 处理 `内容` | 同上 | 实测 |
| ✅-10 | 前缀剥离长词优先：长触发词优先于短触发词 | 长词优先剥离 | 单元测试 |
| ✅-11 | `@bot名` 路由到 lobby | 与改造前一致 | 实测 |
| ✅-12 | `@角色英文名` 路由到 lobby | 视为 `@bot名` 同等 | 实测 |
| ✅-13 | 环境变量 `MENTION_KEYWORD="bot名;角色名"` 可覆盖配置 | 多值受支持 | 实测 |

### 🎯 3.2 方向 B（配置更新 — PM 工作室通知）

| # | 检查项 |
|:-:|:-------|
| ✅-14 | PM 在工作室中逐个 @通知 各 Gateway bot 告知新的触发词配置 |
| ✅-15 | 各 Gateway bot 收到通知后自查确认 |
| ✅-16 | 非 Gateway bot（TG 通道 / Hermes Agent）确认自身工作模式 |
| ✅-17 | 全部确认后 PM 记录「配置就绪」，继续后续 Step |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| 更复杂的触发条件（正则/大小写不敏感） | 保持 `in` / `startswith` 当前逻辑 | 过度工程，当前已够用 |
| Web 端触发词管理 UI | 不做前端多触发词配置 | CLI 配置即可 |
| 动态 runtime 更新触发词 | 不改已部署容器的热更新 | 配置热更新是另一 Issue |
| Agent Card `trigger_preference` 联动 | R63 Agent Card 已有 `mention_keyword` 字段，但与本轮独立 | 后面轮次再做数据联动 |
| `SeededConfig` 种子格式变更 | `mention_keyword` 字段名不变 | 向下兼容要求 |
| handler.py 或 server 端任何改动 | 纯 gateway-plugin 改动 | 降低风险 |
| TG 通道 bot 的触发改造 | 仅改造 ws-bridge Gateway 插件 | TG 通道单独管 |

---

## 5. 管线计划

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | ✅ 已审核通过 | ✅ |
| **1** | 📋 PM | WORK_PLAN.md | 15min |
| **2** | 👷 Arch | 技术方案 | 10min |
| **3** | 👨‍💻 Dev | 编码实现 | 15min |
| **4** | 👀 Review | 代码审查 | 10min |
| **5** | 🦐 QA | 测试报告 | 10min |
| **6** | 🛠️ Admin | 合并 dev→main，部署，更新 bot 配置 | 15min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `gateway-plugin/__init__.py` | **修改** — `mention_keyword` 初始化解耦、触发检查、前缀剥离、频道路由 4 处 | ~20 行净增 |
| docs/R64/* | **新增** — 需求文档 + WORK_PLAN + 技术方案 + 审查 + 测试 | ~150 行 |
| **合计** | | **~20 行净增代码，零风险** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| `_mention_keyword` 被脚本/日志引用但不兼容列表 | 日志格式变化或错误 | 保留 `_mention_keyword = _mention_keywords[0]` 向后兼容 |
| 前缀剥离顺序：多个触发词可能重叠（如 `"小"` 和 `"小开"`） | 剥离错误 | 按长度降序排列 `_mention_keywords`（长词优先匹配 `startswith`） |
| `_determine_channel` 中 `@kw` 匹配与 `@admin` 硬编码不一致 | 路由异常 | `@admin` 保持硬编码不变，只扩展 `@_mention_keywords` |
| 灰度期间新旧版本混跑 | 新 Gateway 插件被回退时行为不一致 | 先部署 dev 测试，再推 main |

### 5.3 回退方案

如果 `mention_keyword` 多值改造后出现异常，最简单的回退是将所有配置恢复为单值（仅 bot 名），**无需回滚代码**：

```bash
# 回退：在 config.yaml 中将多值改回单值
mention_keyword: "小开"  # 之前是 "小开;arch"
# 重启容器后，_mention_keywords = ["小开"]，行为与改造前完全一致
```

---

## 6. 脱敏检查清单

- [ ] docs/R64/*.md 零内部名残留
- [ ] `grep` 内部名/域名模式零匹配
- [ ] gateway-plugin/__init__.py diff 零内部 URL/IP 泄露
