# R71 工作计划 — Web 端诊断 + 顺手修复 🎯

> **仓库：** `datahome73/ws-bridge`（ws-bridge 服务端）
> **状态：** ✅ 已审核（项目负责人审核通过）
> **日期：** 2026-07-05
> **基线 commit：** `b3ed0cd`（R70 3 个 Bug Fix 合并部署完成）
> **基于需求文档：** `docs/R71/R71-product-requirements.md` v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动极小，严禁 scope creep**
- 不改入：角色映射系统 / 自动化测试框架 / 新虾注册 / Android 封装
- 不改出：不引入新 Web 功能、不新开 Tab、不重构前端
- 诊断阶段 **零代码改动**，修复阶段 ≤30 行
- 超出 scope 的改动，审查者直接打回

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | 架构师 | 开发工程师 | — |
| Step 3 | 💻 🅰️ F-9 诊断执行 | 开发工程师 | 架构师 | 零代码，仅诊断 |
| Step 4 | 🔍 审查 | 审查工程师 | 测试工程师 | 审查诊断结果 + 修复方案 |
| Step 5 | 🦐 测试 + 🅱️ 修复 + 🅲 治理 | 测试工程师 | 架构师 | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署归档 | 项目管理 | 架构师 | — |

---

## 1. 管线总览

### 本轮核心

| 阶段 | 内容 | 角色 | 产出 |
|:-----|:------|:-----|:------|
| 🅰️ **诊断** | F-9 Web 端 Tab 空白根因定位（浏览器 DevTools + 进程 + 日志 + Token 四步法） | 开发工程师 | 诊断报告 |
| 🅱️ **修复** | 根据诊断结论：顺手修（≤30 行）或记录方案留下一轮 | 开发工程师 | 修复 commit |
| 🅲 **治理** | TODO v2.36→v2.37 + D-3 脱敏 | 项目管理 | TODO.md + 脱敏 commit |

### 改动范围

仅 `server/web_viewer.py` / `server/templates.py`（可能修改），精确改动点取决于诊断结果：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | 🅱️ 修复 | 视诊断结果定 | `web_viewer.py` / `templates.py` | 0~30 行 |
| 2 | 🅲 治理 | README.md 脱敏 | `docs/README.md` | ~5 行 |
| 3 | 🅲 治理 | TODO.md 版本更新 | `docs/TODO.md` | ~5 行 |

**总估算：** 代码 ≤30 行 + 文档 ≤10 行

---

## 2. 管线步骤（6 步全角色）

### ✅ 需求审核（已完成）

- 项目负责人审核通过 R71 产品需求文档 v1.0  ✅
- commit: `80daa37`

---

### Step 1 — 创建工作室 + WORK_PLAN 定稿 🦸 项目管理

- 创建 R71 开发工作室，邀请 6 位角色成员
- WORK_PLAN 审核确认 → 启动管线
- `!pipeline_status` 验证成员列表完整

---

### Step 2 — 技术方案 🏗️ 架构师

**产出：** `docs/R71/R71-f9-diagnosis-scope.md`

架构师编写 R71 诊断范围文档，明确：

| 章节 | 内容 |
|:-----|:------|
| F-9 根因假设树 | 从需求文档 §1.2 的 7 条假设展开→设计排查优先级 |
| 诊断流程 | 进程检查→DevTools 6 项→日志→Token 的完整操作指南 |
| 顺手修复条件门 | 引用需求文档 §2 的 3 条条件 |
| 修复 3 类预案 | 针对假设①~⑦ 各给出修复代码示例 |
| 降级方案 | 无法访问浏览器时改为 curl + 日志间接推断 |

**参考文档：**
- `server/web_viewer.py`（Web API 路由 + log 回放逻辑）
- `server/templates.py`（前端 JS + CSS + HTML，Tab 架构）
- `docs/R71/R71-product-requirements.md` §6 诊断决策树

**交付条件：** 文档提交 git push dev → `!step_complete step2 --output <sha> --summary "诊断范围确认,7条假设树+"`

---

### Step 3 — 🅰️ F-9 诊断执行 💻 开发工程师

**产出：** `docs/R71/R71-f9-diagnosis.md`

开发工程师按以下流程执行诊断：

#### 3.1 进程与端口检查

```bash
# 目标机器
docker exec ws-bridge-prod ps aux | grep -iE 'python|aiohttp'
ss -tlnp | grep -E '8080|3000|80|443'
curl -s http://localhost:<port>/health
```

记录：进程存活？端口监听？health 返回 `ok`？

#### 3.2 浏览器 DevTools 6 项检查

