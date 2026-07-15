# R121 代码审查报告 — 管线仪表盘按轮次倒序

> **审查人：** 🔍 小周
> **审查目标：** commit `96d7e26`
> **文件：** `server/web_ui/templates.py` + `server/ws_server/main.py`
> **参考文档：** [技术方案](./R121-tech-plan.md)，[需求文档](./R121-product-requirements.md)
> **结论：** ✅ **通过 — 0 Critical, 0 Observation, 建议合并**

---

## 一、审查清单逐项验证

| # | 验收项 | 预期 | 结果 | 证据 |
|:-:|:-------|:-----|:----:|:-----|
| 1 | 多管线倒序 | R121 > R120 > R119 | ✅ | `extractRoundNum` 解析 round_name 数字后缀，nb - na 降序 |
| 2 | 新建管线后排序正确 | R122 在顶部 | ✅ | parseInt("122") = 122 > 121 |
| 3 | 无管线不报错 | 显示空状态 | ✅ | 排序在 `pipelines.length === 0` return 之后，不会执行 |
| 4 | 不影其他 Tab | sortNewestFirst 不变 | ✅ | 仅修改 `renderPipelineDashboard` 内部排序逻辑 |
| 5 | 后端 created_at 补充 | 新管线 created_at 非零 | ✅ | `created_at=time.time()` 追加至 PipelineContext 构造参数 |
| 6 | 已有管线不受影响 | R119/R120 created_at 仍为 0 | ✅ | 修复② 仅对新管线生效，排序由修复① 独立保证 |

## 二、文件改动总览

| 文件 | 改动 | 行数变化 |
|:-----|:------|:---------|
| server/web_ui/templates.py | 新增 `extractRoundNum()` + 替换 sort 行 | **+6 -2** |
| server/ws_server/main.py | PipelineContext 追加 `created_at=time.time()` | **+1** |

**总计：** 2 文件，**+7 -2 行**

---

## 三、发现项

### 🔴 Critical: 无
### 🟡 Observation: 无

### 💡 观察：parseInt 自动忽略非数字后缀

若 `round_name` 为 `"R121-test"`，正则 `/R(\d+)/i` 捕获 `"121"`，`parseInt("121",10) = 121`。非数字后缀被忽略，排序仍然正确。
此行为在 tech plan 中已分析过 ✅

---

## 四、功能完整性验证

### 4.1 排序正确性矩阵

| round_name | extractRoundNum | 排序位置 |
|:-----------|:----------------|:---------|
| R124 | 124 | 顶部 |
| R123 | 123 | ↑ |
| R122 | 122 | 中间 |
| R121 | 121 | ↓ |
| R120 | 120 | 底部 |
| undefined/null | 0 (\|\| 0) | 最底部 |
| "R121-test" | 121 | 正确位置 |
| "r121" | 121 (i flag) | 正确位置 |

### 4.2 边界情况

| 场景 | round_name | match 结果 | 返回值 | 排序表现 |
|:-----|:-----------|:----------|:------:|:---------|
| 正常管线 | "R121" | ["R121","121"] | 121 | 正确 |
| 小写 r | "r122" | ["r122","122"] | 122 | 正确 (/i flag) |
| 无 round_name | undefined | null | 0 | 最底部 |
| null 值 | null | null | 0 | 最底部 |
| 空字符串 | "" | null | 0 | 最底部 |
| 非 R 格式 | "foo" | null | 0 | 最底部 |
| R121-test | "R121-test" | ["R121","121"] | 121 | 正确 |
| 无管线 | N/A | 不执行排序 | N/A | 空状态 ✅ |

### 4.3 后端 created_at 补充验证

| 检查点 | 结果 |
|:-------|:----:|
| PipelineContext 定义 | `created_at: float = 0.0` → 传参后覆盖为 time.time() | ✅ |
| to_dict() 序列化 | `"created_at": self.created_at` 自动包含 | ✅ |
| 已有管线不受影响 | 旧管线默认值 0.0 保留，排序由修复① 独立保证 | ✅ |
| 前端不依赖 created_at | 排序完全基于 round_name 数字 | ✅ |

### 4.4 回归风险分析

| 修改 | 回归风险 | 理由 |
|:-----|:---------|:-----|
| templates.py sort 替换 | 🟢 低 | 仅修改 `renderPipelineDashboard` 内部，与其他 Tab 隔离 |
| main.py created_at 追加 | 🟢 低 | 纯新增参数，不改变原有逻辑 |

---

## 五、汇总 & 结论

### 亮点

- **双重修复：** 前端按 round_name 数字排序（修复①）+ 后端补充 created_at（修复②），两不相依赖
- **边界覆盖完整：** undefined/null/空字符串/非 R 格式/后缀格式 均有防御性兜底
- **零耦合：** 完全隔离在 `renderPipelineDashboard` 函数内，不影响其他 Tab 或后端逻辑
- **极简改动：** 仅 +7 -2 行，回归风险趋近于零

### 结论

> ✅ **审查通过。** 改动精确、防御充分、边界覆盖完整。无回归风险。

---

**审查日期：** 2026-07-16
**审查人：** 🔍 小周