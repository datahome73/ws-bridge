---
pipeline:
  goal: "Gateway mention_keyword 多触发词支持——单值→分号分割多值，`@角色名` 与 `@bot名` 均可触发 bot"
  steps:
    step2:
      role: arch
      title: 技术方案
      context:
        requirements_url: "${pipeline.requirements_url}"
      output_desc: "技术方案文档 URL（commit SHA）"
      feedback_channel: _admin
      timeout_minutes: 10
      escalation: notify_pm
    step3:
      role: dev
      title: 编码实现
      context:
        requirements_url: "${pipeline.requirements_url}"
        tech_plan_url: "${steps.step2.output}"
      input_from: step2
      output_desc: "代码 commit SHA"
      feedback_channel: _admin
      timeout_minutes: 15
      escalation: notify_pm
    step4:
      role: review
      title: 代码审查
      context:
        requirements_url: "${pipeline.requirements_url}"
        code_commit: "${steps.step3.output}"
      input_from: step3
      output_desc: "审查报告 URL（commit SHA）"
      feedback_channel: _admin
      timeout_minutes: 10
      escalation: notify_pm
    step5:
      role: qa
      title: 测试验证
      context:
        requirements_url: "${pipeline.requirements_url}"
        code_commit: "${steps.step3.output}"
      input_from: step3
      output_desc: "测试报告 URL（commit SHA）"
      feedback_channel: _admin
      timeout_minutes: 10
      escalation: notify_pm
    step6:
      role: admin
      title: 合并部署归档
      context:
        requirements_url: "${pipeline.requirements_url}"
        test_report: "${steps.step5.output}"
      input_from: step5
      output_desc: "main 分支 commit SHA"
      feedback_channel: _admin
      timeout_minutes: 15
      escalation: notify_pm
---

# R64 工作计划 — Gateway 多触发词支持 🎯

> **版本：** v1.0 ✅
> **状态：** ✅ 全部完成 — R64 管线已归档
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R64/R64-product-requirements.md v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动集中在 Gateway 插件，严禁 scope creep**

- ✅ **纳入：** `gateway-plugin/__init__.py`、`docs/R64/*`
- ❌ **不改入：** `server/` 下任何文件（handler.py / config.py / agent_card.py 等）、`templates/`、前端、`shared/`、`clients/`
- ❌ **不引入新依赖：** 不新增 pip 包（纯标准库）
- 编码者超出 scope 的改动，审查者直接打回

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案 ≠ 编码 |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 |
| Step 6 | 🦸 合并部署 | admin | arch | — |

---

## 1. 管线总览

### 1.1 本轮核心交付

| # | 方向 | 交付 | 说明 |
|:-:|:----:|:-----|:------|
| 1 | A1 | 初始化解析 | `mention_keyword` 分号分割为 `_mention_keywords` 列表 + 保留 `_mention_keyword` 兼容 |
| 2 | A2 | 触发检查 | `any(kw in content for kw in list)` 替代单值 `not in` |
| 3 | A3 | 前缀剥离 | 长词优先遍历列表剥离触发词前缀 |
| 4 | A4 | 频道路由 | 遍历 `_mention_keywords` 匹配 `@kw` |
| 5 | C | 顺手修复 | 日志改用列表输出 |

### 1.2 改动范围

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A1 | `__init__` 中 `_raw.split(";")` + `_mention_keywords` 列表 + `_mention_keyword = _mention_keywords[0]` 兼容 | `__init__.py` ~L133 | ~5 行 |
| 2 | A2 | 触发检查 `if not any(...)` | `__init__.py` ~L359 | ~5 行 |
| 3 | A3 | 前缀剥离 `for kw in sorted(...)` 长词优先 | `__init__.py` ~L367 | ~6 行 |
| 4 | A4 | 频道路由 `for kw in self._mention_keywords` | `__init__.py` ~L434 | ~4 行 |
| 5 | C | 初始化日志、silent 日志打印列表 | `__init__.py` L144, L361 | ~2 行 |
| **合计** | | | | **~22 行净增** |

