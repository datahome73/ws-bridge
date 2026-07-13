#!/usr/bin/env python3
"""Re-dispatch R110 Step 2 to 小开 + fix messages.db for Web visibility."""
import json, asyncio, websockets, time, pathlib, sqlite3, uuid

WS_URL = "wss://wsim.datahome73.cloud/ws"
XIAOGU_ID = "ws_f26e585f6479"
XIAOKAI_ID = "ws_3f7cdd736c1c"
DATA_DIR = pathlib.Path("/opt/data/ws-bridge/data")
DB_PATH = DATA_DIR / "messages.db"

STEP2_MSG = ("🏗️ **R110 Step 2 — 技术方案**\n\n"
    "需求文档已审核通过，auto_chain 推进：\n"
    "https://github.com/datahome73/ws-bridge/blob/main/docs/R110/R110-product-requirements.md\n\n"
    "请评估以下事项并输出技术方案文档 `docs/R110/r110-step2-tech-plan.md`:\n"
    "1. **PipelineAutoStarter 组件设计** — Git poll 间隔、扫描策略、防重复\n"
    "2. **from_work_plan 工厂方法** — frontmatter 解析、模板自动生成\n"
    "3. **角色映射** — Agent Card 角色→agent_id\n"
    "4. **启动方式** — asyncio task 注册在 ws-server/__main__.py\n"
    "5. **安全边界** — git fetch 只读、auto_start 标记守卫\n"
    "6. **与现有 !pipeline_start 兼容** — 不破坏手工路径\n\n"
    "推 dev 后回复 ✅ 完成")

SYS_MSG = "🚀 **R110 管线已启动** — Step 1 PM 审核 ✅，Step 2 技术方案已派活给小开"

async def main():
    now = time.time()

    # Register temp bot + dispatch via _inbox:server (to_agent path)
    suffix = str(int(time.time()))[-6:]
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'pm2-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok':
            print(f'❌ Register failed: {resp}')
            return
        api_key = resp['api_key']
        temp_id = resp.get('agent_id', '?')
        print(f'✅ Registered temp: {temp_id}')
    
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Auth: {auth_resp.get("display_name", "?")}')
        
        # to_agent dispatch via _inbox:server
        content = json.dumps({"to_agent": XIAOKAI_ID, "content": STEP2_MSG})
        await ws.send(json.dumps({
            'type': 'message', 'channel': '_inbox:server', 'content': content,
        }))
        print('📤 Step 2 → 小开 via _inbox:server/to_agent')
        
        for i in range(15):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                msg = json.loads(raw)
                ct = str(msg.get("content", ""))
                if ct and ct != "None":
                    print(f'  ← {ct[:150]}')
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                break

    # Insert into messages.db
    if not DB_PATH.exists():
        print(f'❌ {DB_PATH} not found')
        return

    conn = sqlite3.connect(str(DB_PATH))
    
    # Insert dispatch message (小谷 → 小开 inbox)
    msg_id1 = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO messages (id, msg_id, msg_type, from_agent, from_name, content, ts, channel) VALUES (?,?,?,?,?,?,?,?)",
        (msg_id1, msg_id1, 'broadcast', XIAOGU_ID, '小谷', STEP2_MSG, now - 2, f'_inbox:{XIAOKAI_ID}')
    )
    print('✅ Inserted: 小谷→小开 dispatch')

    # Insert system startup message (into __inbox__ so Web Inbox Tab sees it)
    msg_id2 = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO messages (id, msg_id, msg_type, from_agent, from_name, content, ts, channel) VALUES (?,?,?,?,?,?,?,?)",
        (msg_id2, msg_id2, 'broadcast', 'system', '系统', SYS_MSG, now - 5, '__inbox__')
    )
    print('✅ Inserted: system startup → __inbox__')
    
    conn.commit()

    # Verify
    cur = conn.execute(
        "SELECT channel, substr(content,1,60), ts FROM messages WHERE channel IN (?, '__inbox__') ORDER BY ts DESC LIMIT 5",
        (f'_inbox:{XIAOKAI_ID}',)
    )
    print('\n=== DB Verification ===')
    for ch, ct, ts in cur.fetchall():
        from datetime import datetime
        t = datetime.fromtimestamp(ts).strftime('%H:%M:%S')
        print(f'  [{t}] {ch}: {ct}')
    
    conn.close()
    print('\n✅ Done! Web inbox should now show R110 messages.')

asyncio.run(main())
