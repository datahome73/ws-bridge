#!/usr/bin/env python3
"""Pipeline AutoRouter — 管线自动路由服务 🚂

独立外挂服务，零 handler.py 侵入。通过 WebSocket 以 bot 身份连接 ws-bridge，
监听 PM 收件箱的转发通知，自动按 WORK_PLAN.md 定义的 topology.chain 派活下一棒。

用法:
    python3 -m server.auto_router --api-key sk_ws_xxx --pm-agent-id ws_xxx
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
import time
from typing import Any

import yaml

logger = logging.getLogger("auto-router")


class PipelineAutoRouter:
    """管线自动路由服务 — 独立外挂，零 handler.py 侵入。"""

    # ── 常量 ──
    _MAX_SEEN_IDS = 1000
    _RECONNECT_INITIAL_DELAY = 1  # 秒
    _RECONNECT_MAX_DELAY = 60  # 秒
    # ── R89 🅱️: Step 超时检测 ──
    _TIMEOUT_CHECK_INTERVAL = 300  # 5 分钟检查一次
    _STEP_DEFAULT_TIMEOUT = 7200   # 2 小时默认超时
    _STANDARD_PIPELINE_ORDER = [
        "product_manager", "pm", "architect", "arch", "developer", "dev",
        "reviewer", "review", "qa", "test", "operations", "ops",
    ]

    def __init__(
        self,
        api_key: str,
        ws_url: str = "wss://wsim.datahome73.cloud/ws",
        pm_agent_id: str = "",
        agent_card_path: str = "",
    ) -> None:
        # ── 连接参数 ──
        self.api_key = api_key
        self.ws_url = ws_url
        self.pm_agent_id = pm_agent_id
        self.agent_card_path = agent_card_path or os.path.join(
            os.path.dirname(__file__), "..", "config", "agent_cards.json"
        )

        # ── WebSocket 状态 ──
        self.ws: Any = None  # websockets.WebSocketClientProtocol
        self.my_agent_id: str = ""
        self.my_inbox: str = ""
        self._running = False
        self._pm_inbox_channel: str = ""

        # ── 管线拓扑缓存 ──
        # Key: round_name → {"chain": [...], "auto_chain": bool, "pipeline": {...}}
        self._topologies: dict[str, dict] = {}

        # ── Step 进度追踪 ──
        # Key: round_name → {"current_step_idx": int, "completed_steps": set[int],
        #                      "chain": list, "topology": dict}
        self._round_progress: dict[str, dict] = {}

        # ── 已处理的 msg_id（去重滑动窗口） ──
        self._seen_ids: set[str] = set()

        # ── 角色→agent_id 索引 ──
        self._role_index: dict[str, list[str]] = {}

        # ── 模板渲染用 ──
        self._pipeline_config: dict = {}
        self._prev_sha: str = ""

        # ── R89 🅱️: Step 超时检测 ──
        # round_name → {step_key: {"dispatch_time": float, "role": str}}
        self._step_dispatch_times: dict[str, dict[str, dict]] = {}
        # round_name → set[step_key]  已通知超时的 step（防重复）
        self._step_timeout_notified: dict[str, set[str]] = {}

    # ═══════════════ 生命周期 ═══════════════

    async def start(self) -> None:
        """启动 AutoRouter 并保持连接（含断线重连）。"""
        self._running = True
        self._build_role_index()
        self._pm_inbox_channel = f"_inbox:{self.pm_agent_id}" if self.pm_agent_id else ""
        logger.info("[AR] 🚂 AutoRouter 启动, pm=%s", self.pm_agent_id[:16] if self.pm_agent_id else "N/A")

        delay = self._RECONNECT_INITIAL_DELAY
        attempts = 0

        while self._running:
            try:
                await self._connect_and_listen()
                # 正常退出 → 重置退避
                attempts = 0
                delay = self._RECONNECT_INITIAL_DELAY
            except asyncio.CancelledError:
                break
            except (OSError, Exception) as e:  # E9: 连接异常
                attempts += 1
                logger.warning(
                    "[AR] 连接断开 (#%d): %s, %ds 后重连", attempts, e, delay
                )
                await asyncio.sleep(delay + random.uniform(0, 2))
                delay = min(delay * 2, self._RECONNECT_MAX_DELAY)

    async def stop(self) -> None:
        """优雅断开连接。"""
        self._running = False
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        logger.info("[AR] 🛑 AutoRouter 已停止")

    async def _connect_and_listen(self) -> None:
        """建立 WS 连接 → 认证 → 恢复状态 → 主监听循环（含超时检测后台 task）。"""
        import websockets

        timeout_task: asyncio.Task | None = None  # 🅱️

        try:
            async with websockets.connect(
                self.ws_url,
                max_size=2**20,
                ping_interval=30,
                ping_timeout=10,
            ) as ws:
                self.ws = ws

                # ① 认证
                await ws.send(json.dumps({"type": "auth", "api_key": self.api_key}))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if resp.get("type") != "auth_ok":
                    raise RuntimeError(f"认证失败: {resp}")
                self.my_agent_id = resp.get("agent_id", "")
                self.my_inbox = f"_inbox:{self.my_agent_id}"
                logger.info("[AR] ✅ 已连接, agent_id=%s", self.my_agent_id[:16])

                # ── 🅱️ 启动超时检测后台 task ──
                timeout_task = asyncio.create_task(self._timeout_check_loop())
                logger.info("[AR] ⏰ 超时检测已启动 (interval=%ds, timeout=%ds)",
                            self._TIMEOUT_CHECK_INTERVAL, self._STEP_DEFAULT_TIMEOUT)

                # ② 启动时重建已有管线状态（B5/B6/B8）
                await self._restore_pipeline_state()

                # ③ 主监听循环
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        await self._handle_message(msg)
                    except json.JSONDecodeError:
                        logger.debug("[AR] 无效 JSON: %s", raw[:80])
                    except Exception as exc:
                        logger.error("[AR] 消息处理异常: %s", exc)
        finally:
            # ── 🅱️ 取消超时 task ──
            if timeout_task and not timeout_task.done():
                timeout_task.cancel()
                try:
                    await timeout_task
                except asyncio.CancelledError:
                    pass

    # ═══════════════ 消息处理 ═══════════════

    async def _handle_message(self, msg: dict) -> None:
        """消息入口 — 只关心 PM 收件箱的管线通知。"""
        channel = msg.get("channel", "")
        content = (msg.get("content") or "").strip()
        msg_id = msg.get("id", "")

        # ── 去重（B3/B10） ──
        if self._mark_seen(msg_id):
            return

        # ── 只监听 PM 收件箱 ──
        if self._pm_inbox_channel and channel != self._pm_inbox_channel:
            return

        # ═══ 信号 1: 管线就绪 ═══
        if "管线已启动" in content or "工作区已就绪" in content:
            round_name = self._extract_round(content)
            if round_name:
                await self._on_pipeline_ready(round_name)
            return

        # ═══ 信号 2: Bot 任务完成 ═══
        if content.startswith("✅ ") and "任务完成" in content:
            await self._on_step_complete(content)
            return

        # ═══ 信号 3: Bot 完成推送（简写格式） ═══
        if content.startswith("✅ 完成") or "✅ 完成，已推" in content:
            await self._on_step_complete(content)
            return

    async def _on_pipeline_ready(self, round_name: str) -> None:
        """管线就绪 → 加载拓扑 → 记录进度（B1/B8）。"""
        topology = await self._fetch_topology(round_name)
        if not topology:
            # E1/E2: 拓扑加载失败，通知 PM
            await self._send_to_pm(
                f"⚠️ AutoRouter: {round_name} 拓扑解析失败，请确认 WORK_PLAN.md 格式"
            )
            return

        chain = topology.get("chain", [])
        auto_chain = topology.get("auto_chain", False)

        if not chain and not auto_chain:
            # E3: 无自动管线标记，跳过
            logger.info("[AR] [%s] 未启用 auto_chain，跳过自动接力", round_name)
            return

        self._round_progress[round_name] = {
            "current_step_idx": -1,
            "completed_steps": set(),
            "chain": chain,
            "topology": topology,
        }
        logger.info("[AR] [%s] 🟢 管线就绪, chain=%d steps", round_name, len(chain))

    async def _on_step_complete(self, content: str) -> None:
        """Step 完成 → 解析 → 找下一步 → 派活/完成（B2/B4/B9）。"""
        role = self._extract_role(content)
        sha = self._extract_sha(content)
        round_name = self._extract_round(content)

        if not round_name or not role:
            logger.debug("[AR] 无法解析完成消息: %s", content[:60])
            return  # E7: 解析失败，忽略

        progress = self._round_progress.get(round_name)
        if not progress:
            logger.debug("[AR] [%s] 无进度记录，跳过（B4）", round_name)
            return  # B4: 管线结束后又收到完成消息

        chain = progress["chain"]

        # 找完成者对应 step 在 chain 中的 index
        current_idx = self._find_role_in_chain(chain, role)
        if current_idx is None:
            logger.debug("[AR] [%s] 角色 %s 不在 chain 中（E6）", round_name, role)
            return  # E6: 角色不在 chain 中，忽略

        # 幂等标记（B3/B10）
        if current_idx in progress["completed_steps"]:
            logger.debug("[AR] [%s] step %d 已完成，跳过重复（B10）", round_name, current_idx)
            return

        progress["completed_steps"].add(current_idx)
        progress["current_step_idx"] = current_idx

        # 找下一棒
        next_idx = current_idx + 1
        if next_idx >= len(chain):
            await self._notify_all_done(round_name)
            return

        next_step = chain[next_idx]
        await self._dispatch_step(round_name, next_step, role, sha, chain)

        # ── 🅱️ 完成时清理该 Step 的计时器 ──
        step_key = chain[current_idx].get("step", "")
        if step_key:
            self._cleanup_dispatch(round_name, step_key)

        logger.info(
            "[AR] [%s] ✅ %s → 🎯 %s (SHA=%s)",
            round_name, role, next_step.get("role", "?"), sha or "?",
        )

    def _find_role_in_chain(self, chain: list, role: str) -> int | None:
        """在 chain 中查找角色对应的 step index。"""
        for i, step in enumerate(chain):
            step_role = step.get("role", "")
            # 精确匹配或前缀匹配（如 "arch" 匹配 "architect"）
            if step_role == role or step_role.startswith(role) or role.startswith(step_role):
                return i
        return None

    # ═══════════════ 管线引擎 ═══════════════

    async def _dispatch_step(
        self,
        round_name: str,
        step_config: dict,
        prev_role: str,
        prev_sha: str,
        chain: list,
    ) -> None:
        """派活下一棒（E4/E5）。"""
        role = step_config.get("role", "")
        title = step_config.get("title", "")
        step_key = step_config.get("step", "")

        # ── 找目标 bot（E4） ──
        target_id = self._resolve_agent_id(role, round_name)
        if not target_id:
            await self._send_to_pm(
                f"❌ AutoRouter: {round_name} {step_key}({role}) "
                f"未找到对应 bot，请手动派活"
            )
            return

        # ── 构建任务上下文 ──
        topology = progress = self._round_progress.get(round_name, {})
        if isinstance(topology, dict):
            topo = topology.get("topology", {})
        else:
            topo = {}
        self._pipeline_config = topo.get("pipeline", {}) if isinstance(topo, dict) else {}
        self._prev_sha = prev_sha

        context_lines = []
        for k, v in (step_config.get("context") or {}).items():
            if v:
                rendered = self._render_template(v, round_name)
                context_lines.append(f"- {k}: {rendered}")
        context_str = "\n".join(context_lines)

        # ── 任务消息 ──
        task_content = (
            f"【{round_name} Step {step_key} 任务 — {title} 🎯】\n\n"
            f"角色: {role}\n"
            f"前一棒 {prev_role} 已完成 ✅ {prev_sha}\n\n"
        )
        if context_str:
            task_content += f"参考：\n{context_str}\n\n"
        task_content += (
            f"请按流程完成任务后推 dev 分支。\n"
            f"完成后请回复 _inbox:server 告知 SHA。"
        )

        # ── 发送（E5: 重试1次） ──
        for attempt in range(2):
            try:
                await self._send_inbox(target_id, task_content)
                # ── 🅱️ 记录派活时间（确保 send 成功后再记录） ──
                self._step_dispatch_times.setdefault(round_name, {})[step_key] = {
                    "dispatch_time": time.time(),
                    "role": role,
                }
                logger.info("[AR] ⏰ [%s] %s(%s) 已记录派活时间",
                            round_name, step_key, role)
                logger.info("[AR] 派活 %s → %s (%s)", round_name, role, target_id[:12])
                return
            except Exception as e:
                if attempt == 0:
                    logger.warning("[AR] 发送失败，重试: %s", e)
                    await asyncio.sleep(1)
                else:
                    logger.error("[AR] 发送失败 %s: %s", target_id[:12], e)
                    await self._send_to_pm(
                        f"❌ AutoRouter: {round_name} {step_key}({role}) "
                        f"WS 发送失败: {e}"
                    )

    async def _notify_all_done(self, round_name: str) -> None:
        """全部完成通知 PM。"""
        await self._send_to_pm(f"🏁 {round_name} 全部 Step 已完成！管线自动闭环。")
        # ── 🅱️ 清空该轮所有计时器 ──
        self._cleanup_all_dispatch(round_name)
        logger.info("[AR] [%s] 🏁 全线闭环", round_name)

    # ── 🅱️ 超时检测辅助方法 ──

    def _cleanup_dispatch(self, round_name: str, step_key: str) -> None:
        """R89 🅱️: 移除指定 Step 的超时计时器。"""
        steps = self._step_dispatch_times.get(round_name)
        if steps and step_key in steps:
            del steps[step_key]
            logger.debug("[AR] ⏰ [%s] %s 计时器已清理", round_name, step_key)
        # 也清理已通知标记
        notified = self._step_timeout_notified.get(round_name)
        if notified and step_key in notified:
            notified.discard(step_key)

    def _cleanup_all_dispatch(self, round_name: str) -> None:
        """R89 🅱️: 清空指定轮次的所有超时计时器。"""
        self._step_dispatch_times.pop(round_name, None)
        self._step_timeout_notified.pop(round_name, None)
        logger.debug("[AR] ⏰ [%s] 全部计时器已清空", round_name)

    async def _timeout_check_loop(self) -> None:
        """R89 🅱️: Step 超时检测后台循环。

        随 _connect_and_listen() 启动，周期检查所有活跃 Step 是否超时。
        """
        while self._running:
            try:
                await self._check_step_timeouts()
            except Exception as e:
                logger.error("[AR] ⏰ 超时检查异常: %s", e)
            await asyncio.sleep(self._TIMEOUT_CHECK_INTERVAL)

    async def _check_step_timeouts(self) -> None:
        """R89 🅱️: 检查所有活跃 Step 是否超时。

        遍历 _step_dispatch_times，超时 ≥ _STEP_DEFAULT_TIMEOUT 则通知 PM。
        同一 Step 仅首次通知（_step_timeout_notified 防重复）。
        """
        now = time.time()
        overdue_count = 0

        for round_name, steps in list(self._step_dispatch_times.items()):
            for step_key, info in list(steps.items()):
                elapsed = now - info["dispatch_time"]
                if elapsed > self._STEP_DEFAULT_TIMEOUT:
                    overdue_count += 1
                    notified = self._step_timeout_notified.setdefault(round_name, set())
                    if step_key not in notified:
                        notified.add(step_key)
                        await self._send_to_pm(
                            f"⏰ AutoRouter 超时告警: {round_name} {step_key} "
                            f"({info['role']}) 已超过 {self._STEP_DEFAULT_TIMEOUT // 3600} 小时 "
                            f"未完成，请检查 Bot 状态"
                        )
                        logger.warning(
                            "[AR] ⏰ [%s] %s(%s) 超时: %.0fs",
                            round_name, step_key, info["role"], elapsed,
                        )

        active_total = sum(len(v) for v in self._step_dispatch_times.values())
        logger.debug("[AR] ⏰ 超时检查: %d/%d 活跃 Step 超时",
                     overdue_count, active_total)

    async def _fetch_topology(self, round_name: str) -> dict | None:
        """从远程 WORK_PLAN.md 读取 frontmatter → pipeline topology。

        E1: YAML 解析失败 → None
        E2: HTTP 请求失败 → None
        """
        # ① 缓存命中
        if round_name in self._topologies:
            return self._topologies[round_name]

        # ② 构造 GitHub raw URL
        base = "https://raw.githubusercontent.com/datahome73/ws-bridge/dev"
        urls_to_try = [
            f"{base}/docs/{round_name}/WORK_PLAN.md",
        ]

        import aiohttp

        for url in urls_to_try:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            logger.debug("[AR] [%s] WORK_PLAN HTTP %s", round_name, resp.status)
                            continue  # E2
                        text = await resp.text()
                        topology = self._parse_topology(text)
                        if topology:
                            self._topologies[round_name] = topology
                            return topology
            except asyncio.TimeoutError:
                logger.debug("[AR] [%s] WORK_PLAN 超时", round_name)
                continue  # E2
            except aiohttp.ClientError as e:
                logger.debug("[AR] [%s] WORK_PLAN 请求失败: %s", round_name, e)
                continue  # E2

        logger.warning("[AR] [%s] 未找到 topology 定义（E2）", round_name)
        return None

    @staticmethod
    def _parse_topology(markdown_text: str) -> dict | None:
        """从 Markdown frontmatter 解析 pipeline topology。

        格式 A（完整）: topology.chain + auto_chain
        格式 B（简写）: auto_chain: true（无 chain，从 steps 推断）
        """
        m = re.match(r"^---\s*\n(.*?)\n---", markdown_text, re.DOTALL)
        if not m:
            return None

        try:
            frontmatter = yaml.safe_load(m.group(1))  # E1
        except yaml.YAMLError as e:
            logger.error("[AR] YAML frontmatter 解析失败: %s", e)
            return None

        if not isinstance(frontmatter, dict):
            return None

        pipeline = frontmatter.get("pipeline", {})
        if not isinstance(pipeline, dict):
            return None

        auto_chain = (
            pipeline.get("auto_chain", False)
            or pipeline.get("topology", {}).get("auto_chain", False)
        )

        # 格式 A: topology.chain 存在
        topology = pipeline.get("topology", {})
        chain = topology.get("chain", []) if isinstance(topology, dict) else []
        if chain:
            return {"chain": chain, "auto_chain": auto_chain, "pipeline": pipeline}

        # 格式 B: 从 steps 按序推断 chain
        if auto_chain:
            steps = pipeline.get("steps", {})
            if isinstance(steps, dict):
                sorted_keys = sorted(
                    steps.keys(),
                    key=lambda k: int(re.search(r"\d+", k).group()) if re.search(r"\d+", k) else 99,
                )
                chain = []
                for key in sorted_keys:
                    step = steps[key]
                    if isinstance(step, dict):
                        chain.append({
                            "step": key,
                            "role": step.get("role", ""),
                            "title": step.get("title", ""),
                            "context": step.get("context", {}),
                        })
                if chain:
                    return {"chain": chain, "auto_chain": True, "pipeline": pipeline}

            # 空 chain + auto_chain → 仅标记，等待动态推断
            return {"chain": [], "auto_chain": True, "pipeline": pipeline}

        return None

    # ═══════════════ 角色映射 ═══════════════

    def _build_role_index(self) -> dict[str, list[str]]:
        """从 Agent Card 构建 role → [agent_id, ...] 反向索引。

        E8: 文件 IO 错误 → 空索引
        """
        cards: dict = {}
        if os.path.exists(self.agent_card_path):
            try:
                with open(self.agent_card_path, encoding="utf-8") as f:
                    cards = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.error("[AR] Agent Card 读取失败（E8）: %s", e)
        else:
            logger.warning("[AR] Agent Card 文件不存在: %s", self.agent_card_path)

        role_index: dict[str, list[str]] = {}
        for agent_id, card in cards.items():
            # 兼容两种格式: pipeline_roles (array) / role (string)
            roles: list[str] = []
            if "pipeline_roles" in card and isinstance(card["pipeline_roles"], list):
                roles = card["pipeline_roles"]
            elif "role" in card:
                roles = [card["role"]]
            for role in roles:
                role_index.setdefault(role, []).append(agent_id)

        self._role_index = role_index
        return role_index

    def _resolve_agent_id(self, role: str, round_name: str) -> str | None:
        """根据 pipeline role 查找 agent_id。

        优先级: 精确匹配 → 子串匹配 → 首 agent 兜底 → None
        """
        if not self._role_index:
            self._build_role_index()

        # 精确匹配
        if role in self._role_index:
            return self._role_index[role][0]

        # 子串匹配: chain 中 role="arch" 匹配索引中的 "architect"
        for known_role, agents in self._role_index.items():
            if role in known_role or known_role in role:
                return agents[0]

        logger.warning("[AR] 角色 %s 无对应 agent（E4）", role)
        return None

    # ═══════════════ 模板渲染 ═══════════════

    def _render_template(self, template: str, round_name: str) -> str:
        """执行模板变量替换: ${pipeline.xxx} / {round} / {prev_sha}"""
        result = template.replace("{round}", round_name)

        def _resolve_pipeline_var(m: re.Match) -> str:
            path = m.group(1).split(".")
            value: Any = self._pipeline_config
            for key in path:
                if isinstance(value, dict):
                    value = value.get(key, m.group(0))
                else:
                    return m.group(0)
            return str(value) if not isinstance(value, (dict, list)) else m.group(0)

        result = re.sub(r"\$\{pipeline\.([^}]+)\}", _resolve_pipeline_var, result)
        result = result.replace("{prev_sha}", self._prev_sha)
        return result

    # ═══════════════ 解析工具 ═══════════════

    @staticmethod
    def _extract_role(content: str) -> str:
        """从完成消息提取角色名称。

        格式: "✅ architect 任务完成: ✅ 完成，已推 dev: abc1234"
               "✅ 完成，已推 dev: abc1234"
        也支持 "完成人: architect" 或 "角色: architect" 格式。
        """
        # 格式1: ✅ architect 任务完成
        m = re.search(r"^✅\s+(\S+)\s+任务完成", content)
        if m:
            return m.group(1)

        # 格式2: ✅ 完成，已推 dev，角色: architect
        m = re.search(r"角色[：:](\S+)", content)
        if m:
            return m.group(1)

        # 格式3: 完成人: architect
        m = re.search(r"完成人[：:](\S+)", content)
        if m:
            return m.group(1)

        return ""

    @staticmethod
    def _extract_sha(content: str) -> str:
        """从完成消息提取 commit SHA。

        格式: "✅ 完成，已推 dev: abc1234"
        """
        m = re.search(r"已推\s*\S*[：:]\s*(\w{7,40})", content)
        if m:
            return m.group(1)

        # 兜底: 直接找 hash
        m = re.search(r"dev[：:]\s*(\w{7,40})", content)
        if m:
            return m.group(1)

        return ""

    @staticmethod
    def _extract_round(content: str) -> str:
        r"""从消息提取轮次名（如 R88）。

        格式: "R88 管线已启动" / "【R88 Step 2..." / 消息中的 R\d+
        """
        m = re.search(r"(R\d{2,3})", content)
        return m.group(1) if m else ""

    # ═══════════════ 通信 ═══════════════

    async def _send_inbox(self, target_id: str, content: str) -> None:
        """发送 inbox 消息到目标 bot。

        R89 🅰️: payload 补全 — 增加 from_name/agent_id/id/ts 四个字段。
        """
        if not self.ws:
            raise RuntimeError("WebSocket 未连接")
        payload = {
            "type": "message",
            "channel": f"_inbox:{target_id}",
            "content": content,
            "from_name": "系统(管线)",
            "agent_id": self.my_agent_id,
            "id": f"auto-{int(time.time() * 1000)}",
            "ts": time.time(),
        }
        await self.ws.send(json.dumps(payload))

    async def _send_to_pm(self, content: str) -> None:
        """发送通知到 PM 收件箱。"""
        if not self.pm_agent_id:
            logger.warning("[AR] pm_agent_id 未配置，无法通知 PM: %s", content[:60])
            return
        await self._send_inbox(self.pm_agent_id, content)

    # ═══════════════ 状态恢复 ═══════════════

    async def _restore_pipeline_state(self) -> None:
        """重启/重连时恢复已有管线状态（B5/B6/B8）。

        v1 实现: 仅恢复已缓存的拓扑信息。
        重连后 PM 可手动确认进度，AutoRouter 从下一个完成消息继续。
        """
        logger.info("[AR] 正在查询活跃管线状态...")
        for round_name in list(self._round_progress.keys()):
            topo = await self._fetch_topology(round_name)
            if topo:
                chain = topo.get("chain", [])
                self._round_progress[round_name]["chain"] = chain
                self._round_progress[round_name]["topology"] = topo
                logger.info(
                    "[AR] [%s] 已恢复管线状态 (%d/%d steps)",
                    round_name,
                    len(self._round_progress[round_name]["completed_steps"]),
                    len(chain),
                )

        if not self._round_progress:
            logger.info("[AR] 无活跃管线，等待新管线事件（B8）")

    # ═══════════════ 去重 ═══════════════

    def _mark_seen(self, msg_id: str) -> bool:
        """标记消息已处理。返回 True 表示重复。"""
        if not msg_id:
            return False
        if msg_id in self._seen_ids:
            return True
        self._seen_ids.add(msg_id)
        # 滑动窗口溢出裁剪（保留最新 500 条）
        if len(self._seen_ids) > self._MAX_SEEN_IDS:
            self._seen_ids = set(list(self._seen_ids)[-500:])
        return False


# ═══════════════ CLI 入口 ═══════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline AutoRouter — 管线自动路由服务 🚂"
    )
    parser.add_argument("--api-key", required=True, help="AutoRouter 的 ws-bridge api_key")
    parser.add_argument("--pm-agent-id", default="", help="PM 的 agent_id")
    parser.add_argument(
        "--ws-url", default="wss://wsim.datahome73.cloud/ws",
        help="ws-bridge WebSocket 地址",
    )
    parser.add_argument(
        "--agent-card-path", default="",
        help="Agent Card JSON 文件路径",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [AR] %(levelname)s %(message)s",
    )

    router = PipelineAutoRouter(
        api_key=args.api_key,
        ws_url=args.ws_url,
        pm_agent_id=args.pm_agent_id,
        agent_card_path=args.agent_card_path,
    )

    try:
        asyncio.run(router.start())
    except KeyboardInterrupt:
        logger.info("[AR] AutoRouter 已停止（Ctrl+C）")


if __name__ == "__main__":
    main()
