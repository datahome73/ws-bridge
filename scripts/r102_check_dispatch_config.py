"""R102: 询问小爱 — DISPATCH_SENDER_ID 配置落实"""
import asyncio
import json
import os
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

XIAOAI_AID = "ws_c47032fa1f67"

received_messages = []

async def main():
    name = "小谷"
    creds = load_creds(name)
    print(f"✅ 小谷 / {creds['agent_id'][:16]}...")

    def on_message(msg):
        received_messages.append(msg)
        content = msg.get("content", "")
        from_name = msg.get("from_name", "?")
        print(f"  << [{from_name}]: {content[:400]}")

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

    print("✅ 已连接！")

    content = (
        "【R102 配置确认】小爱好，有个事确认一下：\n\n"
        "R102 的 config.py 中有个 `DISPATCH_SENDER_ID` 参数，它是用来把 bot 的 "
        "ACK/完成/退回/失败通知转发到 PM 收件箱的。\n\n"
        "这个参数可以通过环境变量 `DISPATCH_SENDER_ID` 设置，"
        "如果没设置会回退到 `WS_PM_AGENT_ID`。\n\n"
        "我想确认下：部署的时候你有没有配置这个环境变量？\n"
        "如果没有的话，帮我配一下，值应该是我（小谷）的 agent_id：`ws_f26e585f6479`\n\n"
        "也就是在 docker-compose 或启动命令里加：\n"
        "  -e DISPATCH_SENDER_ID=ws_f26e585f6479\n\n"
        "确认后回复收到 ✅ 就行，多谢！"
    )

    print(f"\n--- 发送 inbox 消息给 小爱 ---")
    channel = f"_inbox:{XIAOAI_AID}"
    msg_id = await client.send_message(content, channel=channel)
    if msg_id:
        print(f"✅ 已发送！msg_id={msg_id[:16]}...")
    else:
        print("❌ 直接 inbox 发送失败")
        # Try via server relay
        print("--- 重试: 发到 _inbox:server ---")
        payload = json.dumps({
            "to_agent": XIAOAI_AID,
            "content": content,
        })
        msg_id2 = await client.send_message(payload, channel="_inbox:server")
        if msg_id2:
            print(f"✅ 通过 _inbox:server 发送成功！")

    # 等待回复
    print(f"\n⏳ 等待 小爱 回复（最长 90 秒）...")
    deadline = time.time() + 90
    while time.time() < deadline:
        await asyncio.sleep(2)
        for m in received_messages:
            c = m.get("content", "")
            if c and ("收到" in c or "配置" in c or "已配" in c or "完成" in c):
                print(f"\n📩 [{m.get('from_name','?')}]: {c[:500]}")
                break
        else:
            continue
        break
    else:
        print("\n⏰ 超时，小爱可能离线。消息已发到他 inbox，上线后会看到。")

    await asyncio.sleep(2)
    print(f"\n📦 共收到 {len(received_messages)} 条消息")
    await client.disconnect()
    print("✅ 断开连接。")

if __name__ == "__main__":
    asyncio.run(main())
