# R124 开发计划

> **仓库：** `datahome73/ws-bridge`（ws-bridge 服务端）
> **状态：** ✅ Step 1 审核通过 → 待推 dev

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
评估 R124 四项需求的技术方案，产出 `docs/R124/R124-tech-plan.md`。

需要回答以下核心问题：

#### 需求 A — 驳回状态回退

1. **识别入口：** `退回 🔄` 前缀已在 `_handle_server_relay` 中匹配，但当前仅转发给 PM。需新增一个处理器（如 `_handle_reject_back`）来操作 PipelineContext。插入点：在 relay 中 `退回 🔄` 匹配后、return True 之前。
2. **回退逻辑：** 
   - 解析轮次 `R{N}` 和退回的 Step N
   - 从 Step 3（编码 step，index=2）开始，到 Step N（含），全部重置 `status="pending"`、`output=null`、`result_msg=""`
   - 将退回原因写入 `ctx.steps[2]["reject_reason"]`
   - 检查 `ctx.reject_count`（轮次级计数器）是否 ≥ 3，是则标记 `status="stuck"` 并停止操作
   - 正常时递增 `ctx.reject_count`，调用 `mgr.save()`，通知 PM
3. **退回原因提取：** `退回 🔄 R124 Step 3 — 编码不够严谨` → 取 `—` 之后的部分。无 `—` 时取消息前 100 字符。
4. **通知 PM：** 格式 `🔄 R{N} Step {N} 被退回，原因：{原因}。管线已退回到 Step 3（编码环节）。请 PM 决定下一步：派活 Dev 重做 or ##advance 跳过。`
5. **不自动派活：** 仅回退状态，不调用 `_auto_dispatch`。PM 后续通过 inbox 手动派活或 `##advance` 推进。
6. **边界情况：**
   - 退回 Step 2（Arch 环节）→ 回退到 Step 1（需求环节）
   - 管线已完成、已归档或被取消 → 忽略退回消息
   - `reject_count` 达到 3 后第 4 次退回 → 标记 `status="stuck"`，不再重置任何 step

#### 需求 B — 管线自动归档

1. **归档时机：** `_try_advance_pipeline` 中，在 step 推进后，检查 `all(s["status"]=="done" for s in ctx.steps)`，是则调用归档。
2. **归档操作：**
   - 从 `PipelineManager._contexts` 中移除（`pop(round_name)`）
   - 追加到 `/app/data/pipeline_archive.json`（JSON 数组，append 模式）
   - 归档记录附带：全量 step 数据 + artifacts + `archived_at` + `summary`（total_steps / completed_steps / reject_count / total_duration_sec）
3. **手动归档命令：** `##archive##R{N}` → 查管线存在 → 执行归档（同自动归档逻辑）。PM 可用此命令归档任意管线。
4. **归档后 `##status##R{N}`：** 返回 `📦 R{N} 已归档，数据在 pipeline_archive.json`
5. **自动清理（可选）：** archive 文件超过 50 条时保留最近 30 条。
6. **文件路径：** `/app/data/pipeline_archive.json`（与 `pipeline_contexts.json` 同目录）

#### 需求 C — Step 产出基本验证

1. **插入点：** `_try_advance_pipeline` 中，在解析 `##key=value` 之后、推进 step 之前。
2. **SHA 格式验证：**
   - 正则 `^[0-9a-f]{7,40}$` 匹配
   - 匹配 → `output["sha_validation"] = "valid_format"`
   - 不匹配 → `output["sha_validation"] = "invalid_format"`
   - 无 `##sha` → 不产生该字段
3. **远程 git 验证（可选，`PIPELINE_OUTPUT_VERIFICATION=1` 时启用）：**
   - `git ls-remote origin dev` 检查 SHA 存在性
   - `git log --oneline <sha> -1` 获取 commit message，检查是否含 `R{N}`
   - 标记 `verified` / `not_found` / `unchecked` / `commit_round_match`
   - ❗ 远程 git 读取是阻塞/异步 I/O，需用 `asyncio.create_subprocess_exec` 超时控制（5s 超时）
4. **验证不阻断：** 任何验证失败仅标记，不 return。即使 `sha_validation="invalid_format"`，管线照常推进。
5. **环境变量控制：** 新增 `config.PIPELINE_OUTPUT_VERIFICATION`，默认 `0`。

