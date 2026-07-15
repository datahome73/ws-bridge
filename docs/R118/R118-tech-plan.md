# R118 管线 Tab 倒序显示 — 技术方案

> **轮次：** R118
> **类型：** 前端微改动
> **架构师：** 小开
> **基线：** R117（auto-dispatch card key 桥接已部署）
> **参考：** [R118 需求文档](./R118-product-requirements.md)，[WORK_PLAN](./R118-work-plan.md)

---

## 一、问题

### 1.1 现状

Web 仪表盘管线 Tab（Tab 4）渲染管线列表时，排序优先级为：**状态分组 + updated_at 降序**。

当前代码 `server/web_ui/templates.py` L578-584：

```javascript
const order = {running:0, init:1, planning:2, blocked:3, completed:4, cancelled:5, stopped:6};
pipelines.sort(function(a,b) {
  var oa = order[a.status] || 99, ob = order[b.status] || 99;
  if (oa !== ob) return oa - ob;
  return (b.updated_at || 0) - (a.updated_at || 0);
});
```

**效果：** running → init → planning → blocked → completed → cancelled → stopped 顺序分组，组内按 `updated_at` 降序。

**问题：** 新创建的管线出现在底部（因为其状态通常为 `init`，排在 `running` 之后），用户需手动滚动到底部才能看到最新管线。

### 1.2 用户需求

> "管线列表卡片按创建时间倒序排列，最新的管线在最上面，方便查看最新任务" — 需求文档 §2·需求 B

### 1.3 API 数据结构

后端 `/api/pipelines` 返回的每条管线都包含 `created_at` 和 `updated_at` 字段（定义于 `viewer.py` L722-732），前端可直接使用。

---

## 二、修改方案

### 2.1 改动概述

| # | 文件 | 改动 | 行数 |
|:-:|:-----|:------|:----:|
| 1 | `server/web_ui/templates.py` | 修改 L578-584 的 sort 函数 | 4 行 |

**零后端改动，零数据库改动，零新 API。** 纯前端 JavaScript，Ctrl+F5 即生效。

### 2.2 详细设计

**修改前：**

```javascript
// Sort: running first, then planning/blocked, then completed/cancelled
const order = {running:0, init:1, planning:2, blocked:3, completed:4, cancelled:5, stopped:6};
pipelines.sort(function(a,b) {
  var oa = order[a.status] || 99, ob = order[b.status] || 99;
  if (oa !== ob) return oa - ob;
  return (b.updated_at || 0) - (a.updated_at || 0);
});
```

**修改后：**

```javascript
// R118: 按创建时间倒序，最新的管线在最上面
pipelines.sort(function(a,b) {
  return (b.created_at || 0) - (a.created_at || 0);
});
```

### 2.3 设计决策

| 决策 | 选项 | 选择 | 理由 |
|:----|:-----|:-----|:------|
| 排序字段 | `created_at` vs `updated_at` | **`created_at`** | 需求明确要求"**创建时间**倒序"；`updated_at` 在每次状态变更时更新，会让被操作过的旧管线重新排到前面 |
| 排序方向 | 降序 vs 升序 | **降序** | 最新的在上面 |
| 排序粒度 | 纯倒序 vs 状态分组+倒序 | **纯倒序** | 需求明确要求只按创建时间排序；去除状态分组让界面可预测：用户在顶栏附近总能找到最新任务 |
| 后端 vs 前端 | 改 API 排序 vs 前端排序 | **前端排序** | API 返回完整列表，前端排序零耦合，部署后 Ctrl+F5 即可生效 |
| 排序稳定性 | 保持插入顺序 vs 强制稳定性 | 不依赖 | `Array.prototype.sort` 在 V8/Chrome 中自 ES2019 为稳定排序，同 `created_at` 的管线保持原始顺序 |

### 2.4 用户可见效果

- 新创建的管线（如 `##start##R118` 后）立即出现列表顶部 ✅
- 管线推进（Step 1→2→3）不改变其在列表中的位置 ✅
- 完成/取消的管线沉底（因为创建时间较早）✅
- 浏览器 Ctrl+F5 刷新后即生效 ✅

---

## 三、数据流

```
用户打开 Tab 4（管线仪表盘）
  │
  ├─ GET /api/pipelines?token=xxx
  │   └─ 返回所有管线的 [{round_name, status, created_at, updated_at, steps, ...}, ...]
  │
  ├─ 前端排序（L578-584，此轮改动）
  │   └─ sort by created_at DESC
  │
  └─ forEach → createPipelineCard() → appendChild(msgList)
```

---

## 四、验收标准

| # | 标准 | 验证方法 | 预期 |
|:-:|:-----|:---------|:-----|
| V-1 | `##start##R118test` 后新管线在顶部 | 刷新页面观察 | 顶栏第一张卡片为 R118test |
| V-2 | 已完成管线不遮挡新管线 | 查看 R116（已完成）位置 | 在列表下方 |
| V-3 | 排序不破坏数据完整性 | 点击管线卡片查看详情 | 展开后 Step 状态正常 |
| V-4 | 多管线时排序正确 | 创建 2+ 管线 | `created_at` 大的排在前面 |
| V-5 | 无管线时界面正常 | 清空所有管线后刷新 | 显示"📊 暂无管线"空状态 |

---

## 五、回滚方案

| 方式 | 操作 | 生效时间 |
|:----|:-----|:---------|
| 代码回滚 | `git revert` 对应 commit push → Devops 重启容器 | 重启后 |
| 临时恢复 | 浏览器端注释掉 sort 代码（dev 调试用） | 即时 |

---

## 六、无变动清单

| 内容 | 状态 | 理由 |
|:-----|:------|:------|
| 后端 API | 不改 | `handle_api_pipelines` 返回完整列表，排序由前端负责 |
| 后端数据模型 | 不改 | `created_at` 已在 PipelineContext.to_dict() 中 |
| CSS 样式 | 不改 | 倒序由 DOM 顺序决定，card 样式无变化 |
| 其他 Tab | 不改 | Tab 1/2/3 维持原有排序（`sortNewestFirst`） |
| 自动派活代码 | 不改 | R117 已部署，本轮只验证不修改 |

---

> **拟定者：** 小开
> **日期：** 2026-07-15
> **状态：** 定稿
