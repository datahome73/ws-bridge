# R110 Step 2 — 自动派活：零手工启动管线 技术方案

> **轮次：** R110 · **角色：** 架构师（小开）
> **日期：** 2026-07-13
> **状态：** 📝 技术方案
> **前置：** R109 全闭环已上线 ✅ · [需求文档](./R110-product-requirements.md)
> **关联：** [WORK_PLAN](./WORK_PLAN.md)

---

## 目录

1. [PipelineAutoStarter 组件设计](#1-pipelineautostarter-组件设计)
2. [from_work_plan 工厂方法](#2-from_work_plan-工厂方法)
3. [角色映射](#3-角色映射)
4. [启动方式](#4-启动方式)
5. [安全边界](#5-安全边界)
6. [与 !pipeline_start 命令兼容](#6-与-pipeline_start-命令兼容)
7. [执行计划与验收](#7-执行计划与验收)

---

## 1. PipelineAutoStarter 组件设计

### 1.1 职责边界

`PipelineAutoStarter` 职责**极窄**，只做一件事：
> **检测 git push → 找到新轮次 → 启动管线并派活 Step 1**

不做的事：
- ❌ 不派活 Step 2~6（已有 `_auto_dispatch` 和 `_try_advance_pipeline` 接管）
- ❌ 不超时检测（由 `_STEP_TIMEOUT` 负责）
- ❌ 不管理资源（由 PipelineContextManager 管理）
- ❌ 不处理 bot 回复（由 `_handle_server_relay` 处理）

### 1.2 新增文件

**`server/ws_server/pipeline_auto_starter.py`**（约 180 行）

```python
"""
PipelineAutoStarter — Git 感知管线自动启动器。

职责：定期 git fetch origin/dev → 扫描 docs/ 中新 R{N}/WORK_PLAN.md
     → 解析 frontmatter → 创建 PipelineContext → 启动管线 → 派活 Step 1
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ws-bridge.pipeline_auto_starter")

_ROUND_DIR_RE = re.compile(r"^R(\d+)$")
_AUTO_START_RE = re.compile(r"\*\*auto_start:\*\*\s*(true|false)", re.IGNORECASE)


class PipelineAutoStarter:
    """Git 感知的管线自动启动器。"""

    def __init__(
        self,
        repo_path: str,
        data_dir: str,
        pm_agent_id: str,
        context_mgr,  # PipelineContextManager
        dispatch_fn,  # async callable(round_name, agent_id, content)
        poll_interval: int = 60,
    ):
        self._repo_path = repo_path
        self._data_dir = Path(data_dir)
        self._pm_agent_id = pm_agent_id
        self._ctx_mgr = context_mgr
        self._dispatch = dispatch_fn
        self._poll_interval = poll_interval

        self._processed: set[str] = set()  # 已处理轮次
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

    async def stop(self):
        self._running = False

    # ── 初始化 ──────────────────────────────────────────

    def _init_processed_from_existing(self):
        """启动时扫描已有 PipelineContext，防止重启后重复触发。"""
        for ctx in self._ctx_mgr.get_all_active():
            self._processed.add(ctx.round_name)
        if self._processed:
            logger.info("[PAS] restored %d processed rounds: %s",
                        len(self._processed), sorted(self._processed))

    # ── 核心 ────────────────────────────────────────────

    async def _poll_one_cycle(self):
        """一个轮询周期：git fetch → 扫描 → 启动。"""
        if not self._git_fetch():
            return  # git fetch 失败，静默跳过

        new_rounds = self._scan_new_rounds()
        if not new_rounds:
            return

        logger.info("[PAS] found %d new round(s): %s", len(new_rounds),
                     [r for r, _ in new_rounds])

        for round_name, work_plan_path in new_rounds:
            try:
                await self._auto_start_pipeline(round_name, work_plan_path)
            except Exception as e:
                logger.error("[PAS] failed to start %s: %s", round_name, e)

    # ── Git 操作 ─────────────────────────────────────────

    def _git_fetch(self) -> bool:
        """执行 git fetch origin dev，只读操作。

        失败时不抛异常，返回 False 让调用方静默跳过。
        """
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

    # ── 扫描 ─────────────────────────────────────────────

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

            # 已处理过？跳过
            if round_name in self._processed:
                continue

            work_plan = entry / "WORK_PLAN.md"
            req_doc = entry / f"{round_name}-product-requirements.md"

            # 必须的文件都存在？
            if not work_plan.is_file() or not req_doc.is_file():
                continue

            # 文件已在 origin/dev？
            if not self._verify_on_remote(round_name):
                continue

            # auto_start 标记检查
            if not self._check_auto_start(work_plan):
                logger.info("[PAS] %s: auto_start not set, skipping", round_name)
                self._processed.add(round_name)  # 标记避免重复检查
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
            # ls-tree 返回的文件行数 = 已存在的文件数
            line_count = len(r.stdout.strip().split("\n")) if r.stdout.strip() else 0
            return line_count >= 2  # 两个文件都存在
        except Exception:
            return False

    def _check_auto_start(self, work_plan_path: Path) -> bool:
        """检查 WORK_PLAN.md 首部是否包含 auto_start: true。"""
        try:
            head = work_plan_path.read_text(encoding="utf-8")[:500]
            m = _AUTO_START_RE.search(head)
            if m and m.group(1).lower() == "true":
                return True
            # 兼容无 > 前缀格式
            if "auto_start: true" in head or "auto_start:true" in head:
                return True
            return False
        except Exception:
            return False

    # ── 启动管线 ─────────────────────────────────────────

    async def _auto_start_pipeline(self, round_name: str, work_plan_path: str):
        """为发现的新轮次自动启动管线。"""
        logger.info("[PAS] auto-starting pipeline for %s", round_name)

        # 1. 解析 WORK_PLAN.md frontmatter
        plan_info = self._parse_work_plan(work_plan_path)

        # 2. 创建 PipelineContext
        ctx = await self._ctx_mgr.create(
            round_name=round_name,
            task_kind=...,
            workspace_dir=Path(self._repo_path),
            workspace_id=f"auto-{round_name.lower()}",
            pm_inbox_id=f"_inbox:{self._pm_agent_id}",
            total_steps=6,
            created_by=f"system:pipeline_auto_starter",
        )

        # 3. 设置角色映射
        for role_system, agent_id_list in plan_info.get("role_agent_map", {}).items():
            await self._ctx_mgr.update_role_agent_map_round(
                round_name, role_system, agent_id_list,
            )

        # 4. 设置 step 配置 + 模板 + references
        await self._ctx_mgr.update_steps(round_name, plan_info.get("steps", []))
        ctx.round_title = plan_info.get("title", round_name)
        ctx.references = plan_info.get("references", {})
        ctx.message_templates = plan_info.get("message_templates", {})

        # 5. 转换状态 → RUNNING
        await self._ctx_mgr.transition_to(round_name, ...)  # INIT → PLANNING

        # 6. 派活 Step 1 给 PM bot
        step1_msg = ctx.message_templates.get("step1", "")
        if step1_msg:
            await self._dispatch(round_name, self._pm_agent_id, step1_msg)

        # 7. 记录已处理
        self._processed.add(round_name)
        logger.info("[PAS] %s: pipeline auto-started, Step 1 dispatched to PM", round_name)
```

### 1.3 Git Poll 设计

| 参数 | 默认值 | 说明 |
|:-----|:-------|:------|
| `POLL_INTERVAL` | 60s | 检查间隔，环境变量 `PAS_POLL_INTERVAL` 可覆写 |
| `REMOTE_BRANCH` | `origin/dev` | 只 fetch 此分支，减少网络开销 |

**fetch 操作详情：**
- 命令：`git -C {repo_path} fetch origin dev`
- 超时：30s
- 失败行为：日志告警 + 静默跳过本轮
- 安全：**只 fetch，不 pull，不 merge**。工作目录不受影响

### 1.4 扫描策略

```
一次 poll 周期流程：

git fetch origin dev
    ↓
读取 docs/ 目录列表
    ↓
过滤：目录名 = R{数字}
    ↓
过滤：不在 _processed 中
    ↓
过滤：存在 WORK_PLAN.md + R{N}-product-requirements.md
    ↓
过滤：git ls-tree 验证已在 origin/dev
    ↓
过滤：WORK_PLAN.md 含 auto_start: true
    ↓
→ 符合条件的返回 [(round_name, work_plan_path), ...]
```

**为什么不依赖 `git diff`？** 因为 `git fetch` 后不更新本地 ref，用 `ls-tree` 直接查询远程分支状态更安全，避免工作目录污染。

**目录遍历效率：** `docs/` 最多几十个子目录，每次遍历 < 1ms，完全可以忍受。

### 1.5 防重复机制

| 层级 | 机制 | 说明 |
|:-----|:------|:------|
| 1 | `_processed` 内存集 | 已处理轮次不入第二轮 |
| 2 | 使用现有 PipelineContext 初始化 | 重启后 `_init_processed_from_existing()` 扫描已有上下文 |
| 3 | `PipelineContextManager.create()` 内部校验 | 重复轮次抛 `ValueError`（防止并发冲突） |
| 4 | 无 `auto_start` 标记的也加入 `_processed` | 避免每 60s 重复检查同一个跳过轮次 |

### 1.6 与已有组件的集成

```
PipelineAutoStarter              (新增)
  │ 检测新轮次 → 创建上下文 → 启动管线
  │
  ▼
Step 1: PM 审核 (PM bot inbox)
  │
PM 回复 "✅ 完成"
  │
  ▼
_handle_server_relay              (已有)
  │ → _try_advance_pipeline
  │
  ▼
_auto_dispatch                    (已有)
  │ → 派活 Step 2 给小开 (arch)
  │ → 派活 Step 3 给爱泰 (dev)
  │ → ... Steps 2~6 全自动
  │
  ▼
PipelineContextManager            (已有，增加 from_work_plan)
  │ 状态机: INIT → RUNNING → BLOCKED → COMPLETED
```

---

## 2. from_work_plan 工厂方法

### 2.1 方法签名

在 `server/ws_server/pipeline_context.py` 的 `PipelineContextManager` 中新增：

```python
async def from_work_plan(
    self,
    round_name: str,
    work_plan_path: str | Path,
    repo_path: str,
    pm_agent_id: str,
    role_to_agent_ids: dict[str, list[str]],
) -> PipelineContext:
    """从 WORK_PLAN.md 文件创建 PipelineContext。

    解析 frontmatter → 自动填充：
      - round_title（说明字段）
      - message_templates（§2.4 模板规则）
      - references（需求文档 / WORK_PLAN URL）
      - steps（Step 定义）
      - role_agent_map（从传入参数映射）
      - task_dir（workspace_dir / pipeline_tasks / {round_name}）
    """
```

### 2.2 Frontmatter 解析

WORK_PLAN.md 当前使用 Markdown blockquote 格式的 frontmatter：

```markdown
> **轮次：** R110
> **auto_chain:** true
> **auto_start:** true
> **说明：** 新增 PipelineAutoStarter 组件...
> **角色映射：** pm=小谷, arch=小开, dev=爱泰, review=小周, qa=泰虾, ops=小爱
```

解析策略：**不引入 YAML 解析器**（零新增依赖），使用正则从文件头部 500 字符提取键值对：

```python
import re

_FRONTMATTER_RE = re.compile(
    r"> \*\*(\w[\w\s]+?):\*\*\s*(.+?)(?=\n> \*\*|\n\n|\Z)",
    re.DOTALL | re.MULTILINE,
)
_ROLE_MAP_RE = re.compile(r"(\w+)=(\S+)")
_TITLE_RE = re.compile(r"\*\*说明：\*\*\s*(.+)")

def _parse_work_plan_frontmatter(work_plan_path: str) -> dict:
    """解析 WORK_PLAN.md frontmatter 返回结构化 dict。"""
    head = Path(work_plan_path).read_text(encoding="utf-8")[:500]

    result = {}

    # 轮次名（从文件内容提取，或从文件名路径已知）
    m = re.search(r"\*\*轮次：\*\*\s*(R\d+)", head)
    if m:
        result["round_name"] = m.group(1)

    # auto_chain
    m = re.search(r"\*\*auto_chain:\*\*\s*(true|false)", head)
    if m:
        result["auto_chain"] = m.group(1).lower() == "true"

    # auto_start
    m = re.search(r"\*\*auto_start:\*\*\s*(true|false)", head)
    if m:
        result["auto_start"] = m.group(1).lower() == "true"

    # 说明/标题
    m = _TITLE_RE.search(head)
    if m:
        result["title"] = m.group(1).strip()

    # 角色映射字符串 → dict
    m = re.search(r"\*\*角色映射：\*\*\s*(.+)", head)
    if m:
        raw = m.group(1)
        role_map = {}
        for rm in _ROLE_MAP_RE.finditer(raw):
            role_map[rm.group(1)] = rm.group(2)
        result["role_display_map"] = role_map  # {"arch": "小开", ...}

    return result
```

### 2.3 消息模板自动生成

规则（需求文档 §2.4）：

```python
def _generate_message_templates(
    round_name: str, work_plan_path: str, repo_path: str,
) -> dict[str, str]:
    """根据轮次名自动生成 6 步派活模板。"""
    r = round_name.lower()

    # URL 构造
    base = f"https://github.com/datahome73/ws-bridge/blob/main/docs/{round_name}"
    req_url = f"{base}/{round_name}-product-requirements.md"
    wp_url = f"{base}/WORK_PLAN.md"
    tech_url = f"{base}/{r}-step2-tech-plan.md"

    return {
        "step1": (
            f"📋 **{round_name} Step 1 — PM 审核**\n\n"
            f"需求文档已就绪：\n{req_url}\n\n"
            f"请审核后回复 ✅ 完成"
        ),
        "step2": (
            f"🏗️ **{round_name} Step 2 — 技术方案**\n\n"
            f"需求文档：{req_url}\n"
            f"WORK_PLAN：{wp_url}\n\n"
            f"请输出技术方案文档，推 dev 后回复 ✅ 完成"
        ),
        "step3": (
            f"💻 **{round_name} Step 3 — 编码实现**\n\n"
            f"技术方案：{tech_url}\n\n"
            f"按方案实现，推 dev 后回复 ✅ 完成"
        ),
        "step4": (
            f"🔍 **{round_name} Step 4 — 代码审查**\n\n"
            f"审查 Step 3 改动。通过后回复 ✅ 完成"
        ),
        "step5": (
            f"🧪 **{round_name} Step 5 — 测试验证**\n\n"
            f"验证验收标准。全部通过后回复 ✅ 完成"
        ),
        "step6": (
            f"🚀 **{round_name} Step 6 — 合并部署归档**\n\n"
            f"PR dev→main，重建镜像，部署。完成后回复 ✅ 完成"
        ),
    }
```

### 2.4 references 自动构造

```python
def _generate_references(round_name: str) -> dict:
    """生成 references 字典。"""
    base = f"https://github.com/datahome73/ws-bridge/blob/main/docs/{round_name}"
    return {
        "requirements_url": f"{base}/{round_name}-product-requirements.md",
        "work_plan_url": f"{base}/WORK_PLAN.md",
        "tech_plan_url": f"{base}/{round_name.lower()}-step2-tech-plan.md",
    }
```

### 2.5 Step 配置自动生成

```python
def _generate_steps(round_name: str) -> list[dict]:
    """生成默认的 6 步配置列表。"""
    return [
        {"name": "step1", "executor_role": "pm",          "title": "PM 审核"},
        {"name": "step2", "executor_role": "arch",        "title": "技术方案"},
        {"name": "step3", "executor_role": "dev",         "title": "编码实现"},
        {"name": "step4", "executor_role": "review",      "title": "代码审查"},
        {"name": "step5", "executor_role": "qa",          "title": "测试验证"},
        {"name": "step6", "executor_role": "operations",  "title": "合并部署归档"},
    ]
```

### 2.6 from_work_plan 完整实现

```python
async def from_work_plan(
    self,
    round_name: str,
    work_plan_path: str | Path,
    repo_path: str,
    pm_agent_id: str,
    role_to_agent_ids: dict[str, list[str]],  # {"arch": ["ws_xxx"], ...}
) -> PipelineContext:
    """从 WORK_PLAN.md 创建并启动 PipelineContext。"""
    work_plan_path = Path(work_plan_path)
    workspace_dir = Path(repo_path)

    # 解析 frontmatter
    info = _parse_work_plan_frontmatter(str(work_plan_path))

    # 生成模板/references
    templates = _generate_message_templates(round_name, str(work_plan_path), repo_path)
    refs = _generate_references(round_name)
    steps = _generate_steps(round_name)

    # 构建角色映射（系统角色 → agent_id list）
    role_agent_map: dict[str, list[str]] = {}
    role_display_map = info.get("role_display_map", {})
    for system_role, display_name in role_display_map.items():
        # 将 display_name 映射到 agent_id（从外部传入的 role_to_agent_ids）
        # 或直接从 Agent Card 查找
        agent_ids = role_to_agent_ids.get(system_role, [])
        if agent_ids:
            role_agent_map[system_role] = agent_ids

    # 创建上下文
    ctx = PipelineContext(
        round_name=round_name,
        task_kind=PipelineTaskKind.DEV,
        workspace_dir=workspace_dir,
        task_dir=workspace_dir / "pipeline_tasks" / round_name,
        workspace_id=f"auto-{round_name.lower()}",
        pm_inbox_id=f"_inbox:{pm_agent_id}",
        status=PipelineStatus.INIT,
        current_phase="plan",
        current_step=1,
        total_steps=6,
        role_agent_map=role_agent_map,
        created_at=time.time(),
        updated_at=time.time(),
        created_by="system:pipeline_auto_starter",
        round_title=info.get("title", round_name),
        references=refs,
        message_templates=templates,
    )
    ctx.steps = steps

    self._contexts[round_name] = ctx
    self._save()
    logger.info("PipelineContext %s created from work_plan: %s",
                round_name, info.get("title", ""))
    return ctx
```

---

## 3. 角色映射

### 3.1 映射层次

角色映射有三个层次：

```
WORK_PLAN.md frontmatter        Agent Card 注册          PipelineContext
  "角色映射：pm=小谷, ..."   ──→  "小谷" → agent_id    ──→  {"pm": ["ws_xxx"]}
     显示名称                            系统内部 ID              系统角色 → agent_ids
```

### 3.2 映射流程

```
1. 从 WORK_PLAN.md 解析角色映射字符串
     "pm=小谷, arch=小开, dev=爱泰, review=小周, qa=泰虾, ops=小爱"
     ↓
2. 转换为：{"pm": "小谷", "arch": "小开", "dev": "爱泰", ...}
     ↓
3. 从 Agent Card（或全局角色映射）查找每个 display_name 的 agent_id
     "小谷" → ["ws_f26e585f6479"]
     "小开" → ["ws_3f7cdd736c1c"]
     "爱泰" → ["ws_0bb747d3ea2a"]
     ...
     ↓
4. 存入 PipelineContext.role_agent_map：
     {"pm": ["ws_f26..."],
      "arch": ["ws_3f7..."],
      "dev": ["ws_0bb..."],
      ...}
```

### 3.3 实现（Agent Card 查询）

```python
def _resolve_role_agent_ids(
    role_display_map: dict[str, str],  # {"arch": "小开", ...}
) -> dict[str, list[str]]:
    """将 display_name 映射为 agent_id 列表。

    查询顺序：
    1. PipelineContextManager 的全局角色映射（_global_role_map）
    2. Agent Card 注册表（agent_card.get_agent_by_role）
    3. 回退：无映射时返回空列表
    """
    result: dict[str, list[str]] = {}

    # 通过全局角色映射查找
    # 每个 bot 注册时 Agent Card 包含 display_name + roles
    # _refresh_role_agent_map() 维护 role → [agent_id] 映射

    for system_role, display_name in role_display_map.items():
        # 从全局角色映射反向查找该 display_name 对应的 agent_id
        agent_ids = _find_agent_ids_by_display_name(display_name)
        if agent_ids:
            result[system_role] = agent_ids
        else:
            logger.warning(
                "No agent found for role '%s' (display_name='%s')",
                system_role, display_name,
            )
            result[system_role] = []  # 空列表，后续可手动补充

    return result
```

### 3.4 反向查找实现

```python
def _find_agent_ids_by_display_name(display_name: str) -> list[str]:
    """从全局角色映射反向查找 display_name 对应的所有 agent_id。"""
    from .agent_card import get_all_agents  # 延迟 import 避免循环

    found = []
    for agent_id, info in get_all_agents().items():
        if info.get("display_name") == display_name:
            found.append(agent_id)
    return found
```

### 3.5 映射验证

`from_work_plan()` 创建后立即验证：

```python
# 创建后检查角色映射
for role, agents in role_agent_map.items():
    if not agents:
        logger.warning(
            "[PAS] %s: role '%s' has no agent! "
            "Pipeline will not dispatch to this role.",
            round_name, role,
        )
```

空角色映射的 Step 在 `_auto_dispatch` 中会自然跳过（找不到 agent_id 则不派活），不会导致崩溃。

---

## 4. 启动方式

### 4.1 注册为 asyncio Task

在 `server/ws_server/__main__.py` 中注册：

```python
# __main__.py
import asyncio
from .pipeline_auto_starter import PipelineAutoStarter

async def main():
    # ... 现有初始化（config, db, context_mgr, ...）

    # ── R110: 启动 PipelineAutoStarter ──
    pas = PipelineAutoStarter(
        repo_path=config.REPO_PATH,
        data_dir=str(config.DATA_DIR),
        pm_agent_id=config.PM_AGENT_ID,
        context_mgr=context_mgr,
        dispatch_fn=_auto_dispatch,  # 或包装函数
        poll_interval=int(os.environ.get("PAS_POLL_INTERVAL", "60")),
    )
    pas_task = asyncio.create_task(pas.start())

    # ... 启动其他任务 ...

    # 主循环
    await asyncio.gather(
        ws_server_task,
        pas_task,  # PipelineAutoStarter 加入 gather
        # ... 其他协程 ...
    )
```

### 4.2 与 WSS 主循环共存

`PipelineAutoStarter` 是一个独立的 asyncio task，与 WSS 主循环（`_reader_loop`）**在同一事件循环中并行运行**：

```
asyncio event loop
  ├── WebSocket server (accept + reader_loop)
  ├── PipelineAutoStarter.poll_one_cycle()  (每 60s 运行一次)
  ├── _write_bot_status_loop()             (每 10s，R109)
  └── 其他定时任务
```

**优势：**
- 零线程安全顾虑（全 asyncio）
- `_poll_one_cycle()` 执行期间不会阻塞 WSS 消息处理（`asyncio.sleep` 让出控制权）
- `git fetch` 通过 `subprocess.run()` 同步执行，30s 超时，不会永久阻塞

### 4.3 配置项

| 环境变量 | 默认值 | 说明 |
|:---------|:-------|:------|
| `PAS_POLL_INTERVAL` | `60` | Git poll 间隔（秒） |
| `PAS_ENABLED` | `1` | 总开关（`0` 禁用） |
| `PAS_REPO_PATH` | `REPO_PATH` | Git 仓库路径 |
| `PAS_REMOTE` | `origin/dev` | 监听的远程分支 |

### 4.4 关闭方式

```python
# 在 ws-server 优雅关闭时调用
async def shutdown():
    pas.stop()  # 设置 _running = False，下一次 while 循环退出
    await asyncio.sleep(0)  # 让 task 有机会退出
```

---

## 5. 安全边界

### 5.1 安全清单

| # | 风险 | 防护措施 | 严重度 |
|:-:|:-----|:---------|:------:|
| 1 | `git fetch` 损坏工作目录 | 只 fetch，不 pull/merge/checkout | 🔴 高 |
| 2 | `git fetch` 超时阻塞 WSS | 30s 超时 + 异常静默捕获 | 🟡 中 |
| 3 | WORK_PLAN.md 格式异常导致崩溃 | 所有正则匹配用 try/except 包围 | 🔴 高 |
| 4 | 半推文件触发虚假启动 | `git ls-tree` 验证两个文件都在 remote | 🔴 高 |
| 5 | 恶意 WORK_PLAN.md 注入 | 只读解析 frontmatter，不 eval/exec | 🟡 中 |
| 6 | 重启后重复触发 | `_init_processed_from_existing()` 从已有上下文恢复 | 🔴 高 |
| 7 | 并行触发同轮次 | `PipelineContextManager.create()` 带锁防重复 | 🟡 中 |
| 8 | 异常轮次污染 `_processed` | 每个轮次独立 try/except，失败的只记日志不阻塞 | 🟡 中 |
| 9 | `auto_start` 误判 | 严格正则检查 `auto_start: true`，不写默认不启动 | 🟡 中 |
| 10 | 管道泄漏（未归档上下文） | `_processed` 只增不减；重启后从已有上下文恢复 | 🟢 低 |

### 5.2 异常隔离

```
_poll_one_cycle()
  ├── try: _git_fetch()        → fail → return False（静默跳过本轮）
  ├── try: _scan_new_rounds()  → fail → 日志 warning，跳过本轮
  └── for each round:
       └── try: _auto_start_pipeline() → fail → 日志 error，继续下轮
```

**目的：** 一个轮次启动失败不影响其他轮次，一次 git fetch 失败不阻塞永久。

### 5.3 `auto_start` 守卫

所有需要自动启动的 R 轮次必须在 WORK_PLAN.md 头部显式声明：

```markdown
> **auto_start:** true
```

**为什么不是默认 true？** 兼容现有轮次（R75-R109 不自动启动），也允许 PM 选择哪些轮次让系统接管、哪些仍然手工控制。

**检测失败的后果：** 该轮次被加入 `_processed`，不再检查，PM 需手工创建 PipelineContext 并 `!pipeline_start`。

### 5.4 只读 Git 操作

```python
def _git_fetch(self) -> bool:
    """只 fetch，不 merge/pull/checkout。"""
    subprocess.run(
        ["git", "-C", self._repo_path, "fetch", "origin", "dev"],
        capture_output=True, text=True, timeout=30,
    )

def _verify_on_remote(self, round_name: str) -> bool:
    """只读查询远程分支的文件状态。"""
    subprocess.run(
        ["git", "-C", self._repo_path, "ls-tree", "-r", "origin/dev", ...],
        capture_output=True, text=True, timeout=10,
    )
```

**绝对不做：**
- ❌ `git pull` — 不会合并远程更改到工作目录
- ❌ `git checkout` — 不会切换分支
- ❌ `git push` — 不会向 remote 写入
- ❌ `git reset` — 不会修改工作目录状态

---

## 6. 与 !pipeline_start 命令兼容

### 6.1 现有路径

```
手工启动管线：
  PM 发送 "!pipeline_start R110" (或通过 _inbox:server 发送)
    ↓
  handle_pipeline_start() 解析参数
    ↓
  PipelineContextManager.create() 创建上下文
    ↓
  PipelineContextManager.transition_to(RUNNING)
    ↓
  _auto_dispatch(step1, ...) 派活 Step 1

自动启动管线（R110 新增）：
  PipelineAutoStarter 检测到新轮次
    ↓
  PipelineContextManager.from_work_plan() 创建上下文
    ↓
  PipelineContextManager.transition_to(RUNNING)
    ↓
  _auto_dispatch(step1, ...) 派活 Step 1
```

**两条路径的融合点：** `PipelineContextManager`。无论是手工还是自动，最终都通过 `create()` + `transition_to(RUNNING)` + `_auto_dispatch()` 启动。

### 6.2 兼容性保证

| 方面 | 手工 `!pipeline_start` | 自动 PipelineAutoStarter | 冲突？ |
|:-----|:-----------------------|:-------------------------|:-------|
| 创建上下文 | 调用现有 `create()` | 调用 `from_work_plan()` 或 `create()` | 无冲突，`create()` 内部去重 |
| 状态转换 | `transition_to(RUNNING)` | 同 | ✓ 复用 |
| 派活 Step 1 | `_auto_dispatch()` | 同 | ✓ 复用 |
| `_processed` 集 | 不受影响（手工创建的不经 PipelineAutoStarter 检测） | 扫描时自动跳过已有上下文 | ✓ 隔离 |

### 6.3 共存场景

```
场景 A: 手工创建 R110（PM 先手动启动）
  1. PM: !pipeline_start R110
  2. 上下文创建，开始派活
  3. PipelineAutoStarter 检测到 R110（已存在上下文）
  4. _init_processed_from_existing() 已包含 R110
  5. → 跳过，不重复启动 ✅

场景 B: 自动创建 R111（PipelineAutoStarter 先发现）
  1. PipelineAutoStarter 检测到 R111，自动启动
  2. 派活 Step 1 给 PM
  3. PM 可继续手工 !pipeline_start R111
  4. PipelineContextManager.create() 抛 ValueError（已存在）
  5. → PM 被告知 "R111 已存在"，无重复 ✅

场景 C: R112 无 auto_start 标记
  1. PipelineAutoStarter 扫描到 R112
  2. 检查 auto_start: 无标记或 false
  3. 加入 _processed，跳过
  4. PM 手工 !pipeline_start R112
  5. → 正常启动 ✅
```

### 6.4 不影响现有命令

| 命令 | PipelineAutoStarter 影响？ | 原因 |
|:-----|:--------------------------|:------|
| `!pipeline_start` | ❌ 无影响 | 只能创建新上下文，无法阻止自动创建 |
| `!pipeline_stop` | ❌ 无影响 | 停止已启动管线，不影响轮询 |
| `!pipeline_status` | ❌ 无影响 | 只读查询 |
| `!pipeline_force` | ❌ 无影响 | 强制推进，不新建 |
| `!agent_card` | ❌ 无影响 | 角色管理，不触发管线 |

---

## 7. 执行计划与验收

### Step A：实现 `PipelineAutoStarter` 类

**文件：** `server/ws_server/pipeline_auto_starter.py`（~180 行）
**实现：**
1. `__init__()` + `start()` / `stop()`
2. `_init_processed_from_existing()`
3. `_poll_one_cycle()` + `_git_fetch()`
4. `_scan_new_rounds()` + `_verify_on_remote()` + `_check_auto_start()`
5. `_parse_work_plan()` + `_auto_start_pipeline()`
6. `_generate_message_templates()`, `_generate_references()`

**验收：** `python3 -c "from server.ws_server.pipeline_auto_starter import PipelineAutoStarter; print('OK')"` ✅

### Step B：增强 `PipelineContextManager`

**文件：** `server/ws_server/pipeline_context.py`
**实现：**
1. `from_work_plan()` 工厂方法
2. `_parse_work_plan_frontmatter()` 解析函数
3. `_generate_message_templates()`, `_generate_references()`, `_generate_steps()`

**验收：** 单元测试：`from_work_plan("docs/R110/WORK_PLAN.md")` → 正确解析 ✅

### Step C：注册到 `__main__.py`

**文件：** `server/ws_server/__main__.py`
**实现：**
1. 导入 `PipelineAutoStarter`
2. `asyncio.create_task(pas.start())` + 加入 `asyncio.gather()`
3. 受 `PAS_ENABLED` 环境变量控制

**验收：** `python3 -m server.ws_server.__main__` → 日志出现 `[PAS] started` ✅

### Step D：全链路验收（手工测试）

| # | 验收项 | 测试方法 |
|:-:|:-------|:---------|
| V-1 | 推 Rxxx WORK_PLAN + 需求文档到 dev 后 60s 内自动创建 PipelineContext | 检查 `pipeline_contexts.json` 有 Rxxx 条目 |
| V-2 | PipelineContext 解析正确 | `round_name=Rxxx, total_steps=6` |
| V-3 | 自动启动管线（状态 RUNNING） | `ctx.status == running` |
| V-4 | 重复 push 不重复创建 | 第二次 push → 无新上下文 |
| V-5 | 重启后不重新处理已有轮次 | `_processed` 从已有上下文恢复 |
| V-6 | 缺少 `auto_start` 标记的轮次跳过 | WORK_PLAN.md 无 `auto_start` → 跳过 |
| V-7 | `git ls-tree` 验证失败不触发 | 文件不在 remote → 静默跳过 |
| V-8 | Step 1 自动派活到 PM bot | PM bot inbox 收到审核消息 |
| V-9 | Step 1 消息含需求文档链接 | 消息含 `{requirements_url}` |
| V-10 | PM 回复 "✅ 完成" → 自动派活 Step 2 | Step 2 派活到小开 |
| V-11 | Steps 2→6 全链路自动 | 管线自动执行至部署 |
| V-12 | `git fetch` 超时不阻塞 WSS | 网络断开时静默跳过 |
| V-13 | WORK_PLAN.md 格式异常不崩溃 | 非法 frontmatter → log warning |
| V-14 | 与 `!pipeline_start` 共存 | 手工启动仍可用 |

---

> **技术方案版本：** v1.0
> **审核状态：** ⏳ 待 Step 4 代码审查
> **前置依赖：** R109 全闭环已上线 ✅
