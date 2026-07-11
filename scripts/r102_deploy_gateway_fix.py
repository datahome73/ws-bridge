"""R102 派活：泰虾更新 gateway-plugin + 重启"""
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
                print(f"  [{time.strftime('%H:%M:%S',time.localtime(ts))}] {fn} ch={ch} {c[:200]}")
            except:
                break
    asyncio.create_task(reader())

    content = (
        "【R102 gateway-plugin 更新 🛠️】\n\n"
        "泰虾你好！你的回复一直发到 _system 通道，需要修复。\n\n"
        "原因：gateway-plugin/__init__.py 中 _determine_channel 函数\n"
        "只匹配了 ACK ✅ 和 ✅ 完成，没有匹配 收到 ✅ / 已完成 ✅。\n"
        "现已修复并推送到 ws-bridge 仓库 origin/main（commit dab58ed）。\n\n"
        "请按以下步骤操作：\n"
        "1️⃣ 回复 收到 ✅\n"
        "2️⃣ 更新你那边使用的 gateway-plugin/__init__.py\n"
        "   可以从 ws-bridge 仓库拉最新代码，或手动修改：\n"
        "   找到 _determine_channel 函数，在 ACK ✅ 后面加上\n"
        "   收到 ✅ / 已完成 ✅ / 退回 🔄 / 失败 ❌ 的判断\n"
        "3️⃣ 重启你的 bot 进程\n"
        "4️⃣ 回复 已完成 ✅ 确认\n\n"
        "改完后你的回复 channel 会自动变成 _inbox:server！"
    )

    payload = {
        "type": "message", "content": content,
        "channel": "_inbox:server", "to_agent": TAIXIA_AID,
        "from_name": "小谷", "agent_id": agent_id,
        "id": str(uuid.uuid4()), "ts": time.time(),
    }
    print(f"\n═══ 派活 → 泰虾 ═══")
    await ws.send(json.dumps(payload))
    print("   ✅ 已发送")

    print(f"\n═══ 等待完成（最长 120 秒）═══")
    deadline = time.time() + 120
    while time.time() < deadline:
        await asyncio.sleep(1)
        for m in received:
            if "已完成" in m.get("content", ""):
                print(f"\n   ✅ 泰虾已确认！")
                await ws.close()
                return
    print(f"\n   ⏳ 超时")
    await ws.close()

asyncio.run(main())
