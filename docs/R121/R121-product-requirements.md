# R121 产品需求文档（Product Requirements）

## 一、概述

| 字段 | 值 |
|:-----|:----|
| 轮次 | R121 |
| 类型 | 🛠 修复（Bug Fix） |
| 主题 | Web 管线仪表盘按轮次倒序显示 |
| 总步数 | 6 步（全流程管线） |
| 编码量 | 极小（~5 行 JS 排序逻辑变更 + ~1 行 Python created_at 补充） |

---

## 二、问题描述

### 当前行为

Web 端管线仪表盘（Tab4，📊 管线）显示的管线卡片**未按最新轮次排在最前面**。各管线顺序散乱（由后端 dict 遍历顺序决定），最新启动的 R121 不在最顶部。

### 期望行为

管线仪表盘按轮次倒序显示，最新轮次在最上面：

```
R121  ← 最新在顶部
R120
R119
R118
...  ← 更旧的往下排
```

---

## 三、技术分析

### 3.1 根因分析

**前端已有排序代码但无效：**

`templates.py` 中 `renderPipelineDashboard()` 通过 `created_at` 时间戳降序排列：

```javascript
pipelines.sort(function(a,b) {
  return (b.created_at || 0) - (a.created_at || 0);
});
```

但 `##start` 管线创建路径（`_handle_hash_start` in `main.py`）在构造 `PipelineContext` 时**未设置 `created_at`**，默认值为 `0.0`。所有管线 `created_at` 一样，排序退化为输入顺序。

### 3.2 修复方案

**最优方案：按 round_name 的数字部分降序排序**

理由：
- 不依赖 `created_at` 时间戳（可能有多个轮次在同时间段创建）
- 轮次名总是连续的（R119 → R120 → R121），数字大小天然反映新旧
- 即使后端修复了 `created_at`，双重保障无副作用

**实现：**

前端 JS 排序改为解析 round_name 的数字后缀做降序：

```javascript
function extractRoundNum(name) {
  const m = (name || '').match(/R(\d+)/i);
  return m ? parseInt(m[1], 10) : 0;
}

// 替换原有的 sort 行
pipelines.sort(function(a,b) {
  return extractRoundNum(b.round_name) - extractRoundNum(a.round_name);
});
```

**补充修复：** 在 `_handle_hash_start` 中设置 `created_at = time.time()`，防止后续任何依赖时间戳的排序/筛选逻辑再次出问题。

---

## 四、涉及文件与变更摘要

| 文件 | 改动 | 说明 |
|:-----|:-----|:------|
| `server/web_ui/templates.py` | 替换排序函数 | `renderPipelineDashboard()` 中约 3-5 行 JS |
| `server/ws_server/main.py` | 加 1 行参数 | `_handle_hash_start()` 中 `created_at=time.time()` |

---

## 五、验证标准

| # | 验证项 | 预期 |
|:-:|:-------|:------|
| ① | 已有管线 R121、R120、R119 都在数据库 | 三个管线都存在 |
| ② | 访问 Web 端 Tab4 📊 管线 | R121 卡片在顶部，R120 居中，R119 在底部 |
| ③ | 新创建 `##start##R122` 后刷新 | R122 出现在顶部 |
| ④ | 无管线时不报错 | 显示「暂无管线」空状态 |
| ⑤ | 排序不影响消息列表等其他 Tab | 其他 Tab 显示正常 |

---

## 六、管线步说明

### Step 1 — 需求文档已审核
PM（小谷）推 git 标记 WORK_PLAN 已审核。

### Step 2 — 技术方案
Arch（小开）确认改动范围极小，评估排序方案的边界情况（无管线、单管线、同名冲突）。

### Step 3 — 编码实现
Dev（爱泰）实现：修改 `templates.py` 排序逻辑 + `main.py` 补充 `created_at`。

### Step 4 — 代码审查
Review（小周）审查变更是否符合规范，确认不影响其他 Tab。

### Step 5 — 测试验证
QA（泰虾）在生产容器上验证各场景（多管线、单管线、无管线、新建管线后刷新）。

### Step 6 — 合并部署
Ops（用户/小爱）合并 dev → main，重建 Docker 镜像，重启容器。

---

## 七、WORK_PLAN

```yaml
round_num: R121
total_steps: 6
steps:
  - step: 1
    role: pm
    agent: 小谷
    task: 需求文档 & WORK_PLAN 已审核推 git
  - step: 2
    role: arch
    agent: 小开
    task: 技术方案确认（极小改动边界评估）
  - step: 3
    role: dev
    agent: 爱泰
    task: 编码实现排序逻辑
    files:
      - server/web_ui/templates.py
      - server/ws_server/main.py
  - step: 4
    role: review
    agent: 小周
    task: 代码审查
  - step: 5
    role: qa
    agent: 泰虾
    task: 测试验证多场景
  - step: 6
    role: operations
    agent: 小爱/用户
    task: 合并部署到生产
```
