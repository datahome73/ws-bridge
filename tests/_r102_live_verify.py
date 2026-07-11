"""
R102 Live Runtime Verification — 协议验证
测试项目:
  P-1: test ✅ 回路测试 — 双向通信验证
  P-2: 收到 ✅ / ACK ✅ 前缀匹配
  P-3: 已完成 ✅ / ✅ 完成 前缀匹配
  P-4: 退回 🔄 前缀匹配
  P-5: 失败 ❌ 前缀匹配
  P-6: 无前缀沉默（入库留痕）
  P-7: ! 命令透传
"""
import asyncio, json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'clients', 'python'))
from ws_client import WsBridgeClient, load_creds

RESULTS = []
PASS = "✅"
FAIL = "❌"
SERVER = "wsim.datahome73.cloud"

def report(name, status, detail=""):
    icon = PASS if status else FAIL
    RESULTS.append(f"| {name} | {icon} | {detail}")
    print(f"  {icon} {name}: {detail}")

async def run_tests():
    name = "小谷"
    creds = load_creds(name)
    agent_id = creds["agent_id"]
    print(f"[小谷] agent_id={agent_id[:20]}...")

    received = []
    def on_message(msg):
        received.append(msg)
        content = msg.get("content", "")
        from_name = msg.get("from_name", "?")
        print(f"  << [{from_name}]: {str(content)[:120]}")

    client = WsBridgeClient(
        name=name,
        api_key=creds["api_key"],
        agent_id=creds["agent_id"],
        auto_reconnect=False,
    )
    client.on_message = on_message

    ok = await client.connect(f"wss://{SERVER}/ws")
    print(f"[连接] {'✅ 成功' if ok else '❌ 失败'}")
    if not ok:
        return

    await asyncio.sleep(1)
    received.clear()

    # ═══ P-1: test ✅ 回路测试 ═══
    print("\n--- P-1: test ✅ 回路测试 ---")
    await client.send_message("_inbox:server", "test ✅ R102 小谷协议验证")
    await asyncio.sleep(3)
    got = any("test 确认" in m.get("content","") for m in received)
    report("P-1: test ✅ 回路测试", got, "\"✅ test 确认 — 双向通信正常\" 已收到" if got else "未收到回复")
    received.clear()

    # ═══ P-2: 收到 ✅ ═══
    print("\n--- P-2: 收到 ✅ ---")
    await client.send_message("_inbox:server", "收到 ✅ 开始处理任务 R102-P2")
    await asyncio.sleep(2)
    # 收到前缀 → 仅转发PM，无自动确认bot，所以 bot 收件箱不应有回复
    got_reply = any("收到" in m.get("content","") and "确认" in m.get("content","") for m in received)
    report("P-2: 收到 ✅ 无自动确认", not got_reply, "无自动确认（预期行为：仅转发PM）" if not got_reply else "意外收到确认")
    received.clear()

    # ═══ P-3: 已完成 ✅ ═══
    print("\n--- P-3: 已完成 ✅ ---")
    await client.send_message("_inbox:server", "已完成 ✅ R102-P3 验证完成")
    await asyncio.sleep(2)
    auto_ok = any("已收到你的完成通知" in m.get("content","") for m in received)
    report("P-3: 已完成 ✅ 自动确认", auto_ok, "\"✅ 确认，已收到你的完成通知\" 已收到" if auto_ok else "未收到自动确认")
    received.clear()

    # ═══ P-4: 退回 🔄 ═══
    print("\n--- P-4: 退回 🔄 ---")
    await client.send_message("_inbox:server", "退回 🔄 审查不通过，需修改")
    await asyncio.sleep(2)
    auto_tuihui = any("已记录退回" in m.get("content","") for m in received)
    report("P-4: 退回 🔄 自动确认", auto_tuihui, "\"🔄 已记录退回.\" 已收到" if auto_tuihui else "未收到自动确认")
    received.clear()

    # ═══ P-5: 失败 ❌ ═══
    print("\n--- P-5: 失败 ❌ ---")
    await client.send_message("_inbox:server", "失败 ❌ 测试失败，需要重试")
    await asyncio.sleep(2)
    auto_fail = any("已记录失败" in m.get("content","") for m in received)
    report("P-5: 失败 ❌ 自动确认", auto_fail, "\"⚠️ 已记录失败.\" 已收到" if auto_fail else "未收到自动确认")
    received.clear()

    # ═══ P-6: 无前缀沉默 ═══
    print("\n--- P-6: 无前缀沉默 ---")
    await client.send_message("_inbox:server", "这是一条测试消息，无任何前缀匹配")
    await asyncio.sleep(3)
    # 无前缀 → 入库留痕，无任何回复
    silent = not any(m.get("channel","") == f"_inbox:{agent_id}" for m in received)
    report("P-6: 无前缀沉默", silent, "无回复到 bot 收件箱（预期行为：仅入库留痕）" if silent else "收到不应有的回复")
    received.clear()

    # ═══ P-7: ! 命令透传 ═══
    print("\n--- P-7: ! 命令透传 ---")
    await client.send_message("_inbox:server", "!agent_card list")
    await asyncio.sleep(3)
    cmd_ok = any("Agent Cards" in m.get("content","") for m in received)
    report("P-7: !agent_card list", cmd_ok, "Agent Cards 列表已返回" if cmd_ok else "未返回命令结果")
    received.clear()

    # ═══ 打印报告 ═══
    print("\n" + "="*60)
    print("📋 R102 运行时协议测试报告")
    print("="*60)
    print(f"| 测试项 | 结果 | 说明 |")
    print(f"|:-------|:----:|:-----|")
    for r in RESULTS:
        print(r)
    passed = sum(1 for r in RESULTS if "✅" in r)
    total = len(RESULTS)
    print(f"\n**合计**: {total} 项 | ✅ {passed} | ❌ {total - passed}")
    print(f"**通过率**: {passed}/{total} ({passed/total*100:.0f}%)")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_tests())
