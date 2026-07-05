# R71 F-9 Web 端诊断范围 — 假设树 + 诊断流程 + 3 类预案

> **作者：** 🏗️ 架构师  
> **日期：** 2026-07-05  
> **基线 commit：** `053fe68`（WORK_PLAN v1.0 审核通过）  
> **参考版本：** `ws-bridge:r71`（容器已部署，端口 `28787:8765`）  
> **上一轮诊断结论：** 「本次验证中 F-9 未触发——管线全链路通过 WS 客户端完成，未进入 Web 端 UI。建议 R71 安排 Web 端专项验证轮」（R70 验证报告）

---

## 1. F-9 根因假设树（带排查优先级）

从代码阅读 + 架构分析，F-9 Web 端空白的具体链路：  
**浏览器 → HTTP GET `/chat` → 渲染 HTML → JS `init()` → fetch `/api/channels` → render tab bar → `selectTab()` → fetch `/api/chat?channel=...` → 渲染消息列表 → WebSocket `/ws/chat` → 实时推送**

上述链路任一环节断掉，都会导致「Tab 栏可见但消息区空白」。

### 假设优先级排序（P0→P2）

| 优先级 | # | 假设 | 影响链路环节 | 可能性 | 证据来源 | 验证方法 |
|:------:|:-:|:-----|:------------|:------:|:---------|:---------|
| **P0** | ② | **WebSocket 连接失败** — `/ws/chat` 返回非 101 或握手后断开 | 实时推送 | 🔴 高 | `handle_ws_chat()`（web_viewer.py L255-275）：token 验证失败时直接返回 `web.WebSocketResponse()`（未 `prepare`）而非拒绝连接。此实现不报错但在浏览器端表现为「链接被拒绝/关闭」。WS 重连逻辑（templates.py L476-484）：close code ≥4000 时跳转 bind 页 | 浏览器 Network Tab 看 WS 请求状态码 |
| **P0** | ③ | **`/api/chat` 返回空数据或 401** — DB+log fallback 均返回空 | 消息加载 | 🔴 高 | `handle_api_chat()`（web_viewer.py L206-230）：try DB → except pass → log fallback → 仍空 → `{"messages": []}`。可能原因：`CHAT_LOG_DIR` 路径不对 / chat_logs 无数据 / `ms.get_messages_by_channel` 异常被吞 | 浏览器 Network Tab → `/api/chat` 看响应体 + docker logs |
| **P0** | ⑤ | **Token/Session 过期或不存在** — `validate_token()` 检查 ws_im_session cookie 失败 | 全局认证 | 🔴 高 | `validate_token()`（web_viewer.py L139-148）：`persistence.get_web_sessions()` 返回空集时所有 API 返回 401。Web 端 JS（L282-284）：401 时 `location.href = '/chat'` 跳回 bind 页 → 循环重定向但内容空 | 浏览器 Application Tab → Cookies → ws_im_session |
| **P1** | ① | **Web 进程/端口异常** — aiohttp 进程存活但端口映射不对或未启动 | 全局可达 | 🟡 中 | `__main__.py` L796-851：`main()` 始终启动 aiohttp web 服务（无 `--web` 参数条件开关）。端口 = `WS_PORT` 或 `PORT`（config.py L8），默认 `8765`。容器 `-p 28787:8765` 映射正常 | `curl http://localhost:28787/health` |
| **P1** | ④ | **前端 JS 加载失败 / 渲染异常** — `templates.py` 内联 JS 语法错误或 DOM 操作失败 | 前端渲染 | 🟡 中 | `CHAT_TEMPLATE`（templates.py L35+）：内联 JS，无外部依赖。`init()` L410+ 顺序执行：fetch workspaces → renderTabBar → selectTab → loadMessages → connectWS。任何一步抛出未捕获异常都会阻塞后续 | 浏览器 Console Tab 看 JS 报错 |
| **P1** | ⑦ | **`/api/channels` 异常** — `handle_api_channels()` 异常被 `try/except pass` 吞掉，返回空 `channels` | Tab 渲染 | 🟡 中 | `handle_api_channels()`（web_viewer.py L233-252）：`ws_mod.get_all_workspaces()` 异常被 `try/except pass` 吞掉，但静态 lobby 始终存在（L235-237），Tab 栏至少渲染大厅。除非 `channels` 为空时 Tab 渲染异常。实际 Tab1（lobby）始终 visible | 浏览器 Network Tab → `/api/channels` |
| **P2** | ⑥ | **CHAT_LOG_DIR 权限/路径问题** — `config.CHAT_LOG_DIR` 指向的目录不存在或不可写 | 日志回放 | 🟢 低 | `write_chat_log()`（web_viewer.py L48-54）：`mkdir(parents=True, exist_ok=True)` + `open()` 失败打印 warning。但 R71 容器已有运行数据，chat_logs 目录应该存在 | `ls -la DATA_DIR/chat_logs/` |

