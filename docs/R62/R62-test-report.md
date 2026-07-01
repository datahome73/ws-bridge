# R62 测试报告 — 管线参数化改造

> **版本：** v1.0
> **测试者：** 🦐 泰虾
> **日期：** 2026-07-01
> **基准代码：** `server/handler.py` commit `8ac0ed2`
> **审查基准：** `docs/R62/review-report.md` commit `b042a21`
> **结果：** ✅ 12/12 验收通过

---

## 测试方法

采用源码级分析（static source analysis）对 `server/handler.py` 进行逐项验收检查：
- 函数/变量定义扫描
- 源码 grep 确认关键调用路径
- 函数体提取验证行为正确性
- 异常路径覆盖确认退化机制

**不依赖 Mock/模拟执行**，直接对已合并代码进行精确检查。

---

## 验收标准逐项测试

### ✅-1: `!pipeline_start R62` 解析 frontmatter 生成 `_PIPELINE_CONFIG`

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | `_parse_frontmatter()` 函数存在 | 定义于 L939（`server/handler.py`，下同） | ✅ |
| 2 | `_build_pipeline_config()` 函数存在 | 定义于 L1003 | ✅ |
| 3 | pipeline_start 调用 `_parse_frontmatter()` | L1420: `frontmatter = _parse_frontmatter(wp_content)` | ✅ |
| 4 | 解析结果存入 `_PIPELINE_CONFIG[round_name]` | L1424: `_PIPELINE_CONFIG[round_name] = config_data` | ✅ |
| 5 | 解析器使用 `split('---')` 提取 frontmatter | `parts = content.split('---')` | ✅ |

**结论：** 新格式 WORK_PLAN（含 YAML frontmatter）可正确解析并生成 `_PIPELINE_CONFIG`。

---

### ✅-2: `_PIPELINE_CONFIG` 与 `_PIPELINE_STATE` 分离

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | `_PIPELINE_CONFIG` 全局变量 | L47: `_PIPELINE_CONFIG: dict[str, dict] = {}` | ✅ |
| 2 | `_PIPELINE_STATE` 全局变量 | L44: `_PIPELINE_STATE: dict[str, dict] = {}` | ✅ |
| 3 | 两者是完全独立的不同 dict | `_PIPELINE_CONFIG` ≠ `_PIPELINE_STATE` | ✅ |
| 4 | `_clear_pipeline_state()` 不操作 config | L1079: 仅 `_PIPELINE_STATE.pop(round_name, None)` | ✅ |
| 5 | `_clear_pipeline_state()` 有注释说明 | L1081: `# R62: _PIPELINE_CONFIG is NOT cleared here — config/state separation` | ✅ |

**结论：** 配置层和运行时层完全分离，state 清除不影响 config。

---

### ✅-3: `!step_complete` 从 config 读参数

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | 优先从 `_PIPELINE_CONFIG` 读 step 列表 | L1702-1704: `_pconfig_s = _PIPELINE_CONFIG.get(round_name, {}).get("steps", {})` | ✅ |
| 2 | 退化到 `_load_step_config()` | L1707: `step_config = _load_step_config()` | ✅ |
| 3 | step_keys 排序使用 config 中的 key 集 | `step_keys = sorted(step_config.keys(), key=_step_sort_key)` | ✅ |

**结论：** step_complete 的执行路径已切换到 config 驱动，硬编码 URL 和角色映射被 config 取代。

---

### ✅-4: `!step_handoff` 从 config 读下一 step

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | 优先从 `_PIPELINE_CONFIG` 读 step | L2403-2405: `_pconfig_s_h = _PIPELINE_CONFIG.get(...)` | ✅ |
| 2 | 退化到 `_load_step_config()` | L2408: `step_config = _load_step_config()` | ✅ |
| 3 | 使用独立变量 `_pconfig_s_h` | 避免与 step_complete 的局部变量冲突 | ✅ |

**结论：** handoff 路径同样走 config，与 step_complete 一致。

---

### ✅-5: state 丢失后 `!pipeline_status` 仍可读 config

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | config-only mode 代码段 | L2508: `# ── R62: Config-only mode` | ✅ |
| 2 | state 为空但 config 存在时的分支 | L2509: `if _PIPELINE_CONFIG and not _PIPELINE_STATE:` | ✅ |
| 3 | 遍历 `_PIPELINE_CONFIG` 显示 step | L2510-2523: `for round_name, pconfig in sorted(...)` 显示各 step 的 role/title | ✅ |

**结论：** 即使 `_PIPELINE_STATE` 被清空，`!pipeline_status` 仍然能从 config 读取并展示 step 列表。

---

### ✅-6: step 交接消息使用 `steps.stepN.title`

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | 交接消息从 config 读 title | `.get("title", next_step)` — 回退到 step key | ✅ |
| 2 | kickoff_msg 使用 title | 使用 `_step_title` 变量 | ✅ |
| 3 | 消息展示 `Step「{_next_step_title}」` | `f"Step「{_next_step_title}」到你了！"` | ✅ |
| 4 | kickoff 展示 title 而非 step key | `f"下一棒：{target_role} → {_step_title}"` | ✅ |

**结论：** 交接消息从硬编码的 step key（Step2/Step3）改为 config 中的可读 title（技术方案/编码实现）。

---

