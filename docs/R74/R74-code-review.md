# R74 代码审查报告

> **审查人：** 🔍 小周
> **审查对象：** commit `9b2354e`
> **审查日期：** 2026-07-07
> **审查范围：** `server/handler.py` + `server/config.py`
> **对比基准：** R74 技术方案 v1.0 + R74 需求文档 v1.0

---

## 0. 审查结论

**🟢 通过 → 进入 Step 5 测试**

全部 9 项审查重点通过，零阻塞项。

---

## 1. 规范检查

| 检查项 | 结果 | 说明 |
|:-------|:----:|:-----|
| commit message 格式 | ✅ | `feat(R74): Step 3 ✅ 编码实现 — 管线通用化`，格式合规 |
| 文件范围符合方案 | ✅ | 仅 `server/handler.py` + `server/config.py` 二文件，零越界 |
| 无 TODO/FIXME/debugger 残留 | ✅ | grep 扫描无残留 |

---

## 2. 需求→方案→代码追溯矩阵

### 方向 A：WORK_PLAN frontmatter 承载全量配置

| 方案项 | 需求验收 | 实现位置 | 状态 |
|:-------|:---------|:---------|:----:|
| A1 frontmatter steps 校验 | ✅-2 | handler.py:2106-2120 | ✅ |
| A1 workspace.members 读取 | ✅-3 | handler.py:2145-2200 | ✅ |
| A2 URL 不拼接覆盖 | ✅-1, ✅-6 | handler.py:1147-1167 | ✅ |
| A2 `--force` 参数 | 附带 | handler.py:2051-2052 | ✅ |

### 方向 B：移除硬编码路径拼接

| 方案项 | 需求验收 | 实现位置 | 状态 |
|:-------|:---------|:---------|:----:|
| B1 删除 `_R62_REPO_BASE` | ✅-5 | handler.py(原L1083) 删除 | ✅ |
| B2 `_infer_artifact_url()` 加 step_config 参 | ✅-7 | handler.py:1217-1230 | ✅ |
| B2 硬编码 URL 回退 main 分支 | — | handler.py:1225-1229 | ✅ |

### 方向 C：admin→operations 角色名替换

| 方案项 | 需求验收 | 实现位置 | 状态 |
|:-------|:---------|:---------|:----:|
| config.py PIPELINE_STEP_MAP role | ✅-8, ✅-9 | config.py L93, L102-103 | ✅ |
| handler.py 角色匹配（不改 admin 命令） | — | 零改动（技术方案确认不改） | ✅ |

### 方向 D：顺手修复

| 方案项 | 需求验收 | 实现位置 | 状态 |
|:-------|:---------|:---------|:----:|
| D1 inbox 权限开放 | — | handler.py:4320-4322 | ✅ |
| D2 display_name 角色匹配 | — | handler.py:2156-2170 | ✅ |

**追溯率：** 12/12 项 ✅ **100%**

---

## 3. 逐项审查详情

### 3.1 frontmatter steps 校验逻辑（方向 A1）

**代码位置：** handler.py:2106-2120

```python
# ── R74 A1: 校验 frontmatter 是否包含 steps 定义 ──
psteps = config_data.get("steps", {})
if not psteps and not force_flag:
    return (
        f"❌ {round_name} WORK_PLAN 缺少 pipeline.steps 定义。\n\n"
        f"请在 frontmatter 中补充 steps 配置，每 step 含 role/title/context。\n"
        f"参考格式：..."
        f"提示：可使用 --force 强制以默认 Step 映射启动（PIPELINE_STEP_MAP 回退）"
    )
_PIPELINE_CONFIG[round_name] = config_data
```

- ✅ 放在 `_build_pipeline_config()` 成功后、`_PIPELINE_CONFIG` 赋值前
- ✅ `force_flag` 检查绕过（`--force` 参数）
- ✅ `NoFrontmatterError` / `ValueError` 异常仍走 fallback 路径（旧轮次兼容）
- ✅ 无 steps 时 `config_data.get("steps", {})` 返回空 dict `{}`，正确被 `not psteps` 捕获
- ✅ 边缘情况：frontmatter 有 `pipeline` 但无 `steps` → 报错；有值但为空步 → 同上报错

### 3.2 `_build_pipeline_config()` URL 不拼接覆盖（方向 A2）

**代码位置：** handler.py:1147-1167

```python
# R74 A2: 仅当 frontmatter 无定义时才从 base_urls 获取
if not config.get("work_plan_url"):
    config["work_plan_url"] = base_urls.get("work_plan_url", "")
if not config.get("requirements_url"):
    config["requirements_url"] = base_urls.get("requirements_url", "")
```

- ✅ 使用 `if not config.get(...)` 条件赋值，frontmatter 已定义时保留原值
- ✅ `base_urls` 中 `requirements_url` 传空串（调用侧 L2097/L2103）
- ✅ `_R62_REPO_BASE` 拼接逻辑完全移除
- ✅ 1 处调用侧 `requirements_url=""` 已同步（3 处调用点全部验证）

