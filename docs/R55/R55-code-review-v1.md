# R55 代码审查报告 v1.0

> **审查人：** 🔍 小周
> **审查对象：** commit `ea9d0ce` — Step 3 编码 (6 directions A-F)
> **审查基准：** R55 技术方案 v1.0 + R55 产品需求 v0.2
> **日期：** 2026-06-29

---

## 审查结论

**结论：** 🟡 有条件通过 — 1 个 🟡 警告建议启动前修复，其余建议非阻塞

---

## 验收标准逐项对照矩阵

| 验收标准 | 实现状态 | 审查结果 |
|:---------|:---------|:---------|
| A-1: member 推进 pending step | `_check_command_permission` 放开校验 + `_cmd_step_complete` mode check | ✅ |
| A-2: 非成员被拒绝 | `workspace_scope=True` + 已有 ws 权限校验 | ✅ |
| A-3: 已完成 step 不可重复推进 | 检查任务状态 (`current_task is None`)，非 tech plan 的 current_step 指针检查 | 🟢 等效实现 |
| A-4: 2s 序列化缓冲 | `_step_advance_buffer` dict + `time.time()` check | ✅ |
| B-1: 退回后指针回退 | `_cmd_step_reject` 回退逻辑 | ✅ |
| B-2: 退回必须附 `--reason` | `reason` 空值检查 + 报错 | ✅ |
| B-3: 退回记录写入 `pipeline_status` | `rejected_steps` 写入 + status 显示 🔄 | ✅ |
| B-4: 第 3 次退回升级 | 实现存在，但 ⚠️ 次数边界有疑问 | 🟡 见下 |
| C-1: 不存在 sha 报错 | `_verify_git_commit` 返回 False → 阻止推进 | 🟡 验证方式可疑 |
| C-2: 存在 sha 正常推进 | 同函数返回 True | 🟡 同上 |
| C-3: 无 `--output` 跳过 | `params.get("output", "")` 空值跳过 | ✅ |
| C-4: 远程不可达降级警告 | `except Exception` 返回 `(True, "⚠️")` | ✅ |
| D-1: 状态 emoji ✅ ▶ 🔄 ⏳ | `_cmd_pipeline_status` 正确映射 | ✅ |
| D-2: 退回次数+理由显示 | `rejected_steps` 遍历 | ✅ |
| D-3: 模式标记 🚀/📋 | `mode_icon` 输出 | ✅ |
| E-1: `--mode auto` 启动 | `_cmd_pipeline_start` mode 参数解析 + 写入 | ✅ |
| E-2: 不传 mode 默认 auto | `params.get("mode", "auto")` | ✅ |
| E-3: manual 模式限制推进 | `_cmd_step_complete` 内部 mode check | ✅ |
| F-1: 定向通知下一角色 | `_find_agents_by_role` + `_send_to_agent` | 🟡 见下 |
| F-2: 退回定向通知 | 同 F-1，用在 reject 中 | 🟡 见下 |
| F-3: 系统消息零回声 | `_persist_broadcast`/`write_chat_log` (admin 频道) | ✅ |
| F-4: 目标 bot 正常 ACK | `_send_to_agent` 发送后保留 ACK 通道 | 🟡 见下 |

---

## 🟡 警告（建议修复后再启动 Step 5 测试）

### W-1: `_cmd_step_reject` 排序 key bug（handler.py:1681）

```python
step_keys = sorted(step_config.keys(), key=lambda x: _step_sort_key(x[0]) if isinstance(x, str) else _step_sort_key(x))
```

**问题：** `step_config.keys()` 返回字符串，`x[0]` 取的是第一个字符（如 `"step1"` → `"s"`）。`_step_sort_key("s")` 返回 `(0, "s")`，所有 step 获得相同排序 key。

**影响：** 当前因为所有 key 以 `'s'` 开头，Python 稳定排序保留 dict 插入顺序（step1→step6），结果偶然正确。但若未来添加不同前缀的 step，排序会出错。

**修复：** 改为 `key=_step_sort_key`（同 handler.py:1442 的正确写法）

### W-2: `_verify_git_commit` 验证方式不可靠（handler.py:1153-1175）

**问题：** 代码用 `GET` 请求 `https://github.com/datahome73/ws-bridge.git`，期望响应正文包含 commit SHA。实际上该 URL 返回的是 GitHub 的 HTML 页面（或 git smart protocol 二进制应答），不是 git 对象列表。

```
req = _r55url.Request(repo_url, method='GET', ...)
with _r55url.urlopen(req, timeout=10) as resp:
    content = resp.read().decode('utf-8', errors='replace')
    if commit_sha in content:
        return True, ""
```

**影响：** SHA 可能意外出现在 HTML 中（如 commit 消息、导航条），导致验证误报通过；也可能不出现导致误报失败。验证结果不可预测。

