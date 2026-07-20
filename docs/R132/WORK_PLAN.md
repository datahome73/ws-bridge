# R132 工作计划 — !命令全面迁移（## 统一化收官）

| 字段 | 内容 |
|:-----|:------|
| **版本** | v1.0 |
| **关联需求** | `docs/R132/R132-product-requirements.md` |
| **开发分支** | `dev` |
| **目标分支** | `main` |

---

## 管线总览

| Step | 内容 | 状态 | 产出 |
|:-----|:------|:----:|:-----|
| 1 | 需求文档 | ✅ 完成 | `docs/R132/R132-product-requirements.md` |
| 2 | 技术方案 | ⏳ 待办 | 本文档 Step 2 |
| 3 | 编码实现 | ⏳ 待办 | 代码变更 |
| 4 | 代码审查 | ⏳ 待办 | 审查报告 |
| 5 | 测试验证 | ⏳ 待办 | 测试报告 |
| 6 | 合并部署 | ⏳ 待办 | 合 main + 部署 |

---

## Step 2 — 技术方案

### 2.1 修改文件清单

| 文件 | 操作 | 说明 |
|:-----|:----:|:-----|
| `server/ws_server/scenario_matcher.py` | 修改 | 新增 3 个规则组 + 3 个 handler |
| `server/commands/` | 不变 | 旧 `!` 命令保持兼容，本轮不动 |

### 2.2 规则注册

在 `scenario_matcher.py` 的 `MATCH_RULES` 中追加 3 条规则：

```python
# R132 — 步骤操作（优先级 32）
QueryRule(
    priority=32,
    patterns=[r"^##step##(?P<step_action>\w+)(?:##(?P<step_args>.+))?$"],
    handler="handle_step",
),

# R132 — 管理操作（优先级 34）
QueryRule(
    priority=34,
    patterns=[r"^##admin##(?P<admin_action>\w+)(?:##(?P<admin_args>.+))?$"],
    handler="handle_admin",
),

# R132 — 任务操作（优先级 36）
QueryRule(
    priority=36,
    patterns=[r"^##task##(?P<task_action>\w+)(?:##(?P<task_args>.+))?$"],
    handler="handle_task",
),
```

### 2.3 Handler 签名

所有 handler 遵循统一签名：

```python
def handle_<group>(agent_id: str, action: str, args: str, level: int) -> dict:
    # 返回: {"reply": "..."} 或 {"error": "..."}
```

### 2.4 权限

沿用 `_QUERY_LEVEL_MAP` 最小级别表模式（R131 已确立）：

```python
_QUERY_LEVEL_MAP = {
    # R131
    "whoami": 1, "help": 1, "status": 3, "agents": 3, "agent_info": 3, "audit": 4,
    # R132
    "step": 4, "admin": 4, "task": 4,
}
```

### 2.5 旧兼容

- R131 的 `!` → `##` 映射仍保留
- 旧 `commands/` 目录代码不变
- **不新增** `commands/` 中的文件

---

## Step 3 — 编码实现

### 3.1 实现顺序

1. `_QUERY_LEVEL_MAP` 追加 step/admin/task 级别定义
2. 实现 `handle_step()` handler
3. 实现 `handle_admin()` handler
4. 实现 `handle_task()` handler
5. `MATCH_RULES` 追加 3 条新规则

### 3.2 验收条件

- 所有 handler 返回结构统一：`{"reply": "..."}` 或 `{"error": "..."}`
- 权限不足时返回 `{"error": "权限不足：需要 L4 级别"}`
- 未知 action 时返回 `{"error": "未知操作: {action}"}`
- 旧 `!` 命令不受影响

---

## Step 4 — 代码审查

审查清单：

| # | 检查项 |
|:--|:-------|
| 1 | 3 个 handler 是否正确注册到 `MATCH_RULES` |
| 2 | 权限级别配置正确（`_QUERY_LEVEL_MAP`） |
| 3 | 正则 pattern 不与其他规则冲突 |
| 4 | 所有 handler 返回统一 dict 格式 |
| 5 | 旧 `!` 命令仍正常工作 |
| 6 | 无硬编码字符串（如 `"L4"` 写死） |

---

## Step 5 — 测试验证

### 5.1 测试用例

| # | 命令 | 期望 |
|:--|:-----|:------|
| 1 | `##step##complete##R131` | 回复：步骤 R131 已 complete ✅ |
| 2 | `##step##reject##R131##bug太多` | 回复：步骤 R131 已 reject ✅ |
| 3 | `##step##force##R131` | 回复：步骤 R131 已 force ✅ |
| 4 | `##step##unknown##R131` | 回复：未知操作 unknown ❌ |
| 5 | `##admin##set_card##小谷##测试中` | 回复：名片已更新 ✅ |
| 6 | `##admin##reload_agents` | 回复：agent 列表已重载 ✅ |
| 7 | `##admin##reset_pipeline` | 回复：管线已重置 ✅ |
| 8 | `##task##create##新任务` | 回复：任务已创建 ✅ |
| 9 | `##task##list` | 回复：任务列表 ✅ |
| 10 | `##task##rollcall` | 回复：点名统计 ✅ |
| 11 | `!whoami` | 旧命令仍正常工作 ✅ |
| 12 | `!help` | 旧命令仍正常工作 ✅ |

### 5.2 L1 权限验证

| # | 命令 | 期望 |
|:--|:-----|:------|
| 13 | `##step##complete##R131`（L1） | 权限不足：需要 L4 ❌ |
| 14 | `##admin##set_card##小谷`（L1） | 权限不足：需要 L4 ❌ |
| 15 | `##task##create##test`（L1） | 权限不足：需要 L4 ❌ |

---

## Step 6 — 合并部署

```bash
git checkout main
git merge dev
git push origin main
# 小爱部署
```

部署后验证：

| # | 验证项 |
|:--|:-------|
| 1 | `##step##complete##R131` 正常 |
| 2 | `##admin##reload_agents` 正常 |
| 3 | `##task##list` 正常 |
| 4 | `!whoami` 旧命令仍兼容 |
| 5 | L1 用户被挡在新命令外 |

---

*工作计划结束*
