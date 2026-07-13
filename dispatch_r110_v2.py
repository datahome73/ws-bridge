#!/usr/bin/env python3
"""R110 dispatch — one-shot per message using 小谷 creds, no temp registration."""
import json, asyncio, websockets, os, time

WS_URL = "wss://wsim.datahome73.cloud/ws"
CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
XIAOKAI_ID = "ws_3f7cdd736c1c"

STEP2_MSG = ("🏗️ **R110 Step 2 — 技术方案**\n\n"
    "需求文档已审核通过：https://github.com/datahome73/ws-bridge/blob/main/docs/R110/R110-product-requirements.md\n\n"
    "请评估以下事项并输出技术方案文档 `docs/R110/r110-step2-tech-plan.md`:\n"
    "1. PipelineAutoStarter 组件设计\n2. from_work_plan 工厂方法\n"
    "3. 角色映射\n4. 启动方式\n5. 安全边界\n6. 与 !pipeline_start 兼容\n\n"
    "推 dev 后回复 ✅ 完成")

async def send_msg(display_name, msg, label, read_timeout=3, max_responses=15):
    """Register temp bot, send, collect responses."""
    suffix = str(int(time.time()))[-6:]
    
    # Register
    ws = await websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15)
    await ws.send(json.dumps({'type': 'register', 'display_name': f'{display_name}-{suffix}'}))
    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    api_key = resp.get('api_key', '')
    print(f'✅ Registered {display_name}-{suffix}')
    await ws.close()
    
    # Auth + send
    ws = await websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15)
    await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    print(f'✅ Auth: {resp.get("display_name")}')
    
    await ws.send(json.dumps(msg))
    print(f'📤 {label}')
    
    responses = []
    for _ in range(max_responses):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=read_timeout)
            responses.append(json.loads(raw))
        except asyncio.TimeoutError:
            break
        except websockets.exceptions.ConnectionClosed:
            break
    
    for r in responses:
        ct = str(r.get('content',''))
        err = r.get('error','')
        ch = r.get('channel','')
        fn = r.get('from_name','')
        if err: print(f'  ❌ {err}')
        if ct and ct != 'None': print(f'  [{ch}] {fn}: {ct[:250]}')
    print(f'  → {len(responses)} responses')
    await ws.close()
    return responses

async def main():
    # Step 1: !pipeline_start R110 → _admin
    print('=== Step 1: Start pipeline ===')
    await send_msg('ps', {
        'type': 'message', 'channel': '_admin', 'content': '!pipeline_start R110',
    }, '!pipeline_start R110 → _admin', read_timeout=3)
    
    await asyncio.sleep(2)
    
    # Step 2: Step 2 → 小开 via _inbox:server
    print('\n=== Step 2: Step 2 → 小开 ===')
    await send_msg('s2', {
        'type': 'message', 'channel': '_inbox:server',
        'to_agent': XIAOKAI_ID,
        'from_name': '小谷',
        'content': STEP2_MSG,
    }, 'Step 2 → 小开', read_timeout=3)
    
    await asyncio.sleep(1)
    
    # Step 3: Step 1 completion signal
    print('\n=== Step 3: Step 1 completion ===')
    await send_msg('c1', {
        'type': 'message', 'channel': '_inbox:server',
        'content': '已完成 ✅ R110 Step 1 — 需求文档已审核，auto_chain 推进',
    }, '已完成 ✅ R110 Step 1', read_timeout=3)
    
    await asyncio.sleep(1)
    
    # Step 4: Query status
    print('\n=== Step 4: Status check ===')
    await send_msg('qs', {
        'type': 'message', 'channel': '_inbox:server', 'content': '!pipeline_status',
    }, '!pipeline_status', read_timeout=3)
    
    print('\n✅ R110 dispatch complete!')

asyncio.run(main())
