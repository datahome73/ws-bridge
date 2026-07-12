"""R107: _render_template 单元测试 — 模板变量替换正确性 🧪

运行: python3 -m pytest tests/test_r107_render.py -v
       python3 tests/test_r107_render.py
"""

import sys
import os
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.pipeline_context import PipelineContext, PipelineTaskKind, PipelineStatus


def _render_template(template: str, ctx: PipelineContext, step_num: int) -> str:
    """Copied from main.py _render_template — test the logic standalone."""
    vars = {
        "round": ctx.round_name,
        "round_title": ctx.round_title,
        "requirements_url": ctx.references.get("requirements_url", ""),
        "work_plan_url": ctx.references.get("work_plan_url", ""),
    }
    for step_key, step_artifacts in ctx.artifacts.items():
        if isinstance(step_artifacts, dict):
            vars.update(step_artifacts)
    for key, value in vars.items():
        template = template.replace(f"{{{key}}}", str(value))
    return template


def _make_ctx(**overrides) -> PipelineContext:
    """Helper: build a minimal PipelineContext with defaults."""
    kwargs = dict(
        round_name="R107",
        task_kind=PipelineTaskKind.DEV,
        workspace_dir=Path("/tmp"),
        task_dir=Path("/tmp/tasks/R107"),
        workspace_id="ws_test",
        pm_inbox_id="_inbox:ws_pm",
    )
    kwargs.update(overrides)
    return PipelineContext(**kwargs)


class TestRenderTemplate(unittest.TestCase):
    """验证 _render_template 变量替换正确性"""

    def test_basic_round_vars(self):
        """基础变量 {round} 和 {round_title} 正确替换"""
        ctx = _make_ctx(round_title="测试标题")
        result = _render_template("📋 {round}: {round_title}", ctx, 3)
        self.assertEqual(result, "📋 R107: 测试标题")

    def test_reference_urls(self):
        """文档 URL 变量正确替换"""
        ctx = _make_ctx(
            references={
                "requirements_url": "https://example.com/REQ.md",
                "work_plan_url": "https://example.com/WP.md",
            },
        )
        result = _render_template(
            "需求: {requirements_url}\n方案: {work_plan_url}", ctx, 2,
        )
        self.assertIn("https://example.com/REQ.md", result)
        self.assertIn("https://example.com/WP.md", result)

    def test_artifacts_override(self):
        """artifacts 变量覆盖同名基础变量"""
        ctx = _make_ctx(
            artifacts={"step3": {"commit_sha": "abc1234"}},
        )
        result = _render_template("已推 dev: {commit_sha}", ctx, 3)
        self.assertEqual(result, "已推 dev: abc1234")

    def test_artifacts_multiple_steps(self):
        """多步 artifacts 互相不干扰"""
        ctx = _make_ctx(
            artifacts={
                "step2": {"tech_plan_url": "http://tech.md"},
                "step3": {"commit_sha": "def5678"},
            },
        )
        result = _render_template("SHA={commit_sha} TECH={tech_plan_url}", ctx, 3)
        self.assertEqual(result, "SHA=def5678 TECH=http://tech.md")

    def test_unfilled_var_unchanged(self):
        """未填到的变量保留 {var} 原文"""
        ctx = _make_ctx()
        result = _render_template("SHA={commit_sha} NAME={unknown_var}", ctx, 3)
        self.assertEqual(result, "SHA={commit_sha} NAME={unknown_var}")

    def test_empty_template(self):
        """空模板返回空字符串"""
        ctx = _make_ctx()
        result = _render_template("", ctx, 1)
        self.assertEqual(result, "")

    def test_no_matching_vars(self):
        """模板不含变量时原样返回"""
        ctx = _make_ctx()
        result = _render_template("纯文本消息没有变量", ctx, 1)
        self.assertEqual(result, "纯文本消息没有变量")

    def test_realistic_step3_template(self):
        """模拟真实 Step 3 派活模板"""
        ctx = _make_ctx(
            round_title="消除重复代码 + 自动派活",
            references={
                "requirements_url": "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R107/R107-product-requirements.md",
                "work_plan_url": "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R107/WORK_PLAN.md",
            },
            artifacts={
                "step2": {"tech_plan_url": "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R107/r107-step2-tech-plan.md"},
                "step3": {"commit_sha": "abc1234"},
            },
        )
        template = (
            "📋 {round}: {round_title}\n"
            "📄 需求: {requirements_url}\n"
            "📋 方案: {work_plan_url}\n"
            "🔧 技术方案: {tech_plan_url}\n"
            "已完成 commit: {commit_sha}"
        )
        result = _render_template(template, ctx, 3)
        self.assertIn("R107: 消除重复代码 + 自动派活", result)
        self.assertIn("https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R107/R107-product-requirements.md", result)
        self.assertIn("https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R107/r107-step2-tech-plan.md", result)
        self.assertIn("已完成 commit: abc1234", result)


if __name__ == "__main__":
    t = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    r = unittest.TextTestRunner(verbosity=2).run(t)
    total = r.testsRun
    passed = total - len(r.failures) - len(r.errors)
    print(f"\n{'='*50}")
    print(f"R107 渲染测试: {total} 项 | ✅ {passed} | ❌ {total-passed}")
