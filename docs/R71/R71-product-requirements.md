# R71 产品需求 — Web 端诊断 + 顺手修复 🎯

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 需求分析师
> **日期：** 2026-07-05
> **基线：** `b3ed0cd`（R70 3 个 Bug Fix 合并部署完成）
> **R70 测试状态：** ✅ 全链路回归 7/9 通过，3 个 Bug Fix 验证通过
> **本轮改动范围：** 零代码 → 轻度代码（视 F-9 诊断结果，≤30 行净增）

---

## 0. 先验：R70 验证结果

### 0.1 R70 已完成事项

| 事项 | 状态 | 产出 |
|:-----|:----:|:-----|
| 3 个 Bug Fix（workspace 复用 + step_complete 作用域 + 名字→ID 解析） | ✅ | `0636aba` / `1f1ac4f` / `b3ed0cd` |
| R69 功能全链路回归（V-1~V-9） | ✅ 7/9 通过 | `R70-validation-report.md` |
| 角色映射缺陷定位（workspace role ≠ pipeline role） | 🔍 已定位 | 已知问题，本轮不修 |
| **F-9 Web 端诊断** | ❌ 未完成 | R70 所有验证通过 WS 客户端，未进入浏览器 |

### 0.2 为什么 F-9 在 R70 没诊断到

| 原因 | 说明 |
|:-----|:------|
| R70 是 WS 客户端管线验证 | 所有测试通过 Python WsBridgeClient 连接 WebSocket，从未打开浏览器 |
| F-9 是纯 Web 端问题 | Tab 空白是前端渲染/WebSocket连接/日志回放的问题，WS 客户端不受影响 |
| 需要浏览器 DevTools 诊断 | 需 Chrome/Firefox 实际打开 URL，检查 Network / Console / 渲染过程 |

---

## 1. 问题背景

### 1.1 现状

**F-9（P0）：** Web 端 Tab 页加载后持续显示「加载中」，内容区空白。

| 维度 | 描述 |
|:-----|:------|
| **现象** | Web 端 `/chat` 页面（或 `/`）成功加载，Tab 栏可见，但消息区域保持 `加载中...`（`templates.py` L127）不消失 |
| **影响** | 项目负责人无法通过 Web 端观察工作室消息、管线进度、Agent 在线状态——用户观测窗口断裂 |
| **历史** | 最早记录于 TODO F-9，P0 严重度，从未排期修复 |
| **R70 诊断结论** | 「本次验证中 F-9 未触发——管线全链路通过 WS 客户端完成，未进入 Web 端 UI。建议 R71 安排 Web 端专项验证轮」 |

### 1.2 根因假设（待验证）

从代码阅读推测，可能根因包括：

| # | 假设 | 可能性 | 对应的代码/配置 |
|:-:|:-----|:------:|:----------------|
| ① | Web 容器进程未运行 / 端口未监听 | 🟡 中 | 部署后 `__main__.py` 是否自启动 web；nginx 是否反代 |
| ② | WebSocket 连接失败（`/ws/chat` 返回 101↑？） | 🔴 高 | `handle_ws_chat()` → `validate_token()` → WebSocket handshake |
| ③ | `/api/chat` 返回空数据或 401 | 🔴 高 | `handle_api_chat()` → DB/MS fallback 均返回空 |
| ④ | 前端 JS 加载失败 / 报错 | 🟡 中 | templates.py 内联 JS 是否有语法错误或渲染异常 |
| ⑤ | Token/session 过期 | 🟡 中 | `validate_token()` → `persistence.get_web_sessions()` 空集 |
| ⑥ | CHAT_LOG_DIR 权限 / 路径问题 | 🟢 低 | `config.CHAT_LOG_DIR` → `DATA_DIR / "chat_logs"` |
| ⑦ | `handle_api_channels` 异常导致 Tab 列表不渲染 | 🟡 中 | `get_all_workspaces()` 异常被 `try/except pass` 吞掉 |

### 1.3 为什么本轮做？

