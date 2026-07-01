# R62 产品需求 — 管线参数化改造（过渡轮次）

> **版本：** v1.0（初稿，待项目负责人审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-01
> **本轮改动范围：** `server/handler.py` + `server/config.py` — 管线引擎参数抽离，Step 配置从 WORK_PLAN 驱动
> **参考：** TODO R61-1（🟡 P2 管线跳过Step状态丢失）、A2A 协议调研报告 §4.1

---

## 1. 问题背景

### 1.1 当前架构：参数全硬编码

ws-bridge 管线引擎经过 R42~R61 多轮迭代，功能已成型，但**所有 step 定义**都嵌在代码中：

| 硬编码项 | 位置 | 问题 |
|:---------|:-----|:-----|
| **角色映射** | `config.py` L73-86 `PIPELINE_STEP_MAP` | 换项目需改代码、重新部署 |
| **Step 顺序** | `handler.py` L1529 `step_keys = sorted(...)` | 隐式依赖命名约定 |
| **需求文档 URL** | `handler.py` L1343 `raw.githubusercontent.com/.../{round_name}/...` | 代码里硬拼，不可配置 |
| **上下文消息模板** | `handler.py` L1340-1346 R58 A3 kickoff_msg | 消息格式写死在字符串里 |
| **产出引用** | `handler.py` L1601 `context_summary = f"上一步产出: {output_ref}"` | 无结构化产出定义 |
| **反馈途径** | 硬编码 `_admin` 频道 | 无法灵活指定 |
| **超时阈值** | `config.py` 已定义但 handler 中部分未引用 | 新路径不使用 |

### 1.2 连锁效应：R61-1 状态丢失

```
_PIPELINE_STATE = {active, current_step, ws_id}    ← 运行时内存
                         │
手动跳过 Step → _clear_pipeline_state()             ← 全部清空
                         │
后续 !step_complete → 找不到 round_name → 拒绝     ← 管线断裂
```

**根因：** 运行时 state（`_PIPELINE_STATE`）同时承载了两层职责：
1. **配置层**（step 定义、角色顺序、URL）— 应当是只读不变的
2. **运行时层**（当前进行到哪 step、谁在线）— 允许跳过/重置

两层混在一起，跳过 Step 导致整个 state 被清空。

### 1.3 设计原则

> **参数化驱动：** 管线引擎只执行参数包，不关心业务逻辑。
> **人机分离：** 人读 Markdown（WORK_PLAN.md），bot 读 JSON（pipeline_config.json）。
> **一次生成，多次消费：** `!pipeline_start` 从 WORK_PLAN 生成 config 后，所有 Step 流转只读 config。
> **灰度过渡：** 旧硬编码路径保留为 fallback，新 config 不存在时退化到旧行为。

---

## 2. 功能需求

### 方向 A（核心）：Step 参数包定义 + 管线初始化注入 🔴 P0

**目标：** 在 WORK_PLAN 审核通过后，`!pipeline_start` 根据 WORK_PLAN 内容生成 `_PIPELINE_CONFIG`，后续所有 Step 流转从此 config 读取参数。

#### A1 — 定义 pipeline_config schema

每个 workstation 持有一份只读的 step 参数包：

```json
{
  "round": "R62",
  "goal": "管线参数化，work_plan 驱动 step 配置",
  "work_plan_url": "https://raw.githubusercontent.com/.../WORK_PLAN.md",
  "requirements_url": "https://raw.githubusercontent.com/.../R62-product-requirements.md",
  "steps": {
    "step2": {
      "role": "arch",
      "title": "技术方案",
      "context": {
        "requirements_url": "${pipeline.requirements_url}",
        "work_plan_url": "${pipeline.work_plan_url}"
      },
      "output_desc": "技术方案文档 URL",
      "feedback_channel": "_admin",
      "timeout_minutes": 15,
      "escalation": "notify_pm"
    },
    "step3": {
      "role": "dev",
      "title": "编码实现",
      "context": {
        "requirements_url": "${pipeline.requirements_url}",
        "work_plan_url": "${pipeline.work_plan_url}",
        "tech_plan_url": "${steps.step2.output}"
      },
      "input_from": "step2",
      "output_desc": "代码 commit SHA",
      "feedback_channel": "_admin",
      "timeout_minutes": 20,
      "escalation": "notify_pm"
    },
    "step4": {
      "role": "review",
      "title": "代码审查",
      "context": {
        "requirements_url": "${pipeline.requirements_url}",
        "work_plan_url": "${pipeline.work_plan_url}",
        "code_commit": "${steps.step3.output}"
      },
      "input_from": "step3",
      "output_desc": "审查报告 URL",
      "feedback_channel": "_admin",
      "timeout_minutes": 15,
      "escalation": "notify_pm"
    },
    "step5": {
      "role": "qa",
      "title": "测试验证",
      "context": {
        "requirements_url": "${pipeline.requirements_url}",
        "work_plan_url": "${pipeline.work_plan_url}",
        "code_commit": "${steps.step3.output}"
      },
      "input_from": "step3",
      "output_desc": "测试报告 URL",
      "feedback_channel": "_admin",
      "timeout_minutes": 15,
      "escalation": "notify_pm"
    },
    "step6": {
      "role": "admin",
      "title": "合并部署归档",
      "context": {
        "requirements_url": "${pipeline.requirements_url}",
        "work_plan_url": "${pipeline.work_plan_url}",
        "test_report": "${steps.step5.output}"
      },
      "input_from": "step5",
      "output_desc": "main 分支 commit SHA",
      "feedback_channel": "_admin",
      "timeout_minutes": 10,
      "escalation": "notify_pm"
    }
  }
}
```