### 排查顺序建议

```
P0 链路: Token/Session(⑤) → /api/chat(③) → WebSocket(②)  [浏览器无需SSH]
P1 链路: 进程/端口(①) → /api/channels(⑦) → JS报错(④)    [需要SSH或curl]
P2 补查: 日志路径(⑥)                                       [仅日志确认]
```

**原因：** 浏览器 DevTools 的 Network/Console/Application Tab 无需 SSH 权限，可在几分钟内完成 P0 三项检查，排除最高概率根因。P1 中只需 `curl /health` 即可排除 ①。

---

## 2. 诊断流程（完整操作指南）

### Phase A — 进程与端口检查（SSH 到 VPS）

```bash
# A1: 检查容器运行状态
docker ps --filter name=ws-bridge-prod --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"

# A2: 容器内进程检查
docker exec ws-bridge-prod ps aux | grep -i python

# A3: 端口监听检查（容器内或宿主机）
docker exec ws-bridge-prod ss -tlnp | grep -E '8765|8080'

# A4: 宿主机 → 容器端口可达性
curl -s http://127.0.0.1:28787/health
curl -s http://127.0.0.1:28787/
```

**通过条件（进程层正常）：**
- 容器 `Up` + 端口 `28787->8765` ✓
- `ps aux` 显示 python/aiohttp 进程 ✓
- `curl /health` 返回 `ok\n` ✓
- `ss -tlnp` 显示 0.0.0.0:8765 监听 ✓

**失败处理：** 任一不通过 → **诊断结论 = ① Web 进程/端口异常** → 直接跳到 §4 预案 ①

---

### Phase B — 浏览器 DevTools 6 项检查（浏览器操作）

| 步骤 | 端点 | 操作 | 预期结果 | 异常含义 |
|:----:|:-----|:-----|:---------|:---------|
| **B-0** | URL | 浏览器打开 `https://wsim.datahome73.cloud` | 显示 bind 页或聊天页 | URL 不可达 → 容器/nginx 问题 |
| **B-1** | Console | F12 → Console Tab | 无红色报错 | JS 报错 → 假设 ④ |
| **B-2** | `/api/channels` | Network → filter `channels` | 200 + `channels: [...]`（含 lobby） | 401/500 → 假设 ⑤/⑦ |
| **B-3** | `/api/chat?channel=lobby` | Network → filter `chat?` | 200 + `messages: [...]` | 401 → 假设 ⑤；200+`[]` → 假设 ③/⑥ |
| **B-4** | `/ws/chat` | Network → filter `ws` | 101 Switching Protocols | 非 101/拒绝 → 假设 ② |
| **B-5** | `/api/agents/status` | Network → filter `agents/status` | 200 + `agents: {...}` | 401 → 假设 ⑤ |
| **B-6** | Application | Application → Cookies → ws_im_session | 有 `ws_im_session` cookie（若已登录） | 无 cookie → 查看 Network 检查 /api/check 返回 |

**检查顺序：** B-0 → B-2 → B-3 → B-4 → B-1 → B-5 → B-6

**关键观察：** B-3 的响应体决定诊断方向——
- `401` → token 问题（假设 ⑤），查 B-6 cookie
- `200 + messages: [...]` → 后端数据正常，查 B-1（JS 渲染）或 B-4（WS 推送）
- `200 + messages: []` → 日志回放问题（假设 ③/⑥），查 A 和 D

---

### Phase C — 日志检查（SSH 到 VPS）

```bash
# C1: 容器日志—错误/异常
docker logs ws-bridge-prod --tail 100 | grep -iE 'error|traceback|exception|warning.*web|web.*error'

# C2: chat_logs 目录
docker exec ws-bridge-prod ls -la /app/data/chat_logs/ 2>/dev/null || echo "DIR NOT FOUND"

# C3: 若 chat_logs 存在，查看今日大厅日志
docker exec ws-bridge-prod bash -c 'ls -la /app/data/chat_logs/chat_$(date +%Y-%m-%d)*.log 2>/dev/null'
docker exec ws-bridge-prod tail -5 /app/data/chat_logs/chat_$(date +%Y-%m-%d)_lobby.log 2>/dev/null

# C4: 若 chat_logs 不存在，查 DATA_DIR
docker exec ws-bridge-prod env | grep DATA_DIR
docker exec ws-bridge-prod ls -la /app/data/
```

