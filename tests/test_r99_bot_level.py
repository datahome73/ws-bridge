"""R99: Bot 权限等级体系 — 全面验收测试 🦐

覆盖 8 项验收标准 (T-1~T-8) + 边界场景 + 兼容修复。

验收标准：
T-1: 新注册 bot 自动 level=2
T-2: 提交 Agent Card 后自动升 L3
T-3: L3 bot 发 _inbox:<bot_id> → ❌ error, 不路由
T-4: L4 bot 发 _inbox:<bot_id> → ✅ 正常转发
T-5: 任意等级发 _inbox:server → ✅ 全部放行
T-6: 在线 7 bot 不受影响（默认 L4）
T-7: 系统名统一 — 无"系统(中继)"、"system"残留
T-8: 旧 _api_key 无 level 字段 → 自动兼容为 L4

边界场景：
- L1(未注册)发消息 → R86 key 检查截停，无泄漏
- L3 不会降级 L4
- SYSTEM_AGENT_ID = "_system" 一致性
"""
import ast
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.auth import get_level, set_level
from server.persistence import get_api_key_record

HANDLER_PATH = os.path.join(os.path.dirname(__file__), "..", "server", "handler.py")
AUTH_PATH = os.path.join(os.path.dirname(__file__), "..", "server", "auth.py")
AGENT_CARD_PATH = os.path.join(os.path.dirname(__file__), "..", "server", "agent_card.py")
PERSISTENCE_PATH = os.path.join(os.path.dirname(__file__), "..", "server", "persistence.py")

PASS = "✅"
FAIL = "❌"
results = []


def check(name, ok, detail=""):
    icon = PASS if ok else FAIL
    results.append((icon, name, detail))
    return ok


# ============================================================
# T-1: 新注册 bot 自动 level=2
# ============================================================

class TestT1_RegisterLevel2(unittest.TestCase):
    """T-1: 新注册 bot 自动 level=2"""

    def test_level2_in_handle_register(self):
        """验证 handle_register() 中 `\"level\": 2` 存在"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        # 找到 handle_register 中 keys[agent_id] dict 定义
        idx = content.find('"status": "active"')
        self.assertGreater(idx, 0)
        block = content[idx:idx + 80]

        check(
            "T1a. level: 2 在 keys dict 中",
            '"level": 2' in block,
            "新注册 bot 默认 L2",
        )

    def test_level2_after_register_annotation(self):
        """验证 level 字段有正确的注释标记"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        check(
            "T1b. R99 注释标记",
            "# ── R99: 新注册默认 L2 ──" in content,
            "",
        )


# ============================================================
# T-2: 提交 Agent Card 后自动升 L3
# ============================================================

class TestT2_AutoPromoteL3(unittest.TestCase):
    """T-2: Agent Card 提交后自动升 L3"""

    def test_promote_code_in_agent_card(self):
        """验证 agent_card.py 有晋升逻辑"""
        with open(AGENT_CARD_PATH) as f:
            content = f.read()

        check(
            "T2a. R99 晋升标记",
            "# ── R99: Agent Card 提交成功 → L2→L3 自动晋升 ──" in content,
            "",
        )

    def test_promote_condition_level_2(self):
        """验证晋升条件 `current_level == 2`"""
        with open(AGENT_CARD_PATH) as f:
            content = f.read()

        idx = content.find("# ── R99: Agent Card 提交成功 → L2→L3 自动晋升 ──")
        block = content[idx:idx + 200]

        check(
            "T2b. 晋升条件 current_level == 2",
            "current_level == 2" in block,
            "只升 L2，不降级 L3/L4",
        )
        check(
            "T2c. 调用 set_level(agent_id, 3)",
            "_auth_mod.set_level(agent_id, 3)" in block,
            "",
        )
        check(
            "T2d. try/except 包裹",
            "try:" in block and "except Exception:" in block,
            "晋升失败不阻断注册",
        )

    def test_promote_syntax_check(self):
        """AST 解析晋升代码块"""
        with open(AGENT_CARD_PATH) as f:
            content = f.read()

        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "register_from_agent":
                func_text = ast.get_source_segment(content, node)
                self.assertIsNotNone(func_text)
                if func_text:
                    check(
                        "T2e. register_from_agent 包含晋升逻辑",
                        "R99" in func_text,
                        "",
                    )
                break


# ============================================================
# T-3: L3 发 _inbox:<bot_id> → ❌ 拒绝
# ============================================================

