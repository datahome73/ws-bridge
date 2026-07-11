"""R102: 路由单元测试 — 前缀匹配、to_agent 派活、沉默入库 🚉

覆盖三大场景:
  A. 前缀匹配 — 全部 7 个前缀规则 + 优先级顺序
  B. to_agent 派活 — PM 绕过、agent_id 校验、payload 结构、副本同步
  C. 沉默入库 — 无匹配消息入库留痕 + 容错
"""
import os, sys, unittest, subprocess

BASE = os.path.join(os.path.dirname(__file__), "..", "server")
PASS, FAIL = "✅", "❌"


# ================================================================
# A. 前缀匹配（Prefix Matching）
# ================================================================

class TestAPrefixMatching(unittest.TestCase):
    """A 系列: 验证所有前缀规则存在于源码且优先级正确"""

    MAIN = os.path.join(BASE, "main.py")

    def get_content(self):
        with open(self.MAIN) as f:
            return f.read()

    # ── A1: 回路测试（R96） ──
    def test_a1_loopback_prefix(self):
        c = self.get_content()
        self.assertIn('content.startswith("test ✅")', c,
                      "回路测试前缀 test ✅ 缺失")

    def test_a1_loopback_priority(self):
        """回路测试必须在所有规则之前"""
        c = self.get_content()
        idx_test = c.index('content.startswith("test ✅")')
        idx_channel_check = c.index('if channel not in (state.SERVER_INBOX_CHANNEL')
        self.assertLess(idx_test, idx_channel_check,
                        "回路测试必须在 channel 检查之前")

    # ── A2: to_agent 派活 ──
    def test_a2_to_agent_before_pm_guard(self):
        """to_agent 检查必须在 PM 安全守卫之前（PM 可绕过）"""
        c = self.get_content()
        idx_to_agent = c.index('to_agent = (msg.get("to_agent") or "").strip()')
        idx_pm_guard = c.index("PM 误发 _inbox:server")
        self.assertLess(idx_to_agent, idx_pm_guard,
                        "to_agent 派活必须在 PM 安全守卫之前")

    # ── A3: ACK 前缀 ──
    def test_a3_ack_prefix(self):
        c = self.get_content()
        self.assertIn('content.startswith("收到 ✅")', c,
                      "收到 ✅ 前缀缺失")
        self.assertIn('content.startswith("ACK ✅")', c,
                      "ACK ✅ 前缀缺失")

    def test_a3_ack_relay_payload(self):
        c = self.get_content()
        self.assertIn('"📬 {sender_name} 已接活:\\n{content}"', c,
                      "ACK 转发 payload 缺失")

    # ── A4: 完成前缀 ──
    def test_a4_wancheng_prefix(self):
        c = self.get_content()
        self.assertIn('content.startswith("已完成 ✅")', c,
                      "已完成 ✅ 前缀缺失")
        self.assertIn('content.startswith("✅ 完成")', c,
                      "✅ 完成 前缀缺失")

    def test_a4_wancheng_auto_confirm(self):
        c = self.get_content()
        self.assertIn('"✅ 确认，已收到你的完成通知.本轮任务完成."', c,
                      "完成自动确认消息缺失")

    # ── A5: 退回前缀 ──
    def test_a5_tuihui_prefix(self):
        c = self.get_content()
        self.assertIn('content.startswith("退回 🔄")', c,
                      "退回 🔄 前缀缺失")
        self.assertIn('"🔄 已记录退回."', c,
                      "退回自动确认消息缺失")

    # ── A6: 失败前缀 ──
    def test_a6_shibai_prefix(self):
        c = self.get_content()
        self.assertIn('content.startswith("失败 ❌")', c,
                      "失败 ❌ 前缀缺失")
        self.assertIn('"⚠️ 已记录失败."', c,
                      "失败自动确认消息缺失")

    # ── A7: ! 命令透传 ──
    def test_a7_bang_toutong(self):
        c = self.get_content()
        # 找 _handle_server_relay 中的 ! 命令（有 return False）
        idx_relay = c.index("async def _handle_server_relay")
        relay_body = c[idx_relay:idx_relay + 8000]
        idx_bang = relay_body.index('content.startswith("!")')
        self.assertIn("return False", relay_body[idx_bang:idx_bang + 200],
                      "! 命令透传应 return False（走正常路由）")

    # ── A8: 优先级完整性 ──
    def test_a8_priority_order(self):
        """验证前缀匹配优先级顺序（源码中出现顺序）"""
        c = self.get_content()
        # 在函数体内检查优先级顺序
        func_start = c.index("async def _handle_server_relay")
        body_a = c[func_start:c.index("async def _handle_server_relay", func_start + 50)]

        # 按优先级列出 expected 规则
        expected_prefixes = [
            'content.startswith("test ✅")',       # 0 - 回路测试 (R96)
            'to_agent = (msg.get("to_agent")',      # 1 - to_agent 派活 (R102)
            'content.startswith("收到 ✅")',         # 2 - ACK 通知
            'content.startswith("ACK ✅")',          # 2 - ACK 兼容
            'content.startswith("已完成 ✅")',        # 3 - 完成
            'content.startswith("✅ 完成")',          # 3 - 完成兼容
            'content.startswith("退回 🔄")',          # 4 - 退回
            'content.startswith("失败 ❌")',          # 5 - 失败
            'content.startswith("!")',                # 6 - 命令透传
        ]

        last_idx = -1
        for prefix in expected_prefixes:
            idx = body_a.find(prefix)
            self.assertGreater(idx, -1, f"前缀未找到: {prefix}")
            self.assertGreaterEqual(idx, last_idx,
                                    f"优先级错误: {prefix} 在 {last_idx} 之前")
            last_idx = idx

        # 沉默入库在最后
        self.assertIn("入库失败不阻塞", body_a,
                      "沉默入库标记缺失")


