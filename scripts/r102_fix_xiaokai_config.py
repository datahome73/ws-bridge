"""直连透传：指导小开修配置"""
import asyncio
import json
import sys
import time

sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
import importlib.util
spec = importlib.util.spec_from_file_location(
    "ws_client",
    "/opt/data/ws-bridge/clients/python/ws_client.py"
)
ws_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_client)

WsBridgeClient = ws_client.WsBridgeClient
load_creds = ws_client.load_creds

XIAOKAI_AID = "ws_3f7cdd736c1c"
received_messages = []

async def main():
    name = "小谷"
    creds = load_creds(name)
    print(f"✅ 小谷 / {creds['agent_id'][:16]}...\n")

    def on_message(msg):
        received_messages.append(msg)
        from_name = msg.get("from_name", "?")
        content = msg.get("content", "").strip()
        channel = msg.get("channel", "")
        ts = msg.get("ts", 0)
        t_str = time.strftime("%H:%M:%S", time.localtime(ts))
        print(f"  [{t_str}] {from_name} ({channel[:50]}): {content[:200]}")

    client = WsBridgeClient(
        name=name,
        api_key=creds["api_key"],
        agent_id=creds["agent_id"],
        auto_reconnect=False,
        on_message=on_message,
    )

    connected = await client.connect()
    if not connected:
        print("❌ 连接失败")
        return
    print("✅ 已连接！\n")

    content = (
        "小开，你的 bot 配置有问题。\n"
        "你总是在忽略所有派活消息，回复「与本角色无关」。"
        "这说明你的 mention_mode / role 过滤把正常任务也过滤掉了。\n\n"
        "请检查你的 gateway-plugin 配置（比如 config.yaml 中的 mention_mode 和 mention_keyword），"
        "临时关掉角色过滤，或者把「收到 ✅」「已完成 ✅」「小开」加到 mention_keyword 里。\n\n"
        "改完配置重启后，回复 已完成 ✅"
    )

    # 直接发到他的 inbox（不走 R102 中继）
    print("═══ 直连透传给小开 ═══")
    await client.send_message(content, channel=f"_inbox:{XIAOKAI_AID}")
    print("📨 已发送，等回复...\n")

    deadline = time.time() + 60
    while time.time() < deadline:
        await asyncio.sleep(2)
        for m in received_messages:
            c = m.get("content", "")
            fn = m.get("from_name", "")
            ch = m.get("channel", "")
            if "已完成 ✅" in c:
                print(f"✅ 小开确认完成")
                break
    else:
        print("⏰ 超时")

    await client.disconnect()

asyncio.run(main())