| 步骤 | 端点 | 观察点 | 预期 |
|:----:|:-----|:-------|:-----|
| ① | Console | 有 JS 报错？ | 无 |
| ② | `/api/channels` | 返回含 lobby 的频道列表 | 200 OK |
| ③ | `/api/chat?channel=lobby` | 返回消息数组 | 200 + `messages: [...]` |
| ④ | `/ws/chat` | WebSocket 握手状态 | 101 Switching Protocols |
| ⑤ | `/api/agents/status` | Agent 在线列表 | 200 + `agents: {...}` |
| ⑥ | Tab 切换 | Tab2(活跃)/Tab4(管理)是否正常 | 可切换 |

#### 3.3 日志检查

```bash
docker logs ws-bridge-prod --tail 100 | grep -iE 'error|traceback'
ls -la <DATA_DIR>/chat_logs/
tail -5 <DATA_DIR>/chat_logs/chat_<today>_lobby.log
```

#### 3.4 Token/Session 检查

```python
sessions = persistence.get_web_sessions()
print(f"Sessions: {len(sessions)}")
```

#### 3.5 诊断结论

产出明确结论：

> **根因：** [一句话精确说明]
> **分类：** 配置/部署/代码
> **修复预估：** 顺手（≤30 行）/ 排期 / 架构
> **修复方案：** [代码示例或配置命令]

**此 Step 的验证价值：**
- ✅ Agent card：开发工程师在线、被正确指派
- ✅ 收件箱通道：收到架构师的诊断范围文档
- ✅ `!step_complete --summary "诊断完成,根因:XXX" --artifact-url <诊断报告URL>`

---

### Step 4 — 诊断报告审查 + 修复方案审核 🔍 审查工程师

**产出：** `docs/R71/R71-code-review.md`

审查内容：

| 审查项 | 说明 |
|:-------|:------|
| 诊断报告的完整性 | 6 项检查是否全部执行？结论是否闭环？ |
| 根因结论的可靠性 | 现象→排查→根因的逻辑链是否完整 |
| 修复方案是否符合 scope | ≤30 行、不改入不纳范围项 |
| 顺手修复条件门检查 | 3 条条件是否全部满足？ |

**审查结论输出：**
- 🟢 通过（诊断可靠 + 修复方案合规）→ 推进 Step 5
- 🟡 条件通过（诊断可靠但修复方案需调整）→ 调整后推进
- 🔴 退回（诊断不完整/根因未确定）→ 退回 Step 3 补查

**此 Step 的验证价值：**
- ✅ Agent card：审查工程师在线
- ✅ 收件箱通道：收到开发工程师的诊断报告
- ✅ `!step_complete --summary "审查通过" --artifact-url <审查报告URL>`

---

### Step 5 — 🅱️ 修复 + 🦐 回归测试 + 🅲 治理 🦐 测试工程师

**产出：**
- 修复 commit（如果诊断结论是顺手修）
- `docs/TODO.md` v2.37
- `docs/R71/R71-closure-summary.md`

#### 5.1 🅱️ 修复执行（条件门通过时）

如果诊断结论满足顺手修复条件（配置/部署/≤30 行代码 + 不影响管线）：

```bash
# 修复 → git commit → git push dev
git add server/web_viewer.py  # 或 templates.py 等
git commit -m "fix(R71): F-9 根因修复 — [简述]"
git push origin dev
```

#### 5.2 🦐 回归验证

| # | 验证项 | 预期结果 | 方法 |
|:-:|:-------|:---------|:-----|
| ✅-8 | 修复后 Web 端可见最新消息 | Tab 面板显示实时消息流 | 浏览器打开 URL |
| ✅-9 | 各 Tab 可切换 | Tab1(大厅)/Tab2(活跃)/Tab4(管理)正常 | 点击切换 |
| ✅-10 | WebSocket 实时推送 | 发一条消息 → 浏览器即时出现 | 发消息 → 观察 Web 端 |

#### 5.3 🅲 治理

| 操作 | 说明 |
|:-----|:------|
| TODO.md v2.36 → **v2.37** | 版本号更新 |
| R70 完成记录 | 移入「已完成事项」 |
| F-22 标记 ✅ | `!step_complete` 变量作用域 bug 已修复 |
| F-9 状态更新 | 根据诊断结果更新为 ✅或🔄 |
| D-3 脱敏 | `docs/README.md` 内部角色名替换为通用名 |

**此 Step 的验证价值：**
- ✅ 收件箱通道：收到审查工程师报告
- ✅ `!step_complete --summary "修复完成+回归通过" --artifact-url <治理URL>`

---

### Step 6 — 合并部署归档 🦸 项目管理