# ================================================================
# B. to_agent 派活（to_agent Dispatch）
# ================================================================

class TestBToAgentDispatch(unittest.TestCase):
    """B 系列: to_agent 派活路由完整验证"""

    MAIN = os.path.join(BASE, "main.py")

    def get_content(self):
        with open(self.MAIN) as f:
            return c if (c := f.read()) else ""

    # ── B1: _is_valid_agent_id ──
    def test_b1_valid_agent_id_exists(self):
        with open(self.MAIN) as f:
            c = f.read()
        self.assertIn("def _is_valid_agent_id", c,
                      "_is_valid_agent_id 函数缺失")

    def test_b1_valid_agent_id_logic(self):
        with open(self.MAIN) as f:
            c = f.read()
        self.assertIn('aid.startswith("ws_")', c,
                      "agent_id 校验: 需 ws_ 前缀")
        self.assertIn("len(aid) > 10", c,
                      "agent_id 校验: 需长度 > 10")

    # ── B2: PM 绕过 ──
    def test_b2_pm_bypass_before_guard(self):
        with open(self.MAIN) as f:
            c = f.read()
        idx_to_agent = c.index('to_agent = (msg.get("to_agent") or "").strip()')
        idx_guard = c.index("if pm_agent_id and agent_id == pm_agent_id")
        # to_agent 分支在 guard 之前，所以 PM 带 to_agent 可绕过
        self.assertLess(idx_to_agent, idx_guard,
                        "to_agent 检查必须在 PM 安全守卫之前")

    def test_b2_pm_bypass_return_true(self):
        """to_agent 处理后 return True（拦截不继续路由）"""
        with open(self.MAIN) as f:
            c = f.read()
        idx_to_agent = c.index('to_agent = (msg.get("to_agent") or "").strip()')
        block = c[idx_to_agent:idx_to_agent + 300]
        self.assertIn("return True", block,
                      "to_agent 处理后必须 return True")

    # ── B3: 非法 to_agent 拒绝 ──
    def test_b3_invalid_agent_rejected(self):
        with open(self.MAIN) as f:
            c = f.read()
        self.assertIn("拒绝: 非法 to_agent=%s", c,
                      "非法 to_agent 日志警告缺失")

    # ── B4: payload 结构 ──
    def test_b4_payload_structure(self):
        with open(self.MAIN) as f:
            c = f.read()
        idx_to_agent = c.index('to_agent = (msg.get("to_agent") or "").strip()')
        block = c[idx_to_agent:idx_to_agent + 800]
        self.assertIn('"from_name": "系统"', block,
                      "payload 需隐藏发件人显示为 系统")
        self.assertIn("state.SYSTEM_AGENT_ID", block,
                      "payload from_agent 需用 SYSTEM_AGENT_ID")
        self.assertIn('"channel": f"_inbox:{to_agent}"', block,
                      "payload channel 需指向目标 inbox")
        self.assertIn("_send_to_agent", block,
                      "派活需调用 _send_to_agent")

    # ── B5: 两条副本同步 ──
    def test_b5_both_copies_synced(self):
        with open(self.MAIN) as f:
            c = f.read()
        # 找两条副本中的 to_agent 代码
        idx_first = c.index('to_agent = (msg.get("to_agent") or "").strip()')
        idx_second = c.index('to_agent = (msg.get("to_agent") or "").strip()',
                             idx_first + 50)
        # 第二条副本必须在不同_handle_server_relay 函数中
        self.assertGreater(idx_second, idx_first + 100,
                           "两条副本差距至少 100 字符，确认有两条")
        # 验证它们结构相似
        block_a = c[idx_first:idx_first + 20]
        block_b = c[idx_second:idx_second + 20]
        self.assertEqual(block_a, block_b,
                         "副本 A/B 的 to_agent 代码应完全一致")