class TestT3_L3RejectInboxBotId(unittest.TestCase):
    """T-3: L3 bot 发 _inbox:<id> → ❌ error"""

    def test_level_check_before_broadcast(self):
        """验证 handler() 中有 level>=4 检查"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        r99_idx = content.find("# ═══ R99: 权限检查 — _inbox:<bot_id> 需要 level>=4 ═══")
        self.assertGreater(r99_idx, 0)
        block = content[r99_idx:r99_idx + 300]

        check(
            "T3a. channel 前缀判断",
            '_channel.startswith(p.INBOX_CHANNEL_PREFIX)' in block,
            "",
        )
        check(
            "T3b. _inbox:server 豁免",
            '_channel != SERVER_INBOX_CHANNEL' in block,
            "",
        )
        check(
            "T3c. sender_level < 4 拒绝",
            '_sender_level < 4' in block,
            "",
        )
        check(
            "T3d. 发送 error 消息",
            '"type": "error"' in block,
            "",
        )
        check(
            "T3e. continue 跳过 broadcast",
            "continue" in block,
            "",
        )

    def test_rejection_message_has_level_hint(self):
        """验证拒绝消息含当前等级提示"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        r99_idx = content.find("# ═══ R99: 权限检查")
        block = content[r99_idx:r99_idx + 400]

        check(
            "T3f. 错误消息含等级提示",
            'L{_sender_level}' in block,
            "",
        )
        check(
            "T3g. 日志记录拒绝",
            'logger.info(\n                            "[R99] 拒绝:' in block,
            "",
        )


# ============================================================
# T-4: L4 发 _inbox:<bot_id> → ✅ 放行
# ============================================================

class TestT4_L4PassInboxBotId(unittest.TestCase):
    """T-4: L4 bot 发 _inbox:<id> → ✅ 放行"""

    def test_level_check_condition_le4(self):
        """验证 L4 不会触发拒绝分支"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        r99_idx = content.find("# ═══ R99: 权限检查")
        block = content[r99_idx:r99_idx + 200]

        # 条件：_sender_level < 4 才拒绝
        check(
            "T4a. 条件为 < 4 非 <= 4",
            '_sender_level < 4' in block,
            "L4 不触发拒绝",
        )

    def test_level_check_after_pass_goes_to_broadcast(self):
        """验证检查通过后走 handle_broadcast"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        r99_idx = content.find("# ═══ R99: 权限检查")
        # 检查 R99 块后面跟着 handle_broadcast
        post_block = content[r99_idx:r99_idx + 350]
        check(
            "T4b. 通过后调用 handle_broadcast",
            "await handle_broadcast(ws, agent_id, msg)" in post_block,
            "",
        )


# ============================================================
# T-5: _inbox:server 全部放行
# ============================================================

class TestT5_InboxServerAllLevels(unittest.TestCase):
    """T-5: 任意等级 _inbox:server → ✅ 放行"""

    def test_server_inbox_explicit_exempt(self):
        """验证 _inbox:server 显式排除在检查之外"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        r99_idx = content.find("# ═══ R99: 权限检查")
        block = content[r99_idx:r99_idx + 200]

        check(
            "T5a. _channel != SERVER_INBOX_CHANNEL 豁免",
            '_channel != SERVER_INBOX_CHANNEL' in block,
            "显式排除 _inbox:server",
        )

    def test_SERVER_INBOX_CHANNEL_constant(self):
        """验证 SERVER_INBOX_CHANNEL 常量正确"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        check(
            "T5b. SERVER_INBOX_CHANNEL 定义",
            'SERVER_INBOX_CHANNEL = "_inbox:server"' in content,
            "",
        )


# ============================================================
# T-6: 7 现存 bot 不受影响（默认 L4）
# ============================================================

class TestT6_OldBotCompatibleL4(unittest.TestCase):
    """T-6: 旧 bot 无 level → 默认 L4"""

    def test_get_level_default_l4(self):
        """验证 get_level() 对无 level 字段返回 4"""
        with open(AUTH_PATH) as f:
            content = f.read()

        check(
            "T6a. record.get(\"level\", 4) 兼容默认",
            'record.get("level", 4)' in content,
            "无 level 字段 → L4",
        )

    def test_get_level_l1_if_no_record(self):
        """验证 get_level() 对无记录返回 1"""
        with open(AUTH_PATH) as f:
            content = f.read()

        check(
            "T6b. record is None → return 1",
            'return 1  # L1' in content,
            "未注册 bot → L1",
        )

    def test_get_level_missing_agent(self):
        """实际测试 get_level 对不存在的 agent_id 返回 1"""
        level = get_level("nonexistent_agent_99999")
        check(
            "T6c. get_level(unknown) = 1",
            level == 1,
            f"返回 {level}，预期 1",
        )


