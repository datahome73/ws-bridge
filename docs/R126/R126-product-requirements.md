# R126 产品需求文档（Product Requirements）

> **起草人：** 📋 PM（小谷）
> **状态：** 📝 草稿
> **版本：** v1.0

---

## 1. 背景与目标

当前 ws-bridge 管线已实现全自动流转（R88 AutoRouter + R124 驳回回退/归档），但 bot 间交接仍依赖**纯自然语言消息**，缺乏标准化工件格式，导致以下痛点：

| # | 问题 | 场景 | 影响 |
|:-:|:-----|:------|:------|
| P1 | 🎯 **需求理解偏差** | PM 派活→bot 接活，自然语言描述→产出偏离预期 | 驳回循环，每轮浪费 30min+ |
| P2 | 📋 **产出上下文丢失** | Step N 的产出格式不统一，后续步骤无法自动解析 | 人工复制粘贴，易遗漏 |
| P3 | 🔄 **交接信息衰减** | Step 3→Step 4，产出要人工摘要才能传给下一步 | 信息损耗，审查不充分 |
| P4 | 📊 **可追溯性差** | 管线归档后，各步骤产出散落在聊天消息中 | 无法结构化查询 |
| P5 | ❌ **驳回无结构化依据** | Review/QA 驳回时附纯文字原因 | dev 无法精确定位缺陷 |
| P6 | 🔁 **重做无上下文** | dev 修复后再次提交，不记得上次驳回的具体点 | 重复返工 |
| P7 | 🧪 **验收标准模糊** | 各 Step 验收标准在需求文档中，bot 不直接可见 | 产出偏离预期 |

R126 定位为 **Phase 2 核心基础设施补齐轮**——引入 **结构化 Task Card** 作为 bot 间交接的标准化工件载体，消除自然语言歧义，为 Phase 3（Coder Agent）铺垫管线级数据通道。

### 1.1 R126 目标

| 维度 | 当前 | 目标（R126） |
|:-----|:-----|:-------------|
| 消息格式 | 纯自然语言，无标准 schema | 每步派活携带 Task Card（JSON code block），产出也填回 Card |
| 上下文传递 | 人工摘要 + 复制粘贴 | Task Card 自动积累前序 artifacts |
| 驳回效率 | 驳回后重新自然语言沟通 | Review/QA 可在 Card 上标注具体缺陷项 |
| 归档查询 | 归档后只能翻聊天记录 | 归档含结构化 Task Card，可程序化查询 |

---

## 2. Task Card 定义

### 2.1 Task Card Schema

**派活侧卡片（派活时生成，随消息发送）：**

```json
{
  "tc_version": "1.0",
  "round": "R126",
  "step": 3,
  "role": "dev",
  "title": "编码实现结构化 Task Card",
  "requirements_url": "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R126/R126-product-requirements.md",
  "inputs": [
    { "name": "技术方案", "type": "doc_url", "value": "https://...", "from_step": 2 }
  ],
  "acceptance_criteria": [
    { "id": "AC-1", "desc": "Task Card Schema 文档定稿", "status": "pending" },
    { "id": "AC-2", "desc": "派活时 Card 随消息发送", "status": "pending" }
  ],
  "outputs": [],
  "reject_items": [],
  "references": [
    "docs/R126/R126-product-requirements.md"
  ],
  "meta": {
    "assigned_agent": "爱泰",
    "dispatched_at": null,
    "dispatched_by": "小谷",
    "started_at": null,
    "completed_at": null
  }
}
```

**回复侧产出卡片（bot 完成时填充）：**

```json
{
  "tc_version": "1.0",
  "round": "R126",
  "step": 3,
  "outputs": [
    { "name": "实现 Commit", "type": "commit_sha", "value": "abc1234" },
    { "name": "产出文档", "type": "doc_url", "value": "https://..." },
    { "name": "核心文件", "type": "string[]", "value": ["server/pipeline_context.py", "server/auto_router.py"] }
  ],
  "acceptance_criteria": [
    { "id": "AC-1", "desc": "Task Card Schema 文档定稿", "status": "done" },
    { "id": "AC-2", "desc": "派活时 Card 随消息发送", "status": "done" }
  ],
  "reject_items": [],
  "result_summary": "实现了 Task Card 的 schema 定义和派活集成",
  "result_url": "https://github.com/datahome73/ws-bridge/commit/abc1234",
  "meta": {
    "assigned_agent": "爱泰",
    "started_at": 1784300000.0,
    "completed_at": 1784303600.0
  }
}
```

### 2.2 核心字段说明

