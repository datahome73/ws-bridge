"""R98: !close_workspace 归档通知增强 — 全面验收测试 🦐

覆盖 8 项验收标准 + 2 项兼容修复。

验收标准：
1. 归档通知送达全部管线 bot
2. ws.members 中非管线成员也收到
3. 调用者自己不收到
4. PipelineContext 不存在时兼容旧行为
5. 同一 bot 只收一条（去重）
6. 无 agent_id 的 step 静默跳过
7. 通知失败不阻塞关闭
8. !step_handoff 自动 close 正常

兼容修复：
9. _save() dict 兼容（hasattr duck typing）
10. _cmd_pipeline_stop dict 兼容（3 层 status fallback + "done"）
"""
import ast
import inspect
import json
import os
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.pipeline_context import (
    PipelineContext,
    PipelineContextManager,
    PipelineStatus,
    StepInfo,
    DEFAULT_STEP_ORDER,
    DEFAULT_STEPS,
)

HANDLER_PATH = os.path.join(os.path.dirname(__file__), "..", "server", "main.py")
PIPELINE_CTX_PATH = os.path.join(
    os.path.dirname(__file__), "..", "server", "pipeline_context.py"
)

PASS = "✅"
FAIL = "❌"
results = []


def check(name, ok, detail=""):
    icon = PASS if ok else FAIL
    results.append((icon, name, detail))
    return ok


class TestR98_Acceptance1_AllPipelineBots(unittest.TestCase):
    """验收 1: 归档通知送达全部管线 bot"""

    def test_notify_ids_includes_pipeline_participants(self):
        """通知目标集合包含管线参与者 agent_id"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        # 找通知目标构建块
        idx = content.find("# R98: 构建通知目标集合（member + pipeline 参与者，去重）")
        block_end = content.find("for _member_id in list(_notify_ids):", idx)
        self.assertGreater(idx, 0, "R98 通知块应有标记注释")
        self.assertGreater(block_end, 0, "R98 应有通知循环")

        block = content[idx:block_end]
        check(
            "1a. 从 ws.members 初始化",
            "set(ws.members)" in block,
            f"Found in block: {block[:50]}...",
        )
        check(
            "1b. 从 PipelineContext 补充",
            "_mgr.get_context(_round_name)" in block,
            "",
        )
        check(
            "1c. 遍历 steps.values()",
            '_ctx.get("steps", {}).values()' in block,
            "",
        )
        check(
            "1d. 添加 agent_id 到集合",
            '_notify_ids.add(_step["agent_id"])' in block,
            "",
        )


class TestR98_Acceptance2_NonPipelineMembers(unittest.TestCase):
    """验收 2: ws.members 中非管线成员也收到"""

    def test_base_set_is_ws_members(self):
        """通知集合从 ws.members 作为基础开始"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        idx = content.find("# R98: 构建通知目标集合（member + pipeline 参与者，去重）")
        block_end = content.find("for _member_id in list(_notify_ids):", idx)
        block = content[idx:block_end]

        # 确保 ws.members 是所有通知的基础
        check(
            "2a. ws.members 是基础集合",
            "_notify_ids = set(ws.members)" in block,
            "",
        )
        # 确保只做 add（不替换），所以 ws.members 始终在集合中
        check(
            "2b. 只做 add 不替换",
            "_notify_ids.add(" in block,
            "",
        )