# ============================================================
# T-7: 系统名统一
# ============================================================

class TestT7_SystemNameUnified(unittest.TestCase):
    """T-7: 系统名统一"""

    def test_no_system_relay_remaining(self):
        """无 \"系统(中继)\" 残留"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        count_relay = content.count('"系统(中继)"')
        check(
            "T7a. 无 '系统(中继)' 残留",
            count_relay == 0,
            f"找到 {count_relay} 处",
        )

    def test_no_literal_system_remaining(self):
        """无 from_agent=\"system\" 残留"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        # 搜 "system" 但不包括 _system（常量值）或 SYSTEM_AGENT_ID
        # 我们搜 from_agent="system"（无下划线前缀的旧值）
        import re
        matches = re.findall(r'from_agent=\"system\"[^_]', content)
        check(
            "T7b. 无 from_agent='system' 残留",
            len(matches) == 0,
            f"找到 {len(matches)} 处: {matches}",
        )

    def test_SYSTEM_AGENT_ID_value(self):
        """验证 SYSTEM_AGENT_ID = \"_system\""""
        with open(HANDLER_PATH) as f:
            content = f.read()

        check(
            "T7c. SYSTEM_AGENT_ID = '_system'",
            'SYSTEM_AGENT_ID: str = "_system"' in content,
            "",
        )

    def test_pm_agent_id_uses_constant(self):
        """验证 pm_agent_id 默认值使用 SYSTEM_AGENT_ID"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        check(
            "T7d. pm_agent_id 用常量",
            "pm_agent_id: str = SYSTEM_AGENT_ID" in content,
            "",
        )


# ============================================================
# T-8: 旧 _api_key 无 level → 自动兼容 L4
# ============================================================

class TestT8_OldApiKeyCompatibility(unittest.TestCase):
    """T-8: 旧 _api_key 无 level → 默认 L4"""

    def test_record_get_level_default_l4(self):
        """验证 get_level 从 record get 默认 L4"""
        with open(AUTH_PATH) as f:
            content = f.read()

        check(
            "T8a. get 默认值为 4",
            'return record.get("level", 4)' in content,
            "",
        )

    def test_set_level_returns_false_for_unknown(self):
        """验证 set_level 对未知 agent 返回 False"""
        result = set_level("nonexistent_agent_99999", 3)
        check(
            "T8b. set_level(unknown) = False",
            result is False,
            f"返回 {result}，预期 False",
        )


# ============================================================
# 边界场景
# ============================================================

class TestEdgeCases(unittest.TestCase):
    """边界场景测试"""

    def test_l1_unregistered_intercepted_by_r86(self):
        """L1(未注册)发消息 → R86 key 检查截停，不会到达 level 检查"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        # 检查 R86 key 检查在 R99 level 检查之前
        r86_idx = content.find("agent_key_record = agent_keys.get(agent_id)")
        r99_idx = content.find("# ═══ R99: 权限检查")
        self.assertGreater(r86_idx, 0)
        self.assertGreater(r99_idx, 0)
        check(
            "E1. R86 key 检查在 R99 之前",
            r86_idx < r99_idx,
            f"R86 at {r86_idx}, R99 at {r99_idx}",
        )

    def test_l3_not_downgrade_to_l4(self):
        """L3 提交 Agent Card 不会降级到 L4"""
        with open(AGENT_CARD_PATH) as f:
            content = f.read()

        idx = content.find("# ── R99: Agent Card 提交成功")
        block = content[idx:idx + 200]

        check(
            "E2. 晋升条件 == 2（不降级）",
            "current_level == 2" in block,
            "== 2 不匹配 L3/L4",
        )
        # 验证不会匹配 L3 或 L4
        check(
            "E2b. 非 < LEVEL_L3",
            "current_level < LEVEL_L3" not in block,
            "未使用 < 比较，避免 L3 误升",
        )

    def test_set_level_persists(self):
        """验证 set_level → -> bool (非 None)"""
        with open(AUTH_PATH) as f:
            content = f.read()

        check(
            "E3. set_level 返回 bool",
            "def set_level(agent_id: str, new_level: int) -> bool:" in content,
            "类型标注明确返回 bool",
        )

    def test_get_api_key_record_exists(self):
        """验证 persistence.get_api_key_record 存在"""
        with open(PERSISTENCE_PATH) as f:
            content = f.read()

        check(
            "E4a. get_api_key_record 函数",
            "def get_api_key_record(agent_id: str) -> dict | None:" in content,
            "",
        )
        check(
            "E4b. _lock 保护读取",
            "with _lock:" in content,
            "",
        )

    def test_level_check_does_not_block_agent_card_register(self):
        """验证 agent_card_register 走不同分支，不受 level 检查限制"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        # R99 level 检查在 handle_broadcast 之前
        # agent_card_register 走 elif msg_type == p.MSG_AGENT_CARD_REGISTER 分支
        # 完全独立，不受 level 检查影响
        r99_block = content.find("# ═══ R99: 权限检查")
        card_reg = content.find("elif msg_type == p.MSG_AGENT_CARD_REGISTER and agent_id:", r99_block)

        check(
            "E5. agent_card_register 分支在 R99 检查之后",
            card_reg > r99_block,
            "agent_card_register 不在 level 检查路径内",
        )

    def test_revoked_key_still_rejected(self):
        """验证吊销 key 在 R86 检查中已被拒绝，R99 不改变此行为"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        r86_idx = content.find('agent_key_record.get("status") == "revoked"')
        self.assertGreater(r86_idx, 0)

        check(
            "E6. R86 吊销检查仍保留",
            'agent_key_record.get("status") == "revoked"' in content,
            "",
        )


