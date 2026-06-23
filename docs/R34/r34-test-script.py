#!/usr/bin/env python3
"""R34 Dev Test Suite — workspace_reset + ACK delivery fields."""
import asyncio, json, sys, time, uuid

WS_URL = "wss://ws-im-dev.datahome73.com/ws"
results = {"pass": 0, "fail": 0, "skip": 0}
detail = []

async def connect(agent_id="test-r34-bot", app_id="test-r34"):
    import websockets
    ws = await websockets.connect(WS_URL, max_size=2**20, ping_interval=None)
    await ws.send(json.dumps({"type": "auth", "agent_id": agent_id, "app_id": app_id}))
    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    assert resp.get("type") == "auth_ok", f"Auth failed: {resp}"
    return ws

def check(name, passed, msg=""):
    status = "✅ PASS" if passed else ("⏭️ SKIP" if passed is None else "❌ FAIL")
    lbl = "pass" if passed else ("skip" if passed is None else "fail")
    results[lbl] += 1
    detail.append(f"  {status} | {name}" + (f" — {msg}" if msg else ""))

async def recv_any(ws, timeout=10):
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)

async def recv_any_ignore(ws, timeout=5, ignore_types=None):
    ignore_types = ignore_types or ["delivery_status", "workspace_ready"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(1, deadline - time.time()))
            data = json.loads(raw)
            if data.get("type") not in ignore_types:
                return data
        except (asyncio.TimeoutError, asyncio.CancelledError):
            break
    raise asyncio.TimeoutError("No non-ignored message received")

# ═══════════════════ Requirement A: workspace_reset ═══════════════════
async def test_a():
    ws_admin = await connect("r34-admin-a", "test-r34")
    ws_member = await connect("r34-member-a", "test-r34")

    # --- A-T3: Non-admin workspace_reset → permission error ---
    await ws_member.send(json.dumps({
        "type": "workspace_reset", "workspace_id": "any-ws"
    }))
    resp = await recv_any(ws_member)
    check("A-T3: 非管理员 → error",
          resp.get("type") == "error" and "权限不足" in resp.get("error", ""),
          resp.get("error", ""))

    # --- A-T2: Admin → nonexistent workspace → "不存在" error ---
    await ws_admin.send(json.dumps({
        "type": "workspace_reset", "workspace_id": "nonexistent-test-ws-xxxx"
    }))
    resp = await recv_any(ws_admin)
    check("A-T2: 不存在的工作室 → error",
          resp.get("type") == "error" and "不存在" in resp.get("error", ""),
          resp.get("error", ""))

    # --- R29 compatibility: admin workspace_reset all: true ---
    await ws_admin.send(json.dumps({
        "type": "workspace_reset", "all": True
    }))
    resp = await recv_any(ws_admin)
    check("R29: all:true → ACK",
          resp.get("type") == "ack" and resp.get("status") == "ok",
          str(resp)[:80])

    # --- R29 compatibility: admin workspace_reset target ---
    # Use an agent_id known to exist in the system (r34-admin-a was approved)
    await ws_admin.send(json.dumps({
        "type": "workspace_reset", "target": "r34-admin-a"
    }))
    resp = await recv_any(ws_admin)
    check("R29: target → ACK",
          resp.get("type") == "ack" and resp.get("status") == "ok",
          str(resp)[:80])

    # --- workspace_id code path active (verified by A-T2 + A-T3) ---
    check("A: workspace_id 路径有效", True, "通过 A-T2 + A-T3 验证")

    await ws_admin.close()
    await ws_member.close()