#### 需求 D — 超时自动化增强

1. **插入点：** `_pipeline_timeout_scan`（现有后台扫描协程，R122 已建）。
2. **首次超时（30min 告警后）：**
   - 复用现有 30min 超时检测逻辑
   - 在 `timeout_alerted=true` 标记后，新增一步：从 `ctx.steps[step_idx]` 重新构造派活消息，调用 `_send_to_agent` 重发
   - 记录 `re_notified` 标记，防止重复重发
3. **二次超时（45min）：**
   - 新增一个扫描间隔：dispatched_at 距今 > 45min 且 `re_notified=true` 且 `status!="timeout"`
   - 标记 `ctx.steps[step_idx]["status"] = "timeout"`
   - 通知 PM: `⏰ R{N} Step N bot 已 45 分钟未响应，已标记 timeout。请 PM 处理。`
4. **重发消息来源：** 从 `ctx.message_templates` 中读取该 step 的模板，用 `_render_template` 重新渲染（确保包含最新的 context 信息）。如无模板则用默认文本 `R{N} Step {N} — {role}，请继续完成`。
5. **已标记 timeout 的 step：** `##advance##R{N}##step=N` 仍可推进（timeout 不阻断手动操作）。
6. **环境变量控制：** 新增 `PIPELINE_TIMEOUT_RETRY_MINUTES=30`（首次重发时间）和 `PIPELINE_TIMEOUT_MARK_MINUTES=45`（标记 timeout 时间）。默认值分别为 30 和 45。设 `0` 禁用。

#### 全局问题

1. **改动范围预估：** 主要改动在 `server/ws_server/main.py`（`_handle_server_relay` + `_try_advance_pipeline` + `_pipeline_timeout_scan`），新增 3-4 个辅助函数。`config.py` 加 1 个配置项。全部以 `.get()` 安全读取兼容旧数据。
2. **向后兼容：** 
   - 旧 `pipeline_contexts.json` 无 `reject_reason` / `reject_count` / `timeout` 状态 → `.get()` 安全读取
   - 已有 `timeout_alerted` / `dispatched_at` 字段继续使用
   - 归档后 `##status` 返回已归档消息 → 旧管线不受影响（未归档的可查，已归档的提示归档位置）
   - `PipelineManager.get_context()` 返回 None 时，可检查 archive 文件
3. **R122 超时扫描协程已有 `_ensure_timeout_scanner` / `_start_pipeline_timeout_scan_loop` 结构**，需求 D 只需增强 `_pipeline_timeout_scan` 函数体内逻辑，不改变调度模式。
4. **ruff lint: 新增 `asyncio.create_subprocess_exec` 的异步超时需用 `asyncio.timeout()` (Python 3.11+) 或 `asyncio.wait_for()`。**

**产出格式：** 按 `docs/templates/R-tech-plan.md` 模板编写。

---

### Step 3 — 编码（爱泰）

**任务：**
按小开的技术方案实现 R124 四项功能。

**变更文件：**

| 文件 | 改动说明 |
|:-----|:---------|
| `server/ws_server/main.py` | 新增 `_handle_reject_back()` / `_archive_pipeline()` / `_auto_re_notify()` 函数；增强 `_try_advance_pipeline`（验证+归档检测）；增强 `_pipeline_timeout_scan`（超时重发+timeout 标记） |
| `server/common/config.py` | 新增 `PIPELINE_OUTPUT_VERIFICATION` / `PIPELINE_TIMEOUT_RETRY_MINUTES` / `PIPELINE_TIMEOUT_MARK_MINUTES` 配置项 |

**实现要点：**

#### 3.1 驳回状态回退（`_handle_reject_back`）

