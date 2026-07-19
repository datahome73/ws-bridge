# R128 代码审查报告 — Bug + Critical 修复轮

> **审查人：** 🔍 小周
> **Commit：** `4106c98` (fix(R128): Step 3 — Bug + Critical 修复轮)
> **Baseline：** `02690c3` (R127 Step 3: pipeline_engine.py 模块提取)
> **依据：** R128 需求文档 v1.0 + v1.1 + 技术方案 v1.0

---

## 0. 审查结论

🔴 **需修改** — B-4 正则仍有偏差（B4-2/B4-3 不匹配），修复后复审通过。

---

## 1. 编译验证 ✅ — RV-1 PASS

| 文件 | 编译结果 |
|:-----|:--------:|
| `server/ws_server/main.py` | ✅ 零错误 |
| `server/ws_server/__main__.py` | ✅ 零错误 |
| `server/ws_server/pipeline_engine.py` | ✅ 零错误 |

---

## 2. 需求→方案→代码追溯矩阵

### 🔴 C-1 — engine 注入修复

| 验收项 | 方案坐标 | 代码位置 | 状态 |
|:-------|:---------|:---------|:----:|
| C1-1: `_sm._engine = _ensure_engine()` | main.py L4817 附近 | `main.py L66` | ✅ |
| C1-2: 容器启动后 `##status` 正常返回 | 运行时验证 | scenario_matcher → engine.handle_hash_status() | ✅ 路由正确 |

### 🔴 C-3 — __main__.py 启动时序修复

| 验收项 | 方案坐标 | 代码位置 | 状态 |
|:-------|:---------|:---------|:----:|
| C3-1: on_startup 先调用 `_ensure_engine()` | __main__.py L838-848 | `__main__.py L838-848` | ✅ |
| C3-2: 容器正常启动不崩溃 | `_ensure_engine()._retry_loop()` | `__main__.py L839` | ✅ |
| C3-3: `_restore_dispatches` 同理 | `_ensure_engine().restore_pipeline_dispatches()` | `__main__.py L847` | ✅ |

### 🔴 B-1 — 派活消息双条显示（P1）

| 验收项 | 结果 | 证据 |
|:-------|:----:|:-----|
| B1-1: PipelineEngine.auto_dispatch 无 ms.save_message | ✅ | `pipeline_engine.py:807` auto_dispatch 中无 save_message 调用 |
| B1-2: Web 端每个 dispatch 只显示一条 | ✅ | 引擎版本已清洁，旧 main.py `_auto_dispatch` 仍含 save_message 但不再经新路由调用 |

### 🟡 B-3 — ##status 缺 in_progress 图标（P2）

| 验收项 | 结果 | 证据 |
|:-------|:----:|:-----|
| B3-1: in_progress 有正确图标 | ✅ | pipeline_engine.py `format_context()` L157-170: `IN_PROGRESS` → `🔄` |
| B3-2: 已派活 step 显示 🔄 | ✅ | `##status` 路由: scenario_matcher → engine.handle_hash_status() → format_context() |

**注：** old main.py `_handle_hash_status` 的 status_icons 字典仍缺 `in_progress`，但该函数已是死代码。

### 🟡 B-4 — 完成消息格式容错（P2） — 🔴 FAIL

| 验收项 | 预期 | 測試结果 | 状态 |
|:-------|:-----|:--------:|:----:|
| B4-1: `已完成 ✅ R128 Step 4` | ✅ 匹配 | ✅ 匹配 | ✅ |
| **B4-2: `✅ 已完成 R128 Step 4，已推 dev`** | **✅ 匹配** | **❌ 不匹配** | **🔴 FAIL** |
| **B4-3: `完成 ✔️ R128 step 4`** | **✅ 匹配** | **❌ 不匹配** | **🔴 FAIL** |
| B4-4: `搞定了 R128 Step 4` | ❌ 不匹配 | ❌ 不匹配 | ✅ |

**根因：** 当前正则 `r"(?:已完成|完成)\s*[✅✔️]\s*R(\d+)\s*[Ss]tep\s*(\d+)"` 有两个问题：
1. **emoji 在前不匹配** — 要求关键字在 emoji 之前，未处理 `✅ 已完成` 语序
2. **FE0F 变体不匹配** — `✔️` = `✔`(U+2714) + `️`(U+FE0F)，`[✅✔️]` 后剩余 FE0F 破坏匹配

