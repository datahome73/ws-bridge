"""R102 全流程 — 小开，server中转，只发一条"""
import asyncio, json, sys, uuid, time
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
import importlib.util
spec = importlib.util.spec_from_file_location('ws_client', '/opt/data/ws-bridge/clients/python/ws_client.py')
ws_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_client)
load_creds = ws_client.load_creds
import websockets

TARGET_AID = "ws_3f7cdd736c1c"
received = []

async def main():
    creds = load_creds('小谷')
    ws = await websockets.connect("wss://wsim.datahome73.cloud/ws", max_size=2**20)
    await ws.send(json.dumps({"type": "auth", "api_key": creds["api_key"], "agent_id": creds["agent_id"]}))
    auth_resp = await ws.recv()
    print(f"✅ 已连接 (auth: {auth_resp[:60]})")

    async def reader():
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                msg = json.loads(raw)
                if msg.get("type") in ("broadcast", "message", "ack"):
                    received.append(msg)
                    ch = msg.get('channel','')[:40]
                    print(f"  [{msg.get('from_name','?')}] ({ch}): {msg.get('content','')[:120]}")
            except asyncio.TimeoutError:
                return
            except Exception:
                return

    # ═══ 派活：_inbox:server + to_agent，只发一条 ═══
    content = "小开，执行一条系统命令(如 uname -a)，回复 收到 ✅ 确认接活，执行完后回复 已完成 ✅"
    payload = {
        "type": "message",
        "content": content,
        "channel": "_inbox:server",
        "to_agent": TARGET_AID,
        "from_name": "小谷",
        "agent_id": creds["agent_id"],
        "id": str(uuid.uuid4()),
        "ts": time.time(),
    }
    await ws.send(json.dumps(payload))
    print(f"\n📨 已派活（_inbox:server → to_agent，1条）\n")

    # ═══ 等待回复 ═══
    print("═══ 等待回复 ═══")
    got_ack = got_done = False
    deadline = time.time() + 60
    while time.time() < deadline:
        await reader()
        for m in received:
            c = m.get("content","")
            if "已接活" in c and "收到 ✅" in c:
                got_ack = True
                print("   ✅ 小开确认接活")
            if "任务完成" in c and "已完成 ✅" in c:
                got_done = True
                print("   ✅ 小开任务完成")
        if got_ack and got_done:
            break

    print(f"\n═══ 结果 ═══")
    if got_ack and got_done:
        print("   🎉 全流程通过！")
    elif got_ack:
        print("   ⚠️ 只收到 ACK")
    else:
        print("   ❌ 未回复")

    bad = [m for m in received if m.get("channel") == "_system"]
    print(f"\n通道检查: {'❌ 有 _system' if bad else '✅ 无 _system'}")
    print(f"共 {len(received)} 条")
    await ws.close()

asyncio.run(main())
