# R123 开发计划

> **仓库：** `datahome73/ws-bridge`（ws-bridge 服务端）
> **状态：** ✅ Step 1 审核通过 → 已推 dev

---

## 角色分工

| 角色 | 成员 | 职责 |
|:----:|:----:|:-----|
| 📋 PM | 小谷 | 任务编排 + 部署 + 归档 |
| 📐 Arch | 小开 | 技术方案设计 |
| 💻 Dev | 爱泰 | 编码实现 |
| 👁 Review | 小周 | 代码审查 |
| 🧪 QA | 泰虾 | 测试验证 |
| 🚢 Ops | 小爱 | 合并部署 + 生产上线 |

---

## 各 Step 任务详情

### Step 2 — 技术方案（小开）

**任务：**
评估 R123 跨 Step 上下文字动注入的技术方案，产出 `docs/R123/R123-tech-plan.md`。

需要回答以下问题：

1. **Step 产出记录位置：** `_try_advance_pipeline` 中在 advance 之前还是之后记录 step output 和 result_msg？
   - `ctx.steps[i]["output"]` 记录哪些字段？优先从 `##key=value` 提取还是从完成消息分析？
   - `ctx.steps[i]["result_msg"]` 是否截断长度？
2. **动态模板方案：**
   - 确定 Option 1（增强 `_render_template`）的具体实现
   - 动态变量命名格式：`{step2:sha}` vs `{prev_step2_sha}` vs `{step2_sha}`？
   - `_render_template` 从 `ctx.steps[i].output` 中查找变量的实现路径
3. **完成摘要格式：**
   - 派活消息头部附加的摘要文本格式确认（Markdown 版）
   - 摘要内容来源：`ctx.steps[i].agent_name` / `ctx.steps[i].output` / `ctx.steps[i].result_msg`
   - Step 2 派活（前面只有 Step 1 PM）是否显示摘要？
4. **向后兼容：**
   - 旧 `pipeline_contexts.json` 文件中的 `output: null`、`result_msg: ""`、缺失字段如何安全读取？
   - 已有 R115 artifact 逻辑是否完全不动？
5. **改动范围确认：** 涉及文件是否仅 `server/ws_server/main.py`（`_try_advance_pipeline` / `_auto_dispatch` / `_render_template` 三处）？

**产出格式：** 按 `docs/templates/R-tech-plan.md` 模板编写。

---

### Step 3 — 编码（爱泰）

**任务：**
按小开的技术方案实现跨 Step 上下文字动注入。

**变更文件：**

| 文件 | 改动说明 |
|:-----|:---------|
| `server/ws_server/main.py` | `_try_advance_pipeline` 增强（记录 step output + result_msg） + `_auto_dispatch` 增强（重建模板 / 注入摘要） + `_render_template` 增强（动态变量支持） |

**实现要点：**

#### 3.1 Step 产出自动记录

在 `_try_advance_pipeline` 成功解析完成消息并推进 step **之前**，执行产出记录：

```python
# 伪代码逻辑
if completed_step == old_step:
    # R123: 记录 step 产出
    step_idx = completed_step - 1
    step_info = ctx.steps[step_idx]

    # 从 ##key=value 提取（已有的 R115）
    _kv = _extract_artifact_kv(content)
    if _kv:
        ctx.artifacts[f"step{completed_step}"] = _kv

    # R123: 记录 output 和 result_msg
    output = {}
    if _kv and "sha" in _kv:
        output["sha"] = _kv["sha"]
    if _kv and "commit_msg" in _kv:
        output["commit_msg"] = _kv["commit_msg"]
    # 也记录其他有用的 artifact KV
    if _kv:
        for useful_key in ("tech_plan_url", "branch_name", "test_scope",
                           "test_report_url", "test_summary", "review_url"):
            if useful_key in _kv:
                output[useful_key] = _kv[useful_key]

    step_info["output"] = output if output else None
    step_info["result_msg"] = content[:200]  # 截断，防止过长
```

