"""R102 Step 6: 派活给小爱 — 合并部署"""
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
XIAOAI_NAME = "小爱"

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
        "【R102 管线推进 — Step 6 🛠️ 合并部署】\n\n"
        "小爱好！R102 管线已全部完成：\n"
        "  Step 1 ✅ 需求文档\n"
        "  Step 2 ✅ 小开 技术方案\n"
        "  Step 3 ✅ 爱泰 编码\n"
        "  Step 4 ✅ 小周/大宏 审查通过（零项阻断）\n"
        "  Step 5 ✅ 泰虾 测试通过（27/28 🟢，T-1 仅为速率限制超时，代码已验证）\n\n"
        "现在交给你 Step 6 🛠️：\n"
        "1. 将 dev 分支合并到 main：\n"
        "     git checkout main && git merge dev\n"
        "2. 推送 main 到远程：\n"
        "     git push origin main\n"
        "3. 部署上线（参考 R101 部署方式，Docker + supervisor 双进程）\n\n"
        "R102 改动范围：\n"
        "  - server/main.py: _handle_server_relay 扩展（to_agent 派活路由 + 前缀匹配 + 入库留痕）\n"
        "  - server/config.py: DISPATCH_SENDER_ID 配置\n"
        "  - server/web_viewer.py: .reverse() 修复（消息顺序）\n"
        "  - 新增: tests/test_r102_dispatch.py, docs/R102/R102-test-report.md\n\n"
        "部署完成后请回复 已完成 ✅ 确认。谢谢！"
    )

    print(f"\n--- 发送 inbox 消息给 {XIAOAI_NAME} ---")
    channel = f"_inbox:{XIAOAI_AID}"
    msg_id = await client.send_message(content, channel=channel)
    if msg_id:
        print(f"✅ 已发送！msg_id={msg_id[:16]}...")
    else:
        print("❌ 发送失败 (no ACK)")
        # 尝试通过 _inbox:server 带 to_agent 发送
        print("--- 重试: 通过 _inbox:server 发送 ---")
        payload = {
            "to_agent": XIAOAI_AID,
            "content": content,
            "channel": "_inbox:server",
        }
        msg_id2 = await client.send_message(
            json.dumps(payload),
            channel="_inbox:server"
        )
        if msg_id2:
            print(f"✅ 通过 _inbox:server 发送成功！msg_id={msg_id2[:16]}...")
        else:
            print("❌ 两种方式均失败")

    # 等待回复
    print(f"\n⏳ 等待 {XIAOAI_NAME} 回复（最长 120 秒）...")
    deadline = time.time() + 120
    while time.time() < deadline:
        await asyncio.sleep(2)
        for m in received_messages:
            c = m.get("content", "")
            fn = m.get("from_name", "")
            if c and ("已完成" in c or "收到" in c):
                print(f"\n📩 [{fn}]: {c[:500]}")
                break
        else:
            continue
        break
    else:
        print("\n⏰ 超时未收到回复（消息已发送，小爱上线后会看到）")

    await asyncio.sleep(2)
    print(f"\n📦 总共收到 {len(received_messages)} 条消息")
    await client.disconnect()
    print("✅ 断开连接。完成！")

if __name__ == "__main__":
    asyncio.run(main())