### 1.3 关键设计决策

1. **保留 `_mention_keyword` 兼容** — `_mention_keyword = self._mention_keywords[0]`，供日志/调试引用
2. **长词优先剥离** — `sorted(self._mention_keywords, key=len, reverse=True)`，避免 `"小"` 覆盖 `"小开"`
3. **分号分隔** — 与 `;` 作为分隔符，兼容 `MENTION_KEYWORD` 环境变量
4. **完整向下兼容** — 单值 `"小开"` → `split(";")` → `["小开"]` → 行为零变化

---

## 2. 管线步骤

### Step 1 — PM 准备 + 配置通知晨会

1. 推本 WORK_PLAN.md 到远程 dev 分支
2. 执行 `!pipeline_start R64 --work_plan_url <raw_url>` 启动管线
3. **(新增) 配置通知晨会** — 进入工作室后，PM 逐个 @通知 各 Gateway bot，告知需将 `mention_keyword` 更新为「bot名;角色名」多值格式，重启容器生效。要点：
   - 各 bot 自行查找自己容器的 `config.yaml` 中 `mention_keyword` 值
   - 格式示例：`"bot名;角色名"`（角色名建议用英文，如 dev/arch/review/admin）
   - TG 通道 bot 无需修改，确认当前工作模式即可
   - PM 自己也确认 Hermes Agent 模式
4. 全部确认「配置就绪」后，继续 Step 2

**前置条件：** 需求文档已由项目负责人审核通过 ✅

### Step 2 — Arch 技术方案

**主角：** arch | **备用：** dev

**任务：**
1. 阅读需求文档，理解 A1-A4 四点改造
2. 确认「长词优先」排序逻辑：`sorted(list, key=len, reverse=True)` 是否足够
3. 确认 `_mention_keyword = _mention_keywords[0]` 的向后兼容范围（日志 `L144` `L361`）
4. 确认 `MENTION_KEYWORD` 环境变量同样支持多值（`split(";")` 在 `_env()` 之后）
5. 输出 `docs/R64/R64-tech-plan.md`

**完成条件：** 技术方案文档提交到 dev 分支。

### Step 3 — Dev 编码实现

**主角：** dev | **备用：** arch

**任务：** 依据技术方案完成以下 4 处改动：

#### ⚡ 实施顺序

| 顺序 | 改动 | 文件位置 | 验证 |
|:----|:-----|:---------|:-----|
| 1️⃣ | `__init__` 初始化 — `_raw.split(";")` → `_mention_keywords` | L133 | 单值/多值 parse |
| 2️⃣ | 触发检查 — `if not any(kw in content for kw in list)` | L359 | `@arch` 触发小开 |
| 3️⃣ | 前缀剥离 — `for kw in sorted(list, key=len, reverse=True)` | L367 | `小开 收到` → `收到` |
| 4️⃣ | 频道路由 — `for kw in list: if f"@{kw}" in content` | L434 | `@arch` 路由到 lobby |

**完成条件：** 代码推 dev，服务端重启验证 ✅-1~✅-13 方向 A 逐项通过。

### Step 4 — Review 代码审查

**主角：** review | **备用：** qa

**审查重点：**
1. ✅ **Scope 合规** — 未改 `server/` 下任何文件
2. ✅ **向下兼容** — 单值配置零行为变化
3. ✅ **长词优先** — 排序逻辑正确，避免短词误剥
4. ✅ **`_mention_keyword` 兼容** — 保留字段供日志/调试
5. ✅ **无新依赖** — 纯标准库
6. ✅ **grep 残留零** — 无内部名残留

**完成条件：** 审查报告 `docs/R64/R64-code-review.md` 推 dev。

### Step 5 — QA 测试

**主角：** qa | **备用：** review

**测试场景（方向 A 4 处改造逐一验证）：**

