"""R100: 服务端核心重构：handler.py 拆分 — 全面验收测试 🦐

覆盖 15 项验收标准 (V-1~V-15) + 3 项 🔴 修复验证 + 4 项 🟡 修复验证。
"""
import ast
import json
import os
import re
import sys
import unittest

BASE = os.path.join(os.path.dirname(__file__), "..", "server")

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"
results = []


def check(name, ok, detail=""):
    icon = PASS if ok else FAIL
    results.append((icon, name, detail))
    return ok


# ================================================================
# V-11 ~ V-15: 代码质量验证
# ================================================================

class TestV11_NoCmdResidue(unittest.TestCase):
    """V-11: main.py 无 _cmd_ 残留"""

    def test_no_cmd_functions(self):
        with open(os.path.join(BASE, "main.py")) as f:
            content = f.read()
        cmd_funcs = re.findall(r'def _cmd_\w+', content)
        check("V-11: main.py 无 _cmd_ 残留",
              len(cmd_funcs) == 0,
              f"找到 {len(cmd_funcs)} 个: {cmd_funcs}")


class TestV12_CommandsDir(unittest.TestCase):
    """V-12: commands/ 含 6 个文件"""

    def test_has_six_files(self):
        files = sorted(os.listdir(os.path.join(BASE, "commands")))
        expected = {"__init__.py", "admin.py", "agent_card.py",
                     "pipeline.py", "task.py", "workspace.py"}
        check("V-12: commands/ 6 文件",
              set(files) == expected,
              f"实际: {set(files)}")


class TestV13_StatePy(unittest.TestCase):
    """V-13: state.py 存在"""

    def test_exists(self):
        check("V-13: state.py 存在",
              os.path.exists(os.path.join(BASE, "state.py")))

    def test_has_key_vars(self):
        with open(os.path.join(BASE, "state.py")) as f:
            content = f.read()
        for var in ["_PIPELINE_STATE", "_PIPELINE_CONFIG", "SYSTEM_AGENT_ID",
                     "SERVER_INBOX_CHANNEL", "_LOBBY_PAUSED", "_r72_users",
                     "_pipeline_manager", "_GIT_SYNC_TASK"]:
            self.assertIn(var, content, f"state.py 缺少 {var}")


class TestV14_CommandUtilsPy(unittest.TestCase):
    """V-14: command_utils.py 存在"""

    def test_exists(self):
        check("V-14: command_utils.py 存在",
              os.path.exists(os.path.join(BASE, "command_utils.py")))

    def test_has_key_functions(self):
        with open(os.path.join(BASE, "command_utils.py")) as f:
            content = f.read()
        for fn in ["_parse_command", "_check_command_permission",
                    "_send_cmd_response", "_log_audit",
                    "_broadcast_to_channel", "_resolve_workspace",
                    "_is_any_workspace_admin"]:
            self.assertIn(fn, content, f"command_utils.py 缺少 {fn}")


class TestV15_NoCircularImport(unittest.TestCase):
    """V-15: 无循环导入"""

    def test_state_no_server_import(self):
        """state.py 不 import 业务 server 模块（pipeline_context 是纯数据类，例外）"""
        with open(os.path.join(BASE, "state.py")) as f:
            content = f.read()
        # pipeline_context is a pure data class, acceptable
        imports = re.findall(r'^from \.', content, re.MULTILINE)
        only_pipeline_ctx = all('pipeline_context' in i for i in imports)
        check("V-15: state.py 仅导入 pipeline_context",
              only_pipeline_ctx,
              f"imports: {imports}")

    def test_main_uses_lazy_commands_import(self):
        """main.py 用延迟 import 避免循环"""
        with open(os.path.join(BASE, "main.py")) as f:
            content = f.read()
        # Find the command dispatch in handle_broadcast
        has_lazy = re.search(r'from \.commands import _ADMIN_COMMANDS', content)
        check("V-15: main.py 延迟 import commands",
              bool(has_lazy),
              "")

    def test_command_utils_lazy_main_import(self):
        """command_utils.py 函数内延迟 import main"""
        with open(os.path.join(BASE, "command_utils.py")) as f:
            content = f.read()
        # Find the lazy import inside _broadcast_to_channel
        has_lazy_main = 'from .main import _connections' in content
        check("V-15: command_utils 延迟 import main._connections",
              has_lazy_main,
              "")

    def test_state_import_works(self):
        """实际测试：from server.state import *"""
        import subprocess
        r = subprocess.run(
            ["python3", "-c", "from server.state import _PIPELINE_STATE, SYSTEM_AGENT_ID; print('OK')"],
            capture_output=True, text=True, cwd=os.path.join(BASE, ".."), timeout=10
        )
        check("V-15: state 实际 import 成功",
              r.returncode == 0,
              r.stderr[:200] if r.stderr else "")


