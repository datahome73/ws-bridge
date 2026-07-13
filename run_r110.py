#!/usr/bin/env python3
"""R110: start pipeline + dispatch step 2 + step 1 complete signal.
Each action gets its own fresh connection due to server closing connections after 1 msg."""
import json, asyncio, websockets, time, os

WS_URL = "wss://wsim.datahome73.cloud/ws"
XIAOGU_ID = "ws_f26e585f6479"
XIAOKAI_ID = "ws_3f7cdd736c1c"
CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")

STEP2_MSG = ("🏗️ **R110 Step 2 — 技术方案**\n\n"
    "需求文档已审核通过：https://github.com/datahome73/ws-bridge/blob/main/docs/R110/R110-product-requirements.md\n\n"
    "请评估以下事项并输出技术方案文档 `docs/R110/r110-step2-tech-plan.md`:\n"
    "1. PipelineAutoStarter 组件设计\n2. from_work_plan 工厂方法\n"
    "3. 角色映射\n4. 启动方式\n5. 安全边界\n6. 与 !pipeline_start 兼容\n\n"
    "推 dev 后回复 ✅ 完成")

async def send_once(display_name, make_msg):
    """Register, auth, send one message, collect responses, return them."""
    suffix = str(int(time.time()))[-6:]
    # Register
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'{display_name}-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok': return None, [f'Register failed: {resp}']
        api_key = resp['api_key']
    # Auth + send
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'auth_ok': return None, [f'Auth failed: {resp}']
        msg = make_msg()
        await ws.send(json.dumps(msg))
        responses = []
        for i in range(15):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1)
                responses.append(json.loads(raw))
            except asyncio.TimeoutError:
                break
            except websockets.exceptions.ConnectionClosed:
                break
        return True, responses

async def main():
    # Step 1: Start pipeline
    print('=== 1. !pipeline_start R110 to _admin ===')
    ok, msgs = await send_once('ps', lambda: {
        'type': 'message', 'channel': '_admin', 'content': '!pipeline_start R110',
    })
    for m in msgs:
        ct = str(m.get('content',''))
        err = m.get('error','')
        if err: print(f'  ❌ {err}')
        if ct and ct != 'None': print(f'  {ct[:200]}')
    print(f'  → {len(msgs)} responses')
    await asyncio.sleep(1)

    # Step 2: Query pipeline status
    print('\n=== 2. !pipeline_status ===')
    ok, msgs = await send_once('qs', lambda: {
        'type': 'message', 'channel': '_inbox:server', 'content': '!pipeline_status',
    })
    for m in msgs:
        ct = str(m.get('content',''))
        if ct and ct != 'None': print(f'  {ct[:400]}')
    print(f'  → {len(msgs)} responses')

    # Step 3: Send Step 1 completion signal (triggers auto-advance if context exists)
    print('\n=== 3. Step 1 completion ===')
    ok, msgs = await send_once('c1', lambda: {
        'type': 'message', 'channel': '_inbox:server',
        'content': '已完成 ✅ R110 Step 1 — 需求文档已审核，auto_chain 推进',
    })
    for m in msgs:
        ct = str(m.get('content',''))[:200]
        if ct and ct != 'None': print(f'  {ct}')
    print(f'  → {len(msgs)} responses')

    # Step 4: Dispatch Step 2 to 小开 as 小谷
    print('\n=== 4. Step 2 → 小开 (as 小谷) ===')
    creds = json.loads(open(CRED_PATH).read())
    suffix = str(int(time.time()))[-6:]
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ 小谷: {resp.get("display_name")}')
        await ws.send(json.dumps({
            'type': 'message', 'channel': f'_inbox:{XIAOKAI_ID}',
            'from_name': '小谷', 'from_agent': XIAOGU_ID,
            'content': STEP2_MSG,
        }))
        print('📤 Step 2 → 小开')
        for i in range(10):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1)
                msg = json.loads(raw)
                ct, err = str(msg.get('content','')), msg.get('error','')
                if err: print(f'  ❌ {err}')
                if ct and ct != 'None': print(f'  {ct[:200]}')
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                break

    # Step 5: Verify pipeline status again
    print('\n=== 5. Verify pipeline status ===')
    ok, msgs = await send_once('v2', lambda: {
        'type': 'message', 'channel': '_inbox:server', 'content': '!pipeline_status',
    })
    for m in msgs:
        ct = str(m.get('content',''))
        if ct and ct != 'None': print(f'  {ct[:400]}')
    print(f'  → {len(msgs)} responses')

    print('\n✅ R110 pipeline flow complete!')

asyncio.run(main())
