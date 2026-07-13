#!/usr/bin/env python3
"""Pipeline AutoRouter 🚂 — [DISABLED] per user request (2026-07-13)

This service was disabled because of false-positive timeout alarms.
If re-enabled in the future:
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

logger = logging.getLogger("auto-router")


class PipelineAutoRouter:
    """管线自动路由服务 — 独立外挂，零 handler.py 侵入。"""

    # ── 常量 ──
    _MAX_SEEN_IDS = 1000
    _RECONNECT_INITIAL_DELAY = 1  # 秒
    _RECONNECT_MAX_DELAY = 60  # 秒
    # ── R89 🅱️: Step 超时检测 ──
    _TIMEOUT_CHECK_INTERVAL = 300  # 5 分钟检查一次
    # R90 🅲: 从环境变量读取，支持 <=0 禁用
    _STEP_DEFAULT_TIMEOUT = int(os.environ.get("AR_STEP_TIMEOUT", "7200"))
    _STEP_TIMEOUT_ENABLED  = _STEP_DEFAULT_TIMEOUT > 0

    def __init__(
        self,
        api_key: str,
        ws_url: str = "wss://wsim.datahome73.cloud/ws",
        pm_agent_id: str = "",
        data_dir: str = "",
    ) -> None:
        # ── 连接参数 ──
        self.api_key = api_key
        self.ws_url = ws_url
        self.pm_agent_id = pm_agent_id
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(__file__), "..", "data"
        )
        self._pipeline_contexts_path = os.path.join(self.data_dir, "pipeline_contexts.json")
        self.agent_card_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "agent_cards.json"
        )

        # ── WebSocket 状态 ──
        self.ws: Any = None  # websockets.WebSocketClientProtocol
        self.my_agent_id: str = ""
        self.my_inbox: str = ""
        self._running = False
        self._pm_inbox_channel: str = ""

        # ── Step 进度追踪（R97: 通过 PipelineContext JSON 管理，原地保留字典兼容）──
        self._round_progress: dict[str, dict] = {}

        # ── 已处理的 msg_id（去重滑动窗口） ──
        self._seen_ids: set[str] = set()

        # ── 角色→agent_id 索引（R97: 实时查询缓存）──
        self._role_index: dict[str, list[str]] = {}
        self._role_map_ttl = 60  # 缓存 TTL（秒）
        self._last_role_refresh: float = 0.0

        # ── R89 🅱️: Step 超时检测 ──
        # round_name → {step_key: {"dispatch_time": float, "role": str}}
        self._step_dispatch_times: dict[str, dict[str, dict]] = {}
        # round_name → set[step_key]  已通知超时的 step（防重复）
        self._step_timeout_notified: dict[str, set[str]] = {}

        # ── R90 🅲: 超时状态日志 ──
        logger.info(
            "[AR] 超时=%ds (%s)",
            self._STEP_DEFAULT_TIMEOUT,
            "启用" if self._STEP_TIMEOUT_ENABLED else "禁用",
        )

    # ═══════════════ 生命周期 ═══════════════

    async def start(self) -> None:
        """启动 AutoRouter 并保持连接（含断线重连）。"""
        self._running = True
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
                if self._STEP_TIMEOUT_ENABLED:
                    timeout_task = asyncio.create_task(self._timeout_check_loop())
                    logger.info("[AR] ⏰ 超时检测已启动 (interval=%ds, timeout=%ds)",
                                self._TIMEOUT_CHECK_INTERVAL, self._STEP_DEFAULT_TIMEOUT)
                else:
                    logger.info("[AR] ⏰ 超时检测已禁用 (AR_STEP_TIMEOUT=%d)",
                                self._STEP_DEFAULT_TIMEOUT)

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
        """消息入口 — 监听 PM 收件箱 + _admin 频道（R90 🅰️ 白名单模式）。"""
        channel = msg.get("channel", "")
        content = (msg.get("content") or "").strip()
        msg_id = msg.get("id", "")
        logger.debug("[AR] 收到消息: channel=%s, content=%.60s", channel, content)

        # ── 去重（B3/B10） ──
        if self._mark_seen(msg_id):
            return

        # ── 🅰️ R90: 通道过滤改为白名单模式 ──
        is_pm_inbox = self._pm_inbox_channel and channel == self._pm_inbox_channel
        is_admin = channel == "_admin"

        if not is_pm_inbox and not is_admin:
            return  # 只处理 PM inbox 或 _admin 的消息

        # ═══ 信号 1: 管线就绪（PM inbox + _admin 均可） ═══
        if "管线已启动" in content or "工作区已就绪" in content:
            round_name = self._extract_round(content)
            if round_name:
                await self._on_pipeline_ready(round_name)
            return

        # ═══ PM inbox 专有: Step 完成信号 ═══
        if is_pm_inbox:
            if content.startswith("✅ ") and "任务完成" in content:
                await self._on_step_complete(content)
                return
            if content.startswith("✅ 完成") or "✅ 完成，已推" in content:
                await self._on_step_complete(content)
                return

        # _admin 专有: 响应管线停止信号，其他忽略
        if is_admin:
            # ═══ 信号 4: 管线停止（_admin 广播） ═══
            if "Pipeline" in content and "已停止" in content:
                round_name = self._extract_round(content)
                if round_name:
                    await self._cancel_pipeline(round_name)
                return
            return  # 不干扰 admin 频道正常通信

    async def _on_pipeline_ready(self, round_name: str) -> None:
        """R97: 管线就绪 → 读 PipelineContext → 激活第一 Step。"""
        ctx = self._load_pipeline_context(round_name)
        if not ctx:
            await self._send_to_pm(
                f"⚠️ AutoRouter: {round_name} PipelineContext 未找到，"
                f"请确认 !pipeline_start 已成功执行"
            )
            return

        if ctx.get("status") != "running":
            logger.info("[AR] [%s] 管线状态=%s，跳过自动接力", round_name, ctx.get("status"))
            return

        # 找第一个 pending step
        step_order = ctx.get("step_order", [])
        steps = ctx.get("steps", {})
        first_pending = None
        for sk in step_order:
            si = steps.get(sk, {})
            if si.get("status") == "pending":
                first_pending = si
                break

        if not first_pending:
            logger.info("[AR] [%s] 无 pending Step，跳过", round_name)
            return

        # 解析 role → agent_id
        role = first_pending.get("role", "")
        agent_id = await self._resolve_agent_by_role(role)
        if not agent_id:
            await self._send_to_pm(
                f"❌ AutoRouter: {round_name} Step {first_pending['step_key']}({role}) "
                f"未找到对应 bot"
            )
            return

        # 标记 active
        first_pending["status"] = "active"
        first_pending["agent_id"] = agent_id
        self._save_pipeline_context(round_name, ctx)

        # 派活
        await self._dispatch_step(ctx, first_pending, "")
        logger.info("[AR] [%s] 🟢 Step 1 已派活: %s → %s", round_name, role, agent_id[:12])

    async def _on_step_complete(self, content: str) -> None:
        """R97: Step 完成 → 更新 PipelineContext → 下一棒/完成。"""
        round_name = self._extract_round(content)
        sha = self._extract_sha(content)
        if not round_name:
            return

        ctx = self._load_pipeline_context(round_name)
        if not ctx or ctx.get("status") != "running":
            return

        steps = ctx.get("steps", {})
        step_order = ctx.get("step_order", [])

        # 找哪个 step 刚刚完成（匹配 agent_id 或 role）
        completed_step = None
        for sk in reversed(step_order):  # 优先匹配最新的 active step
            si = steps.get(sk, {})
            if si.get("agent_id") and si["agent_id"] in content:
                completed_step = si
                break
        if not completed_step:
            # 回退：找 active step
            for sk in step_order:
                si = steps.get(sk, {})
                if si.get("status") == "active":
                    completed_step = si
                    break
        if not completed_step:
            return

        # 标记完成
        completed_step["status"] = "done"
        completed_step["result_msg"] = content
        completed_step["output"] = {"sha": sha} if sha else {}

        # 找下一步
        current_key = completed_step["step_key"]
        current_idx = step_order.index(current_key)
        next_idx = current_idx + 1

        if next_idx >= len(step_order):
            # 全部完成
            ctx["status"] = "done"
            self._save_pipeline_context(round_name, ctx)
            self._cleanup_all_dispatch(round_name)
            await self._send_to_pm(f"🏁 {round_name} 全部 Step 已完成！管线自动闭环。")
            logger.info("[AR] [%s] 🏁 全线闭环", round_name)
            return

        next_key = step_order[next_idx]
        next_step = steps.get(next_key)
        if not next_step:
            return

        # 激活下一步
        role = next_step.get("role", "")
        agent_id = await self._resolve_agent_by_role(role)
        if not agent_id:
            await self._send_to_pm(
                f"❌ AutoRouter: {round_name} {next_key}({role}) "
                f"未找到对应 bot，请手动派活"
            )
            return

        next_step["status"] = "active"
        next_step["agent_id"] = agent_id
        self._save_pipeline_context(round_name, ctx)

        # 派活
        await self._dispatch_step(ctx, next_step, sha or "")
        logger.info(
            "[AR] [%s] ✅ %s → 🎯 %s (SHA=%s)",
            round_name, completed_step["role"], role, sha or "?",
        )

    # ═══════════════ 管线引擎 ═══════════════

    async def _dispatch_step(
        self,
        ctx: dict,
        step: dict,
        prev_sha: str,
    ) -> None:
        """R97: 派活下一棒（简单模板消息）。"""
        role = step.get("role", "")
        step_key = step.get("step_key", "")
        agent_id = step.get("agent_id", "")

        if not agent_id:
            await self._send_to_pm(
                f"❌ AutoRouter: {ctx['round_name']} {step_key}({role}) "
                f"未指定 agent_id"
            )
            return

        # 构建任务消息
        task_content = self._build_task_message(ctx, step, prev_sha)

        # 发送（重试1次）
        for attempt in range(2):
            try:
                await self._send_inbox(agent_id, task_content)
                # 记录派活时间（超时检测用）
                self._step_dispatch_times.setdefault(ctx["round_name"], {})[step_key] = {
                    "dispatch_time": time.time(),
                    "role": role,
                }
                logger.info("[AR] 派活 %s → %s (%s)", ctx["round_name"], role, agent_id[:12])
                return
            except Exception as e:
                if attempt == 0:
                    logger.warning("[AR] 发送失败，重试: %s", e)
                    await asyncio.sleep(1)
                else:
                    logger.error("[AR] 发送失败 %s: %s", agent_id[:12], e)
                    await self._send_to_pm(
                        f"❌ AutoRouter: {ctx['round_name']} {step_key}({role}) "
                        f"WS 发送失败: {e}"
                    )

    @staticmethod
    def _build_task_message(ctx: dict, step: dict, prev_sha: str) -> str:
        """R97: 机械组装任务消息，不涉及 LLM。"""
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

    # ── R95: 管线停止 ──

    async def _cancel_pipeline(self, round_name: str) -> None:
        """R95: 收到停止信号后取消管线调度。"""
        progress = self._round_progress.pop(round_name, None)
        if progress:
            self._cleanup_all_dispatch(round_name)
            logger.info("[AR] [%s] 🛑 管线已停止，清除进度", round_name)
            await self._send_to_pm(
                f"🛑 AutoRouter: {round_name} 管线已停止，自动调度已取消。"
            )
        else:
            logger.debug("[AR] [%s] 收到停止信号但无活跃进度", round_name)

    async def _timeout_check_loop(self) -> None:
        """R89 🅱️: Step 超时检测后台循环。

        随 _connect_and_listen() 启动，周期检查所有活跃 Step 是否超时。
        """
        # ── R90 🅲: <=0 禁用守卫 ──
        if not self._STEP_TIMEOUT_ENABLED:
            logger.info("[AR] ⏰ 超时检测已禁用 (AR_STEP_TIMEOUT=%d)",
                         self._STEP_DEFAULT_TIMEOUT)
            return  # 不启动定时器
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
        # ── R90 🅲: <=0 禁用守卫 ──
        if not self._STEP_TIMEOUT_ENABLED:
            return
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

    # ═══════════════ PipelineContext I/O ═══════════════

    def _load_pipeline_context(self, round_name: str) -> dict | None:
        """R97: 从 JSON 文件读取 PipelineContext。"""
        path = self._pipeline_contexts_path
        try:
            if os.path.exists(path):
                data = json.loads(open(path, encoding="utf-8").read())
                ctx = data.get(round_name)
                if ctx and isinstance(ctx, dict):
                    return ctx
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("[AR] PipelineContext 读取失败: %s", e)
        return None

    def _save_pipeline_context(self, round_name: str, ctx: dict) -> None:
        """R97: 写回 PipelineContext JSON 文件。"""
        path = self._pipeline_contexts_path
        try:
            data = {}
            if os.path.exists(path):
                data = json.loads(open(path, encoding="utf-8").read())
            data[round_name] = ctx
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("[AR] PipelineContext 保存失败: %s", e)

    # ═══════════════ 角色映射（R97: 实时查询 Agent Card）═══════════════

    async def _resolve_agent_by_role(self, role: str) -> str | None:
        """R97: 从 Agent Card 实时查询 role 对应的 agent_id。"""
        await self._refresh_role_map()

        # ① 精确匹配
        if role in self._role_index:
            agents = self._role_index[role]
            return agents[0] if agents else None

        # ② 子串匹配（"arch" ↔ "architect"）
        for known_role, agents in self._role_index.items():
            if role in known_role or known_role in role:
                return agents[0] if agents else None

        # ③ 角色名缩写匹配
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
                    if exp in self._role_index:
                        return self._role_index[exp][0]
            elif role in expanded:
                if short in self._role_index:
                    return self._role_index[short][0]

        logger.warning("[AR] 角色 %s 无对应 agent", role)
        return None

    async def _refresh_role_map(self) -> None:
        """R97: 从 config/agent_cards.json 读取角色映射（60s TTL 缓存）。"""
        now = time.time()
        if now - self._last_role_refresh < self._role_map_ttl:
            return

        if not os.path.exists(self.agent_card_path):
            logger.warning("[AR] Agent Card 文件不存在: %s", self.agent_card_path)
            self._last_role_refresh = now
            return

        try:
            with open(self.agent_card_path, encoding="utf-8") as f:
                cards = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("[AR] Agent Card 读取失败: %s", e)
            self._last_role_refresh = now
            return

        role_index: dict[str, list[str]] = {}
        for agent_id, card in cards.items():
            roles: list[str] = []
            if "pipeline_roles" in card and isinstance(card["pipeline_roles"], list):
                roles = card["pipeline_roles"]
            elif "role" in card:
                roles = [card["role"]]
            for role in roles:
                role_index.setdefault(role, []).append(agent_id)

        self._role_index = role_index
        self._last_role_refresh = now
        logger.info("[AR] 角色映射已刷新: %d 角色, %d agent(s)",
                     len(role_index), sum(len(v) for v in role_index.values()))

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
        """R97: 重启时从 PipelineContext JSON 恢复活跃管线。"""
        logger.info("[AR] 正在查询活跃管线状态...")
        path = self._pipeline_contexts_path
        restored = 0
        try:
            if os.path.exists(path):
                data = json.loads(open(path, encoding="utf-8").read())
                for round_name, ctx in data.items():
                    if isinstance(ctx, dict) and ctx.get("status") == "running":
                        restored += 1
                        logger.info(
                            "[AR] [%s] 恢复管线 (%d steps)",
                            round_name, len(ctx.get("steps", {})),
                        )
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("[AR] 状态恢复读取失败: %s", e)

        if restored == 0:
            logger.info("[AR] 无活跃管线，等待新管线事件")

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
        "--data-dir", default="",
        help="PipelineContext JSON 所在目录（默认 ./data）",
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
        data_dir=args.data_dir,
    )

    try:
        asyncio.run(router.start())
    except KeyboardInterrupt:
        logger.info("[AR] AutoRouter 已停止（Ctrl+C）")


if __name__ == "__main__":
    main()
