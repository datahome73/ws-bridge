# R54 技术方案 — 自动驾驶管线设计原则技术方向细化

> **版本：** v1.0
> **状态：** ✅ 审核通过
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-29
> **基于：** R53 自动驾驶管线协作设计原则

---

## 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                    R54 五方向全景（设计层）                      │
│                                                              │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│   │  A 放开   │   │ B 退回   │   │ C git    │   │ D 状态   │ │
│   │ 角色校验   │   │ 命令     │   │ 验证     │   │可视化    │ │
│   └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘ │
│        │               │              │              │         │
│        └───────────────┴──────────────┴──────────────┘         │
│                          │                                     │
│                   ┌──────▼──────┐                              │
│                   │  E 模式开关  │── auto/manual                │
│                   └─────────────┘                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 方向 A：放开 `!step_complete` 角色校验

**目标：** 工作区内任意成员可推进 pending step。

**实现方式：** 修改 `_check_command_permission` 对 `step_complete` 命令的处理。

```python
# 在 _check_command_permission() 中增加特殊分支：
if cmd_name == "step_complete" and min_role <= 1:
    # 自动驾驶模式 → 放开角色校验
    return True, ""
```

**约束实现（`_cmd_step_complete` 内部）：**
1. 仅推进 pending step — 检查 current_step 指针
2. 已完成的 step 不可重复推进
3. E 模式隔离 — manual 模式恢复旧校验

---

## 方向 B：新增 `!step_reject` 退回命令

**目标：** 正式退回机制，退回上一步并附理由。

**命令注册：**
```python
"step_reject": {
    "handler": _cmd_step_reject,
    "min_role": 1,           # 工作区成员可用
    "workspace_scope": True,
    "usage": "!step_reject stepN --reason <原因>",
}
```

**退回后状态流转：**
```
!step_reject step3 --reason "变量名阴影"

before: [step1✅] [step2✅] [step3▶] [step4⏳] [step5⏳] [step6⏳]
                                ↑current

after:  [step1✅] [step2✅] [step3▶] [step4⏳] [step5⏳] [step6⏳]
                                ↑current (指针不变，同 step 退回)
        step3 的 task: COMPLETED → INPUT_REQUIRED + 新 task SUBMITTED
```

**退回次数约束：** `TASK_REJECT_CEILING = 2`，第 3 次退回升级通知 PM。

---

## 方向 C：git 自动验证

**目标：** `!step_complete --output <sha>` 时自动验证远程 git 是否存在该 commit。

**实现方式：**
```python
async def _verify_git_commit(commit_sha: str) -> tuple[bool, str]:
    """检查远程 git dev 分支是否存在指定 commit。"""
    repo_url = config.GIT_REMOTE_URL
    # 用 urllib 请求 git ls-remote，超时 10s
    # 存在 → (True, "")；不存在 → (False, "❌ ..."); 超时 → (True, "⚠️ ...")
```

**配置项新增（`config.py`）：**
```python
GIT_REMOTE_URL: str = "https://github.com/datahome73/ws-bridge.git"
```

---

## 方向 D：`!pipeline_status` 增强

**目标：** 显示退回记录 + 状态标记。

**状态 emoji 映射：**
| 状态 | emoji |
|:----|:-----|
| 已完成 | ✅ |
| 当前活跃 | ▶ |
| 被退回 | 🔄 |
| 待启动 | ⏳ |

**mode 标记：** 输出头部 `🚀 auto` 或 `📋 manual`

---

## 方向 E：模式开关

**目标：** 每个管线可设 auto/manual 模式。

**修改 `_cmd_pipeline_start`：**
```python
mode = params.get("mode", "auto").lower()
# 写入 _PIPELINE_STATE
```

**新增 `!pipeline_mode` 命令：**
```python
"pipeline_mode": {
    "handler": _cmd_pipeline_mode,
    "min_role": 3,  # workspace admin
    "workspace_scope": True,
    "usage": "!pipeline_mode <auto|manual>",
}
```

**E 模式行为隔离：**

| 方向 | auto 模式 | manual 模式 |
|:----:|:---------|:-----------|
| A 放开角色校验 | ✅ 任何成员可推进 | ❌ 仅 step 负责人 |
| B 退回命令 | ✅ 可用 | ✅ 可用 |
| C git 验证 | ✅ 可用 | ✅ 可用 |
| D 状态可视化 | ✅ 显示退回记录 | ✅ 显示退回记录 |

---

## 向后兼容分析

| 已有功能 | 影响 |
|:---------|:-----|
| `!step_complete stepN --output <sha>` | ✅ `--output` 改为可选 |
| `!pipeline_status` | ✅ 输出格式增强 |
| `!pipeline_start` | ✅ 新增 `--mode`，默认 auto |
| 旧手动推进流程 | ✅ manual 模式保持旧行为 |

---

## 代码变更概览

| 方向 | 文件 | 操作 | 预估行数 |
|:----:|:----|:----|:--------|
| A | `handler.py` | 修改 `_check_command_permission` + `_cmd_step_complete` | +15 |
| B | `handler.py` | 新增 `_cmd_step_reject` + 命令注册 | +45 |
| C | `handler.py` + `config.py` | 新增 `_verify_git_commit` + `GIT_REMOTE_URL` | +23 |
| D | `handler.py` | 修改 `_cmd_pipeline_status` | +15 |
| E | `handler.py` | 修改 `_cmd_pipeline_start` + 新增 `_cmd_pipeline_mode` | +13 |
| | | **合计** | **~111 行** |

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-06-29 | ✅ 定稿 — 5 方向 A~E 技术方案，推进 R55 编码 |
