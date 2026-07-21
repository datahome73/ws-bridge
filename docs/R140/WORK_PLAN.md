# WORK_PLAN.md — R140

## 目标

修复管线引擎 3 条核心路径（启动/推进/手动推进）中的关键问题：`##advance` 权限扩展（支持协调者）、跨步推进支持、`_auto_dispatch` 失败通知机制。

---

## Step 分派

| Step | 角色 | 责任人 | 具体工作 |
|:----:|:-----|:-------|:---------|
| **1** | 📋 需求 | 小谷 | 编写 `R140-product-requirements.md` + `WORK_PLAN.md` |
| **2** | 📐 技术方案 | 小开 (arch) | 评估跨步推进方案 + 权限设计 + 失败通知接口 |
| **3** | 💻 编码 | 爱泰 (dev) | ① `##advance` 权限扩展（L4 或配置白名单）<br>② `##advance` 跨步推进逻辑（跳过中间步 + 标记 skipped）<br>③ `_auto_dispatch` 增加 notify_ws/notify_agent_id 参数<br>④ `##start` 反馈消息修正（Step 1→Step 2 + 失败提示）<br>⑤ `_try_advance_pipeline` 派活失败通知 |
| **4** | 👁️ 审查 | 小周 (review) | 审查改动不超过 5 个函数、无回归破坏 |
| **5** | 🧪 QA | 泰虾 (QA) | 功能验收 A-1~A-8 + 回归验收 R1~R4 |
| **6** | 🚢 部署 | 小爱 (ops) | 合 main + 部署 |

> 经理负责管线调度，不含在步骤表中。

---

## 改动预览

| 文件 | 操作 | 行数变化 | 说明 |
|:-----|:------|:--------:|:------|
| `server/ws_server/pipeline_engine.py` | 修改 | +~100 行 | `_handle_hash_advance` 权限+跨步 / `_auto_dispatch` 通知 / `##start` 反馈 / 推进通知 |
| `server/common/config.py` | 可选修改 | +~3 行 | 新增 `PIPELINE_COORDINATOR_AGENT_ID` |

---

## 验收计数

- 功能验收：8 项（A-1~A-8）
- 回归验收：4 项（R1~R4）
- **合计：12 项**
