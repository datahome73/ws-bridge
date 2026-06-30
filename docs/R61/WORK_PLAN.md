# R61 工作计划 — F-19/F-20 验证

> **类型：** 纯验证轮次（零代码开发）
> **目标：** 验证 F-19（角色名替代 agent ID）+ F-20（pipeline_start 自动切活跃频道）在真实管线中生效
> **前提：** R60 Gateway 配置已修复，5 bot 全员可达

---

## 一、任务分解

| Step | 角色 | 任务 | 预计工时 |
|:----|:-----|:-----|:--------|
| **A** | PM（小谷） | 编写需求文档 | ✅ 已完成 |
| **B** | PM（小谷） | 编写 WORK_PLAN | ⬅️ 本文件 |
| **2** | Arch（小开） | 技术方案——确认 F-19/F-20 代码完整性 | 15min |
| **3** | Dev（爱泰） | 验证执行——启动测试管线，实操验证 | 20min |
| **4** | Review（小周） | 审查——确认测试结果完整、无遗漏 | 10min ✅ `4004ca7` |
| **5** | QA（泰虾） | 测试报告——输出验收表格 | 10min |
| **6** | PM（小谷） | 合并 + 部署 + 经验固化 | 15min |

**总计：** 约 70min

---

## 二、验证标准

### F-19：角色名显示

| # | 检查项 | 方法 | 预期 |
|:-:|:-------|:----|:-----|
| 1 | 创建工作室成员列表 | 观察 `!pipeline_start` 输出 | 显示 bot 名（小爱、爱泰等）非 agent ID |
| 2 | 系统消息 `_get_agent_display` | 观察 Web 端 studio 消息 | 角色名或 display_name |

### F-20：自动切频道

| # | 检查项 | 方法 | 预期 |
|:-:|:-------|:----|:-----|
| 1 | 成员活跃频道切换 | `!agent_status <id>` 查各成员活跃频道 | 全部 = 新工作室 ID |
| 2 | 点名可达 | 观察点名后 bot 是否 ACK | 全员 ACK |
| 3 | 无人工 `!focus` | 验证全程不用 `!focus` | 自动生效 |

### 全员响应

| # | 检查项 | 预期 |
|:-:|:-------|:-----|
| 1 | 小开（Arch）自动响应点名 | ✅ |
| 2 | 爱泰（Dev）自动响应点名 | ✅ |
| 3 | 小周（Review）自动响应点名 | ✅ |
| 4 | 泰虾（QA）自动响应点名 | ✅ |
| 5 | 小爱（Admin）自动响应点名 | ✅ |

---

## 三、Step 详细说明

### Step B — PM 准备工作

1. 确认 R60-gateway 工作室已关闭
2. 将需求和 WORK_PLAN 推送到远程仓库 dev 分支
3. 确认 main 容器已部署最新代码（含 F-19 + F-20）

### Step 2 — Arch 技术方案

小开需要：
1. 查看 `server/handler.py` 中 `_cmd_pipeline_start()` 第 1327 行确认 `_broadcast_active_channel(ws_id)` 存在
2. 查看 `_get_agent_display()` 第 879 行已实现
3. 确认 `_cmd_create_workspace()` 中的成员列表使用 bot 名而非 agent ID
4. 输出 `docs/R61/R61-tech-plan.md`

### Step 3 — Dev 验证执行

爱泰需要：
1. 在 dev 环境启动 `!pipeline_start R61-test`
2. 检查工作室创建消息中的成员列表格式
3. 执行 `!agent_status` 检查各成员活跃频道
4. 观察点名是否被全员 ACK
5. 无需代码改动
6. 输出 `docs/R61/R61-verification-report.md`

### Step 4 — Review 审查

小周需要：
1. 对照验收标准逐项确认测试结果
2. 输出 `docs/R61/R61-code-review.md`（包含验证结论）

### Step 5 — QA 测试报告

泰虾需要：
1. 按验收标准重新验证关键项
2. 输出 `docs/R61/R61-test-report.md`

### Step 6 — PM 合并部署

小谷需要：
1. 确认所有 Step 输出物完整
2. 将验证报告推送到远程仓库
3. 更新 ws-bridge-dev-tips 技能（Gateway 配置排查经验）
4. 关闭 R61-test 工作室
5. 归档 R61 文档

---

## 四、经验固化方向

| # | 输出物 | 负责人 | 说明 |
|:-:|:-------|:------|:-----|
| 1 | ws-bridge-dev-tips 技能更新 | PM | 补充 Gateway 配置排查 SOP |
| 2 | 角色配置规范 | PM | bot_name 配置原则记录到 memory |
| 3 | 验证流程模板 | PM | 纯验证轮次的工作流模板 |

---

## 五、附录

### 参考文件

- [需求文档](../R61/R61-product-requirements.md)
- [TODO 清单](../../TODO.md) — F-19 ✅、F-20 ✅ 已完成，本次验证
- [handler.py](../../server/handler.py) — F-19: `_get_agent_display()` L879, F-20: `_broadcast_active_channel()` L1327

### 环境信息

| 环境 | WS URL |
|:----|:-------|
| 🧪 dev | `ws-im-dev.datahome73.com:8766/ws` |
| 🏭 main | `wsim.datahome73.cloud:28787/ws` |

### 应急方案

| 异常 | 处理 |
|:----|:-----|
| bot 不响应点名 | 先检查 `!agent_status` 活跃频道，确认 F-20 是否生效 |
| 工作室未自动切换 | 手动执行 `!focus` 恢复 |
| main 版本落后 | 通知小爱部署最新代码后重试 |
