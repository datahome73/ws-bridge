"""
R65: Pipeline git sync — 管线 git 同步自动检测与状态推进。

核心类 PipelineGitSync 周期性检查 pipeline 工作分支的新提交，
通过匹配 commit message、产出文件、author 或兜底规则，自动推进管线状态机。
"""

import asyncio
import logging
import re

logger = logging.getLogger("ws-bridge.pipeline_sync")

# ── 匹配规则 ──────────────────────────────────────────────────────
# 规则1: commit message 含 Step 标记（conventional commit）
STEP_MESSAGE_PATTERNS = [
    re.compile(r'(?:feat|fix|docs|chore)\(R\d+\):'),  # 标准 conventional commit
    re.compile(r'R\d+\s+(?:Step|step)\s+\d+'),         # 显式 Step 标记
    re.compile(r'#\s*R\d+'),                            # 引用标记
]


async def _run_git(args: list[str], repo_path: str, timeout: float = 10.0) -> tuple[int, str, str]:
    """安全的 git CLI 调用封装。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout.decode().strip(), stderr.decode().strip()
    except asyncio.TimeoutError:
        return -1, "", f"git 命令超时 ({timeout}s)"
    except Exception as e:
        return -2, "", f"git 调用异常: {e}"


class PipelineGitSync:
    """管线 git 同步检测器。周期性检查 pipeline 工作分支的新提交，自动推进状态机。"""

    def __init__(self, pipeline_id: str, config: dict):
        """
        Args:
            pipeline_id: 管线标识（如 "R65"）
            config: 配置字典，包含以下键：
                - branch: str (默认 "dev")
                - repo_path: str (默认 "/opt/data/ws-bridge")
                - last_sha: str (上次处理的 commit SHA, 空字符串表示首次)
                - fallback_enabled: bool (默认 True, 兜底规则开关)
        """
        self.pipeline_id = pipeline_id
        self.branch = config.get("branch", "dev")
        self.repo_path = config.get("repo_path", "/opt/data/ws-bridge")
        self.last_sha = config.get("last_sha", "")
        self.fallback_enabled = config.get("fallback_enabled", True)
        # 并发锁 — 同一管线同时只一个 fetch
        self._lock = asyncio.Lock()

    async def sync(self, step_author_map: dict[str, str] | None = None,
                   current_step_idx: int = 0,
                   step_output_files: dict[str, list[str]] | None = None) -> dict | None:
        """检查 git 是否有新提交，如有则推进状态机。

        Returns:
            {
                "synced": True,
                "from_step": "step2",
                "to_step": "step3",
                "new_sha": "abc123def456",
                "commit": {"sha": "...", "message": "...", "author": "..."},
                "mode": "message" | "files" | "author" | "fallback"
            }
            or None if no new commits match.
        """
        async with self._lock:
            commits = await self._get_new_commits()
            if not commits:
                return None

            for commit in commits:
                matched, mode = self._match_commit(
                    commit, current_step_idx,
                    step_author_map, step_output_files,
                )
                if matched:
                    return {
                        "synced": True,
                        "from_step": f"step{current_step_idx}",
                        "to_step": f"step{current_step_idx + 1}",
                        "new_sha": commit["sha"],
                        "commit": commit,
                        "mode": mode,
                    }
            return None

    async def _get_new_commits(self) -> list[dict]:
        """git fetch + git log 获取新提交。

        Returns:
            [{"sha": str, "author": str, "message": str}, ...]
            失败时返回空列表（静默跳过，仅 warning 日志）。
        """
        # 1. git fetch
        rc, _, stderr = await _run_git(
            ["fetch", "--no-tags", "origin", self.branch],
            self.repo_path,
        )
        if rc != 0:
            logger.warning("[pipeline_sync] fetch 失败: %s", stderr)
            return []

        # 2. git log 获取新提交
        range_spec = f"origin/{self.branch}"
        if self.last_sha:
            range_spec = f"{self.last_sha}..origin/{self.branch}"

        rc, stdout, stderr = await _run_git(
            ["log", "--format=%H|%an|%s", range_spec],
            self.repo_path,
        )
        if rc != 0:
            logger.warning("[pipeline_sync] git log 失败: %s", stderr)
            return []

        commits = []
        for line in stdout.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({
                    "sha": parts[0],
                    "author": parts[1],
                    "message": parts[2],
                })

        # 按 commit 时间先后返回（正序）
        commits.reverse()
        return commits

    def _match_commit(self, commit: dict, current_step_idx: int,
                      step_author_map: dict[str, str] | None = None,
                      step_output_files: dict[str, list[str]] | None = None) -> tuple[bool, str]:
        """将 commit 匹配到 Step。

        匹配优先级:
        1. commit message 含 Step 标记
        2. commit 修改了 Step 配置的产出文件
        3. commit author 匹配当前 Step 的角色名
        4. 兜底: pipeline 活跃期间任意新 commit（受 fallback_enabled 控制）

        Returns:
            (matched: bool, mode: str) — mode 为匹配方式
        """
        # 规则1: commit message 含 Step 标记
        msg = commit.get("message", "")
        for pattern in STEP_MESSAGE_PATTERNS:
            if pattern.search(msg):
                return True, "message"

        # 规则2: 产出文件匹配
        if step_output_files:
            step_key = f"step{current_step_idx + 1}"
            expected_files = step_output_files.get(step_key, [])
            if expected_files:
                # 获取此 commit 修改的文件列表
                changed_files = self._get_commit_files(commit["sha"])
                if any(cf.startswith(ef) for ef in expected_files for cf in changed_files):
                    return True, "files"

        # 规则3: author 匹配
        if step_author_map:
            step_key = f"step{current_step_idx + 1}"
            expected_authors = step_author_map.get(step_key, [])
            if commit.get("author", "") in expected_authors:
                return True, "author"

        # 规则4: 兜底
        if self.fallback_enabled:
            return True, "fallback"

        return False, ""

    def _get_commit_files(self, sha: str) -> list[str]:
        """获取 commit 修改的文件列表。"""
        rc, stdout, stderr = _run_git(
            ["diff-tree", "--no-commit-id", "-r", "--name-only", sha],
            self.repo_path,
            timeout=5.0,
        )
        # _run_git is async — need to run in event loop
        # Use a sync wrapper
        import subprocess
        try:
            result = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", sha],
                cwd=self.repo_path,
                capture_output=True, text=True, timeout=5.0,
            )
            if result.returncode == 0:
                return [f.strip() for f in result.stdout.split("\n") if f.strip()]
        except Exception as e:
            logger.warning("[pipeline_sync] diff-tree 失败: %s", e)
        return []


# ── 模块级状态 ────────────────────────────────────────────────────
# pipeline_id → asyncio.Lock
_pipeline_git_locks: dict[str, asyncio.Lock] = {}
# pipeline_id → asyncio.Task (for lifecycle)
_pipeline_git_tasks: dict[str, asyncio.Task] = {}
