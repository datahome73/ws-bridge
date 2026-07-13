#!/usr/bin/env python3
"""R109 验收测试 v2 — 源码级分析
架构大重构 server/ → ws_server/ + web_ui/ + common/ 拆分

运行: python3 docs/R109/test_r109_acceptance.py
"""
import os

PROJECT = "/opt/data/ws-bridge"
PASS, FAIL, WARN = "✅", "❌", "⚠️"
results = []
n = 0


def C(name, ok, detail=""):
    global n
    n += 1
    results.append((PASS if ok else FAIL, name, detail))
    return ok


def read(path):
    try:
        with open(os.path.join(PROJECT, path)) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def grep(text, pattern):
    return [(i, l) for i, l in enumerate(text.split("\n"), 1) if pattern in l]


# ══════════════════════════════════════════════════════════════
# A — 代码结构 & 隔离
# ══════════════════════════════════════════════════════════════
print("=" * 60)
print("A — 代码结构 & 隔离验证")
print("=" * 60)

C("A1a: server/ws_server/ 存在", os.path.isdir(f"{PROJECT}/server/ws_server"))
C("A1b: server/web_ui/ 存在", os.path.isdir(f"{PROJECT}/server/web_ui"))
C("A1c: server/common/ 存在", os.path.isdir(f"{PROJECT}/server/common"))

for f in ["server/web_service.py", "server/web_viewer.py",
          "server/config.py", "server/templates.py.bak",
          "entrypoint.py"]:
    C(f"A2: {f} 已删除", not os.path.exists(f"{PROJECT}/{f}"))

# A3: web_ui 零 ws_server import
web_dir = f"{PROJECT}/server/web_ui"
web_bad = []
for root, dirs, files in os.walk(web_dir):
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)
        rel = os.path.relpath(path, PROJECT)
        with open(path) as fh:
            for lineno, line in enumerate(fh, 1):
                s = line.strip()
                if s.startswith("#"):
                    continue
                # server.ws_server.* imports are NOT allowed in web_ui
                if "ws_server" in s and "import" in s and "server.ws_server" in s:
                    web_bad.append(f"  {rel}:L{lineno} {s}")
C("A3: web_ui 零 ws_server import", len(web_bad) == 0,
  "\n" + "\n".join(web_bad) if web_bad else "clean ✓")

# A4: ws_server 无 web 相关关键词
ws_main = read("server/ws_server/main.py")
for kw in ["BIND_TEMPLATE", "CHAT_TEMPLATE", "handle_github_login",
           "handle_github_callback", "GitHub OAuth"]:
    m = grep(ws_main, kw)
    C(f"A4: ws_server 无 '{kw}'", len(m) == 0,
      f"L{[x[0] for x in m]}" if m else "clean ✓")

# A5: common/auth.py 函数清单
auth = read("server/common/auth.py")
C("A5a: common/auth.py 存在", bool(auth), f"{len(auth)} chars")
for fn in ["get_users", "get_level", "set_level", "get_agent_name",
           "generate_agent_id", "create_api_key", "validate_api_key",
           "revoke_api_key", "is_workspace_admin", "is_global_admin"]:
    ok = f"def {fn}" in auth or f"async def {fn}" in auth
    C(f"A5: auth 有 {fn}()", ok, "MISSING" if not ok else "found ✓")

# A6: viewer.py 不含 WSS 认证函数定义
viewer = read("server/web_ui/viewer.py")
for fn in ["create_api_key", "validate_api_key", "revoke_api_key", "set_level"]:
    m = grep(viewer, f"def {fn}")
    C(f"A6: viewer.py 无 {fn}", len(m) == 0,
      f"L{[x[0] for x in m]}" if m else "clean ✓")

# A7: 全部语法正确
errors = 0
count = 0
for root, dirs, files in os.walk(PROJECT):
    if ".git" in root or "__pycache__" in root or ".venv" in root:
        continue
    for f in files:
        if not f.endswith(".py"):
            continue
        count += 1
        path = os.path.join(root, f)
        try:
            with open(path) as fh:
                compile(fh.read(), path, "exec")
        except SyntaxError as e:
            C(f"A7: {os.path.relpath(path, PROJECT)}", False, str(e))
            errors += 1
if errors == 0:
    C("A7: 全部语法正确", True, f"({count} files ✓)")


# ══════════════════════════════════════════════════════════════
# B — Config 验证
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("B — Config 验证")
print("=" * 60)

config = read("server/common/config.py")
C("B0: common/config.py 存在", bool(config), f"{len(config)} lines")

# 保留项
for item in ["WS_HOST", "WS_PORT", "WS_DATA_DIR", "DATA_DIR",
             "SERVER_INBOX_CHANNEL", "HIDDEN_AGENTS"]:
    C(f"B+: 保留 {item}", item in config)

