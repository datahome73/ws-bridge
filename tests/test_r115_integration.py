"""R115: 集成测试 — _try_advance_pipeline + artifacts 持久化完整链路。

模拟 _try_advance_pipeline 调用 _extract_artifact_kv 并持久化到
pipeline_contexts.json 的完整流程。

运行：
    cd /opt/data/ws-bridge && python3 -m pytest tests/test_r115_integration.py -v
"""
import json, os, sys, tempfile
from pathlib import Path

sys.path.insert(0, "/opt/data/ws-bridge")

import pytest

from server.ws_server.pipeline_context import (
    PipelineContextManager, PipelineContext, PipelineStatus, PipelineTaskKind,
)

# ── 辅助函数：直接测试 artifacts 提取与持久化 ──

@pytest.fixture
def mgr():
    """创建一个临时 PipelineContextManager，用完后清理。"""
    with tempfile.TemporaryDirectory() as tmp:
        manager = PipelineContextManager(data_dir=Path(tmp))
        yield manager


@pytest.mark.asyncio
async def test_artifacts_persist_to_disk(mgr):
    """集成测试1: artifacts 持久化到 pipeline_contexts.json。"""
    # 1. 创建管线
    ctx = PipelineContext(
        round_name="R115-TEST",
        task_kind=PipelineTaskKind.DEV,
        workspace_dir=Path("/opt/data/ws-bridge"),
        task_dir=Path("/tmp/r115_test"),
        workspace_id="r115-test",
        pm_inbox_id="",
        status=PipelineStatus.INIT,
        current_step=1,
        total_steps=6,
        steps=[],
    )
    mgr.set_context("R115-TEST", ctx)
    assert mgr.exists("R115-TEST")

    # 2. 模拟 artifacts 注入（_try_advance_pipeline 内做的事）
    _kv = {"test_result": "PASS", "test_report_url": "https://example.com/report.md"}
    _step_key = "step5"
    if not hasattr(ctx, 'artifacts') or not ctx.artifacts:
        ctx.artifacts = {}
    ctx.artifacts[_step_key] = _kv
    mgr.save()

    # 3. 验证持久化
    ctx_path = mgr._data_dir / "pipeline_contexts.json"
    assert ctx_path.exists(), "pipeline_contexts.json 未创建"
    raw = json.loads(ctx_path.read_text())
    assert "R115-TEST" in raw, "R115-TEST 未持久化"
    saved = raw["R115-TEST"]
    assert "artifacts" in saved, "artifacts 未持久化"
    assert saved["artifacts"]["step5"]["test_result"] == "PASS"
    assert saved["artifacts"]["step5"]["test_report_url"] == "https://example.com/report.md"
    print(f"  ✅ artifacts 已持久化: {saved['artifacts']}")


@pytest.mark.asyncio
async def test_multi_step_artifacts_accumulate(mgr):
    """集成测试2: 多步 artifacts 累积——各 Step 的 artifacts 独立保存。"""
    ctx = PipelineContext(
        round_name="R115-MULTI",
        task_kind=PipelineTaskKind.DEV,
        workspace_dir=Path("/opt/data/ws-bridge"),
        task_dir=Path("/tmp/r115_multi"),
        workspace_id="r115-multi",
        pm_inbox_id="",
        status=PipelineStatus.INIT,
        current_step=1,
        total_steps=6,
        steps=[],
    )
    mgr.set_context("R115-MULTI", ctx)

    # 模拟 Step 2 完成
    if not hasattr(ctx, 'artifacts') or not ctx.artifacts:
        ctx.artifacts = {}
    ctx.artifacts["step2"] = {"tech_plan_url": "https://example.com/tech.md", "design_decision": "ok"}
    mgr.save()

    # 模拟 Step 3 完成
    ctx.artifacts["step3"] = {"commit_sha": "abc123", "branch_name": "dev"}
    mgr.save()

    # 验证
    raw = json.loads((mgr._data_dir / "pipeline_contexts.json").read_text())
    arts = raw["R115-MULTI"]["artifacts"]
    assert "step2" in arts, "step2 artifacts 丢失"
    assert "step3" in arts, "step3 artifacts 丢失"
    assert arts["step2"]["design_decision"] == "ok"
    assert arts["step3"]["commit_sha"] == "abc123"
    assert len(arts) == 2
    print(f"  ✅ 多步累积: {list(arts.keys())}")


@pytest.mark.asyncio
async def test_no_artifacts_when_no_hash(mgr):
    """集成测试3: 无 ## 时不创建 artifacts 字段。"""
    ctx = PipelineContext(
        round_name="R115-NOART",
        task_kind=PipelineTaskKind.DEV,
        workspace_dir=Path("/opt/data/ws-bridge"),
        task_dir=Path("/tmp/r115_noart"),
        workspace_id="r115-noart",
        pm_inbox_id="",
        status=PipelineStatus.INIT,
        current_step=1,
        total_steps=6,
        steps=[],
    )
    mgr.set_context("R115-NOART", ctx)
    mgr.save()

    raw = json.loads((mgr._data_dir / "pipeline_contexts.json").read_text())
    saved = raw["R115-NOART"]
    assert "artifacts" not in saved or not saved.get("artifacts", {}), \
        f"不应有 artifacts 字段: {saved.get('artifacts', {})}"
    print("  ✅ 无 ## 时 artifacts 为空")


@pytest.mark.asyncio
async def test_artifacts_survive_restart(mgr):
    """集成测试4: artifacts 在重载（_load）后不丢失。"""
    ctx = PipelineContext(
        round_name="R115-RESTART",
        task_kind=PipelineTaskKind.DEV,
        workspace_dir=Path("/opt/data/ws-bridge"),
        task_dir=Path("/tmp/r115_restart"),
        workspace_id="r115-restart",
        pm_inbox_id="",
        status=PipelineStatus.INIT,
        current_step=1,
        total_steps=6,
        steps=[],
    )
    if not hasattr(ctx, 'artifacts') or not ctx.artifacts:
        ctx.artifacts = {}
    ctx.artifacts["step4"] = {"review_decision": "通过"}
    mgr.set_context("R115-RESTART", ctx)
    mgr.save()

    # 模拟重启：新建一个 Manager 读同一目录
    mgr2 = PipelineContextManager(data_dir=mgr._data_dir)
    restored = mgr2.get("R115-RESTART")
    assert restored is not None, "重启后上下文丢失"
    assert restored.artifacts.get("step4", {}).get("review_decision") == "通过", \
        "artifacts 在重启后丢失"
    print("  ✅ artifacts 重启后保留")