**通过条件：**
- 无 `error/traceback` 日志 ✓
- `chat_logs/` 目录存在且有今日文件 ✓
- 文件内容有消息记录 ✓

---

### Phase D — Token/Session 检查（SSH 到 VPS）

```bash
# D1: 查看持久化 sessions 数量
docker exec ws-bridge-prod python3 -c "
import json
try:
    with open('/app/data/web_sessions.json') as f:
        sessions = json.load(f)
    print(f'Web sessions count: {len(sessions)}')
    if sessions:
        keys = list(sessions.keys())
        print(f'First token: {keys[0][:16]}...')
        print(f'Sample entry: {json.dumps(sessions[keys[0]], indent=2)}')
    else:
        print('Sessions is empty')
except FileNotFoundError:
    print('web_sessions.json NOT FOUND')
except Exception as e:
    print(f'Error: {e}')
"

# D2: 查看 web_bind_codes（确认 OAuth 流程正常）
docker exec ws-bridge-prod python3 -c "
import json
try:
    with open('/app/data/web_bind_codes.json') as f:
        codes = json.load(f)
    print(f'Web bind codes count: {len(codes)}')
    approved = [k for k,v in codes.items() if v.get(\"approved\")]
    print(f'Approved codes: {len(approved)}')
except FileNotFoundError:
    print('web_bind_codes.json NOT FOUND')
"

# D3: 检查 GitHub OAuth 配置
docker exec ws-bridge-prod env | grep -i github
```

**通过条件：**
- `web_sessions.json` 存在且 count > 0 ✓
- token 格式有效 ✓
- 有已审批的绑定码 ✓

---

## 3. 顺手修复条件门（引用需求文档 §2）

从需求文档 §2「方向 🅱️（修复）」沿用 R70 条件门：

| # | 条件 | 说明 | 检查方法 |
|:-:|:-----|:-----|:---------|
| **1** | 根因是**配置/部署问题**（非代码架构改造） | nginx 配置、docker run 参数、环境变量 | 诊断报告 §6 根因分类 |
| **2** | 修复改动 **≤30 行** 或重启容器/Nginx 即可 | 纯配置修复不计数 | 诊断报告 §7 修复方案行数估算 |
| **3** | 修复**不影响**其他工作管线 | 不改 handler.py/entrypoint.py 核心逻辑 | 代码审查时验证 |

**不满足任一条件** → 修复方案记录到 `TODO.md` 留 R72 排期，本轮仅产出诊断报告。

---

## 4. 修复 3 类预案（覆盖假设①~⑦）

### 预案 A — 配置/部署修复（假设①、⑤、⑥）

**修复类型：** ✅ 顺手修（重启/改环境变量即可）

#### 预案 A-1：Web 进程/端口异常（假设①）

**现象：** `curl /health` 超时/500 / 容器没启动  
**根因可能：** 容器启动参数不对 / 镜像缺少入口 / 端口映射错误  
**修复：**

```bash
# 检查容器日志确认具体情况
docker logs ws-bridge-prod --tail 50

# 如果容器未启动，重新运行
docker stop ws-bridge-prod && docker rm ws-bridge-prod
docker run -d --name ws-bridge-prod --restart unless-stopped \
  -p 28787:8765 \
  -v /opt/ws-bridge-prod/data:/app/data \
  ws-bridge:r71
```

**修复行数：** 0 行代码（运维操作）

---

#### 预案 A-2：Token/Session 持久化问题（假设⑤）

**现象：** Web 页面加载后显示 bind 页（需重新绑定），无法进入聊天页  
**根因可能：** `web_sessions.json` 丢失 / `ws_im_session` cookie 过期（7 天）/ 容器重启后 session 未持久化  
**修复（配置检查）：**

```bash
# 确认持久化数据卷 mount 正确
docker inspect ws-bridge-prod | grep -A2 Mounts

# 确认 sessions 文件存在
docker exec ws-bridge-prod cat /app/data/web_sessions.json | head -5

# 如果数据卷未挂载 → 重新启动并挂载
```

**如果 session 丢失且需要快速恢复：**  
在 VPS 上通过 `/api/approve_web` 创建新的 bind code → 项目负责人浏览器扫码/输入码重新绑定。  
**修复行数：** 0 行代码（配置检查/运维操作）