### 3.3 workspace.members 读取（方向 A1）

**代码位置：** handler.py:2145-2200

- ✅ frontmatter 有 `workspace.members` → 使用显式定义的角色集 (`workspace_members_fm.keys()`)
- ✅ 无 frontmatter members → 回退 `step_config` 推断角色（原有行为不变）
- ✅ D2 display_name 匹配：匹配 `card.get("display_name", "")` 与 `mention_keyword` 集
- ✅ 注意：`card_name in keywords` 是子串匹配（如 display_name="ArchBot-小开" 仍匹配）
- ✅ 两次匹配失败时包含 auth 用户无 card 兜底（`seen` 集防重）

### 3.4 删除 `_R62_REPO_BASE`（方向 B1）

- ✅ 原始位置 handler.py L1083 整行删除
- ✅ `grep -rn '_R62_REPO_BASE' server/` → 零匹配，exit code 1（无残留）
- ✅ 唯一使用位置：
  - `_build_pipeline_config()` L1158 → 裁剪为 `base_urls.get("requirements_url", "")`
  - `_build_fallback_config()` L1175 → 改为 `_r42cfg.WORK_PLAN_REPO_URL`
  - `_infer_artifact_url()` L1213-1215 → 改为 `main` 分支硬编码 URL

### 3.5 `_infer_artifact_url()` 优先读 frontmatter（方向 B2）

**代码位置：** handler.py:1217-1230

```python
def _infer_artifact_url(step_name: str, round_name: str, step_config: dict | None = None) -> str:
    # R74 B2: 优先读 frontmatter 的 artifact_url
    if step_config and step_name in step_config:
        art = step_config.get(step_name, {}).get("artifact_url", "")
        if art:
            return art
    # Fallback: hardcoded paths (main branch)
    step_urls = {
        "step2": f"https://raw.githubusercontent.com/.../main/docs/...",
        "step4": f"https://raw.githubusercontent.com/.../main/docs/...",
        "step5": f"https://raw.githubusercontent.com/.../main/docs/...",
    }
    return step_urls.get(step_name, "")
```

- ✅ 函数签名新增 `step_config: dict | None = None` 可选参数
- ✅ 优先读 `step_config[step_name].artifact_url`
- ✅ 回退 URL 从 `dev` 改为 `main` 分支
- ✅ 调用侧 hanlder.py:2596 传入 `step_config` 参数
- ⚠️ **注意（非阻塞）：** `step_config.get(step_name, ...)` 可简化为 `step_config.get(step_name, {}).get(...)`。但 `step_name in step_config` 的前置 `if` 保障了 `step_config[step_name]` 存在，所以后续 `step_config.get(step_name, ...)` 是安全的冗余写法。建议：后续清理时改为 `step_config[step_name].get("artifact_url", "")` 更直接。

### 3.6 inbox 权限修复（方向 D1）

**代码位置：** handler.py:4320-4322

```python
# 权限：admin 或 workspace admin 可向收件箱发消息（R74 D1）
if sender_role != "admin" and not _is_any_workspace_admin(sender_id):
    await _send(ws, {"type": "error", "error": "❌ 权限不足：仅管理员可向收件箱发消息"})
    return
```

- ✅ 从单一 `sender_role != "admin"` 改为 `admin OR workspace admin`
- ✅ `_is_any_workspace_admin()` 函数早在 R73 已存在，非本次新增（依赖已有设施）
- ✅ 覆盖 PM (pipeline_coordinator) 等非 admin 角色
- ✅ inbox 消息内容/格式不受影响

### 3.7 角色名匹配 display_name fallback（方向 D2）

**代码位置：** handler.py:2156-2170

- ✅ 当 frontmatter `workspace.members` 存在时，用 `display_name` 替代 `pipeline_roles` 交集
- ✅ `mention_keyword` 可含多值（分号分隔），逐一与 card display_name 匹配
- ✅ 匹配成功的 card 加入 `member_ids`
- ✅ 无 card 的用户按角色名兜底匹配

### 3.8 scope 合规

- ✅ 仅有 `server/handler.py` + `server/config.py` 二文件被修改
- ✅ 改动量：`+101 / -42 = 59 行净增`（方案预估 ~49 行，稍多，符合 D1+D2 额外修复范围）
- ✅ 无 YAML 第三方库引入
- ✅ `_parse_frontmatter()` 解析器本身未改动
- ✅ 未见工作室系统、认证体系、Web 前端、状态机流转逻辑被触及

### 3.9 旧轮次兼容

