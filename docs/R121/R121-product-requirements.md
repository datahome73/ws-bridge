# R121 产品需求文档（Product Requirements）

## 一、概述

| 字段 | 值 |
|:-----|:----|
| 轮次 | R121 |
| 类型 | 🛠 修复（Bug Fix） |
| 主题 | Web 管线信息显示倒序 |
| 总步数 | 1 步（PM 直出编码任务） |
| 编码量 | 极小（前端 JS 排序修复 + 后端数据补充） |
| 需求审核 | ✅ David 已确认 |

---

## 二、问题描述

### 当前行为

Web 端管线仪表盘（Tab4：📊 管线）显示的管线卡片**未按最新轮次排在最前面**。当前管线列表的顺序是 R120、R119、R118…（由后端返回顺序决定，未做有效排序）。

### 期望行为

管线仪表盘应该按轮次**倒序**显示，即**最新轮次在最上面**：

```
R121  ← 最新在顶部
R120
R119
R118
...  ← 更旧的往下排
```

---

## 三、技术分析

### 3.1 根因

已有排序代码在 `templates.py` 的 `renderPipelineDashboard()` 函数中，通过 `created_at` 时间戳降序排列：

```javascript
pipelines.sort(function(a,b) {
  return (b.created_at || 0) - (a.created_at || 0);
});
```

但 `##start` 管线创建路径（`_handle_hash_start` in `main.py`）在构造 `PipelineContext` 时**未设置 `created_at`**，默认值为 `0.0`。导致所有管线的 `created_at` 一样（= 0），前端排序退化为输入顺序（后端遍历 PipelineManager._contexts dict 的顺序）。

### 3.2 修复方案

**最优方案：按轮次名（round_name）的数字部分降序排序**

理由：
- 不依赖 `created_at` 时间戳（可能有多个轮次在同一时间段创建）
- 轮次名总是连续的（R119 → R120 → R121），数字大小天然反映新旧
- 即使后端修复了 `created_at`，双重保障无副作用

**实现：**

前端 JS 排序改为解析 round_name 的数字后缀做降序：

```javascript
function extractRoundNum(name) {
  const m = (name || '').match(/R(\d+)/i);
  return m ? parseInt(m[1], 10) : 0;
}

pipelines.sort(function(a,b) {
  return extractRoundNum(b.round_name) - extractRoundNum(a.round_name);
});
```

### 3.3 补充修复（加分项）

在 `_handle_hash_start` 中设置 `created_at = time.time()`，防止后续任何依赖时间戳的排序/筛选逻辑再次出问题：

```python
# In _handle_hash_start, after line ~3266:
ctx = PipelineContext(
    ...
    created_at=time.time(),  # ← 新增
    ...
)
```

---

## 四、涉及文件

| 文件 | 改动 |
|:-----|:-----|
| `server/web_ui/templates.py` | `renderPipelineDashboard()` 中排序逻辑从 `created_at` 改为 `round_name` 数字解析降序 |
| `server/ws_server/main.py` | `_handle_hash_start()` 中 PipelineContext 构造补充 `created_at=time.time()`（可选） |

---

## 五、验证标准

| # | 验证项 | 预期 |
|:-:|:-------|:-----|
| ① | 已有管线 R121、R120、R119 都在数据库 | 三个管线都存在 |
| ② | 访问 Web 端 Tab4 📊 管线 | R121 卡片在顶部，R120 居中，R119 在底部 |
| ③ | 新创建 `##start##R122` 后刷新 | R122 出现在顶部（即使 `created_at` 未设） |
| ④ | 无管线时不报错 | 显示「暂无管线」空状态 |

---

## 六、WORK_PLAN

```yaml
round_num: R121
total_steps: 1
steps:
  - step: 1
    role: dev
    agent: 爱泰
    task: |
      修改 templates.py 的 renderPipelineDashboard() 排序逻辑。
      将 `(b.created_at || 0) - (a.created_at || 0)` 替换为按 round_name 数字解析降序。
      可选：在 _handle_hash_start 补充 created_at=time.time()。
    files:
      - server/web_ui/templates.py
      - server/ws_server/main.py (可选)
```

> **注意：** 此轮仅 1 步编码，无 Step 2（架构师无必要）、无 Step 4（审查极简代码可合并）、无 Step 5（QA 验收即测试）、无 Step 6（部署由用户转发给 Ops）。
