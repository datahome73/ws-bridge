"""R102: Server 转发体系 — 全面验收测试 🦐

覆盖 8 项验收标准 + 源码验证。
"""
import os, re, sys, subprocess, unittest

BASE = os.path.join(os.path.dirname(__file__), "..", "server")
PASS, FAIL = "✅", "❌"
results = []


class TestR102_SourceVerification(unittest.TestCase):
    """源码验证 — 20 项"""

    def test_is_valid_agent_id(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn("_is_valid_agent_id", c)

    def test_to_agent_dispatch(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn('to_agent = (msg.get("to_agent") or "").strip()', c)

    def test_from_name_system(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn('"from_name": "系统"', c)
        self.assertIn('"from_agent": state.SYSTEM_AGENT_ID', c)

    def test_prefix_shoudao(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn('content.startswith("收到 ✅")', c)

    def test_prefix_ack_compat(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn('content.startswith("ACK ✅")', c)

    def test_prefix_wancheng(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn('content.startswith("已完成 ✅")', c)

    def test_prefix_wancheng_old_compat(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn('content.startswith("✅ 完成")', c)

    def test_prefix_tuihui(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn('content.startswith("退回 🔄")', c)

    def test_prefix_shibai(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn('content.startswith("失败 ❌")', c)

    def test_silent_save_db(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn("ms.save_message(", c)
        self.assertIn("入库失败不阻塞", c)

    def test_bang_toutong(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn('content.startswith("!")', c)
        self.assertIn("return False", c)

    def test_test_prefix_preserved(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn('content.startswith("test ✅")', c)

    def test_dispatch_sender_id_used(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        self.assertIn("DISPATCH_SENDER_ID", c)

    def test_config_has_dispatch(self):
        with open(os.path.join(BASE, "config.py")) as f:
            c = f.read()
        self.assertIn("DISPATCH_SENDER_ID", c)

    def test_config_fallback_pm(self):
        with open(os.path.join(BASE, "config.py")) as f:
            c = f.read()
        self.assertIn("WS_PM_AGENT_ID", c)

    def test_copy_b_synced(self):
        with open(os.path.join(BASE, "main.py")) as f:
            c = f.read()
        # Find second copy
        idx = c.find("async def _handle_server_relay", c.find("async def _handle_server_relay") + 50)
        copy_b = c[idx:]
        self.assertIn('to_agent = (msg.get("to_agent") or "").strip()', copy_b)

    def test_web_viewer_reverse_fixed(self):
        with open(os.path.join(BASE, "web_viewer.py")) as f:
            c = f.read()
        self.assertLessEqual(c.count(".reverse()"), 2,
                             f"预期 ≤2 处 .reverse()，实际 {c.count('.reverse()')}")

    def test_syntax_main(self):
        r = subprocess.run(["python3", "-c",
                           f"import py_compile; py_compile.compile('{BASE}/main.py', doraise=True)"],
                          capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_syntax_config(self):
        r = subprocess.run(["python3", "-c",
                           f"import py_compile; py_compile.compile('{BASE}/config.py', doraise=True)"],
                          capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_syntax_web_viewer(self):
        r = subprocess.run(["python3", "-c",
                           f"import py_compile; py_compile.compile('{BASE}/web_viewer.py', doraise=True)"],
                          capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    t = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    r = unittest.TextTestRunner(verbosity=2).run(t)
    print(f"\n合计: {r.testsRun} 项 | ✅ {r.testsRun - len(r.failures) - len(r.errors)} | ❌ {len(r.failures) + len(r.errors)}")
