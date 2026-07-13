#!/usr/bin/env python3
"""Create PipelineContext for R109 and send via WS to trigger auto-dispatch."""
import asyncio, json, os, time

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"
XIAOGU_ID = "ws_f26e585f6479"

R109_CTX = {
    "round_name": "R109",
    "status": "running",
    "current_step": 1,
    "total_steps": 6,
    "current_phase": "PM 审核",
    "created_at": time.time(),
    "triggerer_id": XIAOGU_ID,
    "triggerer_name": "小谷",
    "steps": [
        {"name": "step1", "role": "pm",   "agent_id": XIAOGU_ID,  "agent_name": "小谷", "status": "completed"},
        {"name": "step2", "role": "arch", "status": "pending", "agent_id": "ws_3f7cdd736c1c", "agent_name": "小开"},
        {"name": "step3", "role": "dev",  "status": "pending", "agent_id": "ws_0bb747d3ea2a", "agent_name": "爱泰"},
        {"name": "step4", "role": "review","status": "pending", "agent_id": "ws_fcf496ca1b4f", "agent_name": "小周"},
        {"name": "step5", "role": "qa",   "status": "pending", "agent_id": "ws_eab784ac7652", "agent_name": "泰虾"},
        {"name": "step6", "role": "ops",  "status": "pending", "agent_id": "ws_c47032fa1f67", "agent_name": "小爱"},
    ],
    "step_order": ["step1","step2","step3","step4","step5","step6"],
    "work_plan_url": "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R109/WORK_PLAN.md",
    "message_templates": {
        "step2": "🏗️ **R109 Step 2 — 技术方案**\n\n需求文档已审核通过：https://github.com/datahome73/ws-bridge/blob/main/docs/R109/R109-product-requirements.md\n\n请评估以下事项并输出技术方案文档：\n1. 整体迁移策略 — 分步迁移，避免大爆炸\n2. auth.py / message_store.py / persistence.py 拆分边界\n3. config.py 减法清单\n4. Bot 状态文件传递方案\n5. Dockerfile + supervisor 更新\n\n产出：docs/R109/r109-step2-tech-plan.md\n\n推 dev 后回复 ✅ 完成",
        "step3": "🏗️ **R109 Step 3 — 编码实现**\n\n按技术方案实现。详见 docs/R109/r109-step2-tech-plan.md",
        "step4": "🔍 **R109 Step 4 — 代码审查**\n\n审查 Step 3 的改动：\n- ws-server/ 和 web-ui/ 目录结构\n- import 链验证\n- 减法功能确认\n\n审查通过后回复 ✅ 完成",
        "step5": "🧪 **R109 Step 5 — 测试验证**\n\n验证 27 项验收标准（见需求文档 §5）\n\n全部通过后回复 ✅ 完成",
        "step6": "🚀 **R109 Step 6 — 合并部署归档**\n\nPR: dev → main\n重建 Docker 镜像 ws-bridge:r109\n重启 Supervisor 双进程\n\n部署完成后回复 ✅ 完成",
    },
    "references": {
        "需求文档": "https://github.com/datahome73/ws-bridge/blob/main/docs/R109/R109-product-requirements.md",
        "WORK_PLAN": "https://github.com/datahome73/ws-bridge/blob/main/docs/R109/WORK_PLAN.md",
    },
    "task_kind": "development"
}

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    
    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=10, ping_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        print(f"AUTH: {json.loads(resp).get('type')}")

        # Send message to trigger Step 1 completion → auto-dispatch Step 2
        # Format: bot replies with "✅ 完成" to _inbox:server
        content = json.dumps({
            "to_agent": XIAOGU_ID,
            "content": "✅ 完成 R109 Step 1 — 需求文档审核通过\n\n已推送 main: 796dfed (_cmd_pipeline_start import fix)"
        })
        payload = {"type": "message", "channel": "_inbox:server", "content": content}
        await ws.send(json.dumps(payload))
        print("SENT: Step 1 completion signal to _inbox:server")

        # Wait for response(s) — should trigger auto-dispatch Step 2
        for i in range(10):
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=10)
                d = json.loads(resp)
                ct = str(d.get("content",""))
                ch = d.get("channel","")
                print(f"\n[{d.get('type')}] ch={ch}")
                if ct and ct != "None": print(f"  {ct[:500]}")
            except asyncio.TimeoutError:
                print("\nDONE (timeout)")
                break

asyncio.run(main())
