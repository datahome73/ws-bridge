"""R102 全流程测试：派活 → 小爱写测试报告 → 完成"""
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

XIAOAI_AID = "ws_c47032fa1f67"

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
        print(f"  [{t_str}] {from_name} ({channel[:40]}): {content[:200]}")

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
        "【R102 全流程测试 🧪】\n\n"
        "小爱好！请按以下步骤执行：\n\n"
        "1️⃣ 回复 收到 ✅ 确认接活\n"
        "2️⃣ 在 docs/R102/ 目录下创建一份测试报告，文件名 R102-e2e-test-report.md\n"
        "   内容包含：\n"
        "   - 测试日期\n"
        "   - 测试环境\n"
        "   - 测试项：派活 → ACK → 完成 全链路\n"
        "   - 测试结果：PASS\n"
        "   - 测试人：小爱\n"
        "3️⃣ 回复 已完成 ✅ 确认完成\n\n"
        "这是一个真实的端到端测试任务，请实际创建文件并提交。谢谢！"
    )

    print("═══ ① 小谷 → 派活 → 小爱 ═══")
    msg_id = await client.send_message(
        content,
        channel="_inbox:server",
        to_agent=XIAOAI_AID,
    )
    if msg_id:
        print(f"   ✅ 已发送 msg_id={msg_id[:16]}")
    else:
        print("   ⚠️ 已发送（R102 无 ACK 属正常）\n")

    # ═══ 2. 等回复 ═══
    print("\n═══ ② 等待小爱回复（最长 120 秒）═══")
    ack_received = False
    complete_received = False
    deadline = time.time() + 120

    while time.time() < deadline:
        await asyncio.sleep(1)
        for m in received_messages:
            c = m.get("content", "").strip()
            fn = m.get("from_name", "")
            if "已接活" in c and not ack_received:
                ack_received = True
                print(f"\n   ✅ [{fn}] ACK 已收到！")
            if "已完成" in c and not complete_received:
                complete_received = True
                print(f"\n   ✅ [{fn}] 已完成 已收到！")

        if complete_received:
            break

    # ═══ 3. 总结 ═══
    print("\n═══ ③ 测试结果 ═══")
    if ack_received:
        print(f"   ✅ 派活 → ACK")
    else:
        print(f"   ❌ 派活 → ACK（未收到）")

    if complete_received:
        print(f"   ✅ ACK → 完成")
        print(f"\n   🎉 R102 全流程测试通过！")
    else:
        print(f"   ❌ ACK → 完成（超时，小爱可能还在干活）")

    print(f"\n📦 共收到 {len(received_messages)} 条消息")
    for m in received_messages:
        fn = m.get("from_name", "?")
        c = m.get("content", "").strip()
        ch = m.get("channel", "")
        ts = m.get("ts", 0)
        t_str = time.strftime("%H:%M:%S", time.localtime(ts))
        print(f"  [{t_str}] {fn} ({ch[:40]}): {c[:200]}")

    await client.disconnect()
    print("\n✅ 测试结束")

if __name__ == "__main__":
    asyncio.run(main())