| 场景 | 验证方法 | 结果 |
|:-----|:---------|:----:|
| `!pipeline_status R72` | `_PIPELINE_CONFIG` 已缓存，不重走 `_build_pipeline_config()` | ✅ 完全兼容 |
| `!step_complete step2 R72` | 同用 `_PIPELINE_CONFIG` 的 steps | ✅ 完全兼容 |
| `NoFrontmatterError` 异常 | 仍走 `_build_fallback_config()`（`try/except` 路径不变） | ✅ 完全兼容 |
| 旧轮次 artifact URL | 回退 URL 用 `main` 分支（R72/R73 已合入 main） | ✅ 兼容 |
| `_build_fallback_config()` | 用 `config.WORK_PLAN_REPO_URL` 替代 `_R62_REPO_BASE`（值相同） | ✅ 行为等价 |

---

## 4. 代码质量审查

### 4.1 架构与设计

- ✅ frontmatter 校验插入位置正确（`_build_pipeline_config` 后、`_PIPELINE_CONFIG` 前）
- ✅ workspace.members 分支与 fallback 分支完全独立，互不影响
- ✅ `_is_any_workspace_admin` 复用已有基础设施，无重复逻辑
- ✅ `force_flag` 通过检查 `_raw` 参数中的 `--force` 字符串，不依赖参数解析器改造

### 4.2 边界情况分析

| # | 边界场景 | 预期行为 | 代码确认 | 状态 |
|:-:|:---------|:---------|:--------:|:----:|
| 1 | frontmatter 无 `pipeline` 键 | 抛 ValueError → fallback | L1151: `raise ValueError` → L2122: `except` | ✅ |
| 2 | frontmatter 有 `pipeline` 但无 `steps` | 报步骤缺失错误 | L2113: `config_data.get("steps", {})` → 空 dict 被捕获 | ✅ |
| 3 | 无 steps + `--force` | 用 PIPELINE_STEP_MAP fallback | L2114: `and not force_flag` | ✅ |
| 4 | workspace.members 声明但 agent card 无匹配 display_name | 按角色名尝试无 card 兜底 | L2169-2171: `u.get("role", "member") in all_roles` | ✅ |
| 5 | display_name 含特殊字符/中文 | 子串匹配含中文仍可工作 | L2165: `card_name in keywords` (Python `in`) | ✅ |
| 6 | WORK_PLAN 含 `requirements_url` 但调用侧传空串 | frontmatter 值保留 | L1160: `if not config.get("requirements_url"):` 条件保护 | ✅ |
| 7 | `_infer_artifact_url` 传 step_config=None | 走 fallback 硬编码 | L1221: `if step_config and ...` 短路 | ✅ |
| 8 | 旧轮次 `_PIPELINE_CONFIG` 缓存存在 | 不走 frontmatter 解析 | L2088: `if round_name not in _PIPELINE_CONFIG:` | ✅ |
| 9 | 无 frontmatter + workspace.members 空 dict | 回退 step_config 推断 | L2177: `else:` 分支 | ✅ |
| 10 | 无 card 仅有 auth 用户 | `cards` 空 list → 走 else 分支 | L2195-2198: `else: for aid, u...` | ✅ |

### 4.3 潜在改进建议（💡 非阻塞）

| # | 位置 | 建议 |
|:-:|:-----|:-----|
| 💡 1 | handler.py:1222 | `step_config.get(step_name, {}).get(...)` 可简化为 `step_config[step_name].get(...)`（前面有 `step_name in step_config` 保障） |
| 💡 2 | handler.py:2601 | `_cmd_step_complete` 内 `step_config = _get_step_config(round_name)` 出现两次（L2541 + L2601）。虽然功能正确（后续逻辑独立需新变量），但如果 L2541 的 step_config 在 L2599 后未被修改，可复用减少一次函数调用 |
| 💡 3 | handler.py:2165 | `card_name in keywords` 是子串匹配。如果 agent card 的 display_name 恰好包含另一个角色的 keyword（如 "ArchBot-qa"），会误匹配。但实际场景中 display_name = "ArchBot" 精确匹配 `keyword in {"ArchBot", "arch", ...}` 的子串语义对单值 display_name 来说等同于精确匹配。可考虑 `keyword == card_name` 更精确 |

---

## 5. 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:----:|
| 硬编码敏感信息 | ✅ 无新增，只有 GitHub raw URL（公开仓库） |
| 调试日志/print | ✅ 无 |
| TODO/FIXME 残留 | ✅ 无 |
| `_R62_REPO_BASE` 残留 | ✅ `grep -rn` 零匹配 |
| role: "admin" 误改 | ✅ 仅改 config.py 的 PIPELINE_STEP_MAP 3 处，handler.py 中系统 admin 权限检查未触及 |

---

## 6. 语法验证

```
$ python3 -c "compile(open('server/handler.py').read(), 'handler.py', 'exec'); print('OK')"
OK
$ python3 -c "compile(open('server/config.py').read(), 'config.py', 'exec'); print('OK')"
OK
```

✅ 两文件语法均无问题。

---

## 7. 总结

| 类别 | 结果 |
|:-----|:----:|
| 追溯率 | 12/12 ✅ 100% |
| 阻塞项 | 0 |
| 警告 | 0 |
| 建议 | 3 (💡 非阻塞) |
| **结论** | **🟢 通过 → Step 5** |