| # | 场景 | 方法 | 预期 |
|:-:|:-----|:-----|:------|
| 1 | 单值 parse | `"小开"` → `["小开"]` | `_mention_keywords[0] == "小开"` |
| 2 | 双值 parse | `"小开;arch"` → `["小开", "arch"]` | 两个词均在列表 |
| 3 | 空格 trim | `" 小开 ; arch "` → `["小开", "arch"]` | 无空格残留 |
| 4 | `@bot名` 触发 | 发 `@bot名 收到` | bot 回复 |
| 5 | `@角色英文名` 触发 | 发 `@角色英文名 内容` | bot 回复 |
| 6 | `@dev` 触发 | 发 `@dev 编码` | dev bot 回复 |
| 7 | 无触发词静默 | 发普通消息不含任何 keyword | 不回复 |
| 8 | 前缀剥离 bot名 | 发 `bot名 收到` | bot 收到 `收到` |
| 9 | 前缀剥离 角色名 | 发 `角色英文名 内容` | bot 收到 `内容` |
| 10 | 长词优先 | 触发词含短词和长词 | 长词优先匹配 |
| 11 | 频道路由 | `@角色英文名` 到工作室 | 路由到 lobby |
| 12 | 环境变量 | `MENTION_KEYWORD="bot名;角色名"` | 多值生效 |

**完成条件：** 测试报告 `docs/R64/R64-test-report.md` 推 dev。

### Step 6 — Admin 合并部署归档

**主角：** admin | **备用：** arch

**操作：**

1. 合并 dev→main
2. 构建新镜像 `docker build -t ws-bridge:r64 . && docker compose up -d`
3. 健康检查：确认各 bot 在线
4. **各 bot 自查配置：** 自行更新 `config.yaml` 中 `mention_keyword`，加入角色名触发词
5. 验证：`@arch` / `@dev` / `@review` / `@admin` 点名实际触发
6. 关闭 R64-dev 工作室：`!close_workspace`
7. TODO.md 更新：标注 F-21 ✅ 已完成

---

## 3. 验收清单（从需求文档复制）

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | 单值 `"小开"` → `["小开"]` | ✅ |
| ✅-2 | 多值 `"小开;arch"` → `["小开", "arch"]` | ✅ |
| ✅-3 | 空格 trim | ✅ |
| ✅-4 | `@bot名 收到` → 触发 | ✅ |
| ✅-5 | `@角色英文名 收到` → 触发 | ✅ |
| ✅-6 | `@角色英文名` 触发另一角色 bot | ✅ |
| ✅-7 | 无触发词 → 静默 | ✅ |
| ✅-8 | 前缀剥离 `bot名 收到` → `收到` | ✅ |
| ✅-9 | 前缀剥离 `角色英文名 内容` → `内容` | ✅ |
| ✅-10 | 长词优先匹配 | ✅ |
| ✅-11 | `@bot名` → lobby 路由 | ✅ |
| ✅-12 | `@角色英文名` → lobby 路由 | ✅ |
| ✅-13 | 环境变量多值支持 | ✅ |
| ✅-14 | PM 在工作室逐个 @通知 各 Gateway bot 新配置 | ✅ |
| ✅-15 | 各 Gateway bot 收到通知后自查确认 | ✅ |
| ✅-16 | 非 Gateway bot 确认自身工作模式 | ✅ |
| ✅-17 | 全部确认后继续后续 Step | ✅ |

---

## 4. 不纳入范围 / 严禁 scope creep

| 事项 | 说明 |
|:-----|:------|
| `server/` 下任何文件改动 | F-21 是纯 Gateway 层问题，不动 handler |
| Web 端触发词管理 UI | CLI 配触发词即可 |
| 动态 runtime 更新触发词 | 重启生效即可 |
| Agent Card `trigger_preference` 联动 | 延后 |
| TG 通道 bot 触发改造 | TG 通道不适用 mention_keyword |

---

## 5. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-02 | 初始版本，基于 R64 需求文档 v1.0 ✅ |
| v1.1 | 2026-07-02 | 归档：全部验收项 ✅，TODO F-21 → 🟢 已完成 |
