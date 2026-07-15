# R121V2 管线仪表盘按轮次倒序 — 技术方案

> **轮次：** R121V2
> **类型：** 🛠 前端排序修复
> **架构师：** 小开
> **基线：** R121（23/23 ALL GREEN，已部署）
> **参考：** [R121 需求文档](../R121/R121-product-requirements.md)，[R121 WORK_PLAN](../R121/WORK_PLAN.md)
> **说明：** R121V2 继承 R121 的修复目标，作为新管线轮次独立执行全流程验证。

---

## 一、问题

### 1.1 现象

Web 仪表盘管线 Tab（Tab 4 📊 管线）的管线卡片未按最新轮次排在最前面，顺序散乱。

### 1.2 根因

两层失效导致排序不生效：

**① 后端 `created_at` 未设** — `_handle_hash_start` 构造 `PipelineContext` 时未传入 `created_at=time.time()`，默认 `0.0`。

**② 前端按 `created_at` 降序** — 所有管线 `created_at===0`，`b.created_at - a.created_at` 恒为 0，排序退化为 API 返回顺序。

---

## 二、修改方案

### 2.1 改动总览

| # | 文件 | 改动 | 行数 |
|:-:|:-----|:------|:----:|
| ① | `server/web_ui/templates.py` | 排序改为 `round_name` 数字降序 | ~6 行 |
| ② | `server/ws_server/main.py` | `PipelineContext()` 加 `created_at=time.time()` | ~1 行 |

### 2.2 修改① — 前端排序（`templates.py` L578-585）

**替换为：**

```javascript
// R121V2: sort by round_name number descending (R122 > R121 > R120)
function extractRoundNum(name) {
  const m = (name || '').match(/R(\d+)/i);
  return m ? parseInt(m[1], 10) : 0;
}
pipelines.sort(function(a,b) {
  return extractRoundNum(b.round_name) - extractRoundNum(a.round_name);
});
```

**设计要点：**
- `parseInt(m[1], 10)` — 明确基数为 10，避免 `"012"` 被解析为八进制
- `(name || '')` — 防御 `null/undefined`
- `/R(\d+)/i` — 大小写不敏感，兼容 "R121-test" 格式
- `m ? ... : 0` — 非 R 前缀名称排在最底部

**边界覆盖：**

| 输入 | `extractRoundNum` 输出 | 排序位置 |
|:-----|:----------------------:|:---------|
| "R124" | 124 | 顶部 |
| "R12" | 12 | 中部 |
| "R7" | 7 | 中下部 |
| "R121-test" | 121 | 正常（`\d+` 匹配第一个数字序列） |
| "abc" | 0 | 底部 |
| "" / undefined / null | 0 | 底部 |

### 2.3 修改② — 后端补充 `created_at`（`main.py` L3266）

```python
ctx = PipelineContext(
    ...
    created_by=agent_id,
    created_at=time.time(),  # R121V2: 设置创建时间戳
)
```

**目的：** 为未来任何依赖 `created_at` 的功能（过期清理、watchdog、筛选）提供正确数据。不影响当前排序（排序已改用 `round_name` 数字）。

---

## 三、数据流

```
##start##R121V2
  → _handle_hash_start()
    → PipelineContext(..., created_at=time.time())  ← ✏️ ②
    → 落盘 + 自动派活 Step 2

Web Tab4 打开
  → GET /api/pipelines
  → pipelines.sort(round_name DESC)                ← ✏️ ①
    R121V2 → R121 → R120 → ...
  → 卡片渲染
```

---

## 四、验收标准

| # | 验证项 | 方法 | 预期 |
|:-:|:-------|:-----|:------|
| V-1 | 多管线倒序 | 已有 R121V2/R121/R120 | R121V2 顶部 |
| V-2 | 新管线 `##start##R122` | 创建后刷新 | R122 顶部 |
| V-3 | 单管线 | 仅 1 条管线 | 正常显示 |
| V-4 | 无管线 | 清空后刷新 | 空状态 |
| V-5 | 其他 Tab 不受影响 | Tab1/2/3 | 正常 |
| V-6 | `created_at` 非零 | `/api/pipelines/R121V2` | `created_at` > 0 |

---

## 五、无变动清单

| 内容 | 状态 | 理由 |
|:-----|:------|:------|
| API 层 | 不改 | `/api/pipelines` 返回完整列表，前端排序 |
| PipelineContext 数据模型 | 不改 | `created_at` 字段已存在 |
| CSS 样式 | 不改 | 仅 JS sort 逻辑 |
| 其他 Tab | 不改 | `sortNewestFirst()` 独立 |

---

> **拟定者：** 小开
> **日期：** 2026-07-16
> **状态：** 定稿