# 需求要求删除，但仍被引用 → 记录为「清理遗漏」
# APP_ID: 需求说不再需要
# ADMIN_AGENTS: 需求说没有 admin_bot 了，但 __main__.py 引用
# DISPATCH_SENDER_ID: 需求说合并为 PM_AGENT_ID
items_should_remove = {
    "HTTP_PORT": "Web 配置应移到 web_ui/",
    "APP_ID": "需求: 不再需要",
    "ADMIN_AGENTS": "需求: 没有 admin_bot 了（但 __main__.py 仍引用）",
    "DISPATCH_SENDER_ID": "需求: 合并为 PM_AGENT_ID",
    "WS_ENV": "需求: Web 环境标识",
    "IS_PRODUCTION": "需求: Web 环境标识",
}
for item, reason in items_should_remove.items():
    still_there = item in config
    C(f"B-: {item}", not still_there,
      f"需删除 — {reason}" if still_there else "removed ✓")

# AUTO_DISPATCH_ENABLED 引用检查
ws_main_py = read("server/ws_server/__main__.py")
if "AUTO_DISPATCH_ENABLED" not in config:
    # main.py L2470: config.AUTO_DISPATCH_ENABLED — where does config come from?
    # ws_server/main.py: from server.common import auth, config, persistence
    # So config = server.common.config, which doesn't have AUTO_DISPATCH_ENABLED
    C("B: AUTO_DISPATCH_ENABLED 在 config 中", False,
      "RUNTIME BUG: ws_server/main.py L2470 引用 config.AUTO_DISPATCH_ENABLED\n"
      "           但 from server.common import config 无此属性 → AttributeError")
else:
    C("B: AUTO_DISPATCH_ENABLED 在 config 中", True)


# ══════════════════════════════════════════════════════════════
# C — 前端减法 (需求: 只剩收件箱+历史两个Tab)
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("C — 前端减法 (需求: 只剩收件箱+历史)")
print("=" * 60)

templates = read("server/web_ui/templates.py")

C("C1: BIND_TEMPLATE 已删除", "BIND_TEMPLATE" not in templates,
  "STILL PRESENT L4" if "BIND_TEMPLATE" in templates else "removed ✓")

# TAB_STATE 检查
admin_tabs = [l for l in templates.split("\n") if "🔧" in l]
C("C2: admin Tab (🔧) 已删除", len(admin_tabs) == 0,
  f"STILL PRESENT: {admin_tabs[0].strip()}" if admin_tabs else "removed ✓")

C("C3: wsListBtn 已删除", "wsListBtn" not in templates,
  "STILL PRESENT" if "wsListBtn" in templates else "removed ✓")

for handler in ["handle_api_bind", "handle_api_check", "handle_api_approve_web"]:
    m = grep(viewer, handler)
    C(f"C4: {handler} 已删除", len(m) == 0,
      f"STILL PRESENT L{[x[0] for x in m]}" if m else "removed ✓")
for route in ["/api/bind", "/api/check", "/api/approve_web"]:
    m = grep(viewer, route)
    C(f"C4: 路由 {route} 已删除", len(m) == 0,
      f"STILL REGISTERED L{[x[0] for x in m]}" if m else "removed ✓")


# ══════════════════════════════════════════════════════════════
# D — 数据层拆分
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("D — 数据层拆分")
print("=" * 60)

ws_ms = read("server/ws_server/message_store.py")
c_ms = read("server/common/message_store.py")
C("D1: ws_server/message_store.py 存在", bool(ws_ms), f"{len(ws_ms)} chars")
C("D1: common/message_store.py 存在", bool(c_ms), f"{len(c_ms)} chars")
for fn in ["save_message", "init_db", "get_messages_since",
           "get_messages_by_channel", "search_messages"]:
    ok = (f"def {fn}" in ws_ms or f"async def {fn}" in ws_ms)
    C(f"D1: ws_server ms 有 {fn}()", ok, "MISSING" if not ok else "found ✓")
for fn in ["get_messages_since", "get_messages_by_channel", "get_messages_by_channel_pattern",
           "search_messages"]:
    ok = (f"def {fn}" in c_ms or f"async def {fn}" in c_ms)
    C(f"D1: common ms 有 {fn}() (只读)", ok, "MISSING" if not ok else "found ✓")

c_persist = read("server/common/persistence.py")
C("D2: common/persistence.py 存在", bool(c_persist), f"{len(c_persist)} chars")
for fn in ["get_api_keys", "set_api_keys", "save_api_keys",
           "get_approved_users", "load_approved_users"]:
    ok = (f"def {fn}" in c_persist or f"async def {fn}" in c_persist)
    C(f"D2: persistence 有 {fn}()", ok, "MISSING" if not ok else "found ✓")


# ══════════════════════════════════════════════════════════════
# E — Bot 状态文件传递
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("E — Bot 状态文件传递 (需求: 非 HTTP 轮询)")
print("=" * 60)

