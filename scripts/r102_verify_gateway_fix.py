"""R102 验证：泰虾回复是否已走 _inbox:server"""
import asyncio, json, sys, time, uuid

sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
import importlib.util
spec = importlib.util.spec_from_file_location(
    "ws_client", "/opt/data/ws-bridge/clients/python/ws_client.py"
)
ws_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_client)
load_creds = ws_client.load_creds

TAIXIA_AID = "ws_eab784ac7652"
received = []

async def main():
    creds = load_creds("小谷")
    agent_id, api_key = creds["agent_id"], creds["api_key"]
    import websockets
    ws = await websockets.connect("wss://wsim.datahome73.cloud/ws", max_size=2**20)
    await ws.send(json.dumps({"type": "auth", "api_key": api_key, "agent_id": agent_id}))
    await ws.recv()
    print("✅ 已连接")

    async def reader():
        while True:
            try:
                raw = await ws.recv()
                msg = json.loads(raw)
                received.append(msg)
                fn = msg.get("from_name", "?")
                c = msg.get("content", "").strip()
                ch = msg.get("channel", "")
                ts = msg.get("ts", 0)
                print(f"  [{time.strftime('%H:%M:%S',time.localtime(ts))}] {fn} ch={ch}")
                print(f"    内容: {c[:200]}")
                # 验证：如果收到的系统通知里含 channel 信息
                if ch == "_system":
                    print(f"    ❌ 仍在走 _system！")
                elif ch.startswith("_inbox:ws_f26e585f6479"):
                    print(f"    ✅ 经过 R102 中继转发，通道正确")
            except:
                break
    asyncio.create_task(reader())

    content = "【R102 通道验证 ✅】泰虾，请回复 收到 ✅ 确认网关插件已生效。"

    payload = {
        "type": "message", "content": content,
        "channel": "_inbox:server", "to_agent": TAIXIA_AID,
        "from_name": "小谷", "agent_id": agent_id,
        "id": str(uuid.uuid4()), "ts": time.time(),
    }
    print(f"\n═══ 发送验证消息 ═══")
    await ws.send(json.dumps(payload))
    print("   ✅ 已发送")

    print(f"\n═══ 等待回复（最长 30 秒）═══")
    deadline = time.time() + 30
    while time.time() < deadline:
        await asyncio.sleep(1)

    print(f"\n═══ 结果 ═══")
    if not received:
        print("   ❌ 未收到任何消息")
    else:
        for m in received:
            ch = m.get("channel", "")
            if ch == "_system":
                print("   ❌ 泰虾回复仍在走 _system！网关插件未生效")
            else:
                print(f"   ✅ 通道正确 (ch={ch})")
    await ws.close()

asyncio.run(main())
