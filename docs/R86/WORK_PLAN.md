# R86 工作计划 — Agent API Key 注册认证加固 🛡️

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R86/R86-product-requirements.md v1.0
> **日期：** 2026-07-09

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动极小（~50 行），严禁 scope creep**
- 不改入：Web 端、客户端库、Agent Card、任务状态机、管线命令、workspace 逻辑
- 不改出：API Key 轮转/过期机制、多设备登录、角色权限体系

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | architect | developer | — |
| Step 3 | 💻 编码 | developer | architect | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | reviewer | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | reviewer | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | operations | architect | |

---

## 1. 管线总览

### 改动范围

仅 `server/handler.py` + `server/__main__.py` + `server/auth.py`，精确改动点：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A | `handle_register()` 增加 display_name 重复检测：注册前遍历 `_api_keys.json` 查同名 | `handler.py` L229-270 | ~12 行 |
| 2 | A | 新增 `_find_agent_by_name()` 辅助函数 | `handler.py` 模块级 | ~8 行 |
| 3 | B | `handler()` 消息入口：消息发出前检查 key 活性（active/revoked） | `handler.py` L6165 | ~8 行 |
| 4 | B | `ws_handler()` 消息入口：同上检查 | `__main__.py` L104 | ~8 行 |
| 5 | B | `handle_auth()` auth_ok 去 role 字段 | `handler.py` L200-206 | ~2 行 |
| 6 | C | `revoke_api_key()` 调用后触发 `_force_disconnect_revoked_agent()` | `handler.py` 调用处 | ~10 行 |

**总估算：** ~50 行净增，3 文件改动

### 风险等级

| 风险 | 等级 | 说明 |
|:-----|:----:|:------|
| 部署后旧连接被 B1 拦截 | 🟢 低 | B1 只检查 `status=="revoked"` 的 key，正常 active key 不受影响 |
| A1 误判同名 | 🟡 中 | display_name 已 trimmed 空格，全等比较。如有全角/半角问题需手动修正 |
| 部署顺序 | 🟢 低 | 先部署服务端，客户端无感知——旧 key 认证路径不变 |

---

## 2. 管线步骤

### Step 2：技术方案（Arch）

**主角：** architect（小开） | **备用：** developer（爱泰）

**阅读材料：**
- 📄 需求文档：`docs/R86/R86-product-requirements.md`
- 🔗 涉及代码：`server/handler.py` L229-270（handle_register）、L188-214（handle_auth）、L6165（消息入口）、`server/__main__.py` L104（ws_handler）、`server/auth.py` L68-74（is_approved）

**任务：**
1. 确认 `_find_agent_by_name()` 的最佳位置（handler.py 模块级 vs auth.py）
2. 确认 B1 检查在 `handler()` vs `ws_handler()` 的正确插入点
3. 确认 `revoke_api_key()` 后断连的 `_force_disconnect_revoked_agent()` 实现方式
4. 输出技术方案文档 `docs/R86/R86-tech-plan.md`，含每个改动的精确行号 + 代码对比

**完成条件：** 技术方案已推 dev，含所有方向的具体实现路径

---

### Step 3：编码实现（Dev）

**主角：** developer（爱泰） | **备用：** architect（小开）

**阅读材料：**
- 📄 需求：`docs/R86/R86-product-requirements.md`
- 🏗️ 技术方案：`docs/R86/R86-tech-plan.md`
- 🔗 当前代码：`server/handler.py`、`server/__main__.py`、`server/auth.py`

**任务：**
1. **A1** — `handle_register()` 入口加入 display_name 重复检测
2. **B1** — `handler()` + `ws_handler()` 消息入口加 key 活性检查
3. **B2** — `handle_auth()` 检查 auth_ok 无 role 字段
4. **C1** — `revoke_api_key()` 后 `_force_disconnect_revoked_agent()`

**编码约束：**
- 不改动 `_api_keys.json` 数据格式
- 不改动现有 `get_api_keys()/set_api_keys()` 接口
- `_find_agent_by_name` 返回值含 `agent_id` + `record`，供后续扩展
- B1 检查位置在 `msg_type == "message" and agent_id` 的 handler 入口，不在 `handle_broadcast` 内部

**完成条件：** 3 文件改动完毕，git push dev，告知 SHA

---

### Step 4：代码审查（Review）

**主角：** reviewer（小周） | **备用：** qa（泰虾）

