# R111 — ## 命令启动管线：简洁可靠的自动派活入口 🚀

> **轮次：** R111
> **auto_chain:** true
> **说明：** 新增 `##start##R{N}##key=value` 前缀命令，利用已有 `_handle_server_relay` 机制创建 PipelineContext + 落盘 + 自动派活 Step 1
> **审核链接：** [R111-product-requirements.md](https://github.com/datahome73/ws-bridge/blob/dev/docs/R111/R111-product-requirements.md)

---

## Step 1 — PM 标注已审核（当前） ✅

- R111 需求文档已通过审核
- WORK_PLAN.md 已编写

---

## Step 2 — 实现 `_handle_hash_cmd`（Architect → Dev）

**改动文件：** `server/ws_server/main.py`

### 2.1 在 `_handle_server_relay` 中插入 ## 拦截

**位置：** 在 `# ═══════════════════════════════════════════` 分隔行（L2634）之后、PM 守卫（L2636）之前，插入：

```python
# ═══ R111: ## 命令 ═══
if content.startswith("##"):
    return await _handle_hash_cmd(content, agent_id, ws)
# ═══════════════════════════════════════════
```

**共 3 行。**

### 2.2 新增 `_handle_hash_cmd()` 主分发函数

- 按 `##` 拆分消息内容
- 取第 2 段为 `round_name`（统一 `.upper()`）
- 取第 3+ 段为 `key=value` 数据段
- 分派到 `_handle_hash_start / _handle_hash_status / _handle_hash_stop`

### 2.3 新增 `_handle_hash_start()` — 核心函数

**约 30 行。**

```
1. 防重复检查：mgr.exists(round_name)
2. _refresh_role_agent_map()
3. 从 _ROLE_AGENT_MAP + display_name 桥接 → 填充 steps 的 agent_id
4. 从 kv 提取 references（requirements_url / work_plan_url）
5. 加载默认 message_templates（6 步标准模板）
6. PipelineContextManager.set_context() 写入 pipeline_contexts.json
7. transition_to(RUNNING)
8. _auto_dispatch(ctx, 1) → 派活 Step 1 到小谷
9. 回复发送者 "✅ R{round} 管线已启动"
```

### 2.4 新增 `_handle_hash_status()` / `_handle_hash_stop()`

- **status**：从 mgr.get() 读 PipelineContext → 拼装状态文本 → `_send(ws, ...)` 回复发送者
- **stop**：mgr.cancel() 或 archive() → 回复确认

### 2.5 辅助函数

- `_build_default_templates()` — 返回 6 步标准模板组（复用 `commands/pipeline.py` L234-241 的模板字符串）
- `_build_name_to_ws_map()` — 从 `persistence.get_api_keys()` 构建 display_name → ws_agent_id 映射（已有代码片段，提取为函数）

### 验证方法

```bash
# 本地 grep 确认插入点
grep -n 'startswith.*##' server/ws_server/main.py
# 确认 _handle_hash_cmd 定义
grep -n 'def _handle_hash_cmd' server/ws_server/main.py
# 确认 PM 守卫前已拦截
grep -n 'PM 误发' server/ws_server/main.py
```

---

## Step 3 — 代码审查（Review → 晓周）

审查清单：
- `##` 拦截是否插在 PM 守卫之前（L2633-2636 之间）
- `##` 命令不会被旧规则 0（`!` 透传）误拦截
- PipelineContext 字段填充完整（steps.agent_id、references、message_templates）
- `_auto_dispatch` 调用前 context 已 `set_context` + `transition_to(RUNNING)`
- `##status` 在管线不存在时返回明确错误信息

---

## Step 4 — 测试验证（QA → 泰虾）

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 1 | 发 `##start##R111` → pipeline_contexts.json 有 R111 条目 | curl 或脚本发送 |
| 2 | Step 1 派活到小谷 inbox | Web 端 /api/chat/inbox 可见 |
| 3 | 重复 `##start##R111` → ❌ 管线已存在 | 第二次返回 error |
| 4 | `##status##R111` → 返回当前进度 | 回复含 current_step |
| 5 | `##stop##R111` → 管线取消 | status=CANCELLED |
| 6 | 小谷回复 `已完成 ✅ R111 Step 1` → Step 2 自动推进 | 小开收 Step 2 派活 |

---

## Step 5 — 部署（Ops → 小爱）

1. 合并 dev → main
2. 重建 Docker 镜像 `ws-bridge:r111`
3. 重启容器
4. 验证：发 `##help` 到 `_inbox:server` → 收到帮助列表

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-14 | 初稿 |