| 原因 | 说明 |
|:-----|:------|
| 🔴 **P0 严重度** | Web 端是项目负责人的主要观测窗口，持续空白 = 用户断联 |
| 🟡 **上轮已铺路** | R70 完成了管线验证 + 3 个 bug fix，基础设施稳定，可以集中精力搞前置端 |
| 🟢 **收益明确** | 诊断出根因 + 顺手修复，恢复 Web 端可用性；即使需要大改也产出完整方案 |

---

## 2. 功能需求

### 设计原则

> **先诊断，后修复。** 诊断阶段零代码——通过浏览器 DevTools + 日志分析 + 进程检查三步定位根因。根因确定为配置/部署/≤30 行代码问题则在本轮修复，否则记录完整方案留下轮。

---

### 方向 🅰️（核心）：F-9 Web 端诊断 🔴 P0

#### A1 — 进程与端口检查

在容器/VPS 上执行：

```bash
# Web 进程是否存活
docker exec ws-bridge-prod ps aux | grep aiohttp      # Python web 进程
ss -tlnp | grep -E '8080|3000'                         # Web 端口监听

# 或者直接在宿主机
curl -s http://localhost:<port>/health                 # 健康检查端点
```

**通过标准：** 健康检查返回 `ok\n` + 端口监听正常 = 进程层没问题 → 跳到 A2。进程不存活或端口不监听 → 诊断根因为容器启动配置问题。

#### A2 — 浏览器实际访问 + DevTools

| 步骤 | 操作 | 观察点 |
|:----:|:-----|:-------|
| ① | 打开浏览器 → 访问 Web 端 URL | 页面是否渲染？Tab 栏是否显示？ |
| ② | **Console Tab** | JS 报错？`Uncaught TypeError`？CORS 错误？ |
| ③ | **Network Tab → `/api/chat`** | 请求状态码？返回数据结构？是 `{"messages": []}` 还是 401/500？ |
| ④ | **Network Tab → `/api/channels`** | 是否返回含 lobby 的频道列表？ |
| ⑤ | **Network Tab → `/ws/chat` ** | 是否 101 Switching Protocols？WebSocket 是否建立？ |
| ⑥ | **Network Tab → `/api/agents/status`** | 返回 401？数据为空？ |

**通过标准：** 6 项检查 → 整理出哪条调用链断了 = 根因定位完成。

#### A3 — 日志检查

```bash
# 检查 server.log / aiohttp 日志
docker logs ws-bridge-prod --tail 100 | grep -iE 'error|traceback|web|chat'

# 检查 chat_log 目录是否存在且有数据
ls -la <DATA_DIR>/chat_logs/
cat <DATA_DIR>/chat_logs/chat_2026-07-05_lobby.log | tail -20
```

#### A4 — Token/Session 检查

```python
# 检查 web sessions 是否持久化
import persistence
sessions = persistence.get_web_sessions()
print(f"Web sessions count: {len(sessions)}")
# 如果有 token → 验证
token_sample = next(iter(sessions.keys()))[:16] if sessions else "EMPTY"
```

---

### 方向 🅱️（修复）：根因修复 🟡 P1

根据诊断结果分三类：

| 修复类型 | 条件 | 建议范围 | 示例 |
|:---------|:-----|:---------|:-----|
| **✅ 顺手修** | 配置/部署/≤30 行代码 | 本轮完成 | nginx 配置错误、端口未暴露、前端小 bug |
| **⚠️ 排期修** | >30 行 ≤200 行代码 | 留 R72 | Web 端代码重构、路由改造 |
| **❌ 架构修** | >200 行或涉及跨模块改造 | 记录方案留 R73 | 全栈重写、架构改造 |

**顺手修复条件门（从 R70 沿用）：**

1. ✅ 根因是**配置/部署问题**（非代码架构改造）
2. ✅ 修复改动 **≤30 行** 或 重启容器/Nginx 即可
3. ✅ 修复**不影响**其他工作管线

#### B1 — 如果 Web 容器没启动

```diff
# __main__.py 或 docker run 配置中确认 web 服务入口
# 如: 缺 --web 参数 → 补上
```

#### B2 — 如果 API 端点返回空数据