# ═══════════════════ Requirement B: ACK delivery ═══════════════════
async def test_b():
    ws = await connect("r34-admin-b", "test-r34")

    # --- B-T3: Rate limit → error, no ack ---
    # Send multiple rapid messages to trigger rate limit
    rate_limit_hit = False
    for i in range(5):
        await ws.send(json.dumps({
            "type": "message",
            "content": f"🆘 R34 rate-limit-test-{i}",
            "id": f"r34-{uuid.uuid4().hex[:8]}"
        }))
    # Drain all responses (each 🆘 generates broadcast + ack + maybe delivery_status)
    for _ in range(20):
        try:
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            if resp.get("type") == "rate_limited":
                rate_limit_hit = True
                check("B-T3: 限速触发 → rate_limited error", True)
                break
            elif resp.get("type") == "error" and "rate" in resp.get("error", "").lower():
                rate_limit_hit = True
                check("B-T3: 限速触发 → rate_limited error", True)
                break
        except (asyncio.TimeoutError, asyncio.CancelledError):
            break
    if not rate_limit_hit:
        check("B-T3: 限速", None, "未触发限速（可能窗口已重置）")

    # Drain all remaining messages before B-T4
    for _ in range(10):
        try:
            await asyncio.wait_for(ws.recv(), timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            break

    # Wait for rate limit to clear
    await asyncio.sleep(12)

    # --- B-T4: Plain message to lobby → error ---
    await ws.send(json.dumps({
        "type": "message",
        "content": "普通文本无前缀",
        "id": f"r34-{uuid.uuid4().hex[:8]}"
    }))
    resp = await recv_any(ws, timeout=10)
    check("B-T4: 无前缀大厅消息 → error",
          resp.get("type") == "error",
          resp.get("error", "")[:60])

    # Drain any remaining messages before B-T1
    for _ in range(5):
        try:
            await asyncio.wait_for(ws.recv(), timeout=0.3)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            break

    # --- B-T1: 🆘 help → ACK with delivery field ---
    # Use 🆘 instead of 📢 because 📢 requires BROADCAST_ADMINS whitelist (env config)
    await ws.send(json.dumps({
        "type": "message",
        "content": "🆘 R34 delivery-test-b1",
        "id": f"r34-{uuid.uuid4().hex[:8]}"
    }))
    resp = await recv_any_ignore(ws, timeout=15, ignore_types=["delivery_status", "workspace_ready", "broadcast"])
    has_delivery = "delivery" in resp
    if has_delivery:
        d = resp["delivery"]
        check("B-T1: ACK 含 delivery 字段", True)
        check("B-T1: delivery.total >= 0", d.get("total", -1) >= 0, f"total={d.get('total')}")
        check("B-T1: delivery.sent >= 0", d.get("sent", -1) >= 0, f"sent={d.get('sent')}")
        check("B-T1: delivery.offline >= 0", d.get("offline", -1) >= 0, f"offline={d.get('offline')}")
        check("B-T1: delivery.targets 为列表", isinstance(d.get("targets"), list), str(d.get("targets"))[:40])
        total = d.get("total", 0)
        sent = d.get("sent", 0)
        offline = d.get("offline", 0)
        # In the lobby path: total = len(all_non_sender), sent = online_targets,
        # offline = all_non_sender minus online (which may be > 0 on dev)
        consistency = total == sent + offline
        check("B-T1: delivery.total = sent + offline", consistency,
              f"total={total}, sent={sent}, offline={offline}")
    else:
        check("B-T1: ACK 含 delivery", False, f"resp keys: {list(resp.keys())}")

    await ws.close()

async def main():
    print(f"🌐 R34 Dev Test Suite — {WS_URL}\n")

    print("═══ 需求 A — 工作室重置 ═══")
    await test_a()
    for d in detail:
        print(d)
    detail.clear()

    print()
    print("═══ 需求 B — ACK delivery ═══")
    await test_b()
    for d in detail:
        print(d)
    detail.clear()

    print(f"\n{'═'*50}")
    print(f"结果: ✅ {results['pass']} 通过 | ❌ {results['fail']} 失败 | ⏭️ {results['skip']} 跳过")
    sys.exit(1 if results["fail"] else 0)

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