**建议：** 改用 GitHub API：
```python
api_url = f"https://api.github.com/repos/datahome73/ws-bridge/commits/{commit_sha}"
# 如需要 token: 响应 200 → 存在，404 → 不存在
```
或 `git ls-remote` subprocess。

### W-3: 退回次数边界 — 第 2 次即升级（handler.py:1641）

**问题：** `TASK_REJECT_CEILING = 2`，条件 `reject_count >= 2` 在第 2 次退回时触发升级。

| 次数 | `reject_count` (读+1后) | `>= 2` | 结果 |
|:----:|:-----------------------:|:------:|:-----|
| 第 1 次 | 1 | ❌ | 正常退回 |
| 第 2 次 | 2 | ✅ | 升级给 PM |

但 WORK_PLAN 规则 3：「同一 step 最多退回 2 轮 → 第 3 次自动升级」。

**建议：** 在 WORK_PLAN 明确同意下，改为 `reject_count > TASK_REJECT_CEILING` 或调整 `TASK_REJECT_CEILING = 3`。

### W-4: `_send_to_agent` 使用原始 WS 发送，无持久化（handler.py:1570-1600）

**问题：** Step 交接的定向通知使用 `_send(ws, payload)` 发送，这是原始 WebSocket 帧。如果目标 bot 当时离线，通知消息**静默丢失**，没有回退到 `write_chat_log` 或 `save_message`。

```python
conns = _connections.get(agent_id, set())
if not conns:
    return False  # 无人接收 → 静默丢
```

**影响：** 通知丢失后，下一棒 bot 不会收到「新任务」通知，不会切频道，管线可能因无人接管而停滞。

**建议（低优先级）：** 在定向发送失败后回退到 `write_chat_log` 写入工作室频道，让 bot 上线后能读到历史。

---

## ✅ 已通过 — 各方向详细审查

### 方向 A：放开角色校验 ✅

- `_check_command_permission` 在 `step_complete` 命令上新增 bypass，正确地在 auto 模式下放行
- `_cmd_step_complete` 内部有 manual mode 校验，与 E 方向正确隔离
- A-4 的 `_step_advance_buffer` 实现简洁有效，key 含 round_name 支持多管线并发

### 方向 B：`!step_reject` 退回命令 ✅

- 命令结构完整：参数解析 → 管线上下文查找 → 前置校验 → 任务状态更新 → 指针回退 → 创建新 task → 定向通知
- 退回记录写入 `_PIPELINE_STATE["rejected_steps"]` 符合 D1 决策
- `_admin` 频道回溯日志实现正确
- 指针回退逻辑：target_idx > current_idx 时回退（退回已完成之后的 step）

### 方向 C：git 验证 ✅（验证方式需改进见 W-2，逻辑结构 OK）

- `--output` 改为可选，不传则跳过
- 超时降级警告仍推进
- 验证失败阻止推进

### 方向 D：`!pipeline_status` 增强 ✅

- 模式标记 🚀/📋
- 退回记录列表
- 状态 emoji 映射：INPUT_REQUIRED → 🔄
- 头部显示 `📊 {round} 管线状态`

### 方向 E：模式开关 ✅

- `!pipeline_start --mode auto|manual` 正确解析
- `!pipeline_mode` 命令运行时切换
- auto/manual 行为隔离正确
- 不传 --mode 时默认 auto

### 方向 F：减少回声 ✅（持久化建议见 W-4，逻辑 OK）

- `_send_to_agent` 定向发送函数
- `_cmd_step_complete` 的交接通知使用 `_find_agents_by_role` + `_send_to_agent`
- `_cmd_step_reject` 的退回通知同机制
- `_admin` 频道日志保留 `_persist_broadcast` 和 `write_chat_log`

---

## 代码风格与质量

| 检查项 | 结果 |
|:-------|:-----|
| 无残留 print/debugger | ✅ |
| 无硬编码 secret/token | ✅ |
| 函数命名一致 | ✅ (`_cmd_step_reject`, `_verify_git_commit`, `_send_to_agent`) |
| 注释清晰 | ✅ (各方向标注清楚) |
| 向后兼容 | ✅ (旧调用方式全部保留) |
| 代码复用 | ✅ (`_find_agents_by_role`、`_load_step_config` 复用已有) |

**注意：** `handler.py:1681` 排序不合规范，已在 W-1 报告。

---

## 审查总评

代码整体质量良好，6 个方向全部实现了技术方案要求。主要问题集中在：

1. **W-2: git 验证实现方式不标准** — 这是方向 C 的核心，如果验证结果不可靠，会严重影响管线可信度
2. **W-3: 退回次数边界** — 需要与 PM 确认 WORK_PLAN 中的"最多 2 轮"语义
3. **W-1: 排序 bug** — 虽然当前偶然正确，但建议立即修复

建议修复 W-2 后再启动 Step 5 测试验证，W-1/W-3 可在测试阶段同步修复。