# 需求: ws-server 每 10 秒写入 data/_bot_status.json → web-ui 读文件
# 但实际: web_ui/main.py 仍用 HTTP 轮询 ws-server /api/status

web_main = read("server/web_ui/main.py")

# E1: 文件写入 (ws_server 端)
# 检查是否有任何 bot 状态写入文件的操作
has_file_write = False
for kw in ["_bot_status.json", "bot_status.json"]:
    if kw in ws_main:
        # Ensure it's file write, not just a var name
        for line in ws_main.split("\n"):
            if kw in line and ("write" in line or "dump" in line or "Path" in line):
                has_file_write = True
                break
# Also check if there's a periodic write mechanism
has_periodic = False
for kw in ["asyncio.sleep", "while True", "on_startup"]:
    # We need both a periodic loop and bot_status write
    pass

C("E1: ws_server 写入 _bot_status.json 文件", has_file_write,
  "NOT IMPLEMENTED — 仍用 HTTP 轮询" if not has_file_write else "found ✓")

# E2: 文件读取 (web_ui 端) — 检查是否读文件而非 HTTP
has_file_read = False
for line in web_main.split("\n"):
    if "bot_status" in line.lower() and (".json" in line or "read_text" in line
                                          or "open(" in line or "Path(" in line):
        has_file_read = True
        break
# Also check: does it read from file OR still HTTP poll?
has_http_poll = "_fetch_bot_status" in web_main
if has_http_poll:
    C("E2: web_ui 读文件而非 HTTP 轮询", False,
      "仍用 _fetch_bot_status() HTTP 轮询 ws-server /api/status (每10秒)")
elif has_file_read:
    C("E2: web_ui 读文件而非 HTTP 轮询", True, "文件方式 ✓")
else:
    C("E2: web_ui 读文件而非 HTTP 轮询", False, "NOT IMPLEMENTED")


# ══════════════════════════════════════════════════════════════
# F — 管线消息入库
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("F — 管线消息入库 (save_message 补全)")
print("=" * 60)

# _auto_dispatch: 检查 payload 构造后、_send_to_agent 前是否有 save_message
auto_start = ws_main.find("async def _auto_dispatch")
if auto_start > 0:
    rest = ws_main[auto_start + 1:]
    next_def = rest.find("\nasync def")
    auto_body = rest[:next_def] if next_def > 0 else rest
    has_sm = "save_message" in auto_body
    C("F1: _auto_dispatch 内 save_message", has_sm,
      f"送前入库缺失" if not has_sm else "found ✓")
    # 如果缺失，检查 _send_to_agent 是否内部有 save_message
    if not has_sm:
        st_body = ""
        st_start = ws_main.find("async def _send_to_agent")
        if st_start > 0:
            rest2 = ws_main[st_start + 1:]
            next_def2 = rest2.find("\nasync def")
            st_body = rest2[:next_def2] if next_def2 > 0 else rest2
        C("F1: _send_to_agent 内 save_message", "save_message" in st_body,
          "链上也缺失" if "save_message" not in st_body else "在 _send_to_agent 内部 ✓")

# _handle_server_relay
relay_start = ws_main.find("async def _handle_server_relay")
if relay_start > 0:
    rest = ws_main[relay_start + 1:]
    next_def = rest.find("\nasync def")
    relay_body = rest[:next_def] if next_def > 0 else rest
    C("F2: _handle_server_relay 内 save_message", "save_message" in relay_body,
      "MISSING" if "save_message" not in relay_body else "found ✓")


# ══════════════════════════════════════════════════════════════
# G — Import 清单 (审计用)
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("G — Import 清单 (仅记录)")
print("=" * 60)

for root, dirs, files in os.walk(web_dir):
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)
        rel = os.path.relpath(path, PROJECT)
        with open(path) as fh:
            for line in fh:
                s = line.strip()
                if s.startswith(("import ", "from ")) and not s.startswith("#"):
                    print(f"  {rel}: {s}")

for root, dirs, files in os.walk(f"{PROJECT}/server/ws_server"):
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)
        rel = os.path.relpath(path, PROJECT)
        with open(path) as fh:
            for line in fh:
                s = line.strip()
                if s.startswith(("import ", "from server")) and not s.startswith("#"):
                    print(f"  {rel}: {s}")


# ══════════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("📊  汇总")
print("=" * 60)

p = sum(1 for r in results if r[0] == PASS)
f = sum(1 for r in results if r[0] == FAIL)
print(f"\n总计: {len(results)} 项 | {PASS} {p}/{len(results)} | {FAIL} {f}/{len(results)}")
print(f"\n── 失败项 ──")
for icon, name, detail in results:
    if icon == FAIL:
        print(f"  {name}")
        for d in detail.split("\n"):
            print(f"    {d}")

print(f"\n{'=' * 60}")
if f > 0:
    print(f"结果: {f} 项未通过 — 详见测试报告")
else:
    print(f"结果: ALL GREEN 🟢")
exit(f)
