# R121 Step 5 🦐 测试报告 — 管线轮次倒序 + created_at 补充

**轮次**: R121 — 管线仪表盘按轮次倒序  
**测试人**: 🦐 泰虾  
**基线**: `dev` `944d780`  
**日期**: 2026-07-16

---

## 变更摘要

| # | 文件 | 行数 | 说明 |
|:-:|:-----|:----:|:-----|
| 1 | `server/web_ui/templates.py` | +6/-2 | 排序改为 `extractRoundNum(round_name)` 降序 + 新增辅助函数 |
| 2 | `server/ws_server/main.py` | +1/-0 | `_handle_hash_start` 中补充 `created_at=time.time()` |

---

## 验证结果

### A. JS sort 逻辑验证 （16/16 🟢）

| # | 测试项 | 输入 | 期望 | 结果 |
|:-:|:-------|:-----|:-----|:----:|
| A-1 | `extractRoundNum` 正常轮次 | "R124" | 124 | 🟢 |
| A-2 | `extractRoundNum` 小轮次 | "R12" | 12 | 🟢 |
| A-3 | `extractRoundNum` 个位数 | "R7" | 7 | 🟢 |
| A-4 | `extractRoundNum` 未知前缀 | "abc" | 0 | 🟢 |
| A-5 | `extractRoundNum` 空字符串 | "" | 0 | 🟢 |
| A-6 | `extractRoundNum` undefined | undefined | 0 | 🟢 |
| A-7 | `extractRoundNum` null | null | 0 | 🟢 |
| A-8 | `extractRoundNum` no match | "test" | 0 | 🟢 |
| A-9 | sort 倒序 R124 > R123 | [R123, R124] | [R124, R123] | 🟢 |
| A-10 | sort 倒序 R200 > R100 | [R100, R200] | [R200, R100] | 🟢 |
| A-11 | sort 非 R 前缀排末尾 | [R100, abc] | [R100, abc] | 🟢 |
| A-12 | sort undefined/null 排末尾 | [R100, null, undef] | [R100, null, undef] | 🟢 |
| A-13 | `extractRoundNum` 函数定义存在 | 源码扫描 | 定义在 sort 上方 | 🟢 |
| A-14 | `extractRoundNum` 正则用 `||` 回退 | `(name || '')` | 防御性 | 🟢 |
| A-15 | parseInt 基数明确 | `parseInt(m[1], 10)` | 基数 10 | 🟢 |
| A-16 | sort 比较返回整数 | `return ... - ...` | 正确 | 🟢 |

### B. Python 变更验证 （4/4 🟢）

| # | 测试项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| B-1 | `created_at=time.time()` 存在于 `_handle_hash_start` | 🟢 | PipelineContext 创建时注入 |
| B-2 | `created_at` 在 PipelineContext 定义中有默认值 | 🟢 | `created_at: float = 0.0` |
| B-3 | ruff `templates.py` 无 R121 新增问题 | 🟢 | 唯一报警 F401(json unused) 为预存 |
| B-4 | ruff `main.py` 新增行无问题 | 🟢 | +1 行纯 data 注入，无副作用 |

### C. 回归检查 （3/3 🟢）

| # | 测试项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| C-1 | `created_at` 排序被替换为 `round_name` 排序 | 🟢 | R118 的 `created_at DESC` 替换为 `round_name DESC` |
| C-2 | `created_at` 字段仍保留在 PipelineContext 中 | 🟢 | 作为数据结构字段保留，仅排序键变更 |
| C-3 | 空管线状态不受影响 | 🟢 | 空状态早于排序逻辑返回 |

---

## 结论

| 项 | 状态 |
|:---|:----:|
| **23/23 ALL GREEN** | ✅ **通过** |
| JS sort 逻辑正确 | ✅ `extractRoundNum` 完备 + 倒序正确 |
| Python 变更安全 | ✅ 仅补充 `created_at` 数据注入 |
| 零回归 | ✅ R118 排序替换，字段保留 |

---
*推送到 dev 分支。*