**审查重点：**
1. ✅ A1 重复检测是否覆盖所有路径（display_name 为空/空格/已注册/首次注册）
2. ✅ B1 检查是否在 `handler()` 和 `ws_handler()` 都做了
3. ✅ B1 检查后消息处理使用 `continue` 而非 `break`/`return`（保持连接）
4. ✅ B2 auth_ok 是否真的无 role 字段
5. ✅ C1 `_force_disconnect_revoked_agent` 是否在正确的调用时机
6. ✅ 零 scope creep（不引入不在范围的改动）

**完成条件：** 审查报告已推 dev，结论 🟢 通过 / 🟡 条件通过 / 🔴 退回

---

### Step 5：测试验证（QA）

**主角：** qa（泰虾） | **备用：** reviewer（小周）

**验收清单（从需求文档复制）：**

| # | 检查项 | 测试方法 |
|:-:|:-------|:---------|
| ✅-1 | 同名重复注册被拒 | WS 发 2 次 register(同 display_name)，第 2 次返回 auth_error |
| ✅-2 | 首次注册正常 | 新 display_name 正常收到 register_ok |
| ✅-3 | 无重复名持久化 | 读 `_api_keys.json` 验证 |
| ✅-4 | 空格 trimmed 检测 | display_name=" 小开" → 与 "小开" 视为重复 |
| ✅-5 | 有效 key auth 正常 | auth(正确 api_key) → auth_ok |
| ✅-6 | 有效 key 消息正常 | auth → message → 路由正常 |
| ✅-7 | 吊销 key 后消息被拒 | register → revoke → message → error（连接不断） |
| ✅-8 | 吊销后重 auth 恢复 | revoke → auth(new_key) → message → 正常 |
| ✅-9 | auth_ok 无 role 字段 | 检查 auth_ok payload |
| ✅-10 | revoke 后连接关闭 | revoke → 观察连接状态 |
| ✅-11 | 吊销后可重新 register | revoke → register(同名) → register_ok |
| ✅-12 | 旧 key 不可用 | revoke → auth(旧 key) → auth_error |

**完成条件：** 测试报告已推 dev，12/12 验收通过 ✅

---

### Step 6：合并部署归档（Operations）

**主角：** operations（小爱） | **备用：** architect（小开）

**任务：**
1. `git checkout main && git merge dev && git push origin main`
2. `docker build -t ws-bridge:r86 .`
3. `docker stop ws-bridge-prod && docker rm ws-bridge-prod`
4. `docker run -d --name ws-bridge-prod ... ws-bridge:r86`
5. `!pipeline_status R86` 确认容器健康
6. `!close_workspace ws:xxx` 关闭工作室
7. `docs/TODO.md` 更新版本号

**⚠️ 注意：** git push ≠ 已部署。必须重建镜像再 run 新容器，光 restart 不行。

---

## 3. 验收清单（从需求文档复制）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 同名重复注册被拒 | bot 发 `register{display_name="小开"}` 第二次时返回 auth_error | WS 发 2 次 register |
| ✅-2 | 首次注册正常 | 新 display_name 正常注册，返回 agent_id + api_key | WS 发 register |
| ✅-3 | _api_keys.json 无重复名 | 同名注册失败后文件中该 display_name 只有一条记录 | 读 JSON 文件 |
| ✅-4 | 空格 trimmed 后仍检测同名 | display_name=" 小开" 和 "小开" 视为重复 | 带空格测试 |
| ✅-5 | 已有 key 的 bot 可正常 auth | 正确 api_key auth 正常通过 | WS 发 auth |
| ✅-6 | 有效 key 消息正常发送 | 正常 auth 后消息正常路由 | 发 message |
| ✅-7 | 吊销 key 后消息被拒 | B1 拦截返回 error，连接不断 | revoke → message |
| ✅-8 | 吊销后重 auth 恢复 | 新 auth 后消息正常 | revoke → auth → message |
| ✅-9 | auth_ok 无 role 字段 | auth_ok 不包含 "role" | 检查 payload |
| ✅-10 | revoke_api_key 后连接断开 | agent 连接被关闭 | revoke 后观察 |
| ✅-11 | 吊销后可重新 register | old revoke → register(同名) → register_ok | 全流程 |
| ✅-12 | 旧 key 不可用 | revoke → auth(旧 key) → auth_error | 旧 key auth |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-09 | 初稿 — R86 Agent API Key 认证加固 |