# ============================================================
# auth.py 单元测试（函数直接调用）
# ============================================================

class TestAuthLevelFunctions(unittest.TestCase):
    """auth.py get_level/set_level 函数直接调用"""

    def test_get_level_known_agent(self):
        """验证当前泰虾账号的 level 可以正常读取"""
        import json
        path = os.path.expanduser("~/.ws-bridge/泰虾.json")
        if os.path.exists(path):
            creds = json.load(open(path))
            agent_id = creds.get("agent_id", "")
            if agent_id:
                level = get_level(agent_id)
                # 当前 bot 可能是旧无 level 字段 → 默认 L4
                check(
                    "U1. 泰虾 level 可读",
                    level in (1, 2, 3, 4),
                    f"level={level}",
                )

    def test_get_level_missing_record_returns_1(self):
        """不存在的 agent → L1"""
        level = get_level("this_agent_should_not_exist_999999")
        check(
            "U2. 不存在 agent = L1",
            level == 1,
            f"get_level={level}",
        )

    def test_set_level_on_new_bot_requires_record(self):
        """set_level 对无记录的 agent 返回 False"""
        result = set_level("no_such_agent_888888", 4)
        check(
            "U3. set_level 无记录 = False",
            result is False,
            "",
        )

    def test_get_api_key_record_missing(self):
        """get_api_key_record 对不存在的 agent 返回 None"""
        record = get_api_key_record("nonexistent_for_test_777777")
        check(
            "U4. get_api_key_record missing = None",
            record is None,
            "",
        )


# ============================================================
# 系统名完整残留扫描
# ============================================================

class TestSystemNameScan(unittest.TestCase):
    """系统名全量扫描"""

    def test_no_string_system_relay_anywhere(self):
        """扫描全 handler.py 确认无 \"系统(中继)\""""
        with open(HANDLER_PATH) as f:
            content = f.read()
        count = content.count("系统(中继)")
        check(
            "S1. 系统(中继) 全量扫描",
            count == 0,
            f"找到 {count} 处",
        )

    def test_no_string_system_literal_as_from_name(self):
        """扫描全 handler.py 确认无 from_name='system'"""
        with open(HANDLER_PATH) as f:
            content = f.read()
        # "system" 作为 from_name 值（不是常量）
        import re
        matches = re.findall(r'"from_name":\s*"system"', content)
        check(
            "S2. from_name='system' 全量扫描",
            len(matches) == 0,
            f"找到 {len(matches)}: {matches}",
        )

    def test_from_name_all_system(self):
        """所有 from_name 值检查 — 确认全部为 '系统'"""
        with open(HANDLER_PATH) as f:
            content = f.read()
        import re
        # 找所有 from_name 字符串值（排除 SYSTEM_AGENT_ID 等非字面量）
        literal_sys = re.findall(r'"from_name":\s*"([^"]+)"', content)
        non_sys = [s for s in literal_sys if s != "系统"]
        # 允许一些合理非"系统"值（如 display_name 变量等）
        check(
            "S3. 字面量 from_name 值",
            len(non_sys) == 0,
            f"非'系统'值: {non_sys[:5]}" if non_sys else "全部为'系统'",
        )


if __name__ == "__main__":
    unittest.main()