#### A2 — WORK_PLAN.md 增加 YAML frontmatter（机器段）

**人眼不可见段**（YAML frontmatter，markdown 解析器默认隐藏）：

```yaml
---
pipeline:
  goal: "管线参数化，work_plan 驱动 step 配置"
  steps:
    step2:
      role: arch
      title: 技术方案
      context:
        requirements_url: "${pipeline.requirements_url}"
        work_plan_url: "${pipeline.work_plan_url}"
      output_desc: "技术方案文档 URL"
      feedback_channel: _admin
      timeout_minutes: 15
      escalation: notify_pm
    step3:
      role: dev
      title: 编码实现
      ...
---
```

**人读部分保持不变**——自然语言描述各 step 任务、验收标准。两段互不干扰。

> **注意：** 当前 WORK_PLAN.md 不含 YAML frontmatter。R62 是过渡轮次——**旧格式 WORK_PLAN 兼容支持，退化到当前硬编码行为。**

#### A3 — `!pipeline_start` 解析 frontmatter 生成 `_PIPELINE_CONFIG`

```
!pipeline_start R62
    │
    ├─ 读取 WORK_PLAN URL → 获取文件内容
    ├─ 尝试解析 YAML frontmatter (---...---)
    │   ├─ 成功 → 填充 context URL 模板变量 → 生成 _PIPELINE_CONFIG
    │   └─ 失败（旧格式）→ 退化到当前硬编码行为
    └─ 存储 _PIPELINE_CONFIG[round_name] = {...}
```

**关键点：**
- `_PIPELINE_CONFIG` 与 `_PIPELINE_STATE` **分离为两个独立 dict**
- config 只读 + 不变，state 可写 + 可跳过
- config 不因 `_clear_pipeline_state()` 而被清除

#### A4 — `!step_complete` / `!step_handoff` 改从 config 读参数

| # | 当前行为 | 新行为 |
|:-:|:---------|:-------|
| 拼接需求 URL | 硬编码 `raw.githubusercontent.com/.../docs/{round_name}/...` | 从 config 读 `steps.stepN.context.requirements_url` |
| 找下一 step | `step_keys[current_idx + 1]` — 硬编码顺序 | 从 config 读 `steps` 的键顺序 |
| 消息模板 | `f"下一棒：{target_role} → {next_step}"` 硬编码 | 从 config 读 `steps.stepN.title` |
| 上一步产出引用 | `context_summary = f"上一 Step {step_name} 产出: {output_ref}"` | 从 config 读 `steps.stepN.input_from` + output_ref |

#### A5 — 状态丢失修复（配置层 + 运行时层分离）

```python
# 当前：两层耦合
_PIPELINE_STATE[round_name] = {
    "active": True,
    "current_step": "step2",
    "ws_id": "...",
}

# 目标：分层
_PIPELINE_CONFIG[round_name] = {
    "steps": {...},       # 只读，Step 1 生成，不被清除
    "goal": "...",
    "requirements_url": "...",
    "work_plan_url": "...",
}
_PIPELINE_STATE[round_name] = {
    "active": True,
    "current_step": "step2",
    "ws_id": "...",
    "started_at": ...,
}
```

**效果：** 即使 `!step_handoff` 跳过 step 导致 `<某种情况下>_PIPELINE_STATE` 被清空，引擎从 `_PIPELINE_CONFIG` 即可恢复——step 顺序、角色映射、URL 都在 config 里，不需要从头重建。

### 方向 B（辅助）：旧格式兼容守卫 🟡 P2

**目标：** 没有 frontmatter 的旧 WORK_PLAN 不应报错或阻塞管线。

**实现：**

```python
# pipeline_start 中
try:
    config_data = _parse_frontmatter(work_plan_content)
    _PIPELINE_CONFIG[round_name] = _build_pipeline_config(config_data, round_name)
except NoFrontmatterError:
    # 兼容旧格式：用代码中现有的 PIPELINE_STEP_MAP 和硬编码 URL
    _PIPELINE_CONFIG[round_name] = _build_fallback_config(round_name)
    write_chat_log("系统", f"📋 {round_name}：使用旧格式配置（无 machine-frontmatter）")
```

**守卫条件：**
- 尝试解析 frontmatter 失败 → 静默退化，不报错
- 新版 config 中的 step key 必须与 `PIPELINE_STEP_MAP` 兼容（`step2`~`step6`）
- 解析成功但格式错误（缺必要字段）→ 退化到旧格式，日志报 warning

