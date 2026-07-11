"""R102 全流程测试 v3：派活给泰虾，提交测试报告"""
import asyncio
import json
import os
import sys
import time
import uuid

sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
import importlib.util
spec = importlib.util.spec_from_file_location(
    "ws_client",
    "/opt/data/ws-bridge/clients/python/ws_client.py"
)
ws_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_client)

load_creds = ws_client.load_creds

TAIXIA_AID = "ws_eab784ac7652"
TAIXIA_NAME = "泰虾"

received = []

async def main():
    creds = load_creds("小谷")
    agent_id = creds["agent_id"]
    api_key = creds["api_key"]
    print(f"✅ 小谷 / {agent_id[:16]}...")

    import websockets
    ws = await websockets.connect("wss://wsim.datahome73.cloud/ws", max_size=2**20)
    print("✅ WebSocket 已连接")

    # 认证
    auth_payload = json.dumps({"type": "auth", "api_key": api_key, "agent_id": agent_id})
    await ws.send(auth_payload)
    auth_resp = await ws.recv()
    print(f"✅ 认证成功")

    # 读取线程
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
            except Exception as e:
                print(f"  ⏹ reader: {e}")
                break

    asyncio.create_task(reader())

    # 派活
    content = (
        "【R102 全流程测试 🧪】\n\n"
        f"{TAIXIA_NAME}你好，请完成以下任务：\n\n"
        "1️⃣ 回复 收到 ✅ 确认接活\n"
        "2️⃣ 在 docs/R102/ 目录下创建一份测试报告，文件名 R102-e2e-flow-report.md\n"
        "   内容包含：\n"
        "   - 测试日期\n"
        "   - 测试环境\n"
        "   - 测试项：派活 → ACK → 干活 → 完成 全链路\n"
        "   - 测试结果：PASS\n"
        "   - 测试人：泰虾\n"
        "3️⃣ 回复 已完成 ✅ 确认完成\n\n"
        "请实际创建文件！谢谢！"
    )

    msg_id = str(uuid.uuid4())
    payload = {
        "type": "message",
        "content": content,
        "channel": "_inbox:server",
        "to_agent": TAIXIA_AID,
        "from_name": "小谷",
        "agent_id": agent_id,
        "id": msg_id,
        "ts": time.time(),
    }

    print(f"\n═══ ① 派活 → {TAIXIA_NAME} ═══")
    await ws.send(json.dumps(payload))
    print(f"   ✅ 已发送（无重试）")

    # 等回复
    print(f"\n═══ ② 等待 {TAIXIA_NAME} 回复（最长 120 秒）═══")
    ack_ok = False
    done_ok = False
    deadline = time.time() + 120
    while time.time() < deadline:
        await asyncio.sleep(1)
        for m in received:
            c = m.get("content", "").strip()
            if "已接活" in c:
                ack_ok = True
            if "已完成" in c:
                done_ok = True
        if done_ok:
            break

    print(f"\n═══ ③ 结果 ═══")
    print(f"   派活 → {TAIXIA_NAME}: ✅")
    print(f"   ACK (收到 ✅): {'✅' if ack_ok else '❌'}")
    print(f"   完成 (已完成 ✅): {'✅' if done_ok else '❌（超时）'}")

    if ack_ok and done_ok:
        print(f"\n   🎉 R102 全流程测试通过！")
    elif ack_ok:
        print(f"\n   ⏳ 泰虾已接活，等待完成...")

    await ws.close()
    print("✅ 测试结束")

if __name__ == "__main__":
    asyncio.run(main())