| 字段 | 类型 | 出现位置 | 必填 | 说明 |
|:-----|:------|:-------:|:----:|:------|
| `tc_version` | string | 两者 | ✅ | Schema 版本（当前 "1.0"） |
| `round` | string | 两者 | ✅ | 轮次号 |
| `step` | int | 两者 | ✅ | 步骤号 |
| `role` | string | 派活侧 | ✅ | 当前角色 |
| `title` | string | 派活侧 | ✅ | 本步骤任务标题 |
| `requirements_url` | string | 派活侧 | ✅ | 本轮需求文档 |
| `inputs` | object[] | 派活侧 | ✅ | 前序步骤产出物，每项含 name/type/value/from_step |
| `acceptance_criteria` | object[] | 两者 | ✅ | 验收标准清单含 id/desc/status |
| `outputs` | object[] | 回复侧 | ✅ | 本步骤产出物（bot 填充），每项仅允许 `string`/`string[]`/`number`/`commit_sha`/`doc_url` 五类 type |
| `reject_items` | object[] | 回复侧 | ✅ | 驳回缺陷项列表（review/qa 填充） |
| `references` | string[] | 派活侧 | ✅ | 参考文件路径 |
| `result_summary` | string | 回复侧 | | 完成结果摘要 |
| `result_url` | string | 回复侧 | | 产出链接 |
| `meta` | object | 两者 | ✅ | 元信息（assigned_agent/dispatched_at/started_at/completed_at） |

### 2.3 字段 type 枚举约束

`inputs[].type` 和 `outputs[].type` 字段仅允许以下枚举值：

| type 值 | 说明 | 示例 |
|:--------|:-----|:------|
| `doc_url` | 文档 URL | `https://raw.githubusercontent.com/...` |
| `commit_sha` | Git commit SHA | `abc1234` |
| `string` | 单行文本 | `"审核通过"` |
| `string[]` | 字符串数组 | `["file1.py", "file2.py"]` |
| `number` | 数字 | `42` |
| `test_result` | 测试结果摘要 | `"38/41 🟢 通过"` |

---

## 3. 集成方案

### 3.1 PipelineContext 扩展

**文件：** `server/pipeline_context.py` +~55 行

在 `PipelineContext` 中新增：
- `task_cards: dict[int, dict]` — key 为 step 号，value 为 Task Card
- `_build_task_card(step_num) -> dict` — 自动从 context 生成派活侧卡片
- `_fill_output_card(step_num, kv: dict) -> None` — 从完成消息的 kv 回填产出
- `_add_reject_items(step_num, items: list) -> None` — 将驳回缺陷写入卡片

### 3.2 派活时附加 Task Card

**文件：** `server/auto_router.py` (或 `_auto_dispatch`) +~15 行

`_auto_dispatch()` 在构建派活 payload 时，调用 `_build_task_card(step_num)` 生成 JSON，然后：

```
##task_card=<base64(json)>
```

格式说明：
- `##task_card` 为新增 artifact key
- 值为 `base64.urlsafe_b64encode(json.dumps(card).encode()).decode()`
- 兼容性：旧 bot 忽略未知 `##key=value`，不会报错
- 派活消息内容保持不变，Task Card 仅是附加数据

### 3.3 完成时回填产出

**文件：** `server/ws_server/main.py` +~35 行

bot 完成消息格式：

```
已完成 ✅ R126 Step 3##commit=abc1234##output_url=https://...##output_summary=实现了Task Card
```

`_try_advance_pipeline()` 在解析完成消息时：
1. 提取 `##commit` / `##output_url` / `##output_summary` 等 kv
2. 调用 `_fill_output_card(step_num, kv)` 将产出写入当前 step 的 Task Card
3. `inputs` 自动继承：Step N 的 `outputs` 自动成为 Step N+1 的 `inputs`
4. `acceptance_criteria` 状态继承：若前序步骤全部 AC 标记 done，则当前步骤的 inputs 含此信息

### 3.4 驳回缺陷标注

**文件：** `server/ws_server/main.py` +~15 行

Review/QA bot 驳回时可附加结构化缺陷信息：

```
退回 🔄 R126 Step 3 — 编码实现不符合预期##reject_items=<base64([{"ac_id":"AC-2","severity":"critical","desc":"派活时未附带Card"}])>
```

Server 处理：
1. 解析 `##reject_items` 参数为 JSON 数组
2. 写入对应 step 的 Task Card 的 `reject_items` 字段
3. 解析失败时：仅 log warning，不阻断退回流程

### 3.4.1 驳回二次流转

