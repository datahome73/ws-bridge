#!/usr/bin/env python3
"""
Check R20 Step 5 direction review status.
If file doesn't exist (1st check): resend Step 5 instructions to workgroup (2nd send).
If file doesn't exist (2nd check): notify project-lead.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add client to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'client'))

WS_URL = os.environ.get("WS_BRIDGE_URL", "wss://ws-bridge.example.com/ws")
APP_ID = os.environ.get("WS_BRIDGE_APP_ID", "hermes-agent")
AGENT_ID = os.environ.get("WS_BRIDGE_AGENT_ID", "YOUR_AGENT_ID")
BOT_NAME = os.environ.get("WS_BRIDGE_BOT_NAME", "Bot-Admin")
CHANNEL = os.environ.get("WS_BRIDGE_CHANNEL", "ws:lobby")
REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_R20 = REPO_ROOT / "docs" / "R20"
REVIEW_FILE = DOCS_R20 / "R20-direction-review.md"
WORK_PLAN = DOCS_R20 / "WORK_PLAN.md"

async def send_message_to_channel(content: str):
    """Send a message to the specified channel via ws-bridge WebSocket."""
    import websockets

    ws = None
    try:
        ws = await websockets.connect(
            WS_URL,
            ping_interval=None,
            ping_timeout=None,
            close_timeout=5,
        )

        # Authenticate
        await ws.send(json.dumps({
            "type": "auth",
            "app_id": APP_ID,
            "agent_id": AGENT_ID,
            "name": BOT_NAME,
        }))

        # Wait for auth response
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        resp = json.loads(raw)
        msg_type = resp.get("type", "")
        if msg_type == "auth_ok":
            print(f"Auth OK (role={resp.get('role')})")
        elif msg_type == "pairing_code":
            print(f"Pairing code: {resp.get('code')}")
            return False
        elif msg_type == "auth_error":
            print(f"Auth error: {resp.get('error')}")
            return False

        # Send message to channel
        msg_id = f"step5_{int(time.time())}"
        payload = {
            "type": "message",
            "content": content,
            "to": CHANNEL,
            "from_name": BOT_NAME,
            "agent_id": AGENT_ID,
            "id": msg_id,
            "ts": time.time(),
        }
        await ws.send(json.dumps(payload))
        print(f"Message sent to {CHANNEL}: {content[:80]}...")

        # Wait a moment for ACK
        await asyncio.sleep(2)

        await ws.close()
        print("Connection closed")
        return True

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if ws:
            await ws.close()
        return False


def main():
    # Check if R20-direction-review.md exists
    exists = REVIEW_FILE.exists()
    print(f"R20-direction-review.md exists: {exists}")

    if exists:
        print("=== FILE EXISTS: Updating WORK_PLAN and notifying ===")
        # Read current WORK_PLAN
        wp_text = WORK_PLAN.read_text("utf-8")

        # Replace Step 5 status
        old = "### Step 5：方向审查 🧐 pm-bot 🟡 进行中"
        new = "### Step 5：方向审查 🧐 pm-bot ✅ 已完成"
        if old in wp_text:
            wp_text = wp_text.replace(old, new)
            WORK_PLAN.write_text(wp_text, "utf-8")
            print("WORK_PLAN.md updated: Step 5 ✅")
        else:
            print(f"Could not find '{old}' in WORK_PLAN.md")
            print("Current WORK_PLAN Step 5 line(s):")
            for i, line in enumerate(wp_text.splitlines()):
                if "Step 5" in line or "方向审查" in line:
                    print(f"  {i+1}: {line}")

        # Send notification to workgroup
        msg = (
            f"@dev-bot 💻 Step 6 编码请准备，pm-bot 方向审查已完成 ✅\n\n"
            f"产出：{REVIEW_FILE}\n"
            f"请按照 Step 4 技术方案实现编码，完成后 @admin-bot 推进 Step 7"
        )
        asyncio.run(send_message_to_channel(msg))

        # Save conclusion to memory
        from datetime import datetime
        memory_content = f"""
