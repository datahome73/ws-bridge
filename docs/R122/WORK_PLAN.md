# R122 开发计划

> **仓库：** `datahome73/ws-bridge`（ws-bridge 服务端）
> **状态：** ✅ 项目负责人审核通过

---

## 角色分工

| 角色 | 成员 | 职责 |
|:----:|:----:|:-----|
| 📋 PM | 小谷 | 任务编排 + 部署 + 归档 |
| 📐 Arch | 小开 | 技术方案设计 |
| 💻 Dev | 爱泰 | 编码实现 |
| 👁 Review | 小周 | 代码审查 |
| 🧪 QA | 泰虾 | Dev 测试 + 上线验证 |
| 🚢 Ops | 小爱 | 合并部署 + 生产上线 |

---

## 各 Step 任务详情

### Step 2 — 技术方案（小开）

**任务：**
评估 R122 超时告警功能的技术方案，产出 `docs/R122/R122-tech-plan.md`。

需要回答以下问题：
1. **配置方式：** 超时分钟数和扫描间隔如何定义？建议走 env vars 还是直接在 config.py 里写默认值？
2. **时间戳记录位置：** `_auto_dispatch()` 派活成功后，在哪行代码、在什么字段上记录 `dispatched_at`？
3. **扫描逻辑：** 后台协程每多久 tick？扫描哪些管线（running only）？检查哪些字段？
4. **告警频率：** 如何保证每 step 只发一次告警给 PM？
5. **告警目标：** 发给谁？走什么 channel？
6. **持久化：** `timeout_alerted` 是否要持久化到 JSON？防止重启后重复告警。
7. **边界情况：**
   - 配置 `PIPELINE_TIMEOUT_ALERT_MINUTES=0` 时的行为
   - 同时多个管线超时
   - 容器重启后已有 `in_progress` 状态但无 `dispatched_at` 的旧 step
8. **改动范围确认：** 涉及文件是否仅 `server/common/config.py` 和 `server/ws_server/main.py`？

**产出格式：** 按 `docs/templates/R-tech-plan.md` 模板编写。

---

### Step 3 — 编码（爱泰）

**任务：**
按小开的技术方案实现管线超时告警功能。

**变更文件：**

| 文件 | 改动说明 |
|:-----|:---------|
| `server/common/config.py` | 新增 `PIPELINE_TIMEOUT_ALERT_MINUTES`（默认30）和扫描间隔配置 |
| `server/ws_server/main.py` | `_auto_dispatch()` 成功派活时记录 `dispatched_at` + `timeout_alerted`；新增后台扫描协程；启动时接线 |

**实现要点：**
- `config.py` 新增配置通过 env var `R122_TIMEOUT_ALERT_MINUTES` 覆盖（默认30分钟）
- `config.py` 新增 `R122_TIMEOUT_SCAN_INTERVAL`（默认300秒=5分钟）
- `_auto_dispatch()` 成功派活后：`step_info["dispatched_at"] = time.time()` + `step_info["timeout_alerted"] = False`
- 新增 `_ensure_timeout_scanner()` / `_start_pipeline_timeout_scan_loop()` / `_pipeline_timeout_scan()`
- 扫描逻辑：仅检查 `status=RUNNING` 的管线，遍历 steps 找 `status=in_progress` 且 `dispatched_at` 超过阈值且 `timeout_alerted=False` 的 step
- 告警发给 `config.PIPELINE_PM_AGENT_ID`（小谷），走 `_send_to_agent`
- 告警后设置 `timeout_alerted=True` 并持久化
- 启动位置：`on_message` 入口处与 `_ensure_git_scan()` 并列

**交付要求：**
- 提交格式：`feat(R122): Step 3 — 管线超时告警（30分钟静默后通知PM）`
- 推 `dev` 分支
- 含单元测试（如需）

---

### Step 4 — 代码审查（小周）

**任务：**
审查爱泰对 `config.py` 和 `main.py` 的变更。

**审查要点：**
1. 配置默认值是否合理（30分钟/5分钟扫描）
2. 扫描协程是否 blocking 主事件循环
3. `timeout_alerted` 持久化逻辑是否正确
4. 并发安全：多个管线同时超时是否有锁竞争
5. 边界处理：配置关闭、旧 step 无 `dispatched_at`、告警发送失败

**产出格式：** `docs/R122/R122-code-review.md`

---
### Step 5 — Dev 部署（小爱）

- 构建 `ws-bridge:r122-dev` 镜像
- 部署到 dev 测试环境容器（ws-bridge-dev）
- 健康检查通过（WSS 8765 + Web UI 8766 均可访问）
- 确认启动日志出现 `[R122] 管线超时扫描已启动`

### Step 6 — Dev 测试（泰虾）

产出：`docs/R122/R122-test-report.md`

在 dev 测试环境容器上验证超时告警功能。

**验证项：**

| # | 验证项 | 预期 |
|:-:|:-------|:-----|
| ① | 启动后日志出现 `[R122] 管线超时扫描已启动` | 扫描协程正常启动 |
| ② | 派活一个 step 后，`dispatched_at` 写入 step 字典 | JSON 持久化中有该字段 |
| ③ | step 快速完成（不超时）→ 无告警 | 扫描不误报 |
| ④ | 模拟超时（将阈值临时改为 1 分钟）→ PM 收到告警 | 告警内容含轮次和 step 号 |
| ⑤ | 同一 step 只告警一次（再次扫描不重复发） | PM 只收到一条 |
| ⑥ | `PIPELINE_TIMEOUT_ALERT_MINUTES=0` 启动 | 日志显示已禁用，扫描不运行 |
| ⑦ | 无 running 管线时扫描不报错 | 正常跳过 |

**产出格式：** 按 `docs/templates/R-test-report.md` 模板编写。

### Step 7 — 上线验证（泰虾 + 小爱）

产出：`docs/R122/R122-release-verification.md`

- 创建 `##start##R122V2` 管线，在测试环境跑一次全流程
- 确认超时告警在生产环境正常工作
- 确认容器重启后 `timeout_alerted` 状态不丢失
- ✅ 通过 → Step 8 / ❌ 退回对应环节

### Step 8 — 合并 main + 生产部署（小爱）

- 合并 `dev` → `main`
- 构建 `ws-bridge:r122` 镜像
- 更新生产环境容器
- 确认生产环境启动日志正常

### Step 9 — 归档

- 全员 ACK
- 归档轮次文档

---

## 验收检查表

| # | 验收项 | 优先级 |
|:-:|:------|:-----:|
| A-1 | `in_progress` 的 step 写入 `dispatched_at` 时间戳 | P0 🟢 |
| A-2 | 超时扫描协程每 5 分钟正常运行，不阻塞主循环 | P0 🟢 |
| A-3 | step 正常完成时不触发告警 | P0 🟢 |
| A-4 | step 超时 30 分钟后 PM 收到告警 | P0 🟢 |
| A-5 | 同一 step 不再重复告警 | P0 🟢 |
| A-6 | 无超时的管线扫描不产生副作用 | P1 🟡 |
|| v1.1 | 2026-07-16 | 🏁 归档 — Step 5 测试 ALL GREEN 🟢, Step 6 合并部署 main `6b012a2`, ws-bridge:r122
