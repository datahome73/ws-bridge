# R66 工作计划 — 管线参数化完善

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** 📋 定稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R66/R66-product-requirements.md v1.0 ✅（项目负责人审核通过）

---
pipeline:
  goal: "管线参数化完善 — frontmatter 驱动 Step 链 + Step 产出上下文注入"
  branch: dev
  steps:
    step2:
      role: arch
      title: 技术方案
      primary: arch
      backup: dev
      timeout_minutes: 60
      output_desc: "函数设计与改动点确认"
    step3:
      role: dev
      title: 编码
      primary: dev
      backup: arch
      timeout_minutes: 120
      output_desc: "编码 + 自测"
    step4:
      role: review
      title: 代码审查
      primary: review
      backup: qa
      timeout_minutes: 60
    step5:
      role: qa
      title: 测试验证
      primary: qa
      backup: review
      timeout_minutes: 120
    step6:
      role: admin
      title: 合并部署归档
      primary: admin
      backup: arch
      timeout_minutes: 30
---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动集中，严禁 scope creep**

| 不改入 | 说明 |
|:-------|:------|
| `server/agent_card.py` | Agent Card 持久化是独立轮次，不涉及 |
| `server/pipeline_sync.py` | R65 git sync 逻辑不动，只改消费端 |
| `server/timeout_tracker.py` | 倒计时模块不动 |
| `gateway-plugin/` | Gateway 层不改 |
| `shared/protocol.py` | 协议层不改 |
| 前端 / Web UI | 纯后端改动 |

| 不改出 | 说明 |
|:-------|:------|
| 不引进并行 Step | 超出本轮设计范围 |
| 不做条件分支 | 过度工程 |
| 不做 Agent 注册/API Key 改造 | 独立轮次 |
| 不做 Web 端仪表盘 | 独立轮次 |

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | admin | arch | — |

---

## 1. 管线总览

### 改动范围

仅 `server/handler.py` + 可能 `server/config.py`，精确改动点：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A1 | **新增** `_get_step_config(round_name)` — 公共 step 配置读取函数 | handler.py 新增函数 | ~15 行 |
| 2 | A2 | **新增** `_build_fallback_steps()` — 从 PIPELINE_STEP_MAP 构建，同步 primary/backup | handler.py 新增函数 | ~25 行 |
| 3 | A3 | **修改** 6 处消费点统一替换为 `_get_step_config()` | `_cmd_step_complete/handoff/status/auto_advance/pipeline_start/reject` | ~18 行（6×3） |
| 4 | A4 | **修改** `_auto_advance_pipeline()` — 动态 step 查找 | handler.py L3200 附近 | ~8 行 |
| 5 | B1 | **新增** Step 产出记录逻辑 | `_cmd_step_complete()` 中 | ~8 行 |
| 6 | B2 | **新增** `_render_context()` — 模板变量解（含 `${steps.stepN.xxx}`） | handler.py 新增函数 | ~25 行 |
| 7 | B3 | **修改** 点名消息拼接 — 注入上下文 | `_cmd_step_complete()` 交接处 | ~10 行 |
| 8 | B4 | **修改** `!pipeline_status` 展示 Step 产出 | ~L3082 | ~8 行 |
| 9 | C | **修改** 旧格式兼容守卫 | 贯穿各改动点 | 内置 |

**总估算：** ~100 行净增，~30 行修改

### 与 R65 git sync 的关系

R66 不修改 `pipeline_sync.py`，但 `_auto_advance_pipeline()` 中的 Step 查找逻辑需要从硬编码改为动态 `_get_step_config()`。这是 R65 基建的自然延伸——R65 会走路了（自动推进），R66 让它走哪条路（动态 Step 链）。

### 与 R62 管线参数化的关系

R62 建了骨架（frontmatter 解析器 + `_PIPELINE_CONFIG`），R66 让筋肉附着上去（消费端全部统一走 frontmatter 定义）。

---

## 2. 管线步骤

### Step 2 — 🏗️ 技术方案

**主角：** arch | **备用：** dev