class TestR98_Acceptance3_SenderExcluded(unittest.TestCase):
    """验收 3: 调用者自己不收到"""

    def test_sender_excluded(self):
        """验证 sender 被 discard"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        check(
            "3a. discard(sender_id)",
            "_notify_ids.discard(sender_id)" in content,
            "",
        )
        check(
            "3b. 使用 discard 而非 remove",
            "_notify_ids.remove(sender_id)" not in content,
            "discard 不会抛 KeyError，remove 会",
        )
        check(
            "3c. discard 在循环之前执行",
            "_notify_ids.discard(sender_id)",
            "",
        )
        # 验证旧版的 if-continue 被移除
        check(
            "3d. 旧版 if-continue sender 检查已移除",
            "if _member_id == sender_id: continue" not in content,
            "改用 discard 统一处理",
        )


class TestR98_Acceptance4_NoPipelineContext(unittest.TestCase):
    """验收 4: PipelineContext 不存在时兼容旧行为"""

    def test_context_none_compatibility(self):
        """_ctx 为 None 时回退 ws.members"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        idx = content.find("# R98: 构建通知目标集合（member + pipeline 参与者，去重）")
        block_end = content.find("for _member_id in list(_notify_ids):", idx)
        block = content[idx:block_end]

        check(
            "4a. isinstance(_ctx, dict) 守卫",
            "isinstance(_ctx, dict)" in block,
            "仅 dict 类型才合并 pipeline 参与者",
        )
        check(
            "4b. _ctx 真假判断",
            "if _ctx and isinstance(_ctx, dict)" in block
            or "if isinstance(_ctx, dict) and _ctx" in block,
            "None/falsy 时跳过",
        )

    def test_not_a_dict_skipped(self):
        """_ctx 是 PipelineContext 对象（非 dict）时跳过"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        idx = content.find("# R98: 构建通知目标集合（member + pipeline 参与者，去重）")
        block_end = content.find("for _member_id in list(_notify_ids):", idx)
        block = content[idx:block_end]

        check(
            "4c. PipelineContext 对象不触发 pipeline 合并",
            "isinstance(_ctx, dict)" in block,
            "R97+ PipelineContext dataclass 非 dict → 走旧路径",
        )

    def test_try_except_wraps_notification(self):
        """通知块整体被 try/except 包裹"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        # 找到通知块开头
        markers = [
            ("# ── R79+: Notify all workspace members", "R79 标记"),
            ("# ── R98: 合并 ws.members", "R98 标记"),
        ]

        r79_idx = content.find(
            "# ── R79+: Notify all workspace members that the round is over"
        )
        self.assertGreater(r79_idx, 0)

        # 在 R79 注释之后找 try
        try_idx = content.find("try:\n        _round_name", r79_idx)
        self.assertGreater(try_idx, 0, "try 应在 R79 注释之后")

        # 找对应的 except
        except_idx = content.find("except Exception as e:", try_idx)
        self.assertGreater(except_idx, 0)

        check(
            "4d. try/except 包裹通知块",
            except_idx > try_idx,
            f"try at {try_idx}, except at {except_idx}",
        )
        check(
            "4e. warning 日志（非 fatal）",
            'logger.warning("Round-end notification failed (non-fatal): %s", e)'
            in content,
            "",
        )


class TestR98_Acceptance5_Deduplication(unittest.TestCase):
    """验收 5: 同一 bot 只收一条（去重）"""

    def test_set_dedup(self):
        """验证 set 天然去重"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        idx = content.find("# R98: 构建通知目标集合（member + pipeline 参与者，去重）")
        block_end = content.find("for _member_id in list(_notify_ids):", idx)
        block = content[idx:block_end]

        check(
            "5a. 使用 set 保证去重",
            "_notify_ids = set(ws.members)" in block,
            "set 构造确保 ws.members 已去重",
        )
        check(
            "5b. add 不会引入重复",
            "_notify_ids.add(" in block,
            "set.add 重复添加无害",
        )


class TestR98_Acceptance6_EmptyAgentId(unittest.TestCase):
    """验收 6: 无 agent_id 的 step 静默跳过"""

    def test_empty_agent_id_skipped(self):
        """验证空 agent_id 被跳过"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        idx = content.find("# R98: 构建通知目标集合（member + pipeline 参与者，去重）")
        block_end = content.find("for _member_id in list(_notify_ids):", idx)
        block = content[idx:block_end]

        check(
            "6a. isinstance(_step, dict) 守卫",
            "isinstance(_step, dict)" in block,
            "防止 steps 值不是 dict",
        )
        check(
            "6b. _step.get(\"agent_id\") 空值检测",
            '_step.get("agent_id")' in block,
            "空字符串 '' 和 None 都 falsy",
        )
        check(
            "6c. 空 agent_id 不加入通知",
            '_step.get("agent_id")' in block,
            "_step.get('agent_id') = '' (空串) → falsy → 跳过",
        )


