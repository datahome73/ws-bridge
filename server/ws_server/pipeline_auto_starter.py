"""PipelineAutoStarter — Git 感知管线自动启动器。

职责：定期 git fetch origin/dev → 扫描 docs/ 中新 R{N}/WORK_PLAN.md
     → 解析 frontmatter → 创建 PipelineContext → 启动管线 → 派活 Step 1
"""

import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("ws-bridge.pipeline_auto_starter")

_ROUND_DIR_RE = re.compile(r"^R(\d+)$")


class PipelineAutoStarter:
    """Git 感知的管线自动启动器。

    与 WSS 主循环在同一事件循环中作为独立 asyncio task 运行。
    只 git fetch（不 pull/merge），零工作目录污染。
    """

    def __init__(
        self,
        repo_path: str,
        data_dir: str,
        pm_agent_id: str,
        context_mgr,  # PipelineContextManager
        dispatch_fn: Callable,  # async (round_name, agent_id, content) → None
        poll_interval: int = 60,
    ):
        self._repo_path = repo_path
        self._data_dir = Path(data_dir)
        self._pm_agent_id = pm_agent_id
        self._ctx_mgr = context_mgr
        self._dispatch = dispatch_fn
        self._poll_interval = poll_interval
        self._processed: set[str] = set()
        self._running = False

    async def start(self):
        """启动轮询循环（由 __main__.py 作为 asyncio task 调用）。"""
        self._running = True
        self._init_processed_from_existing()
        logger.info("[PAS] started, poll_interval=%ds", self._poll_interval)
        while self._running:
            try:
                await self._poll_one_cycle()
            except Exception as e:
                logger.warning("[PAS] poll error: %s", e)
            await asyncio.sleep(self._poll_interval)
        logger.info("[PAS] stopped")

    def stop(self):
        """停止轮询（设置 _running=False，下次 while 循环退出）。"""
        self._running = False

    # ── 初始化 ──────────────────────────────────────────

    def _init_processed_from_existing(self):
        """启动时扫描已有 PipelineContext，防止重启后重复触发。"""
        for ctx in self._ctx_mgr.get_all_active():
            if hasattr(ctx, "round_name"):
                self._processed.add(ctx.round_name)
            elif isinstance(ctx, dict):
                self._processed.add(ctx.get("round_name", ""))
        if self._processed:
            logger.info(
                "[PAS] restored %d processed rounds: %s",
                len(self._processed), sorted(self._processed),
            )

    # ── 核心轮询 ──

    async def _poll_one_cycle(self):
        """一个轮询周期：git fetch → 扫描 → 启动。"""
        if not self._git_fetch():
            return
        new_rounds = self._scan_new_rounds()
        if not new_rounds:
            return
        logger.info(
            "[PAS] found %d new round(s): %s",
            len(new_rounds), [r for r, _ in new_rounds],
        )
        for round_name, work_plan_path in new_rounds:
            try:
                await self._auto_start_pipeline(round_name, work_plan_path)
            except Exception as e:
                logger.error("[PAS] failed to start %s: %s", round_name, e)

    # ── Git 操作 ─────────────────────────────────────────

    def _git_fetch(self) -> bool:
        """执行 git fetch origin dev，只读操作。"""
        try:
            r = subprocess.run(
                ["git", "-C", self._repo_path, "fetch", "origin", "dev"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                logger.warning("[PAS] git fetch failed: %s", r.stderr[:200])
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.warning("[PAS] git fetch timed out")
            return False
        except FileNotFoundError:
            logger.error("[PAS] git not found at %s", self._repo_path)
            return False

    # ── 扫描新轮次 ───────────────────────────────────────

    def _scan_new_rounds(self) -> list[tuple[str, str]]:
        """扫描 docs/ 中新出现的 R{N}/WORK_PLAN.md。

        筛选条件：
        1. 目录名匹配 R{数字}
        2. 不在 _processed 中
        3. 目录包含 WORK_PLAN.md + R{N}-product-requirements.md
        4. 文件已在 origin/dev 分支（git ls-tree 验证）
        5. WORK_PLAN.md frontmatter 含 auto_start: true
        """
        docs_dir = Path(self._repo_path) / "docs"
        if not docs_dir.is_dir():
            return []
        new_rounds = []
        for entry in sorted(docs_dir.iterdir()):
            if not entry.is_dir():
                continue
            m = _ROUND_DIR_RE.match(entry.name)
            if not m:
                continue
            round_name = f"R{m.group(1)}"
            if round_name in self._processed:
                continue
            work_plan = entry / "WORK_PLAN.md"
            req_doc = entry / f"{round_name}-product-requirements.md"
            if not work_plan.is_file() or not req_doc.is_file():
                continue
            if not self._verify_on_remote(round_name):
                continue
            if not self._check_auto_start(work_plan):
                logger.info("[PAS] %s: auto_start not set, skipping", round_name)
                self._processed.add(round_name)
                continue
            new_rounds.append((round_name, str(work_plan)))
        return new_rounds

    def _verify_on_remote(self, round_name: str) -> bool:
        """通过 git ls-tree 验证文件是否已在 origin/dev。"""
        try:
            r = subprocess.run(
                ["git", "-C", self._repo_path, "ls-tree", "-r", "origin/dev",
                 f"docs/{round_name}/WORK_PLAN.md",
                 f"docs/{round_name}/{round_name}-product-requirements.md"],
                capture_output=True, text=True, timeout=10,
            )
            line_count = len(r.stdout.strip().split("\n")) if r.stdout.strip() else 0
            return line_count >= 2
        except Exception:
            return False

    def _check_auto_start(self, work_plan_path: Path) -> bool:
        """检查 WORK_PLAN.md 首部是否包含 auto_start: true。"""
        try:
            head = work_plan_path.read_text(encoding="utf-8")[:500]
            if re.search(r"\*\*auto_start:\*\*\s*true", head, re.IGNORECASE):
                return True
            if "auto_start: true" in head or "auto_start:true" in head:
                return True
            return False
        except Exception:
            return False

    # ── 启动管线 ─────────────────────────────────────────

    async def _auto_start_pipeline(self, round_name: str, work_plan_path: str):
        """为发现的新轮次自动启动管线。"""
        logger.info("[PAS] auto-starting pipeline for %s", round_name)

        # 获取全局角色映射作为 role_to_agent_ids
        role_to_agent_ids = self._ctx_mgr.get_global_role_map()

        # 通过 from_work_plan 创建上下文
        ctx = await self._ctx_mgr.from_work_plan(
            round_name=round_name,
            work_plan_path=work_plan_path,
            repo_path=self._repo_path,
            pm_agent_id=self._pm_agent_id,
            role_to_agent_ids=role_to_agent_ids,
        )

        # 转换状态到 RUNNING
        from .pipeline_context import PipelineStatus
        await self._ctx_mgr.transition_to(round_name, PipelineStatus.RUNNING)

        # 派活 Step 1 给 PM
        step1_msg = ctx.message_templates.get("step1", "")
        if step1_msg:
            await self._dispatch(round_name, self._pm_agent_id, step1_msg)

        self._processed.add(round_name)
        logger.info(
            "[PAS] %s: pipeline auto-started, Step 1 dispatched to PM",
            round_name,
        )