**关键约定：bot 在完成消息中用 `##sha=xxx##commit_msg=xxx` 等 key 手动传递信息，Server 不自动调 git 获取。**

#### 3.2 `_render_template` 增强（支持动态变量）

**当前能力：** `_render_template` 只从 `ctx` 基本字段和 `ctx.references` 查找 `{round}`、`{round_title}`、`{requirements_url}`、`{work_plan_url}`。

**增强后支持：**

```python
# 新增变量来源（优先级：artifacts > steps > references > 基本字段）
# 格式：{step2:sha}  → ctx.artifacts["step2"].get("sha", "")
#        {step2:tech_plan_url} → ctx.artifacts["step2"].get("tech_plan_url", "")
#        {step2:agent_name}    → ctx.steps[1].get("agent_name", "")
#        {step2:result_msg}    → ctx.steps[1].get("result_msg", "")
```

`_render_template` 增强路径：
1. 从 `{stepN:field}` 格式提取 step 序号 N 和字段名 field
2. 从 `ctx.artifacts` 中查找 `stepN.get(field)`
3. 从 `ctx.steps[N-1]` 中查找 `output.get(field)`
4. 从 `ctx.steps[N-1]` 中查找 `get(field)`（如 `agent_name`、`result_msg`）
5. 找不到则替换为空字符串

**原有 `{round}`、`{requirements_url}` 等变量不受影响。**

#### 3.3 完成摘要注入

在 `_auto_dispatch` 中派活消息模板渲染完后，在内容的**开头**追加一段摘要：

**Step N >= 3 时触发**，遍历已完成的前置步骤构造摘要。

**格式（Markdown）：**

```
══════ 前置步骤 ══════

**Step 2** 📐 Arch（小开） ✅
提交: `abc1234` — feat(R123): add tech plan
产出: [技术方案](https://...)

**Step 3** 💻 Dev（爱泰） ✅
提交: `def5678` — feat(R123): implement core
分支: dev

════════════════════
```

**摘要数据来源：**
- step 角色 emoji 来自固定的 role emoji 映射（同 `_notify_pm` 中的 `role_names`）
- agent_name 来自 `ctx.steps[i].get("agent_name", "?")`
- 如果 `output.sha` 存在 → 显示 `提交: \`{sha}\` — {commit_msg}`
- 如果 `output` 中有 URL 类字段 → 显示 `产出: [field_name](url)`
- 如果 `result_msg` 存在且无更详细数据 → 显示 `结果: {result_msg_truncated}`
- step status 不是 "done" 时不显示该 step

#### 3.4 向后兼容

- `ctx.steps[i].get("output")` 安全读取，`output: null` / `output: {}` / `output` 不存在均可
- `ctx.steps[i].get("result_msg", "")` 安全读取
- `ctx.artifacts.get("stepN", {})` 安全读取
- 已有 R115 artifacts 存储逻辑不修改
- 已有 R120 step 状态标记逻辑不修改
- `_render_template` 原有 `{round}`、`{round_title}` 等变量的查找逻辑不删除，只扩展

**交付要求：**
- 提交格式：`feat(R123): Step 3 — 跨 Step 上下文字动注入`
- 推 `dev` 分支
- 确保 ruff lint 通过

---

### Step 4 — 代码审查（小周）

**任务：**
审查爱泰对 `main.py` 的变更。

**审查要点：**
1. `_try_advance_pipeline` 中产出记录的时机是否正确（advance 之前记录）
2. `output` 字段覆盖是否完备（sha/commit_msg/tech_plan_url/branch_name 等）
3. `_render_template` 新增变量解析是否存在注入或正则安全问题
4. 摘要注入是否在 `_auto_dispatch` 的 par 位置追加（不破坏模板原有结构）
5. 向后兼容：旧 JSON 数据（`output: null`、无 `result_msg`）是否安全读取
6. 已有 R115/R120 逻辑是否被误改