| 操作 | 说明 |
|:-----|:------|
| 合并 dev → main | 合并修复 commit + 诊断文档 + 治理 commit |
| TODO.md 定稿 | v2.37 最终确认 |
| R71 轮次总结 | 诊断结论 + 修复结论 + 下轮建议 |
| `!workspace_reset` | 关闭工作室 → 各成员切回大厅待命 |

**R70 教训：** git push 后必须 rebuild 镜像（`docker build -t ws-bridge:r72 .`），仅 restart 容器不生效。

---

## 3. 产出物清单

| 文件 | 说明 | 产出 Step |
|:-----|:------|:---------:|
| `docs/R71/R71-product-requirements.md` | 产品需求文档 ✅ 已审核 | 🅰️ |
| `docs/R71/WORK_PLAN.md` | **本文件** — 工作计划 | Step 1 🦸 |
| `docs/R71/R71-f9-diagnosis-scope.md` | 诊断范围与假设树 | Step 2 🏗️ |
| `docs/R71/R71-f9-diagnosis.md` | F-9 根因诊断报告 | Step 3 💻 |
| `docs/R71/R71-code-review.md` | 审查报告 | Step 4 🔍 |
| `server/web_viewer.py` 或 `server/templates.py` | 🅱️ 修复 commit（视结果定） | Step 5 🦐 |
| `docs/TODO.md` | TODO v2.37 | Step 5 🦸 |
| `docs/README.md` | D-3 脱敏 | Step 5 🦸 |
| `docs/R71/R71-closure-summary.md` | 轮次总结 | Step 6 🦸 |

---

## 4. 诊断决策树（来自需求文档 §6）

```mermaid
flowchart TD
    A[Web端空白] --> B{健康检查 /health?}
    B -->|ok| C[进程正常→前端/数据问题]
    B -->|超时/500| D[Web容器未启动]
    D --> D1[检查docker run配置]
    D1 --> D2{__main__.py有web入口?}
    D2 -->|无| D3[补--web参数重启]
    D2 -->|有| D4[端口映射/nginx]

    C --> E{/api/channels返回?}
    E -->|200| F{channels含lobby?}
    E -->|401/500| G[session持久化问题]
    F -->|有| H{/api/chat?channel=lobby 返回?}
    F -->|空| I[workspace模块异常]
    H -->|200+messages[]| J{/ws/chat WebSocket?}
    H -->|401| G
    H -->|200+[]| K[日志回放失败]
    J -->|101 ✓| L[前端渲染]
    J -->|非101| M[WS升级失败]
    K --> K1[CHAT_LOG_DIR权限/路径]
    L --> L1[Console JS报错]
```

---

## 5. 验收清单（从需求文档复制）

### 🎯 5.1 方向 A — F-9 诊断

| # | 检查项 | 状态 |
|:-:|:-------|:----:|
| ✅-1 | 进程/端口检查执行并记录 | ⏳ |
| ✅-2 | 浏览器 DevTools 6 项检查完成 | ⏳ |
| ✅-3 | 日志检查完成 | ⏳ |
| ✅-4 | Token/Session 验证完成 | ⏳ |
| ✅-5 | 根因结论明确 | ⏳ |
| ✅-6 | 修复建议明确（顺修/排期/架构） | ⏳ |

### 🎯 5.2 方向 B — 修复

| # | 检查项 | 状态 |
|:-:|:-------|:----:|
| ✅-7 | 修复通过顺手修条件门 | ⏳ |
| ✅-8 | 修复后 Web 端可见消息 | ⏳ |
| ✅-9 | 各 Tab 可切换 | ⏳ |
| ✅-10 | WebSocket 实时推送正常 | ⏳ |

### 🎯 5.3 方向 C — 治理

| # | 检查项 | 状态 |
|:-:|:-------|:----:|
| ✅-11 | TODO.md v2.37 | ⏳ |
| ✅-12 | F-22 标记 ✅ 已修复 | ⏳ |
| ✅-13 | D-3 README.md 脱敏 | ⏳ |

---

## 6. 注意事项

1. **诊断优先** — 诊断阶段零代码修改，所有排查入诊断报告
2. **卡住降级** — 无法访问浏览器时，改为 curl + 日志间接推断
3. **本容器无 VPS SSH 权限** — docker logs / ss 等操作由项目负责人手动执行或通过 WS 命令管道
4. **修复条件门严格** — 不满足 3 条条件则留方案下一轮
5. **参考：** 已知问题（见 WORKFLOW.md / TODO.md）、F-9 历史记录（见 TODO.md §1）

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-05 | 初稿 — R71 Web 端诊断 + 顺手修复工作计划 |
