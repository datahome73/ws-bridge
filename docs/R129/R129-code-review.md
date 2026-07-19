# R129 代码审查报告 — PipelineAutoStarter 退役清理 + Bug 修复

> **审查人：** 🔍 小周
> **审查范围：** Commit `5a199c6` (feat R129 Step 3 — 纯代码清理) + `5614ceb` (fix B-5/B-6/B-7)
> **Baseline：** `9ee3e0f` (R129 Step 2 技术方案)
> **依据：** R129 需求文档 v1.2 + 技术方案 v1.0

---

## 0. 审查结论

🟢 **通过** — 全部 15 项验收项通过，代码清理彻底彻底无误。

---

## 1. 编译验证 ✅ — RV-1 PASS

| 文件 | 编译结果 |
|:-----|:--------:|
| `server/ws_server/__main__.py` | ✅ 零错误 |
| `server/ws_server/pipeline_context.py` | ✅ 零错误 |
| `server/ws_server/main.py` | ✅ 零错误 |
| `server/ws_server/pipeline_engine.py` | ✅ 零错误 |
| `server/ws_server/scenario_matcher.py` | ✅ 零错误 |

---

## 2. 需求→方案→代码追溯矩阵

### CL: 清理验证 (P0 × 5)

| 编号 | 验收项 | 预期 | 验证方式 | 结果 |
|:-----|:-------|:-----|:---------|:----:|
| **CL-1** | `pipeline_auto_starter.py` 已删除 | 文件不存在 | `test -f` | ✅ 已删除（211 行） |
| **CL-2** | `__main__.py` 无 PipelineAutoStarter import | grep 0 匹配 | `grep -rn PipelineAutoStarter server/` | ✅ 0 匹配 |
| **CL-3** | 全局无 PAS_ENABLED 引用 | grep 0 匹配 | `grep -rn PAS_ENABLED server/` | ✅ 0 匹配 |
| **CL-4** | `pipeline_context.py` 无 `from_work_plan()` | 仅 `from_dict` 存在 | `grep -n "def from_"` | ✅ 唯一方法是 `from_dict` |
| **CL-5** | 无 `created_by="system:pipeline_auto_starter"` | grep 0 匹配 | `grep -rn "pipeline_auto_starter" server/*.py` | ✅ 仅留注释（可接受） |

### FX: 修复验证 (P0 × 3)

| 编号 | 验收项 | 实现位置 | 结果 |
|:-----|:-------|:---------|:----:|
| **FX-1** | `{round}` 占位符在 PipelineEngine 中被替换 | `pipeline_engine.py:216` +1 行 | ✅ |
| **FX-2** | `_send_to_agent` 不产生 DB 回放重复 | `main.py:2536-2548` + `message_store.py:170` `is_duplicate()` | ✅ |
| **FX-3** | `##start/status/advance/archive/stop` 全部正常响应 | `scenario_matcher.py:193-209` 直接调用 `_main._handle_hash_*()` | ✅ |

### RV: 回归验证 (P0 × 4)

| 编号 | 验收项 | 验证 | 结果 |
|:-----|:-------|:-----|:----:|
| **RV-1** | py_compile 全量零错误 | 5 个文件全部通过 | ✅ |
| **RV-2** | `_auto_dispatch` 正常派活 | main.py / pipeline_engine.py dispatch 逻辑未改动 | ✅ |
| **RV-3** | `PAS_ENABLED` 不再需要 | 所有 PAS_ENABLED 引用已删除 | ✅ |
| **RV-4** | is_duplicate 不误删合法消息 | SQL: channel + content + ts > cutoff, 1s 窗口 | ✅ |

### DO: 文档同步 (P1 × 3)

| 编号 | 验收项 | 结果 |
|:-----|:-------|:----:|
| **DO-1** | inbox-message-protocol.md 无 PAS 引用 | ✅ 无相关引用 |
| **DO-2** | TODO.md 无 PAS 相关项 | ✅ 无相关引用 |
| **DO-3** | 无 PAS_ENABLED 文档残留 | ✅ |

---

## 3. 全局 grep 验证

```bash
$ grep -rn "PipelineAutoStarter" server/   → 0 匹配 ✅
$ grep -rn "pipeline_auto_starter" server/*.py → 仅 pipeline_engine.py 注释引用 (3 处) ✅
$ grep -rn "PAS_ENABLED" server/          → 0 匹配 ✅
$ grep -rn "from_work_plan" server/        → 0 匹配 ✅
$ grep -rn "auto_starter" server/          → 仅 pipeline_engine.py 注释 (3 处) ✅
```