**产出格式：** `docs/R123/R123-code-review.md`

---

### Step 5 — 测试验证（泰虾）

**产出：** `docs/R123/R123-test-report.md`

在 dev 测试环境容器上验证跨 Step 上下文注入功能。

**验证项：**

| # | 验证项 | 预期 |
|:-:|:-------|:-----|
| ① | 完成消息 `已完成 ✅ R123 Step 2##sha=abc1234` 后，`ctx.steps[1].output.sha == "abc1234"` | output 正确记录 |
| ② | 完成消息无 `##` 时，`ctx.steps[1].result_msg` 保存原文 | result_msg 退路正确 |
| ③ | `ctx.steps[1].result_msg` 截断不超过 200 字符 | 超长安全 |
| ④ | Step 3 派活消息中出现 `{step2:sha}` 对应的 SHA 值 | 动态变量解析正确 |
| ⑤ | Step 3 派活消息头部出现前置步骤摘要（含 Step 2） | 摘要注入正确 |
| ⑥ | Step 5 派活消息头部出现 Step 2/3/4 的完整摘要 | 多 step 摘要正确 |
| ⑦ | Step 2 派活消息**不包含**摘要（前面只有 Step 1 PM） | 摘要按条件触发 |
| ⑧ | 从旧 `pipeline_contexts.json` 恢复管线（`output: null`），正常派活不报错 | 向后兼容 |
| ⑨ | 已有 `{round}`、`{requirements_url}` 变量继续正常渲染 | 不破坏 |
| ⑩ | 无 artifacts 时不产生空占位符或空行 | 清理干净 |
| ⑪ | `ruff check server/ws_server/main.py` 通过 | 无 lint 问题 |

---

### Step 6 — 合并部署归档（小爱）

**部署流程：**

1. **测试环境部署（ws-bridge-dev）：**
   - 构建 `ws-bridge:r123-dev` 镜像
   - 部署到 dev 测试环境容器
   - 健康检查：WSS 8765 + Web UI 8766
   - 启动日志确认 `feat(R123)` 代码生效

2. **QA 验证通过后合并 main：**
   - `git checkout main && git merge dev`
   - `git push origin main`

3. **生产部署：**
   - 构建 `ws-bridge:r123` 镜像
   - 更新生产环境容器
   - 确认启动日志正常

4. **归档：**
   - 全员 ACK
   - 归档轮次文档

---

## 验收检查表

| # | 验收项 | 优先级 |
|:-:|:------|:-----:|
| A-1 | 完成消息 `##sha=abc1234` 记录到 `ctx.steps[i].output.sha` | P0 🟢 |
| A-2 | 完成消息原文记录到 `ctx.steps[i].result_msg`（200 字符截断） | P0 🟢 |
| A-3 | step output + result_msg 持久化到 `pipeline_contexts.json` | P0 🟢 |
| B-1 | `{step2:sha}` 在派活消息中渲染为实际 SHA 值 | P0 🟢 |
| B-2 | `{step2:tech_plan_url}` 渲染为实际 URL | P0 🟢 |
| B-3 | 无 artifacts 时占位符不显示，不产生空行 | P1 🟡 |
| C-1 | Step 3+ 派活消息头部追加摘要 | P0 🟢 |
| C-2 | 摘要格式正确（step/role/agent/sha/产出链接） | P1 🟡 |
| C-3 | Step 2 不出现摘要 | P2 🔵 |
| D-1 | 旧 `pipeline_contexts.json` 可安全加载（`output: null`） | P0 🟢 |
| D-2 | `{round}` `{requirements_url}` 等旧变量继续正常渲染 | P0 🟢 |
| D-3 | R115 artifacts + R120 step 状态标记不破坏 | P0 🟢 |
| D-4 | ruff lint 通过 | P0 🟢 |