**任务：**
1. 理解需求文档 §2 中三个方向的所有函数和改动点
2. 设计 `_get_step_config()` 的函数签名和逻辑
3. 设计 `_build_fallback_steps()` 的 fallback 逻辑（关注 primary/backup 同步）
4. 设计 `_render_context()` 的模板变量扩展方案（`${steps.stepN.xxx}`）
5. 识别并列出所有 6 处需替换的消费点（精确到行号）
6. 输出 `docs/R66/R66-tech-plan.md`

**注意事项：**
- 消费点查找：`grep -n '_load_step_config\\|_PIPELINE_CONFIG.*get.*steps' server/handler.py`
- `_get_step_config()` 必须是纯函数，不依赖外部状态（只读 `_PIPELINE_CONFIG`）
- `_build_fallback_steps()` 的 primary/backup 字段必须从 `config.PIPELINE_STEP_MAP` 同步——当前 `_build_fallback_config()` 缺失此字段，是个隐含 bug
- `_render_context()` 需要兼容原有的 `${pipeline.xxx}` 变量

**完成条件：**
- [ ] 技术方案文档推 dev
- [ ] `!step_complete step2 --output <sha>`

---

### Step 3 — 💻 编码

**主角：** dev | **备用：** arch

**任务：**

#### 3.1 方向 A：新增公共函数 + 替换消费点

```python
# 新增 — handler.py
def _get_step_config(round_name: str) -> dict:
    """优先 frontmatter，其次 fallback。"""
    pconfig = _PIPELINE_CONFIG.get(round_name, {})
    psteps = pconfig.get("steps", {})
    if psteps:
        return psteps
    return _build_fallback_steps(round_name)


def _build_fallback_steps(round_name: str) -> dict:
    """从 PIPELINE_STEP_MAP 构建 fallback step 配置。"""
    step_map = config.PIPELINE_STEP_MAP
    steps = {}
    for step_key, step_cfg in step_map.items():
        if step_key == "step1":
            continue
        steps[step_key] = {
            "role": step_cfg.get("role", ""),
            "title": step_cfg.get("name", step_key),
            "primary": step_cfg.get("primary"),
            "backup": step_cfg.get("backup"),
            "context": {
                "requirements_url": _get_requirements_url(round_name),
                "work_plan_url": _get_work_plan_url(round_name),
            },
            "output_desc": "",
            "feedback_channel": "_admin",
            "timeout_minutes": int(step_cfg.get("timeout_hours", 6) * 60),
            "escalation": step_cfg.get("escalation", "notify_pm"),
        }
    return steps
```

**6 处替换模式（每处 ~3 行）：**

```python
# ❌ 改造前（各处写法略有不同）：
_pconfig_s = _PIPELINE_CONFIG.get(round_name, {}).get("steps", {})
if _pconfig_s:
    step_config = _pconfig_s
else:
    step_config = _load_step_config()

# ✅ 改造后（统一）：
step_config = _get_step_config(round_name)
```

**6 处位置精确确认（由 arch Step 2 输出精确行号）：**

| # | 函数 | 场景 |
|:-:|:-----|:-----|
| 1 | `_cmd_step_complete()` | Step 完成 → 找下一角色 |
| 2 | `_cmd_step_handoff()` | 跳过/手动推进 |
| 3 | `_cmd_pipeline_status()` | 展示状态 |
| 4 | `_auto_advance_pipeline()` | git sync 自动推进 |
| 5 | `_cmd_pipeline_start()` | 启动时读取配置 |
| 6 | `_cmd_step_reject()` / 退回处理 | 退回后找重试 |

#### 3.2 方向 A4：`_auto_advance_pipeline()` 动态化

```python
# ❌ 改造前：
next_step = f"step{int(current_step.replace('step', '')) + 1}"

# ✅ 改造后：
step_config = _get_step_config(round_name)
step_keys = sorted(step_config.keys(), key=_step_sort_key)
current_idx = next(i for i, k in enumerate(step_keys) if k == current_step)
if current_idx + 1 < len(step_keys):
    next_step = step_keys[current_idx + 1]
```

#### 3.3 方向 B1：产出记录

```python
# 在 _cmd_step_complete() 中，约 step_complete 成功处理后：
pstate = _PIPELINE_STATE.get(round_name, {})
if pstate:
    step_outputs = pstate.setdefault("step_outputs", {})
    step_outputs[step_name] = {
        "sha": output_ref,
        "timestamp": time.time(),
        "output_desc": step_config.get(step_name, {}).get("output_desc", ""),
    }
```