```python
# 伪代码逻辑
def _handle_reject_back(round_name, content, step_rejected):
    ctx = mgr.get_context(round_name)
    if not ctx or ctx.status in ("completed", "archived", "cancelled", "stuck"):
        return  # 忽略无效管线

    # 提取退回原因
    reject_reason = ""
    if "—" in content:
        reject_reason = content.split("—", 1)[1].strip()[:200]
    else:
        reject_reason = content[:100]

    # 轮次级退回计数检查
    reject_count = getattr(ctx, "reject_count", 0) + 1
    if reject_count >= 4:  # 第 4 次退回
        ctx.status = "stuck"
        ctx.reject_count = reject_count
        mgr.save()
        notify_pm(...)
        return

    ctx.reject_count = reject_count

    # 确定回退起点
    # Step 4(Review)/5(QA) → 回退到 Step 3(编码)
    # Step 2(Arch) → 回退到 Step 1(需求)
    rollback_to = 1 if step_rejected <= 2 else 2  # step index

    # 重置 Step rollback_to 及之后所有 step
    for i in range(rollback_to, len(ctx.steps)):
        ctx.steps[i]["status"] = "pending"
        ctx.steps[i]["output"] = None
        ctx.steps[i]["result_msg"] = ""
    ctx.steps[rollback_to]["reject_reason"] = reject_reason

    # 回退管线 current_step
    ctx.current_step = rollback_to + 1

    mgr.save()
    notify_pm(...)
```

#### 3.2 管线自动归档（`_archive_pipeline`）

```python
# 伪代码逻辑
def _archive_pipeline(round_name):
    ctx = mgr.pop(round_name)  # 从活跃上下文移除
    if not ctx:
        return

    archive_record = {
        "round_name": ctx.round_name,
        "status": "completed",
        "archived_at": time.time(),
        "reject_count": getattr(ctx, "reject_count", 0),
        "steps": ctx.steps,
        "artifacts": getattr(ctx, "artifacts", {}),
        "summary": {
            "total_steps": len(ctx.steps),
            "completed_steps": sum(1 for s in ctx.steps if s.get("status") == "done"),
            "reject_count": getattr(ctx, "reject_count", 0),
        }
    }

    # 追加到归档文件
    archive_path = os.path.join(config.DATA_DIR, "pipeline_archive.json")
    records = []
    if os.path.exists(archive_path):
        with open(archive_path) as f:
            records = json.load(f)
    records.append(archive_record)

    # 自动清理（保留最近 30 条）
    MAX_ARCHIVE = 30
    if len(records) > MAX_ARCHIVE + 20:  # 留缓冲
        records = records[-MAX_ARCHIVE:]

    with open(archive_path, "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
```

**归档触发时机：** `_try_advance_pipeline` 中，推进到最后一步后检查：
```python
if ctx.current_step >= len(ctx.steps):
    # 管线完成
    ctx.status = "completed"
    mgr.save()
    _archive_pipeline(ctx.round_name)
    notify_pm(f"📦 R{ctx.round_name} 管线已完成并归档")
```

#### 3.3 Step 产出验证

在 `_try_advance_pipeline` 中，已有 output 记录代码之后、`current_step += 1` 之前插入：

```python
# 验证 sha 格式
sha = output.get("sha", "")
if sha:
    import re
    if re.match(r"^[0-9a-f]{7,40}$", sha):
        output["sha_validation"] = "valid_format"
    else:
        output["sha_validation"] = "invalid_format"

# 远程 git 验证（可选，需 env var 开启）
if config.PIPELINE_OUTPUT_VERIFICATION and sha and output.get("sha_validation") == "valid_format":
    # 异步检查 SHA 存在性（见技术方案具体实现）
    pass  # asyncio.create_subprocess_exec 方式
```

#### 3.4 超时增强

在 `_pipeline_timeout_scan` 中，已有 30min 告警代码之后新增：

```python
# 原有：30min 告警（已存在，不修改）
if elapsed > timeout_minutes * 60 and not step_info.get("timeout_alerted"):
    step_info["timeout_alerted"] = True
    notify_pm(...)

# R124 新增：30min 重发派活
if elapsed > timeout_minutes * 60 and not step_info.get("re_notified"):
    step_info["re_notified"] = True
    _auto_re_notify(ctx, step_num)
    notify_pm("已重新发送派活消息给 {agent_name}")

# R124 新增：45min 标记 timeout
mark_minutes = config.PIPELINE_TIMEOUT_MARK_MINUTES or 45
if elapsed > mark_minutes * 60 and step_info.get("re_notified") and step_info.get("status") != "timeout":
    step_info["status"] = "timeout"
    notify_pm("⏰ {round_name} Step {step_num} 已标记 timeout")
```

**`_auto_re_notify` 实现：**

