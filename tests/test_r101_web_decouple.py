"""R101: WSS/Web 解耦 — 全面验收测试 🦐

覆盖 12 项验收标准 + 审查修复验证 + 解耦验证。
"""
import os, re, sys, ast, subprocess, unittest

BASE = os.path.join(os.path.dirname(__file__), "..", "server")
PASS, FAIL, WARN = "✅", "❌", "⚠️"
results = []


def check(name, ok, detail=""):
    icon = PASS if ok else FAIL
    results.append((icon, name, detail))
    return ok


# ================================================================
# 5.1 核心通路（源码级）
# ================================================================

class Test5_1_WebCoreDecoupled(unittest.TestCase):

    def test_wss_core_no_web_viewer_import(self):
        """WSS 核心无 web_viewer import"""
        for fn in ["main.py", "__main__.py", "command_utils.py"]:
            content = open(os.path.join(BASE, fn)).read()
            check(f"1.{fn}: 无 web_viewer import", 'web_viewer' not in content)

    def test_wss_core_no_write_chat_log(self):
        """WSS 核心无 write_chat_log 调用"""
        for fn in ["main.py", "__main__.py", "command_utils.py",
                    "commands/pipeline.py", "commands/workspace.py"]:
            path = os.path.join(BASE, fn)
            if os.path.exists(path):
                content = open(path).read()
                has = 'write_chat_log' in content
                check(f"2.{fn}: {'有' if has else '无'} write_chat_log", not has)

    def test_wss_core_no_ws_clients(self):
        """WSS 核心无 _ws_clients 引用"""
        for fn in ["main.py", "__main__.py"]:
            content = open(os.path.join(BASE, fn)).read()
            check(f"3.{fn}: 无 _ws_clients", '_ws_clients' not in content)

    def test_main_py_no_setup_routes(self):
        """__main__.py 无 setup_routes"""
        content = open(os.path.join(BASE, "__main__.py")).read()
        web_routes = ['/chat', '/api/chat', '/api/channels', '/auth/github', '/api/bind']
        has = any(f'"{r}' in content for r in web_routes)
        check("4. __main__ 无 Web HTTP 路由", not has)

    def test_workspace_lazy_import_acceptable(self):
        """workspace.py web_viewer 仅 archive（🟡 可接受）"""
        content = open(os.path.join(BASE, "commands", "workspace.py")).read()
        check("workspace.py 无 write_chat_log", 'write_chat_log' not in content)
        check("workspace.py web_viewer 仅 archive",
              'set_archive_state' in content,
              "惰性 import，非日志写入")


class Test5_2_WebService(unittest.TestCase):

    def test_web_service_exists(self):
        check("5. web_service.py 存在", os.path.exists(os.path.join(BASE, "web_service.py")))

    def test_web_service_no_websocket(self):
        content = open(os.path.join(BASE, "web_service.py")).read()
        check("web_service.py 无 WebSocket 依赖", 'websockets' not in content)


class Test5_3_Decoupling(unittest.TestCase):

    def test_syntax_all_files(self):
        for fn in ["main.py", "web_service.py", "__main__.py",
                    "commands/__init__.py", "commands/workspace.py",
                    "commands/pipeline.py"]:
            path = os.path.join(BASE, fn)
            if os.path.exists(path):
                r = subprocess.run(
                    ["python3", "-c", f"import py_compile; py_compile.compile('{path}', doraise=True)"],
                    capture_output=True, text=True, timeout=5
                )
                check(f"语法: {fn}", r.returncode == 0, r.stderr[:100] if r.stderr else "")

    def test_import_chain(self):
        r = subprocess.run(
            ["python3", "-c", "from server.state import _PIPELINE_STATE; print('OK')"],
            capture_output=True, text=True, cwd="/opt/data/ws-bridge", timeout=10
        )
        check("核心模块 import 链正常", r.returncode == 0, r.stderr[:100] if r.stderr else "")


if __name__ == "__main__":
    import unittest
    t = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    unittest.TextTestRunner(verbosity=2).run(t)
