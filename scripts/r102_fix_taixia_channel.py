"""R102 派活：让泰虾修改回复通道为 _inbox:server"""
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
                print(f"  [{t_str}] {fn} ({ch[:40]}): {c[:200]}")
            except Exception:
                break

    asyncio.create_task(reader())

    content = (
        "【R102 配置修正 🛠️】\n\n"
        "泰虾你好！刚才的全流程测试发现一个问题：\n"
        "你的回复发到了 _system 通道（广播），这是不安全的。\n\n"
        "请修改你的配置，让所有回复发送到 _inbox:server 通道。\n"
        "这是 R102 的中继通道，服务端会根据前缀（收到 ✅ / 已完成 ✅ 等）\n"
        "自动把通知转发给小谷（PM），不会广播给其他人。\n\n"
        "操作步骤：\n"
        "1️⃣ 回复 收到 ✅\n"
        "2️⃣ 找到你代码/配置中回复通道设为 _system 的地方，改为 _inbox:server\n"
        "3️⃣ 回复 已完成 ✅ 确认\n\n"
        "谢谢！"
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

    print(f"\n═══ ② 等待回复（最长 120 秒）═══")
    done_ok = False
    deadline = time.time() + 120
    while time.time() < deadline:
        await asyncio.sleep(1)
        for m in received:
            c = m.get("content", "").strip()
            if "已完成" in c:
                done_ok = True
        if done_ok:
            break

    print(f"\n═══ ③ 结果 ═══")
    if done_ok:
        print(f"   🎉 泰虾已确认修改！")
    else:
        print(f"   ⏳ 超时，消息已送达")

    await ws.close()

if __name__ == "__main__":
    asyncio.run(main())
