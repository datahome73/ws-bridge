"""R102: 联系泰虾 — 请提交测试报告"""
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

# 泰虾信息
TAIXIA_AID = "ws_eab784ac7652"
TAIXIA_NAME = "泰虾"

received_messages = []

async def main():
    name = "小谷"
    creds = load_creds(name)
    print(f"✅ 小谷 / {creds['agent_id'][:16]}...")

    def on_message(msg):
        received_messages.append(msg)
        content = msg.get("content", "")
        from_name = msg.get("from_name", "?")
        print(f"  << [{from_name}]: {content[:300]}")

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

    # 发送 inbox 消息给泰虾
    content = (
        "【R102 管线推进】泰虾你好，我是小谷。\n\n"
        "你说已经提交了 R102 的测试报告，但我检查了代码仓库 "
        "(`docs/R102/` 目录)，没有找到测试报告文件。\n\n"
        "请按项目惯例将测试报告提交到 `docs/R102/R102-test-report.md`，"
        "然后 commit + push 到 dev 分支，并在 `_inbox:server` 回复 "
        "`已完成 ✅` 通知我。\n\n"
        "格式可参考之前的测试报告，比如 `docs/R101/R101-test-report.md`。\n"
        "内容包括：测试项、测试结果（🟢通过/🔴失败/🟡有条件）、测试环境等。\n\n"
        "多谢！"
    )

    print(f"\n--- 发送 inbox 消息给 {TAIXIA_NAME} ---")
    channel = f"_inbox:{TAIXIA_AID}"
    msg_id = await client.send_message(content, channel=channel)
    if msg_id:
        print(f"✅ 已发送！msg_id={msg_id[:16]}...")
    else:
        print("❌ 发送失败 (no ACK)")
        await client.disconnect()
        return

    # 等待回复（最长 120 秒）
    print(f"\n⏳ 等待 {TAIXIA_NAME} 回复（最长 120 秒）...")
    deadline = time.time() + 120
    while time.time() < deadline:
        await asyncio.sleep(1)
        for m in received_messages:
            c = m.get("content", "")
            if c and ("已完成" in c or "收到" in c or "测试报告" in c or "提交" in c):
                print(f"\n📩 收到回复: {c[:500]}")
                break
        else:
            continue
        break
    else:
        print("\n⏰ 超时未收到回复")

    await asyncio.sleep(3)
    print(f"\n📦 总共收到 {len(received_messages)} 条消息")
    await client.disconnect()
    print("✅ 断开连接。")

if __name__ == "__main__":
    asyncio.run(main())