驳回→修复→归档的全周期行为规则：

| 阶段 | 行为 |
|:-----|:------|
| ① 初始派活 | Server 生成 Task Card（`reject_items: []`，AC 全部 `pending`） |
| ② 首次完成 | bot 填回 Output Card，`acceptance_criteria` 标记通过/失败 |
| ③ 驳回 | review/qa 填入 `reject_items`，AC 状态恢复 `pending`（涉及项重置） |
| ④ 重做 | dev 清除 `reject_items`（旧值归档到历史快照），修复后重新填充 outputs |
| ⑤ 再次完成 | 新 outputs 覆盖旧 outputs，但旧 outputs 在归档中作为 `outputs_history` 保留 |
| ⑥ 最终归档 | 完整快照含 `reject_items_history` 和 `outputs_history`，供事后追溯 |

> 关键设计：**reject_items 重做清除，历史快照保留**。确保重做 bot 不受旧数据干扰，同时归档可追溯完整生命周期。

### 3.5 ##status 展示 Task Card 摘要

**文件：** `server/ws_server/main.py` +~15 行

`##status##R{N}` 对已完成步骤显示：

```
📊 R126 管线状态

Step 3 (dev) ✅ 已完成
  📎 产出: abc1234 (commit) — 实现了Task Card
  ✅ AC-1 通过 | ✅ AC-2 通过

Step 4 (review) 🔄 进行中...
```

---

## 4. 改动范围估算

| 文件 | 改动 | 估算 |
|:-----|:------|:-----|
| `docs/R126/task-card-schema.md` | **新增** - Schema 定义文档 + 完整示例 | ~80 行 |
| `server/pipeline_context.py` | 新增 `task_cards` 字段 + `_build_task_card()`/`_fill_output_card()`/`_add_reject_items()` | +~55 行 |
| `server/auto_router.py` | `_auto_dispatch()` 派活时附加 `##task_card=<b64>` | +~15 行 |
| `server/ws_server/main.py` | `_try_advance_pipeline()` 解析 `##output_xxx` 回填；`_handle_reject()` 解析 `##reject_items`；`_handle_hash_status()` 展示卡片摘要 | +~55 行 |
| `docs/inbox-message-protocol.md` | 补充 Task Card / output / reject kv 说明；版本号 v3.1→v3.2 | ~10 行 |
| `docs/TODO.md` | 版本号 v2.73→v2.74 + R126 闭环记录 | ~5 行 |

**合计：** 1 新增 + 5 修改文件，**净增 ~+110–140 行**

---

## 5. 验收标准

### TC — Task Card Schema（§2）

| # | 验收项 | 优先级 |
|:-:|:-------|:------:|
| TC-1 | Task Card Schema 文档定稿于 `docs/R126/task-card-schema.md` | 🟢 P0 |
| TC-2 | tc_version 标记为 "1.0" | 🔵 P2 |
| TC-3 | 派活侧卡片字段完整（title/requirements_url/inputs/acceptance_criteria/meta） | 🟢 P0 |
| TC-4 | 回复侧卡片字段完整（outputs/acceptance_criteria/reject_items/result_summary/meta） | 🟢 P0 |
| TC-5 | 文档含 1 个完整示例（从派活到归档全过程） | 🟡 P1 |
| TC-6 | `outputs[].type` 仅允许 `string`/`string[]`/`number`/`commit_sha`/`doc_url` 五类枚举值 | 🟡 P1 |

### OC — 产出回填（§3.2–3.3）

| # | 验收项 | 优先级 |
|:-:|:-------|:------:|
| OC-1 | `_auto_dispatch()` 派活时包含 `##task_card=<b64>` | 🟢 P0 |
| OC-2 | 完成消息中 `##commit/output_url/output_summary` 回填到 Task Card outputs | 🟢 P0 |
| OC-3 | Step N 的 outputs 自动成为 Step N+1 的 inputs（输入输出契约） | 🟢 P0 |
| OC-4 | 旧 bot 不加 `##output_xxx` 不影响已有流程（向后兼容） | 🟢 P0 |

### RJ — 驳回标注（§3.4）

| # | 验收项 | 优先级 |
|:-:|:-------|:------:|
| RJ-1 | 退回消息支持 `##reject_items=<b64_json>` 参数 | 🟡 P1 |
| RJ-2 | reject_items 解析失败时仅 log warning，不阻断退回 | 🟡 P1 |

### CT — 上下文传递（§3.3 + §3.5）

