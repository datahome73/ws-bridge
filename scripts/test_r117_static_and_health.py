#!/usr/bin/env python3
"""
R117 静态验证 + WebSocket 回路测试。
覆盖：_resolve_card_key_to_ws_id 三策略、sent=0 日志、advance logging、##start fallback
"""
import ast, sys, json, asyncio, websockets, os, time
from pathlib import Path

REPO = Path("/opt/data/ws-bridge")
MAIN = REPO / "server/ws_server/main.py"
LINES = MAIN.read_text().split("\n")
PASS, FAIL = 0, 0

def section(s):
    print(f"\n{'─'*50}\n  {s}\n{'─'*50}")

def check(ok, msg, detail=""):
    global PASS, FAIL
    m = "✅" if ok else "❌"
    print(f"  {m} {msg}")
    if not ok and detail:
        for d in detail.split("\n"):
            print(f"     {d}")
    if ok: PASS += 1
    else: FAIL += 1

# ── 1. 函数定义 ──
section("1. 新增函数定义")
check(any('def _resolve_card_key_to_ws_id' in l for l in LINES),
      "_resolve_card_key_to_ws_id() 已定义")
check(any('sent == 0' in l for l in LINES),
      "_send_to_agent sent=0 警告日志")
check(any('[R117]' in l and '尝试自动派活 Step' in l for l in LINES),
      "_try_advance_pipeline 推进日志")
check(any('##start fallback:' in l for l in LINES),
      "##start fallback 日志")

# ── 2. _resolve_card_key_to_ws_id 函数完整性 ──
section("2. _resolve_card_key_to_ws_id 实现")
fn_start = fn_end = None
for i, l in enumerate(LINES):
    if 'def _resolve_card_key_to_ws_id' in l:
        fn_start = i
    elif fn_start and i > fn_start and l.startswith("def ") and not l.strip().startswith("#"):
        fn_end = i
        break
if fn_start:
    body = "\n".join(LINES[fn_start:fn_end or len(LINES)])
    check('_build_name_to_ws_map()' in body, "策略1: display_name → api_keys")
    check('state._r72_users' in body, "策略2: display_name → _r72_users")
    check('_connections' in body, "策略3: _connections + _r72_users 交叉匹配")
    check('return ""' in body, "全失败返回空字符串")
    check('get_agent_card(card_key)' in body, "通过 agent_card 查询 display_name")

# ── 3. 模块依赖 ──
section("3. 模块依赖")
all_text = "\n".join(LINES)
check('ac_mod' in all_text or 'agent_card' in all_text, "可访问 agent_card 模块")
check('persistence' in all_text, "使用 persistence.get_api_keys()")
check('state._r72_users' in all_text, "可访问 state._r72_users")
check('_connections' in all_text, "可访问 _connections")

# ── 4. WebSocket 回路测试 ──
section("4. WebSocket 回路测试")

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
creds = json.loads(open(CRED_PATH).read())
AID = creds["agent_id"]

async def ws_test():
    ws = await websockets.connect("wss://wsim.datahome73.cloud/ws",
                                  max_size=2**20, ping_interval=30, ping_timeout=15)
    await ws.send(json.dumps({"type": "auth", "api_key": creds["api_key"]}))
    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
    dn = resp.get("display_name", "?")
    check(bool(dn), f"认证成功 — {dn}")

    ##help
    await ws.send(json.dumps({
        "type": "message", "channel": "_inbox:server",
        "content": "##help", "from_name": "小谷",
        "agent_id": AID, "ts": time.time(),
    }))
    ok = False
    for _ in range(15):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            r = json.loads(raw)
            ct = str(r.get("content", ""))
            if "##start" in ct:
                ok = True
                break
        except asyncio.TimeoutError:
            break
        except Exception:
            break
    check(ok, "##help 返回命令列表")

    await ws.close()

asyncio.run(ws_test())

# ── 5. 汇总 ──
section("📊 汇总")
print(f"  PASS: {PASS} ✅")
print(f"  FAIL: {FAIL} ❌")
print(f"  TOTAL: {PASS+FAIL}")
if FAIL:
    print("\n  ❌ 存在失败项")
    sys.exit(1)
else:
    print("\n  🎉 全部通过!")
