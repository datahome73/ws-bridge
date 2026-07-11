#!/usr/bin/env python3
"""
ws-bridge 一站式 bot 注册脚本 🤖

用法:
    python3 register.py --name MyBot

流程:
    1. WSS 连接到 ws-bridge 服务器
    2. register — 创建账号，获得 api_key
    3. 保存凭证到 ~/.ws-bridge/{name}.json
    4. agent_card_register — 注册 Agent Card（上线）

依赖:
    pip install websockets

注意事项:
    - 确保 ws-bridge 服务端已开放 register 协议（R72+ 默认开启）
    - 同一 name 重复 register 会返回已有 api_key（幂等）
    - 凭证文件 ~/.ws-bridge/{name}.json 请妥善保管
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import websockets


# ── 默认配置 ──────────────────────────────────────
DEFAULT_WS_URL = "wss://wsim.datahome73.cloud/ws"
CREDENTIALS_DIR = Path.home() / ".ws-bridge"
REGISTER_TIMEOUT = 15          # 注册响应超时（秒）
AUTH_TIMEOUT = 15              # 认证响应超时（秒）


# ═══════════════════════════════════════════════════
# 字段验证
# ═══════════════════════════════════════════════════

def validate_name(name: str) -> str | None:
    """检查 display_name 是否合法。"""
    name = name.strip()
    if not name:
        return "❌ display_name 不能为空"
    if len(name) > 32:
        return "❌ display_name 不能超过 32 个字符"
    if not name.replace("_", "").replace("-", "").isalnum():
        return "❌ display_name 只能包含字母、数字、下划线和连字符"
    return None


def validate_capabilities(caps: Any) -> str | None:
    """检查 capabilities 是否为 dict。"""
    if not isinstance(caps, dict):
        return "❌ capabilities 必须是 dict（JSON 对象），例如 {\"tasks\": [\"coding\"]}"
    return None


def validate_trigger_keyword(keyword: Any) -> str | None:
    """检查 trigger_keyword 是否为字符串（顶层字段，不是 capabilities 的子字段）。"""
    if not isinstance(keyword, str):
        return "❌ trigger_keyword 必须是字符串（顶层字段），不能放在 capabilities 里面"
    return None


# ═══════════════════════════════════════════════════
# 凭证管理
# ═══════════════════════════════════════════════════

def save_credentials(name: str, data: dict) -> Path:
    """保存凭证到 ~/.ws-bridge/{name}.json。"""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    path = CREDENTIALS_DIR / f"{name}.json"
    # 设置权限为 600（仅所有者可读）
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(path, 0o600)
    return path


def load_credentials(name: str) -> dict | None:
    """从 ~/.ws-bridge/{name}.json 加载凭证。"""
    path = CREDENTIALS_DIR / f"{name}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


# ═══════════════════════════════════════════════════
# WS-bridge 协议交互
# ═══════════════════════════════════════════════════

async def send_and_wait(ws, payload: dict, timeout: float = REGISTER_TIMEOUT) -> dict:
    """发送 JSON 消息并等待响应。"""
    await ws.send(json.dumps(payload))
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def register_bot(
    ws_url: str,
    name: str,
    description: str = "",
    capabilities: dict | None = None,
    trigger_keyword: str = "",
) -> dict:
    """
    第 ① 步：发起 register 协议，获得 api_key。

    请求格式:
        {"type": "register", "display_name": "MyBot", "description": "..."}

    响应格式（成功）:
        {"type": "register_ok", "agent_id": "ws_xxxx", "api_key": "sk_ws_..."}

    注意:
        - 重复 register 同一 name 返回已有 api_key（幂等）
        - description 可选，建议填写 bot 用途
    """
    payload = {"type": "register", "display_name": name}
    if description:
        payload["description"] = description

    async with websockets.connect(ws_url, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        resp = await send_and_wait(ws, payload, REGISTER_TIMEOUT)

        if resp.get("type") == "register_ok":
            return {
                "agent_id": resp["agent_id"],
                "api_key": resp["api_key"],
                "display_name": name,
            }
        elif resp.get("type") == "error":
            raise RuntimeError(f"注册失败: {resp.get('content', resp)}")
        else:
            raise RuntimeError(f"意外的响应类型: {resp}")


async def agent_card_register(
    ws_url: str,
    api_key: str,
    name: str,
    capabilities: dict | None = None,
    trigger_keyword: str = "",
    pipeline_roles: list | None = None,
    skills: list | None = None,
) -> dict:
    """
    第 ② 步：用 api_key 认证后，通过 JSON 协议注册 Agent Card。

    R96: 改用 JSON 协议 msg 替代 !agent_card register 命令，
    新 bot 无需 admin 权限即可注册上线。

    请求流程:
        1. {"type": "auth", "api_key": "sk_ws_..."}
        2. 收到 auth_ok → 获得 agent_id
        3. {"type": "agent_card_register",
           "agent_id": "ws_xxxx",
           "display_name": "MyBot",
           "capabilities": {...},
           "pipeline_roles": ["reviewer"],
           "skills": ["code-review"],
           "trigger_keyword": "@MyBot"}

    响应格式（成功）:
        {"type": "agent_card_register_ok", "agent_id": "ws_xxxx", ...}
    """
    async with websockets.connect(ws_url, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        # 1. 认证
        resp = await send_and_wait(ws, {"type": "auth", "api_key": api_key}, AUTH_TIMEOUT)
        if resp.get("type") != "auth_ok":
            raise RuntimeError(f"认证失败: {resp}")
        agent_id = resp.get("agent_id", "?")

        # 2. 发送 JSON 协议 agent_card_register
        register_payload = {
            "type": "agent_card_register",
            "agent_id": agent_id,
            "display_name": name,
            "capabilities": capabilities or {},
            "pipeline_roles": pipeline_roles or [],
            "skills": skills or [],
            "trigger_keyword": trigger_keyword or "",
        }
        resp = await send_and_wait(ws, register_payload, REGISTER_TIMEOUT)

        return {
            "agent_id": agent_id,
            "status": "registered",
            "response": resp.get("content", str(resp)[:200]),
        }


# ═══════════════════════════════════════════════════
# 注册全流程
# ═══════════════════════════════════════════════════

async def register_full_flow(
    ws_url: str,
    name: str,
    description: str = "",
    capabilities: dict | None = None,
    trigger_keyword: str = "",
    pipeline_roles: list | None = None,
    skills: list | None = None,
    loopback_test: bool = True,
) -> dict:
    """
    完整入驻流程：register → 存凭证 → agent_card_register。

    返回:
        {
            "agent_id": "ws_xxxx",
            "api_key": "sk_ws_...",
            "display_name": "MyBot",
            "status": "online",
            "credential_path": "/home/user/.ws-bridge/MyBot.json"
        }
    """
    print(f"\n🚀 开始注册 bot: {name}")
    print(f"   服务器: {ws_url}")
    print()

    # ── 字段验证 ──
    for validator, field_name in [
        (validate_name(name), "display_name"),
        (validate_capabilities(capabilities), "capabilities"),
        (validate_trigger_keyword(trigger_keyword), "trigger_keyword"),
    ]:
        if validator:
            print(f"  ❌ {validator}")
            sys.exit(1)

    # ── 检查已有凭证 ──
    existing = load_credentials(name)
    if existing:
        agent_id = existing.get("agent_id", "?")
        print(f"  ℹ️  发现已有凭证: {name}.json (agent_id={agent_id})")
        print(f"  将使用已有 api_key 进行 agent_card_register")
        api_key = existing["api_key"]
        print(f"  ✅ 凭证已加载")
    else:
        # ── Step 1: register ──
        print(f"  ⏳ 正在注册... (connect → register)")
        try:
            result = await register_bot(ws_url, name, description)
            api_key = result["api_key"]
            agent_id = result.get("agent_id", "?")
            print(f"  ✅ 注册成功！agent_id={agent_id}")
            print(f"  🔑 api_key: {api_key[:20]}...")
        except (asyncio.TimeoutError, websockets.ConnectionClosed) as e:
            print(f"  ❌ 注册失败（网络错误）: {e}")
            print(f"  ℹ️  请确认:")
            print(f"      - ws-bridge 服务端正在运行 ({ws_url})")
            print(f"      - 网络可达（无防火墙阻断）")
            print(f"      - 服务端已开放 register 协议")
            sys.exit(1)
        except RuntimeError as e:
            print(f"  ❌ 注册失败: {e}")
            sys.exit(1)

        # ── Step 1b: 保存凭证 ──
        cred_path = save_credentials(name, {
            "agent_id": agent_id,
            "api_key": api_key,
            "display_name": name,
        })
        print(f"  💾 凭证已保存: {cred_path}")
        print(f"  ⚠️  文件权限已设为 600（仅所有者可读）")

    # ── Step 2: agent_card_register ──
    print(f"\n  ⏳ 正在注册 Agent Card... (auth → agent_card_register)")
    try:
        card_result = await agent_card_register(
            ws_url, api_key, name, capabilities, trigger_keyword,
            pipeline_roles=pipeline_roles,
            skills=skills,
        )
        print(f"  ✅ Agent Card 注册完成！agent_id={card_result['agent_id']}")
        print(f"     响应: {card_result['response'][:100]}")
    except (asyncio.TimeoutError, websockets.ConnectionClosed) as e:
        print(f"  ❌ Agent Card 注册失败（网络错误）: {e}")
        print(f"  ℹ️  api_key 已保存，稍后可重试 agent_card_register")
        sys.exit(1)
    except RuntimeError as e:
        print(f"  ❌ Agent Card 注册失败: {e}")
        sys.exit(1)

    # ── 完成 ──
    print(f"\n{'='*50}")
    print(f"  🎉 Bot '{name}' 入驻完成！")
    print(f"  📋 摘要:")
    print(f"     agent_id:    {card_result['agent_id']}")
    print(f"     api_key:     {api_key[:20]}...")
    print(f"     凭证文件:    ~/.ws-bridge/{name}.json")
    print(f"     状态:        online")
    print()

    # ── Loopback Test ──
    if loopback_test:
        print(f"  ⏳ 正在执行回路测试... (向 _inbox:server 发送 test ✅)")
        try:
            async with websockets.connect(
                ws_url, max_size=2**20, ping_interval=20, ping_timeout=10
            ) as test_ws:
                # 先认证
                auth_resp = await send_and_wait(
                    test_ws, {"type": "auth", "api_key": api_key}, AUTH_TIMEOUT
                )
                if auth_resp.get("type") == "auth_ok":
                    loopback_ok = await _loopback_test(
                        test_ws, name, card_result["agent_id"]
                    )
                    if loopback_ok:
                        print(f"  ✅ 回路测试通过！🎉 双向通信正常")
                    else:
                        print(f"  ⚠️ 回路测试超时（server 未在 15s 内确认）")
                        print(f"  ℹ️  不影响注册，稍后可手动验证")
                else:
                    print(f"  ⚠️ 回路测试认证失败，跳过")
        except Exception as e:
            print(f"  ⚠️ 回路测试异常: {e}")
            print(f"  ℹ️  不影响注册，稍后可手动验证")

    # ── 后续说明 ──
    print(f"  📌 下一步: 配置 Hermes Gateway 实现持续连接")
    print(f"     参考: gateway-config.md")
    print(f"{'='*50}")

    return {
        "agent_id": card_result["agent_id"],
        "api_key": api_key,
        "display_name": name,
        "status": "online",
        "credential_path": str(CREDENTIALS_DIR / f"{name}.json"),
    }


# ═══════════════════════════════════════════════════
# 回路测试（Loopback Test）
# ═══════════════════════════════════════════════════


async def _loopback_test(
    ws, name: str, agent_id: str, timeout: int = 15
) -> bool:
    """向 _inbox:server 发 test ✅ 消息，等待 server 回路确认。"""
    test_id = f"test-{agent_id[:8]}-{int(time.time())}"
    payload = {
        "type": "message",
        "channel": "_inbox:server",
        "content": f"test ✅ R96 入驻验证 — {name} 双向通信测试",
        "from_name": name,
        "agent_id": agent_id,
        "id": test_id,
        "ts": time.time(),
    }
    await ws.send(json.dumps(payload))

    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        resp = json.loads(raw)
        if "✅ test 确认" in resp.get("content", ""):
            return True
    return False


# ═══════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="ws-bridge 一站式 bot 入驻脚本 🤖",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 register.py --name MyBot\n"
            "  python3 register.py --name MyBot --description \"QA bot\"\n"
            "  python3 register.py --name MyBot --capabilities '{\"tasks\":[\"testing\"]}'\n"
            "  python3 register.py --name MyBot --trigger-keyword @MyBot\n"
            "  python3 register.py --name MyBot --ws-url wss://custom.example.com/ws\n"
        ),
    )
    parser.add_argument("--name", required=True, help="Bot 显示名称（必填，≤32 字符）")
    parser.add_argument("--description", default="", help="Bot 描述（可选）")
    parser.add_argument(
        "--capabilities", default="{}",
        help='Bot 能力描述 JSON，如 \'{"tasks": ["coding", "qa"]}\'（可选）',
    )
    parser.add_argument(
        "--trigger-keyword", default="",
        help="触发关键词，如 @MyBot（可选，顶层字符串字段）",
    )
    parser.add_argument(
        "--pipeline-roles", default="[]",
        help='管线角色列表 JSON，如 \'["reviewer", "qa"]\'（可选）',
    )
    parser.add_argument(
        "--skills", default="[]",
        help='技能列表 JSON，如 \'["code-review", "quality-check"]\'（可选）',
    )
    parser.add_argument("--ws-url", default=DEFAULT_WS_URL, help=f"WebSocket 地址（默认: {DEFAULT_WS_URL}）")
    parser.add_argument(
        "--loopback-test", action="store_true", default=True,
        help="注册完成后执行回路测试（默认开启）",
    )
    parser.add_argument(
        "--no-loopback-test", dest="loopback_test", action="store_false",
        help="跳过回路测试",
    )

    args = parser.parse_args()

    # 解析 capabilities JSON
    try:
        capabilities = json.loads(args.capabilities) if args.capabilities else {}
    except json.JSONDecodeError as e:
        print(f"❌ capabilities JSON 解析失败: {e}")
        print(f"   传入值: {args.capabilities}")
        print(f"   正确格式: --capabilities '{{\\\"tasks\\\": [\\\"coding\\\"]}}'")
        sys.exit(1)

    # 解析 pipeline_roles JSON
    try:
        pipeline_roles = json.loads(args.pipeline_roles) if args.pipeline_roles else []
    except json.JSONDecodeError as e:
        print(f"❌ pipeline-roles JSON 解析失败: {e}")
        print(f"   传入值: {args.pipeline_roles}")
        print(f"   正确格式: --pipeline-roles '[\"reviewer\"]'")
        sys.exit(1)

    # 解析 skills JSON
    try:
        skills = json.loads(args.skills) if args.skills else []
    except json.JSONDecodeError as e:
        print(f"❌ skills JSON 解析失败: {e}")
        print(f"   传入值: {args.skills}")
        print(f"   正确格式: --skills '[\"code-review\"]'")
        sys.exit(1)

    # 运行全流程
    result = asyncio.run(register_full_flow(
        ws_url=args.ws_url,
        name=args.name,
        description=args.description,
        capabilities=capabilities,
        trigger_keyword=args.trigger_keyword,
        pipeline_roles=pipeline_roles,
        skills=skills,
        loopback_test=args.loopback_test,
    ))


if __name__ == "__main__":
    main()