**注释说明：** `pipeline_engine.py:L27/L32/L82` 3 处 docstring 提及 `pipeline_auto_starter.py`，属历史模块角色说明。技术方案 §1.4 明确排除注释清理，不影响运行。

---

## 4. 代码质量审查

### 4.1 架构与设计

| 项 | 评价 |
|:---|:------|
| 删除粒度 | ✅ 精确 — 只删 PAS 类 + 死代码，不动活跃代码 |
| __main__.py 衔接 | ✅ PAS init 块紧邻 R118/R119 钩子，删除后 R118 直接跟在 `app = web.Application()` 后，连接自然 |
| pipeline_context.py 双版本 | ✅ 两个同名 `from_work_plan` 都精确删除，使用 `git diff` 逐块确认 |
| B-7 scenario_matcher 修复 | ✅ 从错误的 `_engine: PipelineEngine = None` 改回 `_main._handle_hash_*()` 直接调用 |
| B-6 消息去重 | ✅ SQL 查同 channel + 同 content + 1s 时间窗，实现安全 |
| B-5 占位符别名 | ✅ 1 行 `{round}: ctx.round_name` 解决问题 |

### 4.2 副作用分析

| 风险 | 分析 | 等级 |
|:-----|:------|:----:|
| PAS 删除后启动流程中断 | PAS 已自 R119 起禁用，`PAS_ENABLED=0` 即跳过整个块 | 🟢 |
| from_work_plan 被意外调用 | 已被 R110 版覆盖，仅 PAS 调用，PAS 已删 = 安全 | 🟢 |
| B-7 修复后 `_handle_hash_*` 死代码仍存在 | 旧 engine.handle_hash_* 方法仍可供未来使用，不冲突 | 🟢 |
| is_duplicate 误去重 | 1s 时间窗 + 精确 content 匹配，相同 content 在 1s 内才去重 | 🟢 |
| __main__.py 行号偏移 | PAS 删除后 __main__.py 从 878 行 → 836 行，无关代码无影响 | 🟢 |

### 4.3 潜在改进建议（💡 非阻塞）

| # | 位置 | 建议 |
|:-:|:-----|:------|
| 💡 | `pipeline_engine.py` 模块 docstring (L27/L32/L82) | 未来可考虑从 docstring 移除已删除模块的引用，但本轮不处理 |

---

## 5. 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:----:|
| 敏感信息硬编码 | ✅ 无 |
| 调试日志/print 残留 | ✅ 无 |
| TODO/FIXME 残留 | ✅ 无 |
| 死函数残留 | ✅ 旧 `_handle_hash_*` 在 main.py 中仍存在但已通过 scenario_matcher 直接路由，非死代码 |

---

## 6. 文件改动总览（9ee3e0f → 5a199c6）

| 操作 | 文件 | 行数变化 | 说明 |
|:-----|:-----|:--------:|:------|
| 🗑️ 删除 | `server/ws_server/pipeline_auto_starter.py` | -211 | 整个文件 |
| ✂️ 修改 | `server/ws_server/__main__.py` | -42 | 删除 PAS import + init 块 |
| ✂️ 修改 | `server/ws_server/pipeline_context.py` | -223 | 删除 R109 + R110 两段 `from_work_plan` |
| 🐛 修复 | `server/ws_server/main.py` | +24 -18 | B-6 is_duplicate 去重 |
| 🐛 修复 | `server/ws_server/pipeline_engine.py` | +1 | B-5 `{round}` 占位符 |
| 🐛 修复 | `server/ws_server/scenario_matcher.py` | +13 -17 | B-7 回退直接调用 |
| 🐛 修复 | `server/ws_server/message_store.py` | +19 | 新增 `is_duplicate()` |
| **合计** | **7 文件** | **净 -437 行** | — |

---

## 7. 总结

| 分组 | 状态 | 说明 |
|:-----|:----:|:------|
| CL 清理 (5 项) | ✅ 全部通过 | 文件删除 + import 清理 + 全局 grep 零残留 |
| FX 修复 (3 项) | ✅ 全部通过 | B-5/B-6/B-7 均正确修复 |
| RV 回归 (4 项) | ✅ 全部通过 | 编译 + 派活 + 环境变量 + 去重安全 |
| DO 文档 (3 项) | ✅ 全部通过 | 无 PAS 文档残留 |

**最终裁决：🟢 通过 → Step 5 🧪 QA 验证**

---

*审查报告结束 — 版本 v1.0*