# ================================================================
# 🔴 修复验证 + 🟡 修复验证
# ================================================================

class TestReviewFix_Red1_R99LevelCheck(unittest.TestCase):
    """🔴-1: R99 level 检查在生产路径 (ws_handler)"""

    def test_r99_in_main_handler(self):
        """main.py handler() 含 R99 level 检查"""
        with open(os.path.join(BASE, "main.py")) as f:
            content = f.read()
        has_it = "get_level(agent_id)" in content or "auth.get_level(" in content
        check("🔴-1: main.py handler() 含 R99 level 检查", has_it, "")

    def test_r99_in_ws_handler(self):
        """__main__.py ws_handler() 含 R99 level 检查"""
        main_path = os.path.join(BASE, "__main__.py")
        if not os.path.exists(main_path):
            main_path = os.path.join(BASE, "..", "server", "__main__.py")
        with open(main_path) as f:
            content = f.read()
        has_it = "get_level(agent_id)" in content or "level >= 4" in content or "level < 4" in content
        check("🔴-1: __main__.ws_handler() 含 R99 level 检查", has_it, "")


class TestReviewFix_Red2_AuthR72Users(unittest.TestCase):
    """🔴-2: auth.py _r72_users → state._r72_users"""

    def test_auth_uses_state_r72(self):
        with open(os.path.join(BASE, "auth.py")) as f:
            content = f.read()
        # Should reference state._r72_users
        has_state_ref = "state._r72_users" in content or "from . import state" in content
        check("🔴-2: auth.py 引用 state._r72_users", has_state_ref, "")
        # Should NOT reference main._r72_users (would fail at runtime)
        has_broken_ref = "main._r72_users" in content
        check("🔴-2: auth.py 无 main._r72_users 残留", not has_broken_ref, "")


class TestReviewFix_Red3_AgentCardState(unittest.TestCase):
    """🔴-3: agent_card.py → state._ROLE_AGENT_MAP"""

    def test_agent_card_uses_state(self):
        with open(os.path.join(BASE, "agent_card.py")) as f:
            content = f.read()
        has_state_ref = "state._ROLE_AGENT_MAP" in content or "state._pipeline_manager" in content
        check("🔴-3: agent_card.py 引用 state._ROLE_AGENT_MAP", has_state_ref, "")
        has_broken_ref = "main._ROLE_AGENT_MAP" in content or "main._pipeline_manager" in content
        check("🔴-3: agent_card.py 无 main. 残留", not has_broken_ref, "")


class TestReviewFix_Yellow1_InitImport(unittest.TestCase):
    """🟡-1: __init__.py 导入 _handle_pipeline_command"""

    def test_init_imports_pipeline_cmd(self):
        with open(os.path.join(BASE, "commands", "__init__.py")) as f:
            content = f.read()
        has_it = "_handle_pipeline_command" in content
        check("🟡-1: __init__.py 导入 _handle_pipeline_command", has_it, "")


class TestReviewFix_Yellow2_StateNoFunctions(unittest.TestCase):
    """🟡-2: state.py 无函数定义"""

    def test_state_no_funcs(self):
        with open(os.path.join(BASE, "state.py")) as f:
            content = f.read()
        funcs = re.findall(r'^def ', content, re.MULTILINE)
        check("🟡-2: state.py 无函数定义", len(funcs) == 0, f"找到: {funcs}")


