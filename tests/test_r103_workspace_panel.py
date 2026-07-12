"""R103: Web UI 工作区面板增强 — 验收测试 🦐"""
import os, ast, subprocess, unittest

BASE = os.path.join(os.path.dirname(__file__), "..", "server")
PASS, FAIL = "✅", "❌"


class TestR103_API(unittest.TestCase):
    """API 字段验证"""

    def test_pipeline_round_field(self):
        with open(os.path.join(BASE, "workspace_api.py")) as f:
            tree = ast.parse(f.read())
        found = any(
            isinstance(k, ast.Constant) and k.value == "pipeline_round"
            for node in ast.walk(tree)
            if isinstance(node, ast.Dict)
            for k in node.keys
        )
        self.assertTrue(found)

    def test_roles_field(self):
        with open(os.path.join(BASE, "workspace_api.py")) as f:
            tree = ast.parse(f.read())
        found = any(
            isinstance(k, ast.Constant) and k.value == "roles"
            for node in ast.walk(tree)
            if isinstance(node, ast.Dict)
            for k in node.keys
        )
        self.assertTrue(found)

    def test_syntax_api(self):
        r = subprocess.run(["python3", "-c",
                           f"import py_compile; py_compile.compile('{BASE}/workspace_api.py', doraise=True)"],
                          capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestR103_Frontend(unittest.TestCase):
    """前端模板验证"""

    def setUp(self):
        with open(os.path.join(BASE, "templates.py")) as f:
            self.tpl = f.read()
        idx = self.tpl.find("function buildWsItem")
        end = self.tpl.find("\nfunction ", idx + 5)
        self.body = self.tpl[idx:end] if end > idx else self.tpl[idx:]

    def test_pipeline_round_used(self):
        self.assertIn("pipeline_round", self.body)

    def test_empty_round_ternary(self):
        self.assertIn("pipeline_round", self.body)
        self.assertIn("? ", self.body)

    def test_round_tag_css(self):
        self.assertIn("ws-round-tag", self.body)

    def test_tag_color_from_state(self):
        self.assertIn("+ cls", self.body)

    def test_member_count(self):
        self.assertIn("member_count", self.body)

    def test_archived_created_at(self):
        self.assertIn("created_at", self.body)

    def test_archived_closed_at(self):
        # formatClosedAt is used for time display
        self.assertIn("formatClosedAt", self.tpl)

    def test_syntax_templates(self):
        r = subprocess.run(["python3", "-c",
                           f"import py_compile; py_compile.compile('{BASE}/templates.py', doraise=True)"],
                          capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