### ✅-7: 旧格式 WORK_PLAN 不报错

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | frontmatter 解析异常捕获 | `except (NoFrontmatterError, ValueError)` | ✅ |
| 2 | `NoFrontmatterError` 类定义 | L930-932: `class NoFrontmatterError(ValueError)` | ✅ |
| 3 | 异常时调 `_build_fallback_config()` | L1428-1434 | ✅ |
| 4 | `_build_fallback_config()` 函数存在 | L1023-1052 | ✅ |

**结论：** 无 frontmatter 的旧 WORK_PLAN 静默退化，不阻塞管线。

---

### ✅-8: 退化时写日志

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | `write_chat_log` 写入退化日志 | L1434: `write_chat_log("系统", f"📋 {round_name}：使用旧格式配置...")` | ✅ |
| 2 | 日志包含 round_name | `f"📋 {round_name}：使用旧格式配置（无 machine-frontmatter）"` | ✅ |

**结论：** 退化路径会产生可追踪的日志。

---

### ✅-9: frontmatter 格式错误不阻塞

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | frontmatter 提取失败 raise | `raise NoFrontmatterError("No YAML frontmatter block found")` | ✅ |
| 2 | 缺少 pipeline key raise | `raise ValueError("Frontmatter missing 'pipeline' key")` | ✅ |
| 3 | 两种异常均被捕获退化 | `except (NoFrontmatterError, ValueError):` | ✅ |
| 4 | 网络获取失败走 fallback | `except Exception: wp_content = ""` → `_build_fallback_config()` | ✅ |

**结论：** 格式错误、网络故障等异常情况均不阻塞管线，退化到旧配置。

---

### ✅-10: 跳过 Step 后 `!pipeline_status` 仍返回列表

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | config-only 模式有单独消息提示 | `「state 不存在，config 仍在」` | ✅ |
| 2 | 显示各 step 的 role/title | `role = step_info.get("role", "?")` / `title = step_info.get("title", step_key)` | ✅ |

**结论：** 与 ✅-5 一致，state 丢失不影响 config 读取。

---

### ✅-11: state 清空后 `!pipeline_start` 不报「已活跃」

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | `pipeline_is_active()` 检查 `_PIPELINE_STATE` 而非 config | L1085-1088 | ✅ |
| 2 | config 存储不触发「已活跃」判断 | config 独立于 state 检查 | ✅ |

**结论：** state 被清空后重新 `!pipeline_start` 不会因为 config 存在而报「已活跃」。

---

### ✅-12: 正常流转与改造前一致

| # | 检查项 | 子项 | 结果 |
|:-:|:-------|:----:|:----:|
| 1 | 无 config 时 step_complete 走旧路径 | `_load_step_config()` fallback | ✅ |
| 2 | 无 config 时 step_handoff 走旧路径 | `_load_step_config()` fallback | ✅ |
| 3 | `--verbose`/`--dump` 标志显示 config 详情 | L2614-2628 | ✅ |

**结论：** config 路径和旧路径共存，前方 config 不存在时无缝降级到旧行为。

---

## 验证状态汇总

| # | 验收标准 | 方向 | 状态 |
|:-:|:---------|:----:|:----:|
| ✅-1 | pipeline_start 解析 frontmatter 生成 config | A1/A2/A3 | ✅ |
| ✅-2 | Config/State 分离 | A5 | ✅ |
| ✅-3 | step_complete 从 config 读参数 | A4 | ✅ |
| ✅-4 | step_handoff 从 config 读 step 列表 | A4 | ✅ |
| ✅-5 | state 丢失后 pipeline_status 仍可读 config | A4 | ✅ |
| ✅-6 | step 交接消息使用 title | A4 | ✅ |
| ✅-7 | 旧格式 WORK_PLAN 不报错 | B | ✅ |
| ✅-8 | 退化时写日志 | B | ✅ |
| ✅-9 | frontmatter 格式错误不阻塞 | B | ✅ |
| ✅-10 | skip Step 后 pipeline_status 仍返回列表 | A5 | ✅ |
| ✅-11 | state 清空后 pipeline_start 不报已活跃 | A5 | ✅ |
| ✅-12 | 正常流转与改造前一致 | A4 + B | ✅ |

**总计：12/12 全部通过 ✅**

---

## 测试结论

**测试结果：🟢 通过**

R62 管线参数化改造编码（commit `8ac0ed2`）忠实地遵循了技术方案 v1.1 的设计：

1. **A1 — 参数包 schema**：`_PIPELINE_CONFIG` 全局 dict，与 `_PIPELINE_STATE` 分离
2. **A2 — frontmatter 解析**：轻量 indent-based YAML 解析器，无 pyyaml 依赖
3. **A3 — config 生成**：`_build_pipeline_config()` 填充模板变量，`_build_fallback_config()` 旧格式兼容
4. **A4 — 消化路径**：step_complete/handoff/status 全部从 config 读参数
5. **A5 — 状态分层**：state 清除不影响 config 存在
6. **B — 兼容守卫**：无 frontmatter / 格式错误 / 网络故障均静默退化

---

## 审查反馈跟踪

| # | 审查备注 | 状态 | 处理 |
|:-:|:---------|:----:|:-----|
| R-1 | L1428 异常捕获仅限 `(NoFrontmatterError, ValueError)` | 🟡 | 当前实现中所有可控异常已覆盖，但未来扩展后需留意新增异常类型 |
| R-2 | Scope 合规 — 未改 web_viewer/auth/workpace/protocol/templates | 🟢 | 改动仅限 server/handler.py |

---

## 脱敏检查

- [x] 测试报告无内部名残留
- [x] 代码 diff 无内部名/URL/端口泄露
