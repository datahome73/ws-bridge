# R132 Step 4 — 代码审查报告 🔍（二次审查）

> **轮次：** R132
> **审查人：** 🔍 小周
> **审查对象：** commit `eb7ddc6c46ad`（feat(R132): ##step 规则组迁移 — handle_step handler + rule 28 注册）
> **首次审查：** `efd5dfb3654b`（驳回 — commit 不存在）
> **依据：** `docs/R132/R132-product-requirements.md` v2.0, `docs/R132/R132-tech-plan.md` v1.1
> **审查基准：** dev HEAD `48106d49370a`

---

## ✅ 审查结论：通过（附带 1 🟡 建议）

---

## 一、审查清单逐项验证

| # | 验收项 | 预期 | 结果 | 证据 |
|:-:|:-------|:-----|:----:|:-----|
| 1️⃣ | `handle_step` 正确注册到规则表（优先级 28） | priority=28，介于 rule 25(##query) 和 rule 30(##hash_cmd) 之间 | ✅ | `scenario_matcher.py` 末尾 `register_rule(priority=28)`；`main.py` L4888-4894 注册 `match=_sm.match_step` + `handle=_sm_handle_step` |
| 2️⃣ | 权限级别正确（L4 要求） | `_get_agent_level() < 4 → 拒绝` | ✅ | `handle_step()` L532-536：`if level < 4: await _send_reply(... "权限不足：需要 L4 级别")` |
| 3️⃣ | 正则/匹配不与其他规则冲突 | `##step` 在 `##` 通用匹配(rule 30)之前拦截 | ✅ | `match_step()` 用 `startswith("##step")`，rule 28 优先级低于 query(25) 但高于 hash_cmd(30)，合理插空 |
| 4️⃣ | 6 个 action 路由正确 | complete/reject/restart/force/pause/resume 各有分支 | ✅ | `handle_step()` L540-571：`complete→_cmd_step_complete` / `reject→_cmd_step_reject`(含原因解析) / `restart→_cmd_step_handoff` / `force→_cmd_step_force` / `pause` / `resume` 占位回复 + `else→未知操作` |
| 5️⃣ | 返回统一格式 | handler 返回 bool | ✅ | 所有路径均 `return True`，回复通过 `_send_reply()` 发送 |
| 6️⃣ | 旧 `!step_*` 命令不受影响 | commands/pipeline.py 未被修改 | ✅ | `_cmd_step_complete`(L596) / `_cmd_step_reject`(L1349) / `_cmd_step_force`(L1054) 等均保留；旧命令走 rule 80(!)，新命令走 rule 28(##step)，互不干扰 |

---

## 二、文件改动总览

| # | 文件 | 动作 | 行数变化 | 状态 |
|:-:|:-----|:-----|:--------:|:----:|
| 1 | `server/ws_server/scenario_matcher.py` | 修改 | **+111** | ✅ 新增 match_step + handle_step + _QUERY_LEVEL_MAP 追加 step:4 |
| 2 | `server/ws_server/main.py` | 修改 | **+13** | ✅ 新增 `_sm_handle_step` 包装 + rule 28 注册 |

---

## 三、代码质量发现项

### 🟡 1: `match_query` / `handle_query` 重复定义（死代码）

**位置：** `scenario_matcher.py` L168 + L467（`match_query`），L199 + L480（`handle_query`）
**问题：** 每对函数定义了两次，第二次覆盖第一次。第一次定义（L168-L259 区域）成为死代码——占约 90 行，实际零调用。
**影响：** 功能正确（Python 运行时使用第二次定义），但代码冗余，混淆读者。
**建议：** 清理死代码，删除第一组 `match_query` / `handle_query` / `get_agent_level` 定义。不影响功能，降低维护负担。

### 🟡 2: `match_step` 前缀匹配偏宽

**位置：** `scenario_matcher.py` L460：`if content.startswith("##step"):`
**问题：** `##step` 前缀也会匹配非正规命令如 `##step_urgent##complete##R132`，该消息会透传至 handle_step 并解析 action/args，意外执行。
**影响：** 低——实际使用中不会出现 `##step_` 前缀；且权限 L4 限制了只有高级用户可操作。
**建议：** 收紧为 `if content.startswith("##step##"):` 或使用正则 `^##step##`，避免误匹配。非阻塞建议。

### 🟠 3: `_QUERY_LEVEL_MAP["step"]=4` 为冗余代码

**位置：** `scenario_matcher.py` L183：`"step": 4`
**问题：** `handle_step` 实际使用 `_get_agent_level()` 做硬编码检查，不依赖 `_QUERY_LEVEL_MAP`。该表仅被第一版（已废弃）`handle_query` 引用。追加 `step: 4` 无害但属于未使用代码。
**建议：** 可选清理。技术方案 v1.1 §3.1 已说明该表为死代码，可择机移除。

---

## 四、功能完整性验证

| 场景 | 输入 | 预期 | 验证 |
|:-----|:-----|:-----|:----:|
| 步骤完成 | `##step##complete##R131` | → `_cmd_step_complete` 执行 | ✅ |
| 步骤打回含原因 | `##step##reject##R131##bug太多` | → `_cmd_step_reject` 执行 | ✅ |
| 步骤重启 | `##step##restart##R131` | → `_cmd_step_handoff` 执行 | ✅ |
| 强制推进 | `##step##force##R132` | → `_cmd_step_force` 执行 | ✅ |
| 暂停 | `##step##pause##R132` | → 占位回复 | ✅ |
| 恢复 | `##step##resume##R132` | → 占位回复 | ✅ |
| 未知 action | `##step##unknown##R132` | → `❌ 未知步骤操作` | ✅ |
| 无参数 | `##step` | → 显示帮助文本 | ✅ |
| L1 用户操作 | L1 发 `##step##complete##R131` | → 权限不足 ❌ | ✅ |
| 旧兼容 | `!step_complete R131` | → 旧命令正常 | ✅（未修改旧代码） |
| ##query 不受影响 | `##query##whoami` | → rule 25 拦截 | ✅（priority 25 < 28） |
| ##命令不受影响 | `##start##R132` | → rule 30 拦截 | ✅（priority 30 > 28） |

---

## 五、汇总 & 结论

### 亮点
- 实现完整覆盖 6 个 action，含 `reject` 的原因解析
- 权限检查复用 R131 已确立的 `_get_agent_level()` 模式，双层校验
- 注册位置精确（priority 28），不干扰已有规则
- 向后兼容——旧 `!step_*` 代码零改动

### 🟡 建议
1. 清理 `match_query` / `handle_query` 死代码（~90 行可删）
2. `match_step` 前缀收紧为 `startswith("##step##")` 避免误匹配

### 结论
> **✅ 通过** — 功能完整，6 项验收项全部通过。两处 🟡 建议不影响管线推进。

---

*审查结束*