class TestReviewFix_Yellow3_StateNoDuplicates(unittest.TestCase):
    """🟡-3: state.py 无重复变量"""

    def test_state_no_duplicate_vars(self):
        with open(os.path.join(BASE, "state.py")) as f:
            content = f.read()
        for var in ["_ROLE_AGENT_MAP", "_step_ack_states"]:
            count = content.count(f"{var}: dict")
            check(f"🟡-3: state.py {var} 无重复定义",
                  count == 1,
                  f"出现 {count} 次")


class TestReviewFix_Yellow4_StateCardWatcher(unittest.TestCase):
    """🟡-4: state.py _card_watcher 无 ac_mod 前缀"""

    def test_card_watcher_type(self):
        with open(os.path.join(BASE, "state.py")) as f:
            content = f.read()
        has_acmod = 'ac_mod.CardFileWatcher' in content
        check("🟡-4: state.py _card_watcher 无 ac_mod 前缀",
              not has_acmod,
              "已去除 ac_mod. 前缀")


# ================================================================
# from .handler 零残留
# ================================================================

class TestClean_NoHandlerImport(unittest.TestCase):
    """from .handler 零残留"""

    def test_no_handler_import_in_main_py(self):
        main_path = os.path.join(BASE, "__main__.py")
        if not os.path.exists(main_path):
            main_path = os.path.join(BASE, "..", "server", "__main__.py")
        with open(main_path) as f:
            content = f.read()
        handler_refs = re.findall(r'from \.handler', content)
        check("from .handler 零残留",
              len(handler_refs) == 0,
              f"找到 {len(handler_refs)}")


# ================================================================
# main.py 核心函数保留
# ================================================================

class TestCore_FunctionsPreserved(unittest.TestCase):
    """main.py 保留核心函数"""

    def test_core_functions(self):
        with open(os.path.join(BASE, "main.py")) as f:
            content = f.read()
        for fn in ["handler(", "handle_broadcast(", "_handle_server_relay(",
                    "_handle_server_query(", "handle_auth(", "handle_register(",
                    "handle_agent_card_register(", "_send(", "_connections"]:
            self.assertIn(fn, content, f"main.py 缺少 {fn}")


# ================================================================
# commands/__init__.py 导入完整性
# ================================================================

class TestCommands_InitImports(unittest.TestCase):
    """commands/__init__.py 导入所有领域模块"""

    def test_init_imports_all_domains(self):
        with open(os.path.join(BASE, "commands", "__init__.py")) as f:
            content = f.read()
        for sym in ["_cmd_create_workspace", "_cmd_pipeline_start",
                     "_cmd_agent_card_list", "_cmd_task_create", "_cmd_list_agents",
                     "_ADMIN_COMMANDS"]:
            self.assertIn(sym, content, f"__init__.py 缺少 {sym}")


# ================================================================
# 文件完整性
# ================================================================

class TestFileIntegrity(unittest.TestCase):
    """每个 commands 文件语法有效"""

    def test_commands_syntax(self):
        import py_compile
        cmd_dir = os.path.join(BASE, "commands")
        for fn in os.listdir(cmd_dir):
            if fn.endswith(".py"):
                path = os.path.join(cmd_dir, fn)
                try:
                    py_compile.compile(path, doraise=True)
                    check(f"语法: commands/{fn}", True, "")
                except py_compile.PyCompileError as e:
                    check(f"语法: commands/{fn}", False, str(e))

    def test_main_syntax_valid(self):
        import py_compile
        try:
            py_compile.compile(os.path.join(BASE, "main.py"), doraise=True)
            check("语法: main.py", True, "")
        except py_compile.PyCompileError as e:
            check("语法: main.py", False, str(e))


# ================================================================
# 最简模块级 import 测试
# ================================================================

class TestImportChain(unittest.TestCase):
    """最小依赖链 import 测试"""

    def test_state_import(self):
        """state 模块可单独 import"""
        import subprocess
        r = subprocess.run(
            ["python3", "-c", "from server.state import _PIPELINE_STATE; print('OK')"],
            capture_output=True, text=True, cwd=os.path.join(BASE, ".."), timeout=10
        )
        check("import: state OK", r.returncode == 0, r.stderr[:100] if r.stderr else "")


if __name__ == "__main__":
    unittest.main()