| # | 验收项 | 优先级 |
|:-:|:-------|:------:|
| CT-1 | `##status##R{N}` 对已完成步骤显示产出摘要 | 🟡 P1 |
| CT-2 | 未完成步骤的 Task Card 不展示产出 | 🔵 P2 |
| CT-3 | 无 Task Card 的旧管线执行 `##status` 不报错 | 🟢 P0 |

### RV — 归档与兼容（§3.4.1）

| # | 验收项 | 优先级 |
|:-:|:-------|:------:|
| RV-1 | 归档时 steps 中包含 Task Card 完整快照 | 🟡 P1 |
| RV-2 | reject_items 重做清除，旧数据在 `reject_items_history` 归档 | 🟡 P1 |
| RV-3 | 旧管线 pipeline_archive.json 加载不报错（无 task_card 字段） | 🟢 P0 |

---

## 6. 不做事项（明确排除）

| 排除项 | 理由 |
|:-------|:------|
| ❌ **bot 端 Task Card 解析器实现** | 属于各 bot 适配层，非 server 端范围；R126 仅定义 schema 和 server 端派活/收集机制 |
| ❌ **Phase 3 Coder Agent 集成** | Task Card 为 Coder Agent 铺垫基础，但 Coder Agent 本身非本次范围 |
| ❌ **Web UI Task Card 可视化** | 纯前端工作，排后续轮次 |
| ❌ **Task Card 版本兼容升级（v2 schema）** | 首次落地，v1.0 已够用 |
| ❌ **全量历史管线 Task Card 回溯** | 旧管线无 Task Card 数据，不做追溯 |
| ❌ **多 bot 并行派活** | Task Card Schema 天然支持并行（各 bot 各自填充 outputs），但 R126 仅串行管线场景，并行排后续轮次 |
| ❌ **自动 AC 引擎** | 不自动判断验收标准是否满足，仅做结构化记录 |

---

## 7. 验收检查表

| # | 验收项 | 类型 | 优先级 |
|:-:|:------|:----:|:-----:|
| TC-1 | Task Card Schema 文档定稿 | 规范 | 🔴 P0 |
| TC-2 | tc_version v1.0 | 规范 | 🔵 P2 |
| TC-3 | 派活侧卡片字段完整 | 规范 | 🟢 P0 |
| TC-4 | 回复侧卡片字段完整 | 规范 | 🟢 P0 |
| TC-5 | 文档含完整示例 | 规范 | 🟡 P1 |
| TC-6 | `outputs[].type` 枚举约束 | 规范 | 🟡 P1 |
| OC-1 | 派活时附加 `##task_card` | 代码 | 🟢 P0 |
| OC-2 | `##output_xxx` 回填 outputs | 代码 | 🟢 P0 |
| OC-3 | Step N outputs → Step N+1 inputs | 代码 | 🟢 P0 |
| OC-4 | 旧 bot 不加 kv 不影响 | 回归 | 🟢 P0 |
| RJ-1 | 退回消息支持 `##reject_items` | 代码 | 🟡 P1 |
| RJ-2 | reject_items 解析容错 | 代码 | 🟡 P1 |
| CT-1 | `##status` 展示产出摘要 | 代码 | 🟡 P1 |
| CT-2 | 未完成步骤不展示产出 | 代码 | 🔵 P2 |
| CT-3 | 旧管线不报错 | 回归 | 🟢 P0 |
| RV-1 | 归档含 Task Card 快照 | 代码 | 🟡 P1 |
| RV-2 | reject_items 重做清除 / 历史归档 | 代码 | 🟡 P1 |
| RV-3 | 旧 archive.json 不报错 | 回归 | 🟢 P0 |

---

## 8. 向后兼容性说明

| 场景 | 旧行为 | R126 后行为 | 兼容性 |
|:-----|:-------|:-----------|:------:|
| 旧 bot 不加 `##output_xxx` | 正常完成 | 正常完成，outputs 为空 | ✅ |
| 旧 bot 忽略 `##task_card` | — | `##task_card` 作为未知 kv 被忽略 | ✅ |
| 旧管线已归档 | 正常查询 | 正常查询，steps 中无 task_card | ✅ |
| `##status` 无 task_card 管线 | 正常显示 | 正常显示，不展示卡片摘要 | ✅ |

---

> **审核记录：**
> - v1.0 提交审核：✅ PM 审核通过
> - §2.3 补充 type 枚举约束 — 审阅建议 #3
> - §3.4.1 补充驳回二次流转规则 — 审阅建议 #1
> - §6 排除清单补充「多 bot 并行派活」— 审阅建议 #2
> - 项目负责人审核意见：待定