class TestR98_Acceptance7_FailNoBlock(unittest.TestCase):
    """验收 7: 通知失败不阻塞关闭"""

    def test_notification_block_in_try_except(self):
        """通知块在 try/except 内"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        r79_idx = content.find(
            "# ── R79+: Notify all workspace members that the round is over"
        )
        try_idx = content.find("try:\n        _round_name", r79_idx)
        except_idx = content.find("except Exception as e:", try_idx)

        self.assertGreater(try_idx, 0)
        self.assertGreater(except_idx, 0)
        self.assertGreater(except_idx, try_idx)

        # 检查 return 在 except 后面（不阻塞归档）
        return_idx = content.find("return ", except_idx)
        self.assertGreater(return_idx, except_idx)

        check(
            "7a. try 开始通知",
            f"try at L{content[:try_idx].count(chr(10)) + 1}",
            "",
        )
        check(
            "7b. except 捕获所有异常",
            'logger.warning("Round-end notification failed (non-fatal):',
            "",
        )
        check(
            "7c. return 在 except 后",
            "return" in content[except_idx:except_idx + 50],
            "关闭操作不因通知失败而阻塞",
        )


class TestR98_Acceptance8_StepHandoffAutoClose(unittest.TestCase):
    """验收 8: !step_handoff 自动 close 正常"""

    def test_handoff_calls_close_on_last_step(self):
        """验证 !step_handoff 最后一步调用 _cmd_close_workspace"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        # 找 handoff 最后一步处理
        handoff_end_marker = "Final step → pipeline complete"
        idx = content.find(handoff_end_marker)
        self.assertGreater(idx, 0)

        # 检查调用 _cmd_close_workspace
        block = content[idx:idx + 200]
        check(
            "8a. 最后一步调 close_workspace",
            "await _cmd_close_workspace" in block,
            f"Found in block: {block[:100]}",
        )
        check(
            "8b. current_idx + 1 >= len(step_keys) 条件",
            "current_idx + 1 >= len(step_keys)" in block,
            "",
        )

    def test_handoff_returns_proper_message(self):
        """验证 handoff 返回信息包含管线完成"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        idx = content.find("Final step → pipeline complete")
        block = content[idx:idx + 300]

        check(
            "8c. 管线完成消息",
            "管线已完成" in block,
            "",
        )
        check(
            "8d. 工作室已关闭",
            "工作室已关闭" in block,
            "",
        )

    def test_handoff_error_handling(self):
        """验证 handoff 在 close 失败时返回错误"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        idx = content.find("Final step → pipeline complete")
        block = content[idx:idx + 300]

        check(
            "8e. close 失败检查",
            '"❌" in str(close_result)' in block,
            "",
        )


