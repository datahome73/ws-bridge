# R132 工作计划 — !命令全面迁移（## 统一化收官）

| 字段 | 内容 |
|:-----|:------|
| **版本** | v2.0 |
| **关联需求** | `docs/R132/R132-product-requirements.md` |
| **开发分支** | `dev` |
| **目标分支** | `main` |

---

> **本轮范围调整：** `##admin` 和 `##task` 规则组已取消（admin 角色不存在，task 已被管线替代）。
> **仅迁移 `##step` 一个规则组（6 个步骤操作）。**

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
| `server/ws_server/scenario_matcher.py` | 修改 | 新增 `##step` 规则组 + `handle_step()` handler |
| `server/commands/` | 不变 | 旧 `!` 命令保持兼容，本轮不动 |

### 2.2 规则注册

在 `scenario_matcher.py` 的 `MATCH_RULES` 中追加一条规则：

```python
# R132 — 步骤操作（优先级 32）
QueryRule(
    priority=32,
    patterns=[
        r"^##step##(?P<step_action>\w+)(?:##(?P<step_args>.+))?$",
    ],
    handler="handle_step",
),
```

### 2.3 Handler 签名

```python
def handle_step(agent_id: str, action: str, args: str, level: int) -> dict:
    """
    处理 ##step 命令
    返回: {"reply": "..."} 或 {"error": "..."}
    """
```

### 2.4 权限配置

在 `_QUERY_LEVEL_MAP` 中追加：

```python
_QUERY_LEVEL_MAP = {
    # R131
    "whoami": 1, "help": 1,
    "status": 3, "agents": 3, "agent_info": 3,
    "audit": 4,
    # R132
    "step": 4,
}
```

### 2.5 旧兼容

- 旧 `commands/` 目录代码不变
- 旧 `!step_*` 命令仍可工作（兼容期）

---

## Step 3 — 编码实现

### 3.1 实现顺序

1. `_QUERY_LEVEL_MAP` 追加 `"step": 4`
2. 实现 `handle_step()` handler（6 个 action：complete / reject / restart / force / pause / resume）
3. `MATCH_RULES` 追加 `##step` 规则

### 3.2 验收条件

- `handle_step()` 返回结构统一：`{"reply": "..."}` 或 `{"error": "..."}`
- 权限不足时返回 `{"error": "权限不足：需要 L4 级别"}`
- 未知 action 时返回 `{"error": "未知步骤操作: {action}"}`
- 旧 `!step_*` 命令不受影响

---

## Step 4 — 代码审查

审查清单：

| # | 检查项 |
|:--|:-------|
| 1 | `handle_step` 正确注册到 `MATCH_RULES`（优先级 32） |
| 2 | 权限级别配置正确（`_QUERY_LEVEL_MAP` 中 `step: 4`） |
| 3 | 正则 `^##step##(?P<step_action>\w+)(?:##(?P<step_args>.+))?$` 不与其他规则冲突 |
| 4 | 6 个 action（complete / reject / restart / force / pause / resume）都有对应分支 |
| 5 | 返回统一 dict 格式 |
| 6 | 旧 `!step_*` 命令仍正常工作 |

---

## Step 5 — 测试验证

### 5.1 功能测试

| # | 命令 | 期望 |
|:--|:------|:------|
| 1 | `##step##complete##R131` | 回复：步骤 R131 已完成 ✅ |
| 2 | `##step##reject##R131##bug太多` | 回复：步骤 R131 已打回 ✅ |
| 3 | `##step##restart##R131` | 回复：步骤 R131 已重启 ✅ |
| 4 | `##step##force##R132` | 回复：步骤 R132 已强制推进 ✅ |
| 5 | `##step##pause##R132` | 回复：步骤 R132 已暂停 ⏸️ |
| 6 | `##step##resume##R132` | 回复：步骤 R132 已恢复 ▶️ |
| 7 | `##step##unknown##R132` | 回复：未知步骤操作 unknown ❌ |

### 5.2 兼容测试

| # | 命令 | 期望 |
|:--|:------|:------|
| 8 | `!step_complete R131` | 旧命令仍正常工作 ✅ |
| 9 | `!whoami` | 旧命令仍正常工作 ✅ |
| 10 | `!help` | 旧命令仍正常工作 ✅ |
| 11 | `!set_card xxx` | 旧命令仍工作（不会被误拦截）✅ |

### 5.3 权限测试（L1 用户）

| # | 命令 | 期望 |
|:--|:------|:------|
| 12 | `##step##complete##R131`（L1） | 权限不足：需要 L4 ❌ |
| 13 | `##step##pause##R132`（L1） | 权限不足：需要 L4 ❌ |

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
| 2 | `##step##reject##R131##原因` 正常 |
| 3 | `##step##force##R132` 正常 |
| 4 | `!step_complete R131` 旧命令仍兼容 |
| 5 | L1 用户被挡在 `##step` 命令外 |

---

*工作计划结束*