#### 3.4 方向 B2：`_render_context()`

```python
def _render_context(context: dict, round_name: str, step_outputs: dict) -> dict:
    """解析 context 模板变量，返回渲染后的 dict。"""
    # 先取 pipeline-level 变量
    pconfig = _PIPELINE_CONFIG.get(round_name, {})
    resolved = {}
    for ctx_key, ctx_value in context.items():
        if not isinstance(ctx_value, str):
            resolved[ctx_key] = ctx_value
            continue
        value = ctx_value
        # ${pipeline.xxx} — 原有逻辑
        if "${pipeline." in value:
            ref = value.split("${pipeline.", 1)[1].rstrip("}")
            if ref in pconfig:
                value = value.replace("${pipeline." + ref + "}", str(pconfig[ref]))
        # ${steps.stepN.xxx} — 新增逻辑
        if "${steps." in value:
            ref = value.split("${steps.", 1)[1].rstrip("}")
            parts = ref.split(".", 1)
            if len(parts) == 2:
                step_key, field = parts
                step_out = step_outputs.get(step_key, {})
                value = value.replace("${steps." + ref + "}", str(step_out.get(field, "")))
        resolved[ctx_key] = value
    return resolved
```

#### 3.5 方向 B3：点名消息增强

在 `_cmd_step_complete()` 中生成点名消息时，将渲染后的 context dict 穿件到消息中：

```python
# 在点名消息拼接处，约管线交接逻辑中：
context = step_config.get(next_step, {}).get("context", {})
rendered = _render_context(context, round_name, step_outputs)
context_lines = []
for ctx_key, ctx_value in rendered.items():
    if ctx_value:
        context_lines.append(f"  📎 {ctx_key}: {ctx_value}")
if context_lines:
    rollcall_msg += "\n" + "\n".join(context_lines)
```

#### 3.6 方向 B4：`!pipeline_status` 展示

```python
# 在 _cmd_pipeline_status() 或 _format_step_status() 中：
step_outputs = pstate.get("step_outputs", {})
for step_key in completed_steps:
    out = step_outputs.get(step_key, {})
    sha = out.get("sha", "")[:7]
    desc = out.get("output_desc", "")
    if sha or desc:
        lines.append(f"  └─ 产出: {sha}{' — ' + desc if desc else ''}")
```

#### 3.7 方向 C：旧格式兼容验证

- 所有旧格式代码路径在实际执行中不会进入新逻辑（`_get_step_config()` 返回 fallback → 行为不变）
- `_load_step_config()` 函数保留但不被 6 处消费点引用（仅在 `_build_fallback_steps()` 内部引用）
- 部署后先用 R65 WORK_PLAN 走一次管线验证退化路径

**完成条件：**
- [ ] 代码推 dev
- [ ] 代码包含 `_get_step_config()` + `_build_fallback_steps()`
- [ ] 6 处消费点全部替换
- [ ] `_auto_advance_pipeline()` 动态化
- [ ] B1 产出记录逻辑
- [ ] B2 `_render_context()` 实现
- [ ] B3 点名消息注入上下文
- [ ] B4 `!pipeline_status` 展示产出
- [ ] 旧格式兼容守卫
- [ ] `!step_complete step3 --output <sha>`

---

### Step 4 — 🔍 代码审查

**主角：** review | **备用：** qa

**审查重点：**
1. ✅ 6 处消费点全部替换为 `_get_step_config()`（`grep '_load_step_config'` 零消费残留）
2. ✅ `_build_fallback_steps()` 正确从 `PIPELINE_STEP_MAP` 同步 primary/backup
3. ✅ `_render_context()` 兼容原有 `${pipeline.xxx}` 变量，不破坏旧 frontmatter
4. ✅ 旧格式管线（无 frontmatter）启动正常
5. ✅ 空产出变量容错（返回空字符串而非报错）
6. ✅ 编码者 ≠ 审查者 ✅

**完成条件：**
- [ ] 审查报告推 dev
- [ ] `!step_complete step4 --output <sha>`

---

### Step 5 — 🦐 测试验证