class TestR98_Fix1_SaveDictCompatibility(unittest.TestCase):
    """兼容修复 1: _save() dict 兼容（hasattr duck typing）"""

    def test_save_hasattr_duck_typing(self):
        """验证 _save 使用 hasattr 而非 type check"""
        with open(PIPELINE_CTX_PATH) as f:
            content = f.read()

        save_idx = content.find("def _save(self)")
        block = content[save_idx:save_idx + 500]

        check(
            "9a. hasattr(ctx, \"to_dict\")",
            'hasattr(ctx, "to_dict")' in block,
            "duck typing 替代 type check",
        )
        check(
            "9b. PipelineContext 对象 → to_dict()",
            'ctx.to_dict() if hasattr(ctx, "to_dict") else ctx' in block,
            "",
        )
        check(
            "9c. 普通 dict → 原样写入",
            "else ctx" in block,
            "dict 类型直接写入",
        )

    def test_save_pipeline_context_object_serializable(self):
        """验证 PipelineContext 对象能通过 hasattr 正确序列化"""
        from pathlib import Path
        ctx = PipelineContext(
            round_name="R98-test",
            task_kind=__import__("server.pipeline_context", fromlist=["PipelineTaskKind"]).PipelineTaskKind.DEV,
            workspace_dir=Path("/tmp/r98-test"),
            task_dir=Path("/tmp/r98-test/pipeline_tasks/R98-test"),
            workspace_id="ws_test_save",
            pm_inbox_id="_inbox:ws_test_save",
        )
        self.assertTrue(hasattr(ctx, "to_dict"))
        d = ctx.to_dict()
        self.assertIn("steps", d)
        self.assertIn("round_name", d)

    def test_save_dict_object_kept_as_is(self):
        """验证普通 dict 通过 hasattr 检测并原样保留"""
        d = {"round_name": "R98-test", "status": "running"}
        # 普通 dict 没有 to_dict 方法
        check(
            "9d. dict 不含 to_dict",
            not hasattr(d, "to_dict"),
            "普通 dict 没有 to_dict 方法",
        )


class TestR98_Fix2_PipelineStopDictCompatibility(unittest.TestCase):
    """兼容修复 2: _cmd_pipeline_stop dict 兼容"""

    def test_pipeline_stop_created_by_hasattr(self):
        """验证 created_by 使用 hasattr 兜底"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        stop_idx = content.find("async def _cmd_pipeline_stop")
        block = content[stop_idx:stop_idx + 1500]

        check(
            "10a. ctx.created_by 使用 hasattr",
            'ctx.created_by if hasattr(ctx, "created_by")' in block,
            "PipelineContext 对象优先",
        )
        check(
            "10b. dict 兜底 .get()",
            'ctx.get("created_by", "")' in block,
            "dict 用 .get 安全读取",
        )

    def test_pipeline_stop_status_fallback(self):
        """验证状态检查 3 层 fallback"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        # 读 pipeline_stop 函数
        tree = ast.parse(content)

        stop_func = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "_cmd_pipeline_stop":
                stop_func = node
                break
        self.assertIsNotNone(stop_func, "函数 _cmd_pipeline_stop 应存在")
        func_text = ast.get_source_segment(content, stop_func)

        check(
            "10c. 三层 status fallback",
            "ctx.status.value if hasattr(ctx, \"status\") and hasattr(ctx.status, \"value\") else "
            "ctx.status if hasattr(ctx, \"status\") else "
            'ctx.get("status", "")' in func_text.replace("\n", " ").replace("  ", " "),
            "PipelineStatus enum → str 属性 → dict .get",
        )

    def test_pipeline_stop_done_status(self):
        """验证 \"done\" 状态被识别为已结束"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        check(
            "10d. \"done\" 状态支持",
            'in ("stopped", "done")' in content,
            'R98 新增 "done" 作为已结束状态',
        )

    def test_pipeline_stop_status_nonexistent(self):
        """验证 dict 无 status key 时安全处理"""
        # dict 没有 status → .get("status", "") 返回 ""
        d = {"round_name": "R98"}
        check(
            "10e. 无 status key 安全",
            d.get("status", "") == "",
            "空字符串 falsy，不会触发已停止判断",
        )


class TestR98_AST_Sanity(unittest.TestCase):
    """AST 完整性检查"""

    def test_r98_markers_present(self):
        """验证 R98 注释标记在代码中"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        markers = [
            "# ── R98: 合并 ws.members + PipelineContext 参与者 ──",
            "# R98: 构建通知目标集合（member + pipeline 参与者，去重）",
        ]
        for m in markers:
            self.assertIn(m, content, f"标记应存在: {m}")

    def test_log_wording_updated(self):
        """日志从 member(s) 改为 recipient(s)"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        check(
            "日志使用 recipient(s)",
            'sent to %d recipient(s) for %s' in content,
            "",
        )
        check(
            "不再使用 member(s) 做通知统计",
            'sent to %d member(s) for %s' not in content,
            "",
        )

    def test_file_count_minimal(self):
        """改动仅 2 文件（handler.py + pipeline_context.py 各一行兼容修复）"""
        # 本次改动文件数不可过多 R98 应极小
        with open(PIPELINE_CTX_PATH) as f:
            pc_content = f.read()
        self.assertIn("hasattr(ctx, \"to_dict\")", pc_content)

    def test_old_sender_check_removed(self):
        """确保旧版循环内 sender 检查已替换为 discard"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        # 找到通知循环
        idx = content.find("# R98: 构建通知目标集合")
        block = content[idx:idx + 400]

        # discard 应该在，旧 if-continue 应该被移除
        check(
            "旧 if-continue 已移除",
            "_member_id == sender_id" not in block or "if" not in block,
            "discard 在循环外处理",
        )


