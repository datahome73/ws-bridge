#!/usr/bin/env python3
"""
广播 WORK_PLAN.md 当前进度到 ws-im 工作群。
cron 定时执行，各虾上线即可收到最新状态。

读取本地仓库的 WORK_PLAN.md（不需要 GitHub API 鉴权）。
"""

import os
import re
import sys
from pathlib import Path

# 本地仓库路径 — 当前脚本在 scripts/，仓库根在 parent of parent
REPO_ROOT = Path(__file__).resolve().parent.parent
WORK_PLAN_PATH = REPO_ROOT / "WORK_PLAN.md"

WS_URL = os.environ.get("WS_BRIDGE_URL")
APP_ID = os.environ.get("WS_BRIDGE_APP_ID", "ws-bridge")
AGENT_ID = os.environ.get("WS_BRIDGE_AGENT_ID")
BOT_NAME = os.environ.get("WS_BRIDGE_BOT_NAME", "bot")
REPO_URL = os.environ.get("REPO_URL", "https://github.com/your-org/your-repo")


def read_work_plan():
    """Read WORK_PLAN.md from local repo."""
    try:
        return WORK_PLAN_PATH.read_text("utf-8")
    except Exception as e:
        print(f"Failed to read WORK_PLAN: {e}", file=sys.stderr)
        return None


def parse_status(text):
    """Parse checkboxes and extract current step info."""
    status_lines = []
    current_step = None
    step_done = False
    next_step = None

    for line in text.splitlines():
        # Match ## □ / ## □ (step headers)
        m = re.match(r'^##\s*□\s+(Step\s+\S+|.*?)(?:\s*[:：]?\s*.*)?$', line)
        if m and not line.startswith('## □ Step') and not any(x in line for x in ['说明', '工作流']):
            continue

        m2 = re.match(r'^##\s*□\s+(.*)$', line)
        if m2:
            title = m2.group(1).strip()
            status_lines.append(f"📋 {title}")
            current_step = title
            step_done = False
            if '✅' in title:
                step_done = True
            elif '待启动' in title or '进行中' in title:
                if next_step is None:
                    next_step = current_step
            continue

        # Check for x] or ] 
        ck = re.match(r'^\s*-\s*\[\s*([ xX])\s*\]\s+(.*)', line)
        if ck:
            done = ck.group(1).strip().lower() == 'x'
            task = ck.group(2).strip()
            icon = '✅' if done else '⬜'
            status_lines.append(f"  {icon} {task}")

    return status_lines, current_step, step_done, next_step


def send_message_to_workgroup(content):
    """Send a message via ws-im WebSocket."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'client'))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'ws_client',
        str(Path(__file__).resolve().parent.parent / 'client' / 'ws_client.py')
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    import asyncio

    async def _send():
        client = mod.WsBridgeClient(
            ws_url=WS_URL,
            app_id=APP_ID,
            agent_id=AGENT_ID,
            name=BOT_NAME,
            auto_reconnect=False,
        )
        await client.connect()
        # Split long messages if needed
        for line in content.split('\n'):
            if line.strip():
                await client.send_message(line)
            await asyncio.sleep(0.2)
        await asyncio.sleep(1)
        await client.disconnect()

    asyncio.run(_send())


def main():
    text = read_work_plan()
    if not text:
        return

    status_lines, current_step, step_done, next_step = parse_status(text)

    # Build message
    lines = ["📋 **ws-im 工作进度报告**"]
    lines.append(f"仓库: {REPO_URL}")
    lines.append("")

    # Current step highlight
    if next_step:
        lines.append(f"📍 **当前: {next_step}**")
    else:
        lines.append("✅ **全部完成**")

    lines.append("")
    lines.append("**各 Step 状态:**")
    for line in status_lines:
        lines.append(line)

    lines.append("")
    lines.append("---")
    lines.append(f"请在完成当前 Step 后 @{BOT_NAME} 确认")

    message = '\n'.join(lines)

    try:
        send_message_to_workgroup(f"{BOT_NAME} @all: {message}")
        print("Status broadcast sent successfully")
    except Exception as e:
        print(f"Failed to send: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