---

#### 预案 A-3：CHAT_LOG_DIR 权限/路径问题（假设⑥）

**现象：** `write_chat_log` 正常写日志，但 `read_channel_logs` 读不到文件  
**根因可能：** `config.CHAT_LOG_DIR` 路径与数据卷不匹配 / 文件权限不对  
**修复：**

```bash
# 确认 CHAT_LOG_DIR 路径
docker exec ws-bridge-prod python3 -c "
from server.config import CHAT_LOG_DIR, DATA_DIR
print(f'CHAT_LOG_DIR: {CHAT_LOG_DIR}')
print(f'DATA_DIR: {DATA_DIR}')
print(f'Exist: {CHAT_LOG_DIR.exists()}')
"

# 如果路径不对 → 设置 WS_DATA_DIR 环境变量重启
```

**修复行数：** 0 行代码（环境变量配置）

---

### 预案 B — 代码小修（假设③、⑦、④）

**修复类型：** ✅ 顺手修（≤30 行代码改动）

#### 预案 B-1：`/api/chat` 返回空数据（假设③）

**现象：** DevTools 看到 `/api/chat` 返回 `{"channel":"lobby","messages":[]}`，但 chat_logs 有数据  
**根因可能：** `handle_api_chat()` 中 `ms.get_messages_by_channel()` 异常被 `try/except pass` 吞掉 → fallback 到 `read_channel_logs` → `read_channel_logs` 也返回空  
**修复方向：**

```python
# web_viewer.py L206-230 — handle_api_chat()
# 当前: try DB → except pass → log fallback (days=7)
# 可能问题：read_channel_logs 的 day offset 计算使用本地时区但 log 文件名用 UTC+7 日期
# 修复建议 1: 在 except DB 时加日志，不 silent fail
# 修复建议 2: 确保 log 文件名匹配
```

```diff
    try:
        db_msgs = ms.get_messages_by_channel(channel, config.DATA_DIR, limit=limit)
        if db_msgs:
            return web.json_response({"channel": channel, "messages": db_msgs})
-   except Exception:
-       pass
+   except Exception as e:
+       logger.warning("DB msg fetch failed for %s: %s", channel, e)

    messages = read_channel_logs(channel, days=7)
```

**修复行数：** ~3 行

---

#### 预案 B-2：`/api/channels` 异常（假设⑦）

**现象：** Tab 栏只显示大厅（lobby），无其他 channel Tab  
**根因可能：** `ws_mod.get_all_workspaces()` 抛出异常 → `try/except pass` 吞掉  
**修复方向：**

```diff
    channels = [
        {"id": "lobby", "name": "大厅", "emoji": "🌐", "state": "active"},
    ]
    try:
        ws_list = ws_mod.get_all_workspaces()
        ...
-   except Exception:
-       pass
+   except Exception as e:
+       logger.warning("Workspace list fetch failed: %s", e)
```

**修复行数：** ~3 行

**注意：** 此修复不影响 Tab 栏显示（lobby 始终存在），只是让缺失的 workspace Tab 恢复。  
**F-9 空白根因不在此处**（即使 channels 为空，Tab 1 大厅也应显示内容）。

---

#### 预案 B-3：前端 JS 渲染异常（假设④）

**现象：** Console 报 JS 错误，但 Network 请求都正常  
**根因可能：** `templates.py` 内联 JS 语法错误 / DOM 操作引用 null 元素 / `__VIEWER__` 插入导致 XSS 破坏  
**修复方向：**

```javascript
// 典型修复模式：添加防御性 null 检查
// 如果 init() 中某步失败，catch 并显示错误信息而非静默失败
```

```diff
async function init() {
+ try {
    // ... existing init code ...
+ } catch(e) {
+   document.getElementById('msgList').innerHTML = 
+     '<div class="empty">加载异常: ' + escapeHtml(e.message) + '</div>';
+ }
```

**修复行数：** ~10 行

---

#### 预案 B-4：WebSocket 连接失败（假设②）

**现象：** Network Tab 显示 `/ws/chat` 非 101 状态码  
**根因可能：** `validate_token()` 返回 None → `handle_ws_chat()` 返回未 `prepare` 的 WebSocketResponse  
**修复方向：**

```diff
async def handle_ws_chat(request: web.Request) -> web.WebSocketResponse:
    token = request.query.get("token", "")
    if not validate_token(token):
-       return web.WebSocketResponse()
+       raise web.HTTPUnauthorized()
```

