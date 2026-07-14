# R117 代码审查报告 — 自动派活修复轮

> **审查人：** 🔍 小周
> **基线：** `origin/dev`（commit `014ab2321f78c58b2d1c9d2eb4f2e1e044281e38`）
> **审查目标：** `server/ws_server/main.py`（R100 重构后的 4071 行模块）
> **参考文档：** [技术方案](./R117-tech-plan.md)，[需求文档](./R117-product-requirements.md)
> **结论：** ✅ **通过 — 0 Critical, 2 Observation, 建议合并**

---

## 一、审查清单逐项验证

| # | 验收项 | 预期 | 结果 | 证据 |
|:-:|:-------|:-----|:----:|:-----|
| 1 | _resolve_card_key_to_ws_id("arch-bot") 返回 ws_xxx | 函数返回有效 WS ID | ✅ | L2851-2885 三策略实现完整 |
| 2 | 未知 card key 返回 "" | 空字符串 | ✅ | L2860-2861 early return "" |
| 3 | ##start## 创建后所有 step agent_id 为 ws_ 前缀 | 创建时 bridge 正确 | ✅ | L3009-3019 双保险 bridge + fallback |
| 4 | Step 1 -> Step 2 自动派活 | 日志 + 实际发送 | ✅ | L2457-2461 推进日志 + ensure_future |
| 5 | card key 无对应 WS 连接时 warning | [R117] 无法解析 card key | ✅ | L2571-2575 |
| 6 | sent=0 日志（目标离线） | warning 不崩溃 | ✅ | L2361-2365 |
| 7 | 已有管线不受影响 | 正常返回 | ✅ | 纯新增逻辑，无回归路径 |

---

## 二、文件改动总览

| # | 位置 | 行号 | 改动 | 行数 | 状态 |
|:-:|:-----|:----:|:-----|:----:|:----:|
| 1 | _resolve_card_key_to_ws_id() 新增 | L2851-2885 | 三策略 fallback 函数 | **+35** | ✅ |
| 2 | _auto_dispatch() card key fallback | L2562-2575 | startswith("ws_") 检查 + resolve | **+14** | ✅ |
| 3 | _handle_hash_start() else fallback | L3013-3019 | name_to_ws 失败时调用 resolve | **+7** | ✅ |
| 4 | _send_to_agent() sent=0 日志 | L2361-2365 | 循环后检查 sent==0 | **+5** | ✅ |
| 5 | _try_advance_pipeline() 推进日志 | L2457-2460 | dispatch 前 log 标记 | **+4** | ✅ |

**总计：** 1 文件修改，5 处插入，～**+65 行**（不含空行/注释）

---

## 三、发现项

### 🔴 Critical: 无

### 🟡 Observation 1: 策略 2 字段名差异

**位置：** _resolve_card_key_to_ws_id() L2873-2875

**实际代码：** 只检查 _rec.get("name", "") == display_name

**需求文档** 额外检查 _rec.get("display_name")。

**分析：** _r72_users 注册时仅存 name 键（{"name": display_name}），display_name 字段不存在。需求文档的死分支不会实际命中。**实现正确。**

### 🟡 Observation 2: 函数内局部 import 冗余

**位置：** _handle_hash_start() L2990-2991

ac_mod 已在模块级 L18 import。函数内重复 import 为 _ac_mod 无实际影响。变量作用域正确，无 shadow。

### 💡 Suggestion: _r72_users key 命名一致性

_r72_users 注册时用 {"name": ...}，persistence.get_api_keys() 用 "display_name"。策略 2/3 依赖 _r72_users 的 "name" 键——历史原因，当前成立。标注为未来技术债。

---

## 四、功能完整性验证

### 4.1 三策略 fallback 覆盖度

| 策略 | 数据源 | 匹配条件 | 覆盖场景 | 完整性 |
|:----:|:-------|:---------|:---------|:------:|
| 1 | persistence.get_api_keys() | display_name -> ws_id | api_key 已注册的 bot | ✅ |
| 2 | state._r72_users | name -> agent_id | R72 已注册 bot | ✅ |
| 3 | _connections + _r72_users 交叉 | 运行时连接扫描 | 在线但 api_key 未注册的 bot | ✅ |

**结论：** 三策略按优先级由窄到宽，完整覆盖所有注册场景。边界情况：
- card 为 None -> L2859-2861 立即返回 "" ✅
- display_name 为空 -> L2865 if display_name: 跳过 ✅
- 全部未命中 -> L2885 返回 "" ✅

### 4.2 副作用分析

| 修改 | 潜在副作用 | 验证 |
|:-----|:-----------|:-----|
| _auto_dispatch() 修改 next_step_info["agent_id"] | 内存中 agent_id 被改写 | ✅ 末端调用，后续无代码依赖 |
| _handle_hash_start() 中 agent_id_for_step 改写 | 在 steps_list.append() 前影响 | ✅ 纯局部作用域 |
| _send_to_agent() sent=0 日志 | 纯日志，无逻辑变更 | ✅ |
| _resolve_card_key_to_ws_id() 调用 _build_name_to_ws_map() | 每次 fallback 触发 O(n) | ✅ 管线 N<=10，开销可忽略 |

### 4.3 sent=0 日志截断安全

- ✅ target_agent_id[:20] 截断保护：WS ID ws_xxx 截前 20 字符，不泄露完整 ID
- ✅ 日志级别 warning，prometheus 可见
- ✅ 不包含 payload 内容，不泄露业务信息

### 4.4 变量作用域（函数内 import）

- ✅ _ac_mod（函数内局部）与 ac_mod（模块级）名称不同，无 shadow
- ✅ _resolve_card_key_to_ws_id() 内部使用 ac_mod（模块级），与调用方 _ac_mod 无关
- ✅ DEFAULT_STEPS / DEFAULT_STEP_ORDER 仅在此函数内需要，局部 import 是 Python 惯用法

---

## 五、汇总 & 结论

### 亮点

- **零侵入设计：** 所有 5 处修改均为纯新增代码（插入），无原有代码删除或修改，回归风险极低
- **三策略全面覆盖：** _resolve_card_key_to_ws_id() 的 fallback 树从精确匹配到运行时扫描，无遗漏
- **防御性编程：** _auto_dispatch() 中 fallback 失败时 return False 优雅跳过，不会崩溃
- **日志完备性：** sent=0 日志 + 推进日志 + fallback 日志，三处串联形成完整链路追踪

### 结论

> ✅ **审查通过。** 5 处修改均正确实现技术方案。三策略 fallback 完整覆盖所有注册场景，无副作用，无回归风险。仅发现 2 处非阻塞观察项。

### 建议顺序

1. 合并到 dev
2. 后续轮次中清理需求文档 R117-product-requirements.md 策略 2 的死分支
3. (可选) 未来将 _r72_users 的 key 命名规范化

---

**审查日期：** 2026-07-15
**审查人：** 🔍 小周
