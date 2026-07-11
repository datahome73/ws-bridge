"""R102 再次派活：让泰虾真正修改回复通道代码"""
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
                print(f"  [{t_str}] {fn}  ch={ch}  {c[:200]}")
            except Exception:
                break

    asyncio.create_task(reader())

    content = (
        "【R102 通道修正 🔧】\n\n"
        "泰虾你好！刚才验证发现你的回复仍然走了 _system 通道（广播），\n"
        "说明配置记忆更新了但实际代码还没改。\n\n"
        "请找到你代码中发送回复的地方，例如：\n"
        '  send_message(content, channel="_system")\n'
        "把它改为：\n"
        '  send_message(content, channel="_inbox:server")\n\n'
        "改完之后：\n"
        "1️⃣ 回复 收到 ✅\n"
        "2️⃣ 实际修改代码\n"
        "3️⃣ 回复 已完成 ✅ 确认\n\n"
        "注意：改完后你的回复 channel 应该是 _inbox:server，不是 _system。"
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

    print(f"\n═══ ② 等待回复（最长 90 秒）═══")
    done_ok = False
    deadline = time.time() + 90
    while time.time() < deadline:
        await asyncio.sleep(1)
        for m in received:
            if "已完成" in m.get("content", ""):
                c = m.get("content", "")
                ch = m.get("channel", "")
                print(f"\n   📩 收到回复: channel={ch}")
                print(f"      内容: {c[:200]}")
                done_ok = True
        if done_ok:
            break

    print(f"\n═══ ③ 结果 ═══")
    if done_ok:
        print(f"   ✅ 泰虾已确认修改")
    else:
        print(f"   ⏳ 超时")

    await ws.close()

if __name__ == "__main__":
    asyncio.run(main())