**主角：** qa | **备用：** review

**测试方法：** 模拟验证 + 代码审计
**轮次性质：** 后端改动，无可运行的测试环境

| # | 验收标准 | 测试方法 |
|:-:|:---------|:---------|
| ✅-1 | 3 步 frontmatter → 管线只走 3 步 | 代码审计：`_get_step_config()` + step_keys 排序逻辑 |
| ✅-2 | 7 步 frontmatter → 正常走 | 同上 |
| ✅-3 | 新角色 `security_review` → 点名正确 | 代码审计：role 字段传递链 |
| ✅-4 | 无 frontmatter → fallback 6 步 | 代码审计：`_build_fallback_steps()` 完整性 |
| ✅-5 | fallback 含 primary/backup | 代码审计：`_build_fallback_steps()` 中同步逻辑 |
| ✅-6 | 零 `_load_step_config()` 消费残留 | 代码审计：`grep '_load_step_config'` 只出现于 `_build_fallback_steps` |
| ✅-7 | auto-advance 动态找下一步 | 代码审计：`_auto_advance_pipeline()` 使用 `_get_step_config()` + `_step_sort_key` |
| ✅-8 | 自定义 Step 名（step_a/b/c） | 代码审计：`_step_sort_key` 支持非数字 Step 名 |
| ✅-9 | 产出自动记录 | 代码审计：B1 产出记录逻辑 |
| ✅-10 | 点名消息自动注入上下文 | 代码审计：B2/B3 渲染和拼接逻辑 |
| ✅-11 | `${steps.stepN.sha}` 正确解 | 代码审计：`_render_context()` 模板变量解析 |
| ✅-12 | 未完成 Step 产出容错 | 代码审计：空产出返回空字符串 |
| ✅-13 | `!pipeline_status` 展示产出 | 代码审计：status 输出增强逻辑 |
| ✅-14~16 | 旧格式兼容 | 代码审计：退化路径无侵入 |

**完成条件：**
- [ ] 测试报告推 dev
- [ ] `!step_complete step5 --output <sha>`

---

### Step 6 — 🦸 合并部署归档

**主角：** admin | **备用：** arch

**任务：**
1. 合并 dev → main
2. 构建新镜像 `ws-bridge:r66`
3. 部署 dev 容器验证（验证前线管自动流转）
4. 部署 main 容器
5. 健康检查：`!pipeline_status` 正常、旧格式管线正常
6. 更新 TODO.md
7. 归档工作室、恢复大厅

**完成条件：**
- [ ] 合并 dev→main 推远程
- [ ] 镜像构建并部署
- [ ] 健康检查通过
- [ ] `!pipeline_status` 正常
- [ ] 旧 R65 WORK_PLAN 启动验证通过
- [ ] TODO.md 已更新
- [ ] `!step_complete step6 --output <sha>`

---

## 3. 验收清单（从需求文档复制）

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | frontmatter 定义 3 步 → 管线只走 3 步 | ⏳ |
| ✅-2 | frontmatter 定义 7 步 → 正常走 7 步 | ⏳ |
| ✅-3 | frontmatter 定义新角色 → 点名正确 | ⏳ |
| ✅-4 | `_get_step_config()` 无 frontmatter → fallback 6 步 | ⏳ |
| ✅-5 | fallback 包含 primary/backup | ⏳ |
| ✅-6 | 6 处消费全部替换，零残留 | ⏳ |
| ✅-7 | auto-advance 动态找下一步 | ⏳ |
| ✅-8 | 自定义 Step 名可运行 | ⏳ |
| ✅-9 | 产出自动记录 | ⏳ |
| ✅-10 | 点名消息含上下文 | ⏳ |
| ✅-11 | `${steps.stepN.sha}` 模板变量正确解 | ⏳ |
| ✅-12 | 未完成 Step 容错（空值） | ⏳ |
| ✅-13 | `!pipeline_status` 展示产出 | ⏳ |
| ✅-14 | 无 frontmatter → 管线正常 | ⏳ |
| ✅-15 | 旧格式主备正常 | ⏳ |
| ✅-16 | partial frontmatter → fallback 正常 | ⏳ |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-03 | 初稿，基于 R66 需求文档 v1.0 ✅ 起草 |
