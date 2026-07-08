import asyncio, json, websockets, os

async def register():
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        # ════ 注册 ════
        await ws.send(json.dumps({
            'type': 'register',
            'display_name': '小谷',
            'description': 'PM 机器人，负责需求管理和项目管线'
        }))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        agent_id = resp['agent_id']
        api_key = resp['api_key']
        print(f'✅ agent_id = {agent_id}')
        print(f'✅ api_key = {api_key}')

        # ════ 保存凭证 ════
        os.makedirs(os.path.expanduser('~/.ws-bridge'), exist_ok=True)
        with open(os.path.expanduser('~/.ws-bridge/小谷.json'), 'w') as f:
            json.dump({'agent_id': agent_id, 'api_key': api_key, 'display_name': '小谷'}, f, indent=2)
        print('📁 已保存 ~/.ws-bridge/小谷.json')

        # 清空残留
        await asyncio.sleep(0.5)
        for _ in range(3):
            try: await asyncio.wait_for(ws.recv(), timeout=0.3)
            except: break

        # ════ Agent Card 注册 ════
        await ws.send(json.dumps({
            'type': 'agent_card_register',
            'display_name': '小谷',
            'description': 'PM 机器人',
            'pipeline_roles': ['pm'],
            'skills': ['需求分析', '项目管理'],
            'trigger_keyword': '小谷;PM;需求分析师',
            'capabilities': {
                'platforms': ['ws-bridge'],
                'skills': ['需求分析', '项目管理'],
            },
        }))
        card = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert card.get('display_name') == '小谷', f'display_name 不匹配: {card}'
        print(f'📇 Card OK: status={card.get("status")}, agent_id={card.get("agent_id")}')
        print(f'📇 详情: {json.dumps(card, ensure_ascii=False)}')

asyncio.run(register())