---

## 3. 验收标准

### 🎯 3.1 方向 A（核心）

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-1 | `!pipeline_start R62` 解析 frontmatter | 非旧格式 WORK_PLAN → 成功生成 `_PIPELINE_CONFIG`，无报错 |
| ✅-2 | `_PIPELINE_CONFIG` 与 `_PIPELINE_STATE` 分离 | state 被清除后 config 独立存在 |
| ✅-3 | `!step_complete` 从 config 读参数 | URL 拼接、step 角色、消息模板均来自 config，不再硬编码 |
| ✅-4 | `!step_handoff` 从 config 读下一 step | step 顺序、下一角色从 config 读取，不再走 `step_keys` 排序 |
| ✅-5 | state 丢失后 `!pipeline_status` 仍可读 config 信息 | `!pipeline_status` 展示 config 中定义的 step 列表（即使 state 不活跃）|
| ✅-6 | step 交接消息使用 `steps.stepN.title` | 消息显示「技术方案 → 编码实现」，不再硬编码「Step2 → Step3」|

### 🎯 3.2 方向 B（兼容）

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-7 | 旧格式 WORK_PLAN（无 frontmatter）不报错 | 退化到 `_build_fallback_config`，管线正常启动 |
| ✅-8 | 退化时写一条日志 | `write_chat_log("系统", "使用旧格式配置...")` |
| ✅-9 | frontmatter 格式错误不阻塞 | 静默退化，不报错 |

### 🎯 3.3 状态丢失修复

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-10 | `!step_handoff` 跳过 Step→state 清空后，`!pipeline_status` 仍返回 step 列表 | 从 config 读取 step 定义 |
| ✅-11 | 手动 `!step_handoff stepX` 后，`!pipeline_start` 不报「管线已活跃」| 旧 state 不存在，config 存在不影响重新启动 |
| ✅-12 | 正常流转不变 | `!step_complete Step2 → Step3 → Step4` 与改造前行为一致 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:-----|
| F-16 Agent Card 角色持久化 | 不引入 Agent Card 作为角色数据源 | 下一轮专项处理 |
| D-4 历史文档脱敏 | 不清理 docs/R{N}/*.md | 不在本轮范围 |
| WORK_PLAN 编辑器/模板生成器 | 不写前端或 CLI 生成 frontmatter 的工具 | 保持手动编写 |
| 多项目配置模板 | 不为其他项目创建 pipeline_config 模板 | 先搭骨架，模板化延后 |
| `!step_reject` 参数化改造 | 不改造退回命令的硬编码 | 影响较小，延后 |
| Web 端 Tab 页加载空白（F-9）| 不排查 | 基础设施问题，不在代码层 |
| 非 step2~step6 的自定义 step | 不引入动态 step 数 | R62 只重构现有 5+1 step 的读取方式 |

---

## 5. 管线计划

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md + config schema 定义 | 20min |
| **2** | 👷 Arch | 技术方案（各 A1-A5 具体实现路径） | 15min |
| **3** | 👨‍💻 Dev | 编码 + 测试（handler.py + config.py 改动） | 25min |
| **4** | 👀 Review | 代码审查（重点关注兼容守卫路径） | 15min |
| **5** | 🦐 QA | 测试报告（新老格式兼容测试） | 15min |
| **6** | 🛠️ Admin | 合并 dev→main，部署，归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/config.py` | 新增 `_PIPELINE_CONFIG` 全局变量？或直接在 handler.py 中新增 | ~5 行 |
| `server/handler.py` | **新增** `_parse_frontmatter()`、`_build_pipeline_config()`、`_build_fallback_config()` | ~50 行 |
| `server/handler.py` | **修改** `_cmd_pipeline_start()` — 解析 frontmatter → 生成 config | ~15 行 |
| `server/handler.py` | **修改** `_cmd_step_complete()` — 改从 config 读参数 | ~20 行 |
| `server/handler.py` | **修改** `_cmd_step_handoff()` — 改从 config 读参数 | ~15 行 |
| `server/handler.py` | **修改** `_cmd_pipeline_status()` — 支持 config-only 模式 | ~10 行 |
| `server/handler.py` | **修改** `_clear_pipeline_state()` — 不清理 config | ~3 行 |
| `docs/R62/WORK_PLAN.md` | 新增 YAML frontmatter 示例 | ~30 行 |
| **合计** | **净增 ~80 行，修改 ~50 行** | **~130 行** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| 新管道与旧 step_complete 路径冲突 | 旧 Bot 调 `!step_complete` 可能走错路径 | 方向 B 兼容守卫+退化静默 |
| config 格式定义不完整导致后续轮次再改 schema | 浪费重构成本 | schema 精简，只抽离当前硬编码项，不做过度设计 |
| 状态丢失修复不彻底 | 问题仍然存在 | ✅-10/✅-11 作为验收标准严格测试 |

---

## 6. 脱敏检查清单

- [ ] docs/R62/*.md 零内部名残留
- [ ] 代码 diff 零内部名/URL/端口泄露
- [ ] `grep` 内部名/域名模式 零匹配
