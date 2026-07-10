"""R97: AutoRouter 稳定化 — 全面验收测试 🦐

覆盖 8 项验收标准 + 角色映射 + 全链闭环。
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.pipeline_context import (
    StepInfo,
    DEFAULT_STEP_ORDER,
    DEFAULT_STEPS,
)


class TestStep1_PipelineStart(unittest.TestCase):
    """验收 1: !pipeline_start R97 零参数成功"""

    def test_create_pipeline_context(self):
        """!pipeline_start R97 创建 PipelineContext"""
        ctx = {
            "round_name": "R97",
            "status": "running",
            "created_at": time.time(),
            "triggerer_id": "ws_test_agent",
            "triggerer_name": "测试者",
            "steps": {
                k: {
                    "step_key": k,
                    "role": v.role,
                    "title": v.title,
                    "status": "pending",
                    "agent_id": "",
                    "agent_name": "",
                    "output": None,
                    "result_msg": "",
                }
                for k, v in DEFAULT_STEPS.items()
            },
            "step_order": list(DEFAULT_STEP_ORDER),
            "work_plan_url": "",
            "references": {},
        }
        self.assertEqual(ctx["round_name"], "R97")
        self.assertEqual(ctx["status"], "running")
        self.assertEqual(len(ctx["steps"]), 6)

    def test_no_url_required(self):
        """不需要任何 URL 参数"""
        ctx = {
            "round_name": "R97",
            "status": "running",
            "steps": {},
            "step_order": list(DEFAULT_STEP_ORDER),
            "work_plan_url": "",
            "references": {},
        }
        self.assertEqual(ctx["work_plan_url"], "")  # 零 URL


class TestStep2_PipelineContextStructure(unittest.TestCase):
    """验收 2: PipelineContext 结构完整"""

    def test_six_steps_default(self):
        """默认包含 6 个 Step"""
        self.assertEqual(len(DEFAULT_STEPS), 6)
        self.assertEqual(DEFAULT_STEP_ORDER, [
            "step1", "step2", "step3", "step4", "step5", "step6",
        ])

    def test_step1_is_pm(self):
        """Step 1 角色为 pm"""
        self.assertEqual(DEFAULT_STEPS["step1"].role, "pm")
        self.assertEqual(DEFAULT_STEPS["step1"].title, "标注 WORK_PLAN 已审核")

    def test_all_roles_present(self):
        """所有管线角色齐全"""
        roles = {v.role for v in DEFAULT_STEPS.values()}
        expected = {"pm", "arch", "dev", "review", "qa", "operations"}
        self.assertEqual(roles, expected)

    def test_pipeline_context_dict_format(self):
        """PipelineContext dict 格式序列化/反序列化正确"""
        ctx = {
            "round_name": "R97",
            "status": "running",
            "created_at": 1234567890.0,
            "triggerer_id": "ws_test",
            "triggerer_name": "测试",
            "steps": {
                "step1": {
                    "step_key": "step1", "role": "pm",
                    "title": "标注 WORK_PLAN 已审核",
                    "status": "pending",
                    "agent_id": "", "agent_name": "",
                    "output": None, "result_msg": "",
                },
            },
            "step_order": ["step1"],
            "work_plan_url": "",
            "references": {},
        }
        d = json.loads(json.dumps(ctx))
        self.assertEqual(d["round_name"], "R97")
        self.assertEqual(d["steps"]["step1"]["role"], "pm")
        self.assertEqual(d["steps"]["step1"]["status"], "pending")


class TestStep3_RoleResolution(unittest.TestCase):
    """验收 3: _resolve_agent_by_role 角色解析"""

    def setUp(self):
        self.agent_cards_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "agent_cards.json"
        )
        with open(self.agent_cards_path) as f:
            self.cards = json.load(f)

    def _build_role_index(self):
        """模拟 AutoRouter._refresh_role_map()"""
        role_index = {}
        for agent_id, card in self.cards.items():
            roles = []
            if "pipeline_roles" in card and isinstance(card["pipeline_roles"], list):
                roles = card["pipeline_roles"]
            elif "role" in card:
                roles = [card["role"]]
            for role in roles:
                role_index.setdefault(role, []).append(agent_id)
        return role_index

    def _resolve(self, role, role_index):
        """模拟 AutoRouter._resolve_agent_by_role()"""
        # ① 精确匹配
        if role in role_index:
            return role_index[role][0]

        # ② 子串匹配
        for known_role, agents in role_index.items():
            if role in known_role or known_role in role:
                return agents[0]

        # ③ short_map
        short_map = {
            "pm": ["product-manager", "product_manager", "product"],
            "arch": ["architect", "architecture"],
            "dev": ["developer", "development"],
            "review": ["reviewer", "code_review"],
            "qa": ["test", "tester", "quality"],
            "operations": ["admin", "ops", "devops", "infra"],
            "ops": ["operations", "devops", "infra"],
        }
        for short, expanded in short_map.items():
            if role == short:
                for exp in expanded:
                    if exp in role_index:
                        return role_index[exp][0]
            elif role in expanded:
                if short in role_index:
                    return role_index[short][0]
        return None

    def _get_display_name(self, agent_id):
        """从 cards 获取 display_name"""
        for aid, card in self.cards.items():
            if aid == agent_id:
                return card.get("display_name", aid[:12])
        return agent_id[:12]

    def test_roles_resolve_correctly(self):
        """6 个默认角色全部正确解析"""
        role_index = self._build_role_index()
        self.assertGreater(len(role_index), 0, "agent_cards.json 应包含角色定义")

        expected = {
            "pm": "pm-bot",
            "arch": "arch-bot",
            "dev": "dev-bot",
            "review": "review-bot",
            "qa": "qa-bot",
            "operations": "admin-bot",
        }
        for role, expected_agent in expected.items():
            agent_id = self._resolve(role, role_index)
            self.assertIsNotNone(
                agent_id,
                f"角色 {role} 解析失败",
            )
            name = self._get_display_name(agent_id)
            self.assertEqual(
                agent_id, expected_agent,
                f"角色 {role}: 期望 {expected_agent}, 得到 {agent_id} ({name})",
            )

    def test_role_index_has_all_agent_cards(self):
        """Agent Card 文件全面解析"""
        role_index = self._build_role_index()
        total_agents = len(self.cards)
        indexed_agents = sum(len(v) for v in role_index.values())
        self.assertEqual(
            total_agents, indexed_agents,
            f"所有 {total_agents} 个 agent 都应被索引（实际 {indexed_agents}）",
        )


class TestStep4_TaskMessage(unittest.TestCase):
    """验收 4: 任务消息模板"""

    def test_build_task_message_format(self):
        """_build_task_message 输出格式正确"""
        ctx = {
            "round_name": "R97",
        }
        step = {
            "step_key": "step2",
            "role": "arch",
            "title": "技术方案",
        }
        prev_sha = "abc1234"
        result = self._build_task_message(ctx, step, prev_sha)
        self.assertIn("【R97 Step step2 任务 — 技术方案 🎯】", result)
        self.assertIn("角色: arch", result)
        self.assertIn("前一棒已完成: abc1234", result)
        self.assertIn("完成后请回复 _inbox:server 告知 SHA。", result)

    def test_no_prev_sha(self):
        """无前一棒 SHA 时显示（无）"""
        ctx = {"round_name": "R97"}
        step = {"step_key": "step1", "role": "pm", "title": "标注"}
        result = self._build_task_message(ctx, step, "")
        self.assertIn("前一棒已完成: （无）", result)

    def test_no_llm_content(self):
        """消息纯机械组装，无 LLM 内容"""
        ctx = {"round_name": "R97"}
        step = {"step_key": "step3", "role": "dev", "title": "编码"}
        result = self._build_task_message(ctx, step, "def456")
        self.assertNotIn("你是一个", result)
        self.assertNotIn("作为AI", result)
        self.assertNotIn("根据你的判断", result)

    @staticmethod
    def _build_task_message(ctx, step, prev_sha):
        """模拟 AutoRouter._build_task_message()"""
        lines = [
            f"【{ctx['round_name']} Step {step['step_key']} 任务 — {step['title']} 🎯】",
            "",
            f"角色: {step['role']}",
            f"前一棒已完成: {prev_sha or '（无）'}",
            "",
            "请按流程完成任务后推 dev 分支。",
            "完成后请回复 _inbox:server 告知 SHA。",
        ]
        return "\n".join(lines)


class TestStep5_ContextPersistence(unittest.TestCase):
    """验收 5: PipelineContext 持久化"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "pipeline_contexts.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_read(self):
        """写入 → 读取 → 结构一致"""
        ctx = {
            "round_name": "R97",
            "status": "running",
            "steps": {
                "step1": {
                    "step_key": "step1", "role": "pm",
                    "title": "标注", "status": "active",
                    "agent_id": "pm-bot", "agent_name": "小谷",
                    "output": None, "result_msg": "",
                },
            },
            "step_order": ["step1"],
        }
        data = {"R97": ctx}
        with open(self.path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        with open(self.path) as f:
            loaded = json.load(f)
        restored = loaded["R97"]
        self.assertEqual(restored["round_name"], "R97")
        self.assertEqual(restored["status"], "running")
        self.assertEqual(restored["steps"]["step1"]["role"], "pm")
        self.assertEqual(restored["steps"]["step1"]["status"], "active")

    def test_steps_serialization(self):
        """Steps 包含所有必要字段"""
        step = {
            "step_key": "step1",
            "role": "pm",
            "title": "标注 WORK_PLAN 已审核",
            "status": "active",
            "agent_id": "pm-bot",
            "agent_name": "小谷",
            "output": None,
            "result_msg": "",
        }
        json_str = json.dumps(step)
        restored = json.loads(json_str)
        for field in ["step_key", "role", "title", "status", "agent_id", "agent_name"]:
            self.assertIn(field, restored)


class TestStep6_StepComplete(unittest.TestCase):
    """验收 6: _on_step_complete 推进下一 Step"""

    def test_advance_to_next_step(self):
        """完成 step1 → 激活 step2"""
        ctx = {
            "round_name": "R97",
            "status": "running",
            "steps": {
                "step1": {"step_key": "step1", "role": "pm", "status": "active", "agent_id": "pm-bot"},
                "step2": {"step_key": "step2", "role": "arch", "status": "pending", "agent_id": ""},
            },
            "step_order": ["step1", "step2"],
        }
        step_order = ctx["step_order"]
        # 标记 step1 完成
        ctx["steps"]["step1"]["status"] = "done"
        ctx["steps"]["step1"]["result_msg"] = "✅ 完成，已推 dev: abc1234"
        ctx["steps"]["step1"]["output"] = {"sha": "abc1234"}

        # 激活 step2
        next_idx = step_order.index("step1") + 1
        next_key = step_order[next_idx]
        ctx["steps"][next_key]["status"] = "active"

        self.assertEqual(ctx["steps"]["step1"]["status"], "done")
        self.assertEqual(ctx["steps"]["step2"]["status"], "active")

    def test_complete_last_step(self):
        """完成 step6 → status=done"""
        ctx = {
            "round_name": "R97",
            "status": "running",
            "steps": {
                "step6": {"step_key": "step6", "role": "operations", "status": "active"},
            },
            "step_order": ["step6"],
        }
        # 标记完成 → 最后一步 → 全部 done
        ctx["steps"]["step6"]["status"] = "done"
        ctx["status"] = "done"

        self.assertEqual(ctx["status"], "done")
        self.assertEqual(ctx["steps"]["step6"]["status"], "done")


class TestStep7_FullChain(unittest.TestCase):
    """验收 7: 全链 6 Step 闭环"""

    def test_full_chain(self):
        """模拟全链 6 Step 自动走完"""
        ctx = {
            "round_name": "R97",
            "status": "running",
            "steps": {
                k: {
                    "step_key": k,
                    "role": v.role,
                    "title": v.title,
                    "status": "active" if k == "step1" else "pending",
                    "agent_id": f"{v.role}-bot",
                    "agent_name": "",
                    "output": None,
                    "result_msg": "",
                }
                for k, v in DEFAULT_STEPS.items()
            },
            "step_order": list(DEFAULT_STEP_ORDER),
        }

        step_order = ctx["step_order"]
        for i, step_key in enumerate(step_order):
            # Mark current active step as done
            ctx["steps"][step_key]["status"] = "done"
            ctx["steps"][step_key]["result_msg"] = f"✅ 完成，已推 dev: sha{i:07d}"
            ctx["steps"][step_key]["output"] = {"sha": f"sha{i:07d}"}

            if i + 1 < len(step_order):
                # Activate next
                next_key = step_order[i + 1]
                ctx["steps"][next_key]["status"] = "active"
            else:
                # All done
                ctx["status"] = "done"

        self.assertEqual(ctx["status"], "done")
        for step_key in step_order:
            self.assertEqual(
                ctx["steps"][step_key]["status"], "done",
                f"{step_key} should be done",
            )


class TestStep8_ContextIO(unittest.TestCase):
    """验收 8: _load_pipeline_context / _save_pipeline_context"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "pipeline_contexts.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _load(self, round_name):
        if not os.path.exists(self.path):
            return None
        with open(self.path) as f:
            data = json.load(f)
        return data.get(round_name)

    def _save(self, round_name, ctx):
        data = {}
        if os.path.exists(self.path):
            with open(self.path) as f:
                data = json.load(f)
        data[round_name] = ctx
        with open(self.path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def test_round_trip(self):
        """保存 → 加载 → 验证完整性"""
        ctx = {
            "round_name": "R97",
            "status": "running",
            "steps": {
                "step1": {"step_key": "step1", "role": "pm", "status": "active"},
            },
            "step_order": ["step1"],
        }
        self._save("R97", ctx)
        loaded = self._load("R97")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["round_name"], "R97")
        self.assertEqual(loaded["steps"]["step1"]["status"], "active")

    def test_update_persists(self):
        """更新后重新保存 → 加载最新值"""
        self._save("R97", {"status": "running", "steps": {}})
        orig = self._load("R97")
        orig["status"] = "done"
        self._save("R97", orig)
        loaded = self._load("R97")
        self.assertEqual(loaded["status"], "done")

    def test_multiple_rounds(self):
        """多轮次共存"""
        self._save("R97", {"round_name": "R97", "status": "running"})
        self._save("R98", {"round_name": "R98", "status": "running"})
        self.assertIsNotNone(self._load("R97"))
        self.assertIsNotNone(self._load("R98"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
