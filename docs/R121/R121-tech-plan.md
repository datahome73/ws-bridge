# R121 管线仪表盘按轮次倒序 — 技术方案

> **轮次：** R121
> **类型：** 🛠 修复（Bug Fix）
> **架构师：** 小开
> **基线：** `ws-bridge:r120`（R120 文档验证轮已闭环）
> **参考：** [R121 需求文档](./R121-product-requirements.md)，[WORK_PLAN](./WORK_PLAN.md)

---

## 一、问题分析

### 1.1 当前行为

Web 仪表盘管线 Tab（Tab 4）打开后，管线卡片排序散乱，最新轮次不在顶部。

### 1.2 根因

**两层失效：**

**① 后端：`created_at` 未设（`pipeline_context.py` L129）**

```python
class PipelineContext:
    created_at: float = 0.0  # 默认值 0.0
```

`_handle_hash_start()`（`main.py` L3266）构造 `PipelineContext(...)` 时**未传入 `created_at`**，导致所有管线 `created_at=0.0`：

```python
ctx = PipelineContext(
    round_name=round_name,
    # ... 其他参数 ...
    # ❌ 缺少 created_at=time.time()
)
```

**② 前端：按 `created_at` 排序退化为输入顺序（`templates.py` L578-581）**

```javascript
pipelines.sort(function(a,b) {
  return (b.created_at || 0) - (a.created_at || 0);  // 全为 0 → 不排序
});
```

所有管线 `created_at === 0`，`b.created_at - a.created_at` 恒等于 0，排序退化为 `Array.prototype.sort` 的原始插入顺序（JavaScript 稳定排序，即 REST API 返回顺序）。

### 1.3 影响范围

| 影响 | 范围 |
|:-----|:------|
| 用户视角 | 每次需滚动到底部找最新管线 |
| 数据正确性 | 仅显示顺序问题，管线内容不受影响 |
| 其他 Tab | 消息列表 Tab 1/2/3 使用 `sortNewestFirst()` 函数，独立于管线排序 |

---

## 二、修改方案

### 2.1 改动总览

| # | 文件 | 改动 | 行数 |
|:-:|:-----|:------|:----:|
| ① | `server/web_ui/templates.py` | 替换排序函数：`round_name` 数字降序 | ~5 行 |
| ② | `server/ws_server/main.py` | `PipelineContext()` 加 `created_at=time.time()` | ~1 行 |

### 2.2 修改① — 前端排序（`templates.py` L578-581）

**当前代码：**
```javascript
    // Sort: newest first by created_at
    pipelines.sort(function(a,b) {
      return (b.created_at || 0) - (a.created_at || 0);
    });
```

**修改后：**
```javascript
    // R121: sort by round_name number descending (R121 > R120 > R119)
    pipelines.sort(function(a,b) {
      var na = parseInt((a.round_name || '').replace(/^R/i, '')) || 0;
      var nb = parseInt((b.round_name || '').replace(/^R/i, '')) || 0;
      return nb - na;
    });
```

**设计决策：**

| 选项 | 选择？ | 理由 |
|:-----|:------:|:------|
| `round_name` 数字解析 | ✅ | 轮次名 R{数字} 天然反映新旧，不受 `created_at` 是否设置影响 |
| `parseInt` + `replace(/^R/i,'')` | ✅ | 处理 "R121" → 121，"R120" → 120；大小写不敏感 |
| `\|\| 0` fallback | ✅ | 无 `round_name` 或非 "R{N}" 格式时 fallback 到 0（排最底部） |
| 保留 `created_at` 降序 | ❌ | 依赖 `created_at` 已证明不可靠；双重排序增加复杂度无意义 |

**边界情况：**
- 无管线（`pipelines.length === 0`）：排序不执行，显示空状态 ✅
- 单管线：排序无影响 ✅
- `round_name` 为 "R121-test"：`parseInt` 会解析到 121（`parseInt` 自动忽略非数字后缀）✅
- 无 `round_name` 字段：`\|\| 0` fallback ✅

### 2.3 修改② — 后端补充 `created_at`（`main.py` L3266）

**当前代码：**
```python
    ctx = PipelineContext(
        round_name=round_name,
        task_kind=PipelineTaskKind.DEV,
        workspace_dir=workspace_dir,
        task_dir=task_dir,
        workspace_id="",
        pm_inbox_id=config.PIPELINE_PM_AGENT_ID,
        status=PipelineStatus.INIT,
        current_step=1,
        total_steps=len(DEFAULT_STEPS),
        steps=steps_list,
        references=references,
        message_templates=templates,
        round_title=kv.get("round_title", round_name),
        created_by=agent_id,
    )
```

**修改后（追加 1 行参数）：**
```python
    ctx = PipelineContext(
        ...
        created_by=agent_id,
        created_at=time.time(),  # ═══ R121: 设置创建时间戳，供未来排序/筛选使用 ═══
    )
```

**设计决策：**

| 选项 | 选择？ | 理由 |
|:-----|:------:|:------|
| `created_at=time.time()` | ✅ | 当前排序用 `round_name` 数字，但 `created_at` 是通用元信息，其他功能（watchdog、过期清理）未来可能依赖 |
| 同时更新 `updated_at` | ❌ | `updated_at` 在 `transition_to()` 和 `advance_step()` 中自动更新，无需手动设置 |
| 持久化影响 | ✅ 无 | `to_dict()` / `from_dict()` 已序列化 `created_at`，加参数后自动落盘和恢复 |

---

## 三、数据流图

```
##start##R121
  │
  ▼
_handle_hash_start() (main.py L3210)
  │
  ├─ PipelineContext(..., created_at=time.time())  ← ✏️ 修改②
  │
  ▼
Web UI Tab4 加载
  │
  ├─ GET /api/pipelines → [{round_name: "R121", ...}, {round_name: "R120", ...}]
  │
  ├─ pipelines.sort(... ← ✏️ 修改①: round_name 数字降序
  │   R121 (121) - R120 (120) - R119 (119) - ...
  │
  └─ forEach → createPipelineCard → appendChild
      R121 卡片 ─┐
      R120 卡片  │ 最新在上
      R119 卡片 ─┘
```

---

## 四、验收标准

| # | 验证项 | 方法 | 预期 |
|:-:|:-------|:-----|:------|
| V-1 | 多管线倒序 | 已有 R121/R120/R119 时打开 Tab4 | R121 顶部 → R120 → R119 底部 |
| V-2 | 新建管线后刷新 | `##start##R122` → 刷新页面 | R122 出现在顶部 |
| V-3 | 单管线 | 仅 1 条管线 | 正常显示，无报错 |
| V-4 | 无管线 | 清空后刷新 | 显示「暂无管线」空状态 |
| V-5 | 排序不影响其他 Tab | 切换到 Tab1/2/3 | 消息列表正常（`sortNewestFirst`） |
| V-6 | 新管线 `created_at` 正确 | 查看 `/api/pipelines/R122` | `created_at` 为非零时间戳 |
| V-7 | 已有管线不受影响（修复②仅对新创建生效） | 查看 R119/R120 数据 | `created_at` 仍为 0.0，但排序正常工作（修复①） |

---

## 五、回滚方案

| 方式 | 操作 | 生效 |
|:-----|:------|:-----|
| 前端回滚 | 恢复 `templates.py` L578-581 为 `created_at` 降序 | Ctrl+F5 刷新后 |
| 后端回滚 | 删除 `main.py` 中的 `created_at=time.time()` line | 容器重启后 |

---

> **拟定者：** 小开
> **日期：** 2026-07-16
> **状态：** 定稿
