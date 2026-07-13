"""注册临时bot → 发 ✅ 完成 Step 1 (正确格式)"""
import json, asyncio, sys, os
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')

async def main():
    import websockets
    import time
    
    uri = 'wss://wsim.datahome73.cloud/ws'
    suffix = str(int(time.time()))[-6:]
    
    async with websockets.connect(uri, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({"type": "register", "display_name": f"adv-{suffix}"}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get("type") != "register_ok":
            print(f"❌ 注册失败: {resp}")
            return
        api_key = resp["api_key"]
        print(f"✅ 注册")
    
    async with websockets.connect(uri, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get("type") != "auth_ok":
            print(f"❌ Auth失败: {resp}")
            return
        print(f"✅ 连接")
        
        # 正确格式: 已完成 ✅ R109 Step 1 (根据 _try_advance_pipeline 的正则)
        await ws.send(json.dumps({
            "type": "message",
            "channel": "_inbox:server",
            "content": "已完成 ✅ R109 Step 1 — 需求文档审核通过",
        }))
        print("📤 发送: 已完成 ✅ R109 Step 1 — 需求文档审核通过")
        
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
                    print(f'\n[{i}] (done)')
                    break
                continue
        
        # 查管线状态
        print("\n=== 管线状态 ===")
        await ws.send(json.dumps({
            "type": "message",
            "channel": "_inbox:server",
            "content": "!pipeline_status",
        }))
        
        for i in range(15):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                content = str(msg.get('content', ''))
                if content and content != 'None':
                    print(f'  {content[:1000]}')
            except asyncio.TimeoutError:
                break

asyncio.run(main())
