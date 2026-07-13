"""R102 派活：指导小开修 ACK 前缀"""
import asyncio, json, uuid, time
import sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
import importlib.util
spec = importlib.util.spec_from_file_location('ws_client', '/opt/data/ws-bridge/clients/python/ws_client.py')
ws_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_client)
load_creds = ws_client.load_creds
import websockets

TARGET_AID = "ws_3f7cdd736c1c"

async def main():
    creds = load_creds('小谷')
    ws = await websockets.connect("wss://wsim.datahome73.cloud/ws", max_size=2**20)
    await ws.send(json.dumps({"type": "auth", "api_key": creds["api_key"], "agent_id": creds["agent_id"]}))
    auth_resp = await ws.recv()
    print(f"✅ 已连接")

    content = (
        "小开，你的 ACK 前缀配反了。\n\n"
        "你现在回的是「✅ 收到」，R102 协议要求「收到 ✅」（中文在前，对勾在后）。\n"
        "请把你的 gateway-plugin 配置中回复前缀改为「收到 ✅」，重启后测试。\n\n"
        "改好后回复 已完成 ✅"
    )
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
    print(f"📨 已派活（指导小开改 ACK 前缀）")

    # 简单等一会看回复
    received = []
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            msg = json.loads(raw)
            if msg.get("type") == "broadcast":
                received.append(msg)
                print(f"  << [{msg.get('from_name','?')}]: {msg.get('content','')[:150]}")
        except asyncio.TimeoutError:
            continue
        except Exception:
            break

    await ws.close()

asyncio.run(main())