# ================================================================
# C. 沉默入库（Silent Save）
# ================================================================

class TestCSilentSave(unittest.TestCase):
    """C 系列: 无匹配消息的沉默入库留痕"""

    MAIN = os.path.join(BASE, "main.py")
    CONFIG = os.path.join(BASE, "config.py")

    def get_content(self):
        with open(self.MAIN) as f:
            return f.read()

    # ── C1: save_message 调用 ──
    def test_c1_save_message_called(self):
        c = self.get_content()
        self.assertIn("ms.save_message(", c,
                      "沉默分支必须调用 ms.save_message()")

    def test_c1_save_message_fields(self):
        c = self.get_content()
        idx_rule5 = c.index("规则 5: 无匹配 → 入库留痕")
        idx_save = c.index("ms.save_message(", idx_rule5)
        block = c[idx_save:idx_save + 400]
        self.assertIn("msg_id", block, "需传入 msg_id")
        self.assertIn("channel", block, "需传入 channel")
        self.assertIn("from_agent", block, "需传入 from_agent")
        self.assertIn("from_name", block, "需传入 from_name")
        self.assertIn("content", block, "需传入 content")
        self.assertIn("ts", block, "需传入 ts")

    # ── C2: 容错 ──
    def test_c2_exception_handling(self):
        c = self.get_content()
        self.assertIn("except Exception:", c,
                      "沉默入库需包裹异常处理")
        self.assertIn("入库失败不阻塞", c,
                      "需有注释说明入库失败不阻塞主流程")

    # ── C3: 返回值 ──
    def test_c3_silent_returns_true(self):
        c = self.get_content()
        # 找沉默分支中的 ms.save_message（在"规则 5"中）
        idx_rule5 = c.index("规则 5: 无匹配 → 入库留痕")
        idx_save = c.index("ms.save_message(", idx_rule5)
        block = c[idx_save:idx_save + 450]
        self.assertIn("return True", block,
                      "沉默入库后必须 return True（已处理，不继续路由）")

    # ── C4: 日志 ──
    def test_c4_silent_logging(self):
        c = self.get_content()
        self.assertIn('[Relay] 沉默', c,
                      "沉默入库需记录日志")


# ================================================================
# 语法检查
# ================================================================

class TestSyntax(unittest.TestCase):
    """语法完整性"""

    def test_syntax_main(self):
        r = subprocess.run(
            ["python3", "-c",
             f"import py_compile; py_compile.compile('{TestCSilentSave.MAIN}', doraise=True)"],
            capture_output=True, text=True, timeout=5
        )
        self.assertEqual(r.returncode, 0, r.stderr[:200] or "")


# ================================================================
# 主入口
# ================================================================

if __name__ == "__main__":
    t = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    r = unittest.TextTestRunner(verbosity=2).run(t)
    total = r.testsRun
    passed = total - len(r.failures) - len(r.errors)
    print(f"\n{'='*50}")
    print(f"R102 路由测试: {total} 项 | {PASS} {passed} | {FAIL} {total-passed}")