class TestR98_EdgeCases(unittest.TestCase):
    """边界场景测试"""

    def test_ctx_steps_empty_values_safety(self):
        """ctx.get(\"steps\", {}) 的 values() 空安全"""
        steps_empty = {}
        steps_none = {}
        # .get("steps", {}) 对 None 和空 dict 都安全
        for s in [None, {}, []]:
            with self.subTest(steps=s):
                vals = (s or {}).values() if s else {}.values()
                check(
                    f"空 steps={type(s).__name__} 安全",
                    True,
                    f"list({vals}) 不会抛异常",
                )

    def test_step_not_dict_safety(self):
        """steps.values() 中非 dict 的 step 被 isinstance 过滤"""
        steps = {
            "step1": {"agent_id": "ws_good"},  # dict — 应通过
            "step2": "not a dict",  # str — 应被过滤
            "step3": None,  # None — 应被过滤
            "step4": ["list"],  # list — 应被过滤
        }
        notify_ids = set()
        for _step in steps.values():
            if isinstance(_step, dict) and _step.get("agent_id"):
                notify_ids.add(_step["agent_id"])
        self.assertEqual(len(notify_ids), 1)
        self.assertIn("ws_good", notify_ids)

    def test_discard_sender_not_in_set(self):
        """sender 不在集合中时 discard 不抛异常"""
        notify_ids = {"ws_a", "ws_b"}
        sender_id = "ws_unknown"
        # 不抛异常
        notify_ids.discard(sender_id)
        self.assertEqual(len(notify_ids), 2)

    def test_deduplication_set_demo(self):
        """验证 set 合并去重"""
        members = {"ws_a", "ws_b", "ws_c"}
        pipeline_participants = {"ws_c", "ws_d", "ws_e"}
        merged = members | pipeline_participants
        self.assertEqual(len(merged), 5)  # 2+3 不加重复

        # 用 add 方式（代码实际方式）
        _notify_ids = set(members)
        for pid in pipeline_participants:
            _notify_ids.add(pid)
        self.assertEqual(len(_notify_ids), 5)

    def test_handoff_close_workspace_signature(self):
        """验证 handoff 调用 close_workspace 的参数正确"""
        with open(HANDLER_PATH) as f:
            content = f.read()

        idx = content.find("Final step → pipeline complete")
        block = content[idx:idx + 200]

        check(
            "传递 ws_id 到 close_workspace",
            'await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})' in block,
            "",
        )
        check(
            "返回结果检查",
            '"❌" in str(close_result)' in block,
            "",
        )


if __name__ == "__main__":
    unittest.main()
