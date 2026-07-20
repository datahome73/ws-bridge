# -*- coding: utf-8 -*-
"""R136 EXT-5: Git sync scheduler — extracted from main.py.

Pure extraction — no semantic changes. References state._PIPELINE_STATE,
state._PIPELINE_CONFIG, state._GIT_SYNC_TASK, config, and pps.PipelineGitSync.
"""
import asyncio
import time
import logging

from . import state
from server.common import config
from . import pipeline_sync as pps

logger = logging.getLogger("ws-bridge")


# ── R65 A2: Git sync lifecycle ──


def _ensure_git_scan() -> None:
    """在 handler 初始化时调用一次.启动 git sync 定时循环."""
    if not config.ENABLE_GIT_SYNC:
        logger.info("[R65] Git sync 已禁用（ENABLE_GIT_SYNC=false）")
        return
    if state._GIT_SYNC_TASK is None or state._GIT_SYNC_TASK.done():
        state._GIT_SYNC_TASK = asyncio.create_task(_start_git_sync_loop())
        logger.info("[R65] Git sync watchdog 已启动（interval=%ds）", config.GIT_SYNC_INTERVAL)


async def _start_git_sync_loop():
    """独立的 git 同步定时循环，每 GIT_SYNC_INTERVAL 秒执行一次."""
    while True:
        await asyncio.sleep(config.GIT_SYNC_INTERVAL)
        try:
            await _pipeline_git_sync_scan()
        except Exception as e:
            logger.warning("[R65] git_sync_scan error: %s", e)


async def _pipeline_git_sync_scan():
    """遍历所有活跃管线，检查 git 同步."""
    for pid, pstate in list(state._PIPELINE_STATE.items()):
        if not pstate.get("active"):
            continue
        if not config.ENABLE_GIT_SYNC:
            continue

        # 从 state._PIPELINE_CONFIG 读取管线专属配置
        pconfig = state._PIPELINE_CONFIG.get(pid, {})
        sync_config = {
            "branch": pconfig.get("git_sync_branch", config.GIT_SYNC_BRANCH),
            "repo_path": pconfig.get("repo_path", config.REPO_PATH),
            "last_sha": pstate.get("last_output_sha", ""),
            "fallback_enabled": config.GIT_SYNC_FALLBACK,
        }

        syncer = pps.PipelineGitSync(pid, sync_config)
        result = await syncer.sync()
        if result and result.get("synced"):
            # _auto_advance_pipeline is in main.py — imported at call site
            from .main import _auto_advance_pipeline
            await _auto_advance_pipeline(pid, result)
            pstate["_last_git_sync_ts"] = time.time()