```diff
# handle_api_chat 中 MS 退路问题
- if db_msgs:
+ try:  # 加强退路
```

#### B3 — 如果前端 JS 报错

```diff
# templates.py 中 JS 修复
```

---

### 方向 🅲（治理）：清理 + TODO 更新 🟢 P3

#### C1 — TODO.md 更新

| 操作 | 说明 |
|:-----|:------|
| 版本号 | v2.36 → **v2.37** |
| R70 完成记录 | 移入「已完成事项」 |
| F-22 状态 | 更新为 `✅ R70 已修复`（3 个 commit） |
| F-9 状态 | 根据诊断结果更新 |
| D-3 推进 | docs/README.md 脱敏清理 |

#### C2 — D-3 docs/README.md 脱敏

检查 `docs/README.md` 中的内部角色名引用，替换为通用角色名（需求分析师/项目管理/架构师/开发工程师/审查工程师/测试工程师/项目负责人）。

---

## 3. 验收标准

### 🎯 3.1 方向 A — F-9 Web 端诊断

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 进程/端口检查执行 | 明确记录 Web 进程状态 + 端口监听情况 | 诊断报告 §进程检查 |
| ✅-2 | 浏览器 DevTools 6 项检查完成 | Console / Network(/api/chat, /api/channels, /ws/chat, /api/agents/status) 逐项记录 | 诊断报告 §DevTools |
| ✅-3 | 日志检查 | `docker logs` / `chat_logs` 目录检查记录 | 诊断报告 §日志 |
| ✅-4 | Token/Session 验证 | web sessions 数量 + 有效性检查 | 诊断报告 §Token |
| ✅-5 | **根因结论** | 精准定位：「因为 XX，所以 Tab 空白」 | 诊断报告 §根因 |
| ✅-6 | 修复建议 | 明确标注「顺修 / 排期 / 架构」 | 诊断报告 §建议 |

### 🎯 3.2 方向 B — 根因修复

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-7 | 修复通过顺手修条件门 | ≤30 行 / 配置级 / 不影响管线 | 审查 |
| ✅-8 | 修复后 Web 端可正常看到消息 | 登录后 Tab 面板显示最新消息 | 浏览器实测 |
| ✅-9 | 修复后各 Tab 可点击切换 | Tab1(大厅) / Tab2(活跃) / Tab4(管理) 正常切换 | 浏览器实测 |
| ✅-10 | 修复后 WebSocket 在线推送正常 | 新消息实时出现在 Web 端 | 发一条消息 → 浏览器可见 |

### 🎯 3.3 方向 C — 治理清理

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-11 | TODO.md v2.36 → v2.37 | 版本号更新 + 新增 R71 条目 | 检查文件头 |
| ✅-12 | F-22 标记 ✅ 已修复 | 状态更新 | grep TODO.md |
| ✅-13 | D-3 docs/README.md 脱敏 | 零内部角色名残留 | `grep -nE '(需求分析师|项目管理|架构师|开发工程师|审查工程师|测试工程师|项目负责人)' docs/README.md` 只应匹配替换后的通用名 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| 📊 进度 Tab 功能修复 | 已在 R52 移除（F-18） | 不恢复已移除功能 |
| 🔧 角色映射缺陷（workspace role ≠ pipeline role） | 架构改造 | 需完整轮次 |
| 📱 Web 端封装 Android APK（R36-2） | 新功能 | 专属轮次 |
| 🆕 新虾注册流程（R36-B/C） | 注册流程 | 专属轮次 |
| 🗂️ 自动化测试套件增强 | 测试基建 | 专属轮次 |
| 🐛 角色映射持久化改进 | 架构改造 | 影响面大，需单独规划 |

---

## 5. 管线计划

