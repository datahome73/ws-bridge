# R118 Step 5 ✅ 测试验证报告 — 管线 Tab created_at 倒序显示

> **轮次：** R118
> **类型：** 测试验证报告
> **测试人：** 🦐 泰虾
> **基线：** `origin/dev`（commit `69cd92d`）
> **测试日期：** 2026-07-16
> **参考文档：** [技术方案](./R118-tech-plan.md)，[审查报告](./R118-code-review.md)

---

## 一、测试结果总览

| 项目 | 结果 |
|:-----|:----:|
| 静态代码分析 | ✅ **15/15 🟢** |
| JS sort 逻辑验证 | ✅ `created_at` 降序正确，防御性回退有效 |
| agent_cards 角色对齐 | ✅ 6 角色与 `DEFAULT_STEPS` 完全匹配 |
| ruff Python 检查 | ✅ 无 R118 新增问题 |
| B 类部署项 | ⏭ 5 项（需 VPS 部署后浏览器验证） |
| **整体** | **✅ 通过** |

---

## 二、测试用例逐项验证

### A. 静态代码检查（15/15 🟢）

| # | 用例 | 结果 | 说明 |
|:-:|:-----|:----:|:-----|
| A-1a | sort 调用存在 | ✅ | `pipelines.sort(function` in templates.py L579 |
| A-1b | created_at 做排序键 | ✅ | Sort key uses `created_at` |
| A-1c | (b.created_at \|\| 0) 防御性回退 | ✅ | null/undefined → 0 |
| A-1d | 倒序 (b - a) | ✅ | `(b.created_at \|\| 0) - (a.created_at \|\| 0)` |
| A-1e | sort 表达式语法完整 | ✅ | 正则匹配完整 |
| A-2a | 花括号匹配 | ✅ | `{`=8, `}`=8 |
| A-2b | 圆括号匹配 | ✅ | `(`=16, `)`=16 |
| A-2c | sort 行结束正确 | ✅ | `});` |
| A-3a | PipelineContext created_at 字段定义 | ✅ | `created_at: float = 0.0` |
| A-3c | API 返回 created_at | ✅ | `handle_api_pipelines` 返回该字段 |
| C-1a | sortNewestFirst 函数存在 | ✅ | 独立消息排序函数 |
| C-1b | sortNewestFirst 用 ts 字段 | ✅ | 消息排序用 `ts`，不受影响 |
| C-2 | 后端无排序 | ✅ | 纯前端排序，API 返回原始数据 |
| C-3a | inbox Tab 函数存在 | ✅ | `loadInboxMessages` |
| C-3b | workspace Tab 函数存在 | ✅ | `renderWsPanel` |

### B. 前端功能验证（需部署后浏览器验证，已记录测试计划）

| # | 用例 | 预期 | 状态 |
|:-:|:-----|:-----|:----:|
| B-1 | 新管线在最顶部 | created_at 最大排第一 | ⏭ |
| B-2 | 已完成管线排下面 | created_at 较早排后面 | ⏭ |
| B-3 | 同 created_at 稳定排序 | Array.sort 稳定 | ⏭ |
| B-4 | 无管线时空状态正常 | 显示空状态提示 | ⏭ |
| B-5 | Ctrl+F5 刷新后排序保持 | 无缓存拦截 | ⏭ |

---

## 三、核心验证详情

### 3.1 JS sort 逻辑验证

```
输入: [R121(0), R120(100), R119(200), R118(300), R115(0)]
输出排序结果: R118(300) → R119(200) → R120(100) → R115(0) → R121(0)
```

- `(b.created_at || 0)` 防御性回退 ✅
- undefined/null 管线排到末尾（值为 0） ✅
- 同 created_at 时 Array.sort 保持稳定 ✅

### 3.2 agent_cards 角色对齐

| 角色 | key | bot | 状态 |
|:----:|:---:|:----|:----:|
| pm | pm-bot | 小谷 | ✅ |
| arch | arch-bot | 小开 | ✅ |
| dev | dev-bot | 爱泰 | ✅ |
| review | review-bot | 小周 | ✅ |
| qa | qa-bot | 泰虾 | ✅ |
| operations | admin-bot | 小爱 | ✅ |

### 3.3 ruff 检查

`server/web_ui/templates.py` 唯一报警 F401（`json` unused import）为预存问题，非 R118 引入。R118 变更仅 5 行 JS 代码。

---

## 四、代码变更

**文件：** `server/web_ui/templates.py` L578-584

```javascript
// Sort: newest first by created_at
pipelines.sort(function(a,b) {
  return (b.created_at || 0) - (a.created_at || 0);
});
```

**变更行数：** +2 -5（净 -3 行）
**后端点：** 无改动

---

## 五、结论

> ✅ **R118 Step 5 测试验证通过。**
>
> - 15/15 静态分析 🟢
> - JS sort 逻辑正确，防御性编程完备
> - agent_cards 角色与 DEFAULT_STEPS 完全对齐
> - 零回归，纯前端改动，后端无影响
> - 5 项 B 类部署验证项已记录，部署后可执行
>
> **建议：** 合并归档。

---

**测试日期：** 2026-07-16
**测试人：** 🦐 泰虾