```python
def _auto_re_notify(ctx, step_num):
    step_idx = step_num - 1
    step_info = ctx.steps[step_idx]
    target_agent_id = step_info.get("agent_id", "")

    # 从模板重新构造派活消息
    tmpl = _render_template(ctx, step_num)
    if not tmpl:
        tmpl = f"📋 {ctx.round_name} Step {step_num} — {step_info.get('role', '?')}，请继续完成"

    _send_to_agent(target_agent_id, {
        "type": "broadcast",
        "channel": f"_inbox:{target_agent_id}",
        "content": f"🔄 消息重发 — {tmpl}",
        "from_name": "系统",
        "agent_id": "system",
    })
```

**【交付要求】**
- 提交格式：`feat(R124): Step 3 — 四项自动流转增强`
- 提交分多个 commit：
  - `feat(R124): Step 3.1 — 驳回状态回退`
  - `feat(R124): Step 3.2 — 管线自动归档`
  - `feat(R124): Step 3.3 — Step 产出基本验证`
  - `feat(R124): Step 3.4 — 超时自动化增强`
- 推 `dev` 分支
- 确保 ruff lint 通过

---

### Step 4 — 代码审查（小周）

**任务：**
审查爱泰对 `main.py` + `config.py` 的变更。

**审查要点：**

| # | 审查项 | 说明 |
|:-:|:-------|:------|
| 1 | `_handle_reject_back` 入口安全 | 退回消息解析是否正确？`—` 分割健壮性？shell 注入风险？ |
| 2 | 回退范围正确性 | Step 4/5 退回是否回退到 index=2（Step 3）？Step 2 退回是否回退到 index=0（Step 1）？ |
| 3 | `reject_count` 轮次级计数器 | 达到 3 后第 4 次是否正确 stuck？跨退回是否持续累计？ |
| 4 | `_archive_pipeline` 文件 I/O | `pipeline_archive.json` 并发写入安全？JSON 格式是否正确？ |
| 5 | 归档后 `##status` 响应 | `PipelineManager.get_context()` 返回 None 时是否回查 archive 文件？ |
| 6 | SHA 格式验证正则 | `^[0-9a-f]{7,40}$` 是否覆盖 7 字符短 SHA 和 40 字符全长？ |
| 7 | 远程 git 验证超时 | `asyncio.create_subprocess_exec` 是否有 5s timeout？超时后是否标记 `unchecked`？ |
| 8 | 超时重发逻辑 | `re_notified` 标记只写一次？`_auto_re_notify` 中 `_send_to_agent` 的 target 是否正确？ |
| 9 | 向后兼容 | 旧 JSON 所有新字段用 `.get()` 读取？timeout 标记是否覆盖旧 `timeout_alerted`？ |

**产出格式：** `docs/R124/R124-code-review.md`

---

### Step 5 — 测试验证（泰虾）

**产出：** `docs/R124/R124-test-report.md`

在 dev 测试环境容器上验证 R124 四项功能。

**验证项：**

#### 需求 A — 驳回状态回退

| # | 验证项 | 预期 |
|:-:|:-------|:-----|
| ① | 发 `退回 🔄 R124 Step 4 — 编码质量需改进` → `ctx.steps[2].status == "pending"` | Step 3~4 重置为 pending |
| ② | `ctx.steps[2]["reject_reason"] == "编码质量需改进"` | 退回原因正确记录 |
| ③ | 发 `退回 🔄 R124 Step 5`（无 `—`）→ `reject_reason` 取前 100 字符 | 无分隔符退路正确 |
| ④ | 连续退 3 次后第 4 次退回 → `ctx.status == "stuck"` | 循环限制生效 |
| ⑤ | 已归档管线收到退回消息 → 忽略（不修改任何状态） | 无效管线防护 |
| ⑥ | `ctx.steps[0]`（Step 1 PM）不受回退影响，保持 done | 回退范围正确 |
| ⑦ | 回退后 `##status##R124` 显示 current_step=3，Step 3~5 all pending | 状态显示正确 |

#### 需求 B — 管线自动归档

| # | 验证项 | 预期 |
|:-:|:-------|:-----|
| ⑧ | 全 step done 后 `pipeline_archive.json` 新增一条记录 | 自动归档 |
| ⑨ | 归档记录含 full steps + artifacts + archived_at + summary | 数据完整 |
| ⑩ | 归档后 `##status##R{N}` 返回「已归档，数据在 pipeline_archive.json」 | 状态显示正确 |
| ⑪ | `##archive##R{N}` 手动归档一条活跃管线 | 手动归档命令工作 |
| ⑫ | `##archive##R{NONEXISTENT}` 返回「管线不存在」 | 不存在管线友好提示 |

