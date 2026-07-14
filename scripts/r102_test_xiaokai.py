"""R102 全流程测试：派活 → 小开 → 收到 ✅ → 完成 ✅"""
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

TARGET_AID = "ws_3f7cdd736c1c"
TARGET_NAME = "小开"

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

    # ═══ 1. 派活 ═══
    content = (
        f"【R102 全流程测试 🧪 — {TARGET_NAME}】\n\n"
        f"{TARGET_NAME}你好！请按以下步骤执行：\n\n"
        "1️⃣ 回复 收到 ✅ 确认接活\n"
        "2️⃣ 执行一条系统命令： ls -la /app/ 或者 uname -a 都可以\n"
        "3️⃣ 回复 已完成 ✅ 并附上命令输出\n\n"
        "这是 R102 全流程测试，验证派活 → ACK → 完成 链路是否正常。\n"
        "完成后我会自动确认。"
    )

    print("═══ 1. 派活 ═══")
    msg_id = await client.send_message(
        content,
        channel="_inbox:server",
        to_agent=TARGET_AID,
    )
    print(f"   ✅ 已派活 (msg_id={msg_id})\n")

    # ═══ 2. 等待系统转发（收到 ✅/已完成 ✅ 的中继通知）═══
    print("═══ 2. 等待回复（最多 90 秒）═══")
    got_ack = False
    got_done = False
    deadline = time.time() + 90
    while time.time() < deadline:
        await asyncio.sleep(1)
        for m in received_messages:
            c = m.get("content", "")
            ch = m.get("channel", "")
            fn = m.get("from_name", "")
            if "已接活" in c and "收到 ✅" in c:
                got_ack = True
                print(f"   ✅ {TARGET_NAME} 已确认接活（channel={ch}）\n")
                break
        if got_ack:
            break
    if not got_ack:
        print("   ⚠️ 30秒内未收到 ACK，继续等待...\n")

    while time.time() < deadline:
        await asyncio.sleep(1)
        for m in received_messages:
            c = m.get("content", "")
            ch = m.get("channel", "")
            fn = m.get("from_name", "")
            if "任务完成" in c and "已完成 ✅" in c:
                got_done = True
                print(f"   ✅ {TARGET_NAME} 任务完成（channel={ch}）\n")
                break
        if got_done:
            break

    # ═══ 3. 结果 ═══
    print("═══ 3. 结果 ═══")
    if got_ack and got_done:
        print("   🎉 R102 全流程测试通过！")
        print("   派活 → 收到 ✅ → 已完成 ✅ 链路正常")
        print("   所有消息走 _inbox:server 中继，无 _system 广播")
    elif got_ack and not got_done:
        print("   ⚠️ 收到 ACK 但未收到完成")
    else:
        print("   ❌ 未收到任何回复")

    # ═══ 4. 通道安全检查 ═══
    print("\n═══ 4. 通道安全检查 ═══")
    bad_channels = [m for m in received_messages if m.get("channel") == "_system"]
    if bad_channels:
        print(f"   ❌ 发现 {len(bad_channels)} 条消息走了 _system:")
        for m in bad_channels:
            print(f"      [{m.get('from_name','?')}]: {m.get('content','')[:80]}")
    else:
        print("   ✅ 所有消息均未走 _system")

    print(f"\n总共收到 {len(received_messages)} 条消息")
    await client.disconnect()

asyncio.run(main())
