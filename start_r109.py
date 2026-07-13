"""注册临时 bot → 发 !pipeline_start R109 → 读回复"""
import json, asyncio, sys, os
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')

async def main():
    import websockets
    import time
    
    uri = 'wss://wsim.datahome73.cloud/ws'
    suffix = str(int(time.time()))[-6:]
    
    # 1. 注册
    async with websockets.connect(uri, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({"type": "register", "display_name": f"tmp-{suffix}"}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get("type") != "register_ok":
            print(f"❌ 注册失败: {resp}")
            return
        api_key = resp["api_key"]
        agent_id = resp["agent_id"]
        print(f"✅ 注册: {agent_id}")
    
    # 2. 连接并发送命令
    async with websockets.connect(uri, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get("type") != "auth_ok":
            print(f"❌ Auth失败: {resp}")
            return
        print(f"✅ 已连接: {resp.get('display_name')}")
        
        # 发 pipeline_start
        await ws.send(json.dumps({
            "type": "message",
            "channel": "_inbox:server",
            "content": "!pipeline_start R109",
        }))
        print("📤 发送: !pipeline_start R109 → _inbox:server")
        
        # 收集所有回复
        msgs = []
        for i in range(30):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                msgs.append(msg)
                mt = msg.get('type', '?')
                ch = msg.get('channel', '')
                content = str(msg.get('content', ''))
                error = msg.get('error', '')
                from_agent = msg.get('from_agent', '')
                
                if content and content != 'None':
                    print(f'\n[{i}] {mt} ch={ch} from={from_agent}')
                    print(f'  {content[:1500]}')
                elif error:
                    print(f'\n[{i}] ERROR: {error[:300]}')
                else:
                    print(f'\n[{i}] {mt} {json.dumps(msg, ensure_ascii=False)[:200]}')
                    
            except asyncio.TimeoutError:
                if msgs:
                    print(f'\n[{i}] (done, {len(msgs)} msgs)')
                    break
                continue
        
        # 3. 再查一次管线状态确认
        print("\n=== 查管线状态 ===")
        await ws.send(json.dumps({
            "type": "message",
            "channel": "_inbox:server",
            "content": "!pipeline_status",
        }))
        print("📤 发送: !pipeline_status → _inbox:server")
        
        for i in range(15):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                content = str(msg.get('content', ''))
                ch = msg.get('channel', '')
                if content and content != 'None':
                    print(f'  [{i}] ch={ch}')
                    print(f'  {content[:1500]}')
            except asyncio.TimeoutError:
                print(f'  [{i}] (no more)')
                break

asyncio.run(main())
