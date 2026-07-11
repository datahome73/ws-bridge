"""R102 验证：泰虾回复通道是否已改为 _inbox:server"""
import asyncio
import json
import sys
import time
import uuid

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
    agent_id = creds["agent_id"]
    api_key = creds["api_key"]
    print(f"✅ 小谷 / {agent_id[:16]}...")

    import websockets
    ws = await websockets.connect("wss://wsim.datahome73.cloud/ws", max_size=2**20)
    print("✅ WebSocket 已连接")

    auth_payload = json.dumps({"type": "auth", "api_key": api_key, "agent_id": agent_id})
    await ws.send(auth_payload)
    await ws.recv()
    print("✅ 认证成功")

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
                t_str = time.strftime("%H:%M:%S", time.localtime(ts))
                print(f"  [{t_str}] {fn}  channel={ch}  {c[:200]}")
            except Exception:
                break

    asyncio.create_task(reader())

    content = (
        "【R102 通道验证 🧪】\n\n"
        "泰虾你好！请回复 收到 ✅ 确认你的回复通道已改为 _inbox:server。\n"
        "注意：这条回复一定要通过 _inbox:server 发送，不要走 _system。"
    )

    msg_id = str(uuid.uuid4())
    payload = {
        "type": "message", "content": content,
        "channel": "_inbox:server", "to_agent": TAIXIA_AID,
        "from_name": "小谷", "agent_id": agent_id,
        "id": msg_id, "ts": time.time(),
    }

    print(f"\n═══ ① 派活 → 泰虾 ═══")
    await ws.send(json.dumps(payload))
    print(f"   ✅ 已发送")

    print(f"\n═══ ② 等待回复（最长 60 秒）═══")
    deadline = time.time() + 60
    while time.time() < deadline:
        await asyncio.sleep(1)

    print(f"\n═══ ③ 收到的消息 ═══")
    if received:
        for m in received:
            fn = m.get("from_name", "?")
            c = m.get("content", "").strip()
            ch = m.get("channel", "")
            ts = m.get("ts", 0)
            t_str = time.strftime("%H:%M:%S", time.localtime(ts))
            print(f"  [{t_str}] {fn}  channel={ch}")
            print(f"     内容: {c[:200]}")
            # 验证回复通道
            if ch == "_inbox:server":
                print(f"     ✅ 通道正确！")
            elif ch == "_system":
                print(f"     ❌ 仍在走 _system 广播！")
    else:
        print(f"   ❌ 未收到任何消息")

    await ws.close()
    print("✅ 测试结束")

if __name__ == "__main__":
    asyncio.run(main())