#### 需求 C — Step 产出基本验证

| # | 验证项 | 预期 |
|:-:|:-------|:-----|
| ⑬ | `##sha=abc1234` → `output["sha_validation"] == "valid_format"` | 7 字符 SHA 通过 |
| ⑭ | `##sha=0eafdc2e1b3c4d5f6a7b8c9d0e1f2a3b4c5d6e7f` → valid | 40 字符 SHA 通过 |
| ⑮ | `##sha=not-a-sha` → `output["sha_validation"] == "invalid_format"` | 非法格式标记 |
| ⑯ | 无 `##sha` 字段 → output 中无 sha_validation | 无字段不产生验证 |
| ⑰ | `PIPELINE_OUTPUT_VERIFICATION=1` 时，有效 SHA 触发远程 git 检查 | 可选验证启停正确 |
| ⑱ | 验证从不阻断推进（即使 invalid_format，pipeline 照常推进） | 非阻断原则 |
| ⑲ | 远程 git 检查超时 → `sha_validation == "unchecked"` | 超时安全回退 |

#### 需求 D — 超时自动化增强

| # | 验证项 | 预期 |
|:-:|:-------|:-----|
| ⑳ | 30min 超时后 `re_notified` 标记写入 step info | 重发标记 |
| ㉑ | 30min 超时后 bot 收到重发的派活消息 | 消息实际重发 |
| ㉒ | 45min 超时后 step status 标记为 `"timeout"` | timeout 标记 |
| ㉓ | timeout 后 `##advance` 仍然可推进管线 | 不阻断手动操作 |
| ㉔ | `PIPELINE_TIMEOUT_RETRY_MINUTES=0` 禁用重发 | 环境变量控制 |
| ㉕ | 原有 30min 首次告警不被破坏 | 向后兼容 |
| ㉖ | 回归测试：全 6 步自动派活零断流 | 不破坏已有功能 |

---

### Step 6 — 合并部署归档（小爱）

**部署流程：**

1. **测试环境部署（ws-bridge-dev）：**
   - 构建 `ws-bridge:r124-dev` 镜像
   - 部署到 dev 测试环境容器
   - 健康检查：WSS 8765 + Web UI 8766
   - 启动日志确认 `feat(R124)` 代码生效

2. **QA 验证通过后合入 main：**
   - `git checkout main && git merge dev`
   - `git push origin main`

3. **生产部署：**
   - 构建 `ws-bridge:r124` 镜像
   - 更新生产环境容器
   - 确认启动日志正常
   - 注意：`pipeline_archive.json` 是运行时创建的新文件，不占用已有存储

4. **归档：**
   - 全员 ACK
   - 归档轮次文档

---

## 验收检查表

| # | 验收项 | 优先级 |
|:-:|:------|:-----:|
| A-1 | Review 退回 Step 4 → step 3~4 status 重置为 pending，output 清空 | P0 🟢 |
| A-2 | 退回原因写入 `ctx.steps[2]["reject_reason"]` | P0 🟢 |
| A-3 | 退回后仅回退状态，不自动重新派活 | P0 🟢 |
| A-4 | PM 收到退回通知（含原因 + 管线已退回 Step 3 状态） | P0 🟢 |
| A-5 | 累计退回 3 次后第 4 次 stuck，停止回退 | P1 🟡 |
| A-6 | 无 `—` 退回消息取前 100 字符 | P2 🔵 |
| B-1 | 管线全 step done 后自动归档到 pipeline_archive.json | P0 🟢 |
| B-2 | `##archive##R{N}` 手动归档命令 | P1 🟡 |
| B-3 | 归档后 `##status` 返回「已归档」 | P1 🟡 |
| C-1 | `##sha=abc1234` → `sha_validation == "valid_format"` | P1 🟡 |
| C-2 | `##sha=bad`（非法）→ `sha_validation == "invalid_format"` | P1 🟡 |
| C-3 | 验证从不阻断管线推进 | P0 🟢 |
| D-1 | 30min 超时后重发派活 + 告警 | P1 🟡 |
| D-2 | 45min 超时后标记 step 为 timeout | P1 🟡 |
| D-3 | 回归测试：全 6 步自动派活零断流 | P0 🟢 |