**修复行数：** ~2 行

**注意：** 当前行为（返回未 `prepare` 的 WSResponse）在浏览器端表现为「WebSocket 连接失败」，客户端重连 3 秒后再次尝试。若 token 持续无效，会产生无限重连循环。改用 `HTTPUnauthorized` 后，客户端 WS `onclose` 检测到 code 4000-4999 会跳转 bind 页。

---

### 预案 C — 架构改造记录（留 R72+）

**修复类型：** ❌ 架构修（>200 行或跨模块改造）

| 假设 | 场景 | 改造规模 | 记录位置 |
|:----:|:-----|:---------|:---------|
| ④* | 前端需要完整重写（当前内联 JS 200+ 行无模块化） | 500+ 行 | `TODO.md` §架构项 |
| ②* | WebSocket 鉴权机制需要统一（当前 WS 与 API 两套 token 验证） | 50+ 行跨文件 | `TODO.md` §待排期 |
| ⑤* | Session 持久化需要更可靠的 fallback 机制 | 100+ 行 | `TODO.md` §待排期 |

**注意：** 上述仅在诊断确认根因需要架构级改造时才启用，不属于本轮预设目标。

---

## 5. 降级方案

### 场景 1：无法访问浏览器

**触发条件：** Web URL 不可达 / 项目负责人不在电脑前 / 网络隔离无法访问  
**替代方案：** 全 curl 诊断（无需浏览器）

```bash
# D1: 检查 /api/channels
curl -s http://127.0.0.1:28787/api/channels | python3 -m json.tool

# D2: 检查 /api/chat（需要有效 token）
curl -s "http://127.0.0.1:28787/api/chat?channel=lobby&limit=5&token=<TOKEN>" | python3 -m json.tool

# D3: 检查 WebSocket 握手（需要 websocat 或 wscat）
echo "" | websocat -v "ws://127.0.0.1:28787/ws/chat?token=<TOKEN>" 2>&1 | head -20

# D4: 检查 session cookie 有效性（直接从文件读取 token）
docker exec ws-bridge-prod python3 -c "
import json
with open('/app/data/web_sessions.json') as f:
    s = json.load(f)
for token, entry in list(s.items())[:2]:
    print(f'Token: {token[:20]}... Name: {entry.get(\"name\")}')
"
```

**产出标注：** 诊断报告 §2 注明「远程 curl 诊断，未实际打开浏览器」

---

### 场景 2：Token 未知（无法通过认证访问 API）

**触发条件：** 不知道当前有效 token，session 持久化数据丢失  
**替代方案：**

```bash
# 直接从数据卷读 session token
docker exec ws-bridge-prod cat /app/data/web_sessions.json | \
  python3 -c "import sys,json; d=json.load(sys.stdin); next(iter(d.keys()), 'NONE')"

# 如果没有有效 session → 创建新的 bind code
curl -X POST http://127.0.0.1:28787/api/bind  # 生成新绑定码
# 然后通过 WS 命令审批: !approve_web <CODE>
```

---

### 场景 3：VPS SSH 不可用

**触发条件：** 本容器无 VPS SSH 权限 / SSH key 失效  
**替代方案：** 通过 WS Bridge WebSocket 管道向服务端发命令

```
!exec docker exec ws-bridge-prod curl -s http://127.0.0.1:8765/health
!exec docker exec ws-bridge-prod ls -la /app/data/chat_logs/
```

---

## 6. 诊断产出物模板

诊断 Step（Step 3）产出 `docs/R71/R71-f9-diagnosis.md` 结构：

| 章节 | 内容 |
|:-----|:------|
| §1 基本信息 | 诊断时间、Web URL、容器版本、基线 commit |
| §2 Phase A — 进程检查 | 容器状态 + `ps aux` + `ss -tlnp` + `curl /health` |
| §3 Phase B — 浏览器 DevTools | B-0~B-6 逐项截图/记录（或标注「降级使用 curl」） |
| §4 Phase C — 日志分析 | `docker logs` + `chat_logs/` 检查结果 |
| §5 Phase D — Token/Session | sessions 数量 + 有效性 + bind codes |
| §6 根因结论 | 一句话精准结论 + 假设#引用 |
| §7 修复建议 | 方案 + 代码/配置示例 + 预估行数 + 条件门判定 |

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-05 | 初稿 — F-9 诊断范围 + 假设树 + 诊断流程 + 3 类预案 |
