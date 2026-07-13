"""R109: Pipeline auto-starter — scan WORK_PLAN.md files & auto-create contexts.

No background loop (user disabled all auto features 2026-07-13).
Call scan_and_start() explicitly on server startup or via !command dispatch.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .pipeline_context import PipelineContextManager

logger = logging.getLogger("ws-bridge.auto_starter")


def find_work_plans(repo_path: Path) -> list[Path]:
    """扫描 docs/<round>/WORK_PLAN.md 文件，按轮次名排序返回。

    只匹配 docs/R{N}/WORK_PLAN.md 格式的路径。
    """
    docs_dir = repo_path / "docs"
    if not docs_dir.exists():
        logger.debug("docs/ not found at %s", docs_dir)
        return []

    plans: list[Path] = []
    for child in sorted(docs_dir.iterdir()):
        if child.is_dir() and child.name.startswith("R"):
            wp = child / "WORK_PLAN.md"
            if wp.exists():
                plans.append(wp)
    return plans


def parse_work_plan_meta(path: Path) -> dict:
    """解析 WORK_PLAN.md 的 > **key:** value frontmatter。

    Returns:
        {round_name: str, roles: dict, auto_chain: bool, ...}
    """
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")

    meta: dict = {
        "round_name": "",
        "roles": {},
        "auto_chain": False,
        "steps": [],
    }
    in_frontmatter = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("> **"):
            in_frontmatter = True
            rest = stripped[2:].strip()
            if ":** " in rest:
                parts = rest.split(":** ", 1)
                key = parts[0].strip("*").strip().lower()
                val = parts[1].strip()
                if key in ("轮次", "round"):
                    meta["round_name"] = val.upper().strip()
                elif key in ("auto_chain",):
                    meta["auto_chain"] = val.strip().lower() in ("true", "yes", "1")
                elif key in ("角色映射", "roles", "role mapping"):
                    roles = {}
                    for pair in val.split(","):
                        pair = pair.strip()
                        if "=" in pair:
                            role, name = pair.split("=", 1)
                            roles[role.strip()] = name.strip()
                    meta["roles"] = roles
        elif in_frontmatter and not stripped.startswith(">"):
            in_frontmatter = False

    # Extract steps from ### headers
    import re

    for line in lines:
        m = re.match(r"^###\s+Step\s+(\d+)\s*[—–-]?\s*(.*)", line.strip())
        if m:
            meta["steps"].append({
                "num": int(m.group(1)),
                "title": m.group(2).strip().replace("✅", "").strip(),
            })

    return meta


async def scan_and_start(
    mgr: PipelineContextManager,
    repo_path: str | Path,
    pm_inbox_id: str = "",
    created_by: str = "_system",
) -> int:
    """扫描 docs/<round>/WORK_PLAN.md，为尚无 PipelineContext 的轮次自动创建。

    Args:
        mgr: PipelineContextManager 实例。
        repo_path: 仓库根路径。
        pm_inbox_id: PM 的 inbox channel ID。
        created_by: 创建者 agent_id。

    Returns:
        新创建的管线数量。
    """
    repo = Path(repo_path)
    plans = find_work_plans(repo)
    if not plans:
        logger.info("No WORK_PLAN.md files found under docs/")
        return 0

    count = 0
    for wp_path in plans:
        meta = parse_work_plan_meta(wp_path)
        round_name = meta.get("round_name", "")
        if not round_name:
            logger.warning("Skipping %s: no round_name in frontmatter", wp_path)
            continue

        # Skip if already exists
        if mgr.exists(round_name):
            logger.debug("Pipeline %s already exists, skipping", round_name)
            continue

        try:
            await mgr.from_work_plan(
                work_plan_path=wp_path,
                workspace_dir=repo,
                workspace_id=round_name.lower(),
                pm_inbox_id=pm_inbox_id,
                created_by=created_by,
            )
            count += 1
            logger.info(
                "Auto-started pipeline %s from %s (roles=%s, steps=%d)",
                round_name, wp_path.name,
                meta.get("roles", {}),
                len(meta.get("steps", [])),
            )
        except Exception as exc:
            logger.error("Failed to auto-start %s: %s", round_name, exc)

    if count:
        logger.info("Auto-started %d pipeline(s) from WORK_PLAN files", count)
    return count


class PipelineAutoStarter:
    """管线自动启动器 — 服务器启动时扫描 WORK_PLAN.md 并创建 PipelineContext。

    零后台循环（用户已禁用自动特性 2026-07-13）。
    生命周期由 aiohttp app.on_startup / on_shutdown 管理。
    """

    def __init__(
        self,
        repo_path: str = "/opt/data/ws-bridge",
        data_dir: str = "./data",
        pm_agent_id: str = "",
        context_mgr: PipelineContextManager | None = None,
        dispatch_fn=None,
    ):
        self.repo_path = repo_path
        self.data_dir = data_dir
        self.pm_agent_id = pm_agent_id
        self._ctx_mgr = context_mgr
        self._dispatch = dispatch_fn
        self._running = False

    @property
    def ctx_mgr(self) -> PipelineContextManager | None:
        return self._ctx_mgr

    @ctx_mgr.setter
    def ctx_mgr(self, mgr: PipelineContextManager) -> None:
        self._ctx_mgr = mgr

    async def start(self) -> None:
        """首次启动：扫描并创建 WORK_PLAN 管线。

        不循环。启动后即静默。
        """
        if self._running:
            logger.debug("PipelineAutoStarter already running")
            return
        self._running = True
        mgr = self._ctx_mgr or PipelineContextManager(data_dir=Path(self.data_dir))
        count = await scan_and_start(
            mgr,
            self.repo_path,
            pm_inbox_id=self.pm_agent_id,
            created_by="_system",
        )
        logger.info(
            "PipelineAutoStarter: %d pipeline(s) auto-started, entering standby",
            count,
        )

    def stop(self) -> None:
        """停止（清理标记）。"""
        self._running = False
        logger.info("PipelineAutoStarter stopped")