| Step | 角色 | 产出 | 预计耗时 |
|:----:|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 🏗️ 架构师 | 技术方案（F-9 诊断流程设计 + 3 条假设树） | 15min |
| **3** | 💻 开发工程师 | 🅰️ F-9 诊断执行（浏览器 DevTools + 进程检查 + 日志） | 25min |
| **4** | 🔍 审查工程师 | 诊断报告审查 + 🅱️ 修复方案审核 | 15min |
| **5** | 🦐 测试工程师 | 🅱️ 修复后 Web 端回归验证 + 🅲 治理检查 | 20min |
| **6** | 🛠️ 项目管理 | 合并部署归档 + TODO 更新 + D-3 脱敏 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/web_viewer.py` | **可能修改** — 视诊断结果 | ~0–30 行 |
| `server/templates.py` | **可能修改** — 前端 JS/CSS 修复 | ~0–15 行 |
| `docs/README.md` | **脱敏** — 角色名替换 | ~5 行 |
| `docs/TODO.md` | **版本更新** — v2.36→v2.37 | ~5 行 |
| `docs/R71/R71-f9-diagnosis.md` | **新增** — F-9 诊断报告 | 新增文件 |
| `docs/R71/R71-closure-summary.md` | **新增** — 轮次总结 | 新增文件 |
| **本轮上限** | | **≤30 行代码** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| Web 端 URL 不可达（容器/VPS 网络问题） | 无法执行浏览器诊断 | 降级为 curl + 日志间接推断，产出的诊断报告标注「远程不可达」 |
| 浏览器 DevTools 发现复杂前端 bug | 需要大改模板/JS | 记录完整修复方案，留 R72 排期 |
| F-9 根因 = 服务器整体挂了 | Web 端 + WS 客户端都不可用 | 管线推进本身即证明 WS 端正常，F-9 是 Web 子模块问题 |
| 本容器无 VPS SSH 权限 | 无法执行 `docker logs` / `ss` | 通过 WS Bridge WebSocket 管道向服务端发命令；或由项目负责人手动执行诊断命令 |

---

## 6. 诊断流程设计

### 6.1 诊断决策树

```mermaid
flowchart TD
    A[Web 端空白] --> B{健康检查 /health?}
    B -->|ok\n| C[进程/端口正常 → 前端/数据问题]
    B -->|超时/500| D[Web 容器未启动]
    D --> D1[检查 docker run 配置]
    D1 --> D2{__main__.py 是否有 web 入口?}
    D2 -->|无| D3[补 --web 参数并重启]
    D2 -->|有| D4[检查端口映射/nginx]

    C --> E{/api/channels 返回?}
    E -->|200 OK| F{channels 含 lobby?}
    E -->|401/500| G[session 持久化问题]
    F -->|有| H{/api/chat?channel=lobby 返回?}
    F -->|空| I[workspace 模块异常]
    H -->|200 + messages[]| J{/ws/chat WebSocket?}
    H -->|401| G
    H -->|200 + []| K[日志回放失败]
    J -->|101 ✓| L[前端渲染问题]
    J -->|非 101| M[WS 升级失败]
    K --> K1[检查 CHAT_LOG_DIR 权限/路径]
    L --> L1[检查 Console JS 报错]
```

### 6.2 诊断产出物

`docs/R71/R71-f9-diagnosis.md` 包含：

| 章节 | 内容 |
|:-----|:------|
| §1 基本信息 | 时间、Web URL、Web 容器版本 |
| §2 进程检查 | `ps aux` / `ss` / `curl /health` 结果 |
| §3 浏览器 DevTools | Console 错误列表 + Network 请求跟踪表 |
| §4 日志分析 | `docker logs` / `chat_logs/` 分析 |
| §5 Token/Session | 会话数量 + 有效性 |
| §6 根因结论 | 一句话精准结论 |
| §7 修复建议 | 方案 + 代码/配置示例 + 预估时间 |

---

## 7. 脱敏检查清单

- [ ] docs/R71/*.md 零内部名残留
- [ ] `grep -nE '^(小|@)\\w+' docs/R71/*.md` 零匹配
- [ ] 使用通用角色名（PM / arch / dev / review / QA / admin）
- [ ] 不包含真实 agent_id / token / URL
- [ ] docs/README.md 脱敏检查

---

## 8. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-05 | 初稿 — R71 Web 端诊断 + 顺手修复需求 |