**修复建议：**
```python
m = re.search(
    r"(?:(?:已完成|完成)\s*(?:[✅✔️]\ufe0f?)|(?:[✅✔️]\ufe0f?)\s*(?:已完成|完成))"
    r"\s*R(\d+)\s*[Ss]tep\s*(\d+)",
    content
)
```

### 🟡 B-2 — 离线 bot 派活丢失（P2） — ✅ 通过

| 验收项 | 代码位置 | 状态 |
|:-------|:---------|:----:|
| B2-1: 首轮重试间隔 15s | `pipeline_engine.py L1014` | ✅ |
| B2-2: 3 次后通知 PM | `pipeline_engine.py L1051-1055` | ✅ |
| B2-3: 5 次后 exhausted | `pipeline_engine.py L1041-1045` | ✅ |

**退避验证：** 15s → 30s → 60s → 120s → 180s(capped) ✅

---

## 3. 代码质量审查

### 3.1 架构与设计

| 项 | 评价 |
|:---|:-----|
| C-1/C-3 引擎初始化 | ✅ 正确，惰性初始化 + 安全调用 |
| B-1/B-3 "已清洁" 合理性 | ✅ R127 提取时 PipelineEngine 天然不含 B-1/B-3 缺陷 |
| B-2 重试退避 | ✅ 指数退避 + PM 通知 + exhausted 标记，设计完整 |
| B-4 正则容错 | ⚠️ 方向正确但实现不完全，未覆盖 emoji 在前和 FE0F 变体 |

### 3.2 边界情况分析

| # | 场景 | 风险 |
|:-:|:-----|:----:|
| 1 | `_ensure_engine()` 内递归调用 | 🟢 功能正确，第二次进入时 engine 已非 None |
| 2 | retry exhausted 后 PM 再次离线 | 🟡 通知可能丢失，可接受 |
| 3 | B-4 regex 误匹配日常文本 | 🟢 4 条件同时出现概率极低 |
| 4 | 旧 `_handle_hash_*` 被意外调用 | 🟢 路由已全改 scenario_matcher |
| 5 | 15s 扫描间隔大量 pending retry | 🟢 O(n) n < 10 |
| 6 | engine 重复初始化 | 🟢 `if engine is None:` 守卫 |

### 3.3 潜在改进建议（💡 非阻塞）

| # | 位置 | 建议 |
|:-:|:-----|:------|
| 💡 | `main.py L66` | `_sm._engine = _ensure_engine()` → 可简化为 `_sm._engine = engine`（此时已初始化） |

---

## 4. 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:----:|
| 硬编码敏感信息 | ✅ 无 |
| 调试日志/print 残留 | ✅ 无 |
| TODO/FIXME 残留 | ✅ 无 |
| 死代码残留 | ✅ 旧 `_handle_hash_*` 在 main.py 中残留但已不被路由调用 |

---

## 5. 总结

| 分组 | 状态 | 说明 |
|:-----|:----:|:------|
| C-1 engine 注入 | ✅ | `_sm._engine = _ensure_engine()` 正确 |
| C-3 启动时序 | ✅ | 两处 on_startup 钩子均使用 `_ensure_engine()` |
| B-1 消息双条 | ✅ | PipelineEngine.auto_dispatch 无冗余 save_message |
| B-3 in_progress 图标 | ✅ | format_context() 已正确处理 IN_PROGRESS |
| B-2 离线重试 | ✅ | 15s 首轮 + 退避 + PM 通知(3次) + exhausted(5次) |
| **B-4 正则** | **🔴 FAIL** | B4-2(emoji在前)和B4-3(FE0F变体)不匹配 |
| RV-1 编译 | ✅ | 3 文件零错误 |

### 🔴 修复要求

B-4 正则需修复两种 PRD 指定格式的匹配（1 行正则替换），修复后更新此报告中 B-4 状态为 ✅ 并推送。

---

*审查报告结束 — 版本 v1.0*