## R20 Step 5 方向审查 — 完成 ({datetime.now().strftime('%Y-%m-%d %H:%M')})

- 状态：✅ 已完成
- 产出：{REVIEW_FILE}
- pm-bot 方向审查通过
- WORK_PLAN.md Step 5 已更新为 ✅
- 已通知 @dev-bot 准备 Step 6 编码
"""
        memory_path = Path.home() / ".hermes" / "profiles" / "default" / "memories" / "r20_step5_complete.md"
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(memory_content.strip(), "utf-8")
        print(f"Memory saved to {memory_path}")

    else:
        print("=== FILE NOT FOUND: Resending Step 5 instructions ===")
        # Read current count or start at 1
        count_file = DOCS_R20 / ".step5_reminder_count"
        count = 1
        if count_file.exists():
            try:
                count = int(count_file.read_text("utf-8").strip())
            except:
                pass

        if count >= 2:
            print(f"Count is {count} >= 2 — notifying project-lead")
            msg = (
                f"@project-lead ⚠️ pm-bot 方向审查已超时\n\n"
                f"Step 5 方向审查已发送两轮指令 (第1次+第2次)，等待超过 5+10 分钟仍未完成。\n"
                f"请私聊 pm-bot 催一催，确认是否遇到阻塞卡点。\n\n"
                f"详情：{DOCS_R20}/ 下缺少 R20-direction-review.md"
            )
            asyncio.run(send_message_to_channel(msg))
            print("Notified project-lead")

            # Save to memory
            from datetime import datetime
            memory_content = f"""
## R20 Step 5 方向审查 — 超时 ({datetime.now().strftime('%Y-%m-%d %H:%M')})

- 状态：🔴 超时
- 已发送两轮指令仍未完成
- 已通知 @project-lead 私聊 pm-bot 催促
- 等待 pm-bot 方向审查完成后继续
"""
            memory_path = Path.home() / ".hermes" / "profiles" / "default" / "memories" / "r20_step5_timeout.md"
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text(memory_content.strip(), "utf-8")
            print(f"Memory saved to {memory_path}")
        else:
            print(f"Count is {count} — sending Step 5 instructions (2nd send)")
            msg = (
                f"@pm-bot ⚠️ Step 5 方向审查 — 第二遍指令（请立即执行）\n\n"
                f"任务：审查 @architect-bot 的技术方案方向\n"
                f"产出：`docs/R20/R20-direction-review.md`\n\n"
                f"审查要点：\n"
                f"1. 对比 Step 3 需求文档，确认方案方向正确\n"
                f"2. 技术实现路径是否合理\n"
                f"3. 三类结论：🟢 通过 → Step 6 / 🟡 需补充 → 退回 architect-bot / 🔴 方向错误 → project-lead 介入\n\n"
                f"⏱️ 请在收到消息后尽快完成（目标：5分钟内），完成后 @admin-bot 确认推进 Step 6"
            )
            asyncio.run(send_message_to_channel(msg))

            # Increment count
            count += 1
            count_file.write_text(str(count), "utf-8")
            print(f"Reminder count updated to {count}")
            print(f"Count file: {count_file}")

            # Save to memory
            from datetime import datetime
            memory_content = f"""
## R20 Step 5 方向审查 — 第二遍指令已发送 ({datetime.now().strftime('%Y-%m-%d %H:%M')})

- 状态：🟡 等待中
- 第2次发送 Step 5 指令到工作群
- 语气更坚定，要求立即执行
- 如果仍未完成，下次检查将通知 project-lead 介入
"""
            memory_path = Path.home() / ".hermes" / "profiles" / "default" / "memories" / "r20_step5_reminder2.md"
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text(memory_content.strip(), "utf-8")
            print(f"Memory saved to {memory_path}")


if __name__ == "__main__":
    main()
