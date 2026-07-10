# R88 产品需求 — 管线自动路由：Pipeline AutoRouter 🚂

> **版本：** v3.0（独立服务架构 — AutoRouter 外挂服务，零 handler.py 侵入）
> **状态：** 📝 待审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-10
> **前置条件：** R87 `_inbox:server` 中继架构已部署 ✅ | 所有 bot 已适配 `_inbox:server` 回复协议 ✅

---

## 1. 问题背景

### 1.1 现状

R87 已完成 `_inbox:server` 中继架构，当前通信流：

```
PM                                Server                              Bot
│                                  │                                  │
│① 派活 ───────── _inbox:<bot_id> ─→│─────────────────────────────────→│
│                                  │                                  │
│                                  │←── ② ACK ✅ R{轮次} 收到！─────┤
│                                  │     (_inbox:server)              │
│←── ③ 转发 ACK ──────────────────┤                                  │
│                                  │         [bot 干活中...]         │
│                                  │←── ④ ✅ 完成 ──────────────────┤
│←── ⑤ 转发 完成 ────────────────┤                                  │
│                                  │── ⑥ 自动确认 ── _inbox:<bot_id>─→│
│                                  │                                  │
│  PM 仍需手动发送下一棒的派活     ←──────── 无自动接力 ──────────────│
```

**核心问题：** PM 每完成一个 Step 都要手动给下个 bot 发派活消息。每个轮次 PM 手动派活 5+ 次。

### 1.2 正确的思路

**PM 本身就是管线的一环——Step 1。**

| 轮次 | Step | 角色 | 工作内容 |
|:----:|:----:|:-----|:---------|
| 🅰️ | **Step 1** | **📋 PM** | 写需求文档 + WORK_PLAN（含 frontmatter 拓扑定义）+ `!pipeline_start` |
| 🅱️ | Step 2 | 👷 Arch | 技术方案设计 |
| 🅲 | Step 3 | 👨‍💻 Dev | 编码实现 |
| 🅳 | Step 4 | 👀 Review | 代码审查 |
| 🅴 | Step 5 | 🦐 QA | 测试验证 |
| 🅵 | Step 6 | 🛠️ Ops | 合并部署归档 |

**PM 完成 Step 1 后从管线中退场，AutoRouter 服务接手。** arch 收到的任务消息和 PM 手动派活时一模一样——bot 不 care 消息是谁发的。

> 📌 **对 bot 来说：通信方式完全没变化。** 任务消息的 channel 是 `_inbox:<bot_id>`，bot 该 ACK 就 ACK，该干活就干活。只是消息的 `from_name` 从「PM」变成「系统(管线)」，bot 不需要做任何适配改动。

---

## 2. 方案设计

### 2.1 架构决策：独立服务 vs handler.py 侵入

**决策：AutoRouter 做成独立外挂服务，不往 handler.py 加一行代码。**

| 方案 | handler.py 内嵌 | **独立服务（✅ 选定）** |
|:-----|:---------------|:---------------------|
| 侵入性 | 修改核心路由逻辑 ~60 行 | **零侵入** |
| 回归风险 | 中（handler 是核心路由） | **无**（现有代码完全不动） |
| 部署 | 随 server 一起重启 | 独立启动/停止 |
| 开发独立性 | 绑定 server 代码库 | 独立文件，可单独测 |
| 容错 | server 挂了 AutoRouter 也挂 | server 挂了 AutoRouter 仍在（在线确认等恢复） |
| 兼容性 | 修改后旧路由需回归测试 | **全手动模式零影响** |
| 未来扩展 | 耦合在 handler 里 | 可独立扩展（并行拓扑/异常回退等） |

**这样做的好处：**
- 想全手动 inbox → 不启动 AutoRouter，和之前一模一样
- 要自动化管线 → 启动 AutoRouter 服务
- 两者互不影响，兼容各种场景
- 技术实现选型给 arch（架构师）做技术方案时定细节，这里给高层架构

### 2.2 架构示意

```
┌─────────────────────────────────────────────────────────────────┐
│                     ws-bridge Server                            │
│  ┌──────────────┐  ┌──────────────────┐  ┌─────────────────┐   │
│  │ handle_auth  │  │ handle_broadcast │  │ _inbox:server   │   │
│  │ handle_reg.  │  │ (正常路由)        │  │ 中继 (R87 现有)  │   │
│  └──────────────┘  └──────────────────┘  └─────────────────┘   │
│                                              ↑                  │
└──────────────────────────────────────────────┼──────────────────┘
                                               │
                                     WebSocket (连接为 bot)
                                               │
                            ┌──────────────────┴──────────────────┐
                            │         AutoRouter Service           │
                            │                                      │
                            │  • 监听 PM 收件箱 (inbox 通知)        │
                            │  • 读取 Pipeline Topology 配置       │
                            │  • Step 完成 → 派活下一棒            │
                            │  • 全部完成 → 通知 PM                │
                            └──────────────────────────────────────┘
```

**AutoRouter 在 ws-bridge 眼中就是一个普通 bot：**
- 用 api_key 认证连接
- 有自己的 `_inbox:<router_id>` 收件箱
- 能发消息到其他 bot 的 `_inbox:<bot_id>`
- 能收来自 `_inbox:server` 中继的转发通知
- **不需要特殊权限**——发 inbox 消息的能力普通 bot 就有

### 2.3 通信流（R88 后）

```
PM                     ws-bridge Server              AutoRouter Service          Bot N
│                            │                            │                       │
│① Step 1:                  │                            │                       │
│ 写需求+WORK_PLAN           │                            │                       │
│ → !pipeline_start         │                            │                       │
│                            │                            │                       │
│② Server 处理:              │                            │                       │
│  解析 frontmatter          │                            │                       │
│  创建 workspace            │                            │                       │
│  通知 PM "已就绪"           │                            │                       │
│                            │                            │                       │
│                            │ ③ RouteStep N=1→2 ──────→│                       │
│                            │   (查询 PM inbox 通知)      │                       │
│                            │                            │── ④ 派活 Step2 ────→│
│                            │                            │    _inbox:arch        │
│                            │                            │                       │
│                            │  ←────────---⑤ ACK ✅ ←──│                       │
│                            │           (正常中继)        │                       │
│  ←── ⑥ 转发 ACK ────────┤                            │                       │
│                            │                            │                       │
│                            │                            │     [arch 干活中...]  │
│                            │                            │                       │
│                            │  ←────────---⑦ ✅ 完成 ←─│                       │
│                            │           (正常中继)        │                       │
│  ←── ⑧ 转发 完成 ──────┤                            │                       │
│                            │  ←── ⑨ 自动确认 bot ────→│                       │
│                            │                            │                       │
│                            │ ⑩ 路由 Step 2→3 ────────→│                       │
│                            │   (检测到 Step 2 已完成)   │── ⑪ 派活 Step3 ────→│
│                            │                            │    _inbox:dev          │
│                            │                            │                       │
│                     ... 以此类推到 Step 6 ...                              │
│                            │                            │                       │
│                            │  ←─── Step 6 ops ✅ 完成──│                       │
│  ←── ⑫ 全部完成通知 ──┤                            │                       │
│                            │                            │                       │
```

**PM 视角：** `!pipeline_start` → 坐等通知 → 收全部完成 → 下班 🏁

**Bot 视角：** 和现在一模一样——收到的消息 `from_name` 从「PM」变成「系统(管线)」，bot 完全透明。

### 2.4 核心设计原则

| # | 原则 | 说明 |
|:-:|:-----|:------|
| 1 | **零 handler.py 侵入** | AutoRouter 是独立服务，不修改现有 server 代码 |
| 2 | **bot 透明** | Bot 的 ACK/完成协议完全不变，bot 零改动 |
| 3 | **全手动兼容** | 不启动 AutoRouter，PM 手动 inbox 模式完全不变 |
| 4 | **PM = Step 1** | `!pipeline_start` 是 Step 1 完成信号，之后 AutoRouter 接手 |
| 5 | **标准 bot 身份** | AutoRouter 用 api_key 连接，发 inbox，收通知——不需要特殊权限 |
| 6 | **无状态设计** | Pipeline Topology 来自 WORK_PLAN frontmatter（已持久化），AutoRouter 启动时重读 |

---

## 3. 实现方案

### 3.1 AutoRouter 服务概览

**文件位置：** `server/auto_router.py`（独立文件，不修改 handler.py）

**运行方式：**
- `python3 -m server.auto_router --api-key <key>` — 独立进程
- 或由 `docker-compose` 管理（与 ws-bridge server 平行）
- 或由 operations（运维）按需启动/停止

**依赖：** 仅需 `websockets` + `PyYAML` + 标准库（已存在）

### 3.2 核心流程

```
AutoRouter 启动
    │
    ├─ ① 连接 ws-bridge（WS + api_key 认证）
    │
    ├─ ② 连接就绪，等待事件
    │
    ├─ ③ 收到消息
    │    ├─ 来自 PM 收件箱的 ACK/完成 转发通知（R87 中继）
    │    ├─ 来自 _inbox:server 的直接通知（可选）
    │    └─ 其他 → 忽略
    │
    ├─ ④ 检测到 "✅ X 任务完成" 或 管线启动信号
    │    ├─ 解析 round_name + step_name + SHA
    │    └─ 读取 Pipeline Topology
    │
    ├─ ⑤ 有下一棒？
    │    ├─ 是 → 派活到 _inbox:<next_bot_id>
    │    └─ 否 → 通知 PM "全部完成"
    │
    └─ ⑥ 回到 ③ 继续监听
```

### 3.3 AutoRouter 的输入信号

AutoRouter 通过收到的消息判断管线和 Step 状态。它关心的消息来源：

| 信号类型 | 来源 | 触发条件 | 示例消息 |
|:---------|:-----|:---------|:---------|
| **🆕 管线就绪** | `_admin` 频道系统消息 | `!pipeline_start` 成功创建 workspace | `📋 R88 管线已启动，工作区已就绪` |
| **📬 Bot ACK** | PM 收件箱转发 | R87 bot 发 `ACK ✅` → server 转发 PM | `📬 architect 已接活: ACK ✅ R88 收到！` |
| **✅ Bot 完成** | PM 收件箱转发 | R87 bot 发 `✅ 完成` → server 转发 PM | `✅ architect 任务完成: ✅ 完成，已推 dev: abc1234` |
| **🏁 全部完成** | 无下一棒时的自产信号 | 最后一个 Step 的 `✅ 完成` → 自动发完工通知 | `🏁 R88 全部 Step 已完成！` |

> **实际上 AutoRouter 只需监听 PM 收件箱的转发通知**（R87 第 ③⑤ 步）。当 PM 收到 `✅ architect 任务完成` 的转发时，AutoRouter 就解析它、查拓扑、派活下一棒。
>
> **为什么不监听 `_inbox:server`？** 省事——PM 收件箱的转发通知已经是格式化后的消息，直接解析即可。

### 3.4 各函数接口

```python
# server/auto_router.py — 独立服务，不修改 handler.py

import asyncio, json, logging, re, time
import websockets

logger = logging.getLogger("auto_router")


class PipelineAutoRouter:
    """管线自动路由服务。
    
    以 bot 身份连接 ws-bridge，监听 PM 收件箱的转发通知，
    检测 Step 完成信号后自动派活下一棒。
    """
    
    def __init__(self, api_key: str, ws_url: str = "wss://wsim.datahome73.cloud/ws",
                 pm_agent_id: str = "", agent_card_path: str = ""):
        self.api_key = api_key
        self.ws_url = ws_url
        self.pm_agent_id = pm_agent_id
        self.agent_card_path = agent_card_path  # 或从卡片读角色映射
        
        # 运行时状态
        self.ws = None
        self.my_agent_id = ""
        self.my_inbox = ""
        
        # — Pipeline Topology 缓存 —
        # Key: round_name (如 "R88")
        # Value: {"chain": [...], "auto_chain": bool, "steps": {...}}
        self._topologies: dict[str, dict] = {}
        
        # — Step 进度追踪 —
        # Key: round_name → Value: {"current_step_idx": int, "completed_steps": set}
        self._round_progress: dict[str, dict] = {}
    
    # ── 生命周期 ──
    
    async def start(self):
        """启动 AutoRouter 并保持连接。"""
        async with websockets.connect(self.ws_url, max_size=2**20) as ws:
            self.ws = ws
            # 认证
            await ws.send(json.dumps({"type": "auth", "api_key": self.api_key}))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if resp.get("type") != "auth_ok":
                raise RuntimeError(f"认证失败: {resp}")
            self.my_agent_id = resp.get("agent_id", "")
            self.my_inbox = f"_inbox:{self.my_agent_id}"
            logger.info("AutoRouter 已连接, agent_id=%s", self.my_agent_id[:16])
            
            # 查询现有活跃管线，重建进度
            await self._restore_pipeline_state()
            
            # 主循环：监听消息
            async for raw in ws:
                try:
                    await self._handle_message(json.loads(raw))
                except Exception as e:
                    logger.error("消息处理异常: %s", e)
    
    # ── 消息处理 ──
    
    async def _handle_message(self, msg: dict):
        """处理接收到的每条消息。"""
        channel = msg.get("channel", "")
        content = msg.get("content", "").strip()
        from_name = msg.get("from_name", "")
        
        # 只关心 PM 收件箱的转发通知
        if channel != f"_inbox:{self.pm_agent_id}":
            return
        
        # 信号 1: 管线就绪（!pipeline_start 成功）
        if "管线已启动" in content or "工作区已就绪" in content:
            round_name = self._extract_round(content)
            if round_name:
                await self._on_pipeline_ready(round_name)
            return
        
        # 信号 2: Bot 任务完成（PM 收到 "✅ X 任务完成" 转发）
        if content.startswith("✅ ") and "任务完成" in content:
            await self._on_step_complete(content)
            return
        
        # 其他消息不关心
        # （ACK 转发不需要处理——AutoRouter 只看完成信号）
    
    # ── 管线就绪处理 ──
    
    async def _on_pipeline_ready(self, round_name: str):
        """!pipeline_start 成功后，加载拓扑配置，记录管线状态。"""
        # 从远程 WORK_PLAN 读取 frontmatter 拓扑
        topology = await self._fetch_topology(round_name)
        if not topology:
            logger.warning("[%s] 未找到 topology 定义，跳过自动接力", round_name)
            return
        
        chain = topology.get("chain", [])
        if not chain:
            logger.warning("[%s] topology.chain 为空，跳过", round_name)
            return
        
        # 记录进度：当前在 Step 1，等待 Step 1 完成信号
        self._round_progress[round_name] = {
            "current_step_idx": -1,   # 还没开始
            "completed_steps": set(),
            "chain": chain,
            "topology": topology,
        }
        logger.info("[%s] AutoRouter 已就绪，chain=%d steps", round_name, len(chain))
    
    # ── Step 完成处理 ──
    
    async def _on_step_complete(self, content: str):
        """处理 Step 完成通知 → 自动派活下一棒。"""
        # 提取信息: 角色名 + SHA
        # 格式: "✅ architect 任务完成: ✅ 完成，已推 dev: abc1234"
        role = self._extract_role(content)      # 如 "architect"
        sha = self._extract_sha(content)         # 如 "abc1234"
        round_name = self._extract_round(content)
        
        if not round_name or not role:
            logger.debug("无法解析完成消息: %s", content[:60])
            return
        
        progress = self._round_progress.get(round_name)
        if not progress:
            logger.debug("[%s] 无进度记录，跳过", round_name)
            return
        
        chain = progress["chain"]
        
        # 找完成者在 chain 中的 index
        current_idx = None
        for i, step in enumerate(chain):
            if step.get("role") == role:
                current_idx = i
                break
        
        if current_idx is None:
            logger.debug("[%s] 角色 %s 不在 chain 中", round_name, role)
            return
        
        # 标记完成
        progress["completed_steps"].add(current_idx)
        progress["current_step_idx"] = current_idx
        
        # 找下一棒
        next_idx = current_idx + 1
        if next_idx >= len(chain):
            # 全部完成！
            await self._notify_all_done(round_name)
            return
        
        next_step = chain[next_idx]
        
        # 派活下一棒
        await self._dispatch_step(
            round_name=round_name,
            step_config=next_step,
            prev_role=role,
            prev_sha=sha or "",
            chain=chain,
        )
        
        logger.info(
            "[%s] ✅ %s → 🎯 %s (SHA=%s)",
            round_name, role, next_step.get("role", "?"), sha or "?",
        )
    
    # ── 派活逻辑 ──
    
    async def _dispatch_step(self, round_name: str, step_config: dict,
                              prev_role: str, prev_sha: str, chain: list):
        """发送派活消息到目标 bot 的 inbox。"""
        role = step_config.get("role", "")
        title = step_config.get("title", "")
        step_key = step_config.get("step", "")
        
        # 找目标 bot 的 agent_id
        target_id = self._resolve_agent_id(role, round_name)
        if not target_id:
            await self._send_to_pm(
                f"❌ AutoRouter: {round_name} {step_key}({role}) "
                f"未找到对应 bot，请手动派活"
            )
            return
        
        # 构建上下文
        context_lines = []
        for k, v in step_config.get("context", {}).items():
            if v:
                context_lines.append(f"- {k}: {v}")
        context_str = "\n".join(context_lines) if context_lines else ""
        
        # 任务消息
        task_content = (
            f"【{round_name} Step {step_key} 任务 — {title} 🎯】\n\n"
            f"角色: {role}\n"
            f"前一棒 {prev_role} 已完成 ✅ `{prev_sha}`\n\n"
        )
        if context_str:
            task_content += f"参考：\n{context_str}\n\n"
        task_content += (
            f"请按流程完成任务后推 dev 分支。\n"
            f"完成后请回复 _inbox:server 告知 SHA。"
        )
        
        # 发消息
        await self._send_inbox(target_id, task_content)
        logger.info("[AutoRouter] 派活 %s → %s (%s)", round_name, role, target_id[:12])
    
    # ── 工具函数 ──
    
    async def _fetch_topology(self, round_name: str) -> dict | None:
        """从远程 WORK_PLAN 读 frontmatter，提取 topology。"""
        # 1. 通过 !pipeline_status 或直接查询
        # 2. 从 GitHub raw URL 读取 WORK_PLAN.md
        # 3. 解析 frontmatter 提取 topology.chain
        ...
    
    def _resolve_agent_id(self, role: str, round_name: str) -> str | None:
        """根据 role 名找对应 bot 的 agent_id。通过 Agent Card 映射。"""
        # 1. 从缓存的本轮 _r72_users 查
        # 2. 从 Agent Card pipeline_roles 查
        ...
    
    def _extract_role(self, content: str) -> str | None:
        """从"✅ architect 任务完成:..."中提取角色名。"""
        m = re.match(r'✅ (\w+) 任务完成', content)
        return m.group(1) if m else None
    
    def _extract_sha(self, content: str) -> str | None:
        """从"已推 dev: abc1234"中提取 SHA。"""
        m = re.search(r'(?:已推 dev[:\s]+|commit[:\s]+|SHA[:\s]*)([0-9a-f]{7,40})', content)
        return m.group(1) if m else None
    
    def _extract_round(self, content: str) -> str | None:
        """从消息中提取轮次名。"""
        m = re.search(r'\b(R\d{1,3})\b', content)
        return m.group(1) if m else None
    
    async def _send_inbox(self, target_id: str, content: str):
        """发送 inbox 消息。"""
        await self.ws.send(json.dumps({
            "type": "message",
            "channel": f"_inbox:{target_id}",
            "content": content,
            "from_name": "系统(管线)",
            "agent_id": self.my_agent_id,
            "id": f"auto-{int(time.time()*1000)}",
            "ts": time.time(),
        }))
    
    async def _send_to_pm(self, content: str):
        """发送通知到 PM 收件箱。"""
        if self.pm_agent_id:
            await self._send_inbox(self.pm_agent_id, content)
    
    async def _notify_all_done(self, round_name: str):
        """全部 Step 完成 → 通知 PM。"""
        await self._send_to_pm(
            f"🏁 {round_name} 全部 Step 已完成！管线自动闭环。"
        )
        logger.info("[%s] 🏁 全部完成，通知 PM", round_name)
    
    async def _restore_pipeline_state(self):
        """启动时查询已有活跃管线，恢复进度状态。"""
        # 发 !pipeline_status 查询所有活跃管线
        # 或从 _admin 频道历史读取
        ...


# ── 入口 ──

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pipeline AutoRouter Service")
    parser.add_argument("--api-key", required=True, help="AutoRouter 的 ws-bridge api_key")
    parser.add_argument("--pm-agent-id", default="", help="PM 的 agent_id")
    parser.add_argument("--ws-url", default="wss://wsim.datahome73.cloud/ws")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [AR] %(message)s")
    
    router = PipelineAutoRouter(
        api_key=args.api_key,
        ws_url=args.ws_url,
        pm_agent_id=args.pm_agent_id,
    )
    
    try:
        asyncio.run(router.start())
    except KeyboardInterrupt:
        logger.info("AutoRouter 已停止")
```

### 3.5 Pipeline Topology 定义（frontmatter）

```yaml
pipeline:
  name: "R88 Pipeline AutoRouter"
  work_plan_url: "https://raw.githubusercontent.com/.../docs/R88/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/.../docs/R88/R88-product-requirements.md"

  topology:                              # ← 🆕 管线拓扑定义
    auto_chain: true                     # 启用自动接力
    chain:                               # Step 链（有序列表，从 Step 2 开始）
      - step: step2
        role: architect
        title: 技术方案
        context:
          requirements_url: "${pipeline.requirements_url}"
          work_plan_url: "${pipeline.work_plan_url}"
      - step: step3
        role: developer
        title: 编码实现
        context:
          requirements_url: "${pipeline.requirements_url}"
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step4
        role: reviewer
        title: 代码审查
        context:
          requirements_url: "${pipeline.requirements_url}"
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step5
        role: qa
        title: 测试验证
        context:
          requirements_url: "${pipeline.requirements_url}"
          code_review_url: "docs/{round}/{round}-code-review.md"
      - step: step6
        role: operations
        title: 合并部署归档
        context:
          requirements_url: "${pipeline.requirements_url}"
          test_report_url: "docs/{round}/{round}-test-report.md"

  steps:                                 # 兼容现有格式（!step_complete 等）
    step2:
      role: architect
      title: 技术方案
    step3:
      role: developer
      title: 编码实现
    step4:
      role: reviewer
      title: 代码审查
    step5:
      role: qa
      title: 测试验证
    step6:
      role: operations
      title: 合并部署归档
```

**关于 `chain` vs 现有的 `steps`：**

| 字段 | 用途 | 适用于 |
|:-----|:------|:-------|
| `topology.chain` | **AutoRouter** — 有序数组，表达 Step 自动接力关系 | 独立服务读取 |
| `steps` | **`!step_complete`** — 用于状态机推进（现有） | handler.py 解析 |

两者并存且不冲突——一个面向 AutoRouter，一个面向管线状态机。

### 3.6 简写格式

标准 6-Step 管线可省略 `topology.chain`：

```yaml
pipeline:
  auto_chain: true                       # ← 仅需 1 行
  steps:
    step2: { role: architect, title: 技术方案 }
    step3: { role: developer, title: 编码实现 }
    step4: { role: reviewer, title: 代码审查 }
    step5: { role: qa, title: 测试验证 }
    step6: { role: operations, title: 合并部署归档 }
```

AutoRouter 启动时检测不到 `chain` 就按 role 顺序排序派活。

### 3.7 不纳入范围

| 事项 | 原因 |
|:-----|:------|
| **并行 Step 拓扑** — chain 支持 `parallel: true` | 线性先跑通，并行留 R89 |
| **异常回退** — 完成消息不合格式时自动回退 PM | v1 直接通知 PM 手动处理 |
| **Step 跳过** | 非核心场景 |
| **动态拓扑修改** | 拓扑在 pipeline_start 时固定 |
| **结构化 Task Card** | 自然语言模板先跑通 |
| **handler.py 的任何修改** | AutoRouter 是独立服务，零侵入 |

### 3.8 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/auto_router.py` | **新增** — 完整独立服务 | ~250 行 |
| `server/config.py` | **可选新增** — 默认拓扑常量/agent_card 路径（AutoRouter 启动参数也可） | ~10 行 |
| **handler.py** | **✅ 零改动！** | **0 行** |

**净增：** ~250 行全新文件。零回归风险。bot 端零改动。

---

## 4. 验收标准

### 🎯 4.1 核心功能

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | `!pipeline_start` 含 topology → AutoRouter 检测到管线就绪 | AutoRouter 日志打印 "已就绪，chain=N steps" | 启动管线 → 检查 AutoRouter 日志 |
| ✅-2 | arch 发 `✅ 完成` → AutoRouter 自动派活 Step 3 dev | dev inbox 收到任务消息（from_name="系统(管线)"） | 检查 dev 收件箱 |
| ✅-3 | Step 3 → 4, Step 4 → 5, Step 5 → 6 全线自动 | 全部自动接力，PM 未手动发任何一条中间派活 | 日志统计 AutoRouter 派活次数 |
| ✅-4 | Step 6 ops 发 `✅ 完成` → AutoRouter 发「全部完成」通知 PM | PM 收到 `🏁 R{轮次} 全部 Step 已完成！` | 检查 PM 收件箱 |
| ✅-5 | 自动派活消息包含正确的 SHA 引用 | 任务中引用了前一棒的 commit SHA | 检查任务内容 |
| ✅-6 | 自动派活消息包含正确的 context URL | 任务中提及前一棒的文档 URL | 同上 |
| ✅-7 | 不启动 AutoRouter → 管线照常手动运行 | PM 手动 inbox 模式完全不变 | 不启动服务，正常手动派活 |
| ✅-8 | AutoRouter 停止 → 不影响已启动的管线 | 管线不丢失，PM 切回手动继续 | 停止 AutoRouter，PM 手动接力 |

### 🎯 4.2 bot 透明性验证

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-9 | Bot 收到 server 派活后，正常发 ACK ✅ | Bot 的 ACK 协议不变 |
| ✅-10 | Bot 正常干活、正常 `✅ 完成` | Bot 的工作流不变 |
| ✅-11 | Bot 回复地址仍是 `_inbox:server` | 不受发送者影响 |

### 🎯 4.3 安全与恢复

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-12 | AutoRouter 找不到目标 agent → 通知 PM + 继续 | PM 收到 ❌ 通知 |
| ✅-13 | AutoRouter 重启后恢复活跃管线进度 | 启动时查询 `!pipeline_status` 重建状态 |
| ✅-14 | 无 topology 的管线 → AutoRouter 安静跳过 | 日志提示 "未找到 topology" 但无错误 |
| ✅-15 | AutoRouter 断线重连 | 自动重连（现有 ws 库已支持） |
| ✅-16 | PM 手动派活与 AutoRouter 不冲突 | 两者都可以发 inbox，bot LLM 自行处理 |

### 🎯 4.4 文档更新

| # | 检查项 |
|:-:|:-------|
| ✅-17 | `inbox-message-protocol.md` 更新为 AutoRouter 服务模型 |
| ✅-18 | TODO.md Phase 2 + 版本号更新 |
| ✅-19 | `server/auto_router.py` 模块注释和 README |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:----:|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| 🅰️ **Step 1** | **📋 PM** | WORK_PLAN.md（含 topology 定义）→ `!pipeline_start` | 5min |
| 🅱️ **Step 2** | 👷 Arch | 技术方案（含服务架构、角色映射策略、chain 解析） | 10min |
| 🅲 **Step 3** | 👨‍💻 Dev | 编码实现 `auto_router.py`（~250 行） | 20min |
| 🅳 **Step 4** | 👀 Review | 代码审查（重点：断线重连、角色映射鲁棒性） | 10min |
| 🅴 **Step 5** | 🦐 QA | 测试报告（19 项验收 + 端到端场景） | 15min |
| 🅵 **Step 6** | 🛠️ Ops | 注册 AutoRouter 服务 + 部署 + 更新文档 | 10min |

### 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| **角色映射不准** — `_resolve_agent_id` 找不到 bot | 派活失败 | 通知 PM 手动 + 日志，不阻任何现有流程 |
| **`!pipeline_start` 消息被 AutoRouter 错过** | AutoRouter 感知不到管线启动 | 启动时 `_restore_pipeline_state` 查现有管线 |
| **AutoRouter 断线** — 服务挂了 | 自动接力停止 | 断线重连（ws 库自带）+ PM 手动补位 |
| **AutoRouter 重启后进度丢失** | 不知道当前到哪一步 | `_restore_pipeline_state` 查询 `!pipeline_status` |
| **多个 AutoRouter 实例冲突** | 重复派活 | 只允许一个实例运行（进程级锁或 PM 管理） |
| **handler.py 不改 → 无法读取 `_PIPELINE_CONFIG`** | AutoRouter 读不到 frontmatter 拓扑 | AutoRouter 自己从 WORK_PLAN raw URL 下载解析 frontmatter，不依赖 server 内存状态 |

---

## 6. R88 与 Roadmap 的对应关系

```
Phase 1 — 稳定 Inbox ✅
       ↓
Phase 2 — 自动化管线（进行中）
       ├── ✅ R87: `_inbox:server` 中继架构
       ├── 🔄 **R88: Pipeline AutoRouter** ← 当前轮次
       ├── 🔲 R89: 异常回退 + 并行拓扑
       ├── 🔲 R90: 结构化 Task Card / 监控增强
       └── 🔲 R91: 跨轮次连续工作
       ↓
Phase 3 — Coder Agent 编码专精（待启动）
```

---

## 7. 完整端到端场景

### 场景：6-Step 管线全线自动接力

```
准备工作（Step 1 — PM）：
  ① 写 R88-product-requirements.md
  ② 写 WORK_PLAN.md（含 pipeline.topology.chain 定义）
  ③ 推 dev
  ④ 执行 !pipeline_start R88 --work_plan_url <raw_url>

Server 处理 !pipeline_start：
  ⑤ 解析 frontmatter → 创建 workshop → 通知全员就绪

AutoRouter 感知管线启动：
  ⑥ 从 PM 收件箱收到 "R88 管线已启动，工作区已就绪"
  ⑦ 从 WORK_PLAN 远程 URL 读取 frontmatter → 解析 topology.chain
  ⑧ 发现 chain=[arch, dev, review, qa, ops]，auto_chain=true
  ⑨ 记录进度: round_progress["R88"] = {current_idx: -1}

  ── 等待第一个 ✅ 完成通知 ──

Step 2（arch）：
  ➉ PM 自己给 arch 派活（AutoRouter 等待 PM 完成 Step 2 也行，
    或者 PM 发给 arch，arch 完成时触发 AutoRouter）
  — 实际流程: PM 完成 Step 1 后，通知 arch 开始或 AutoRouter
    检测到 Step 1 完成后自动派活 arch

  arch 收活 → ACK ✅ → 写技术方案 → 推 dev → ✅ 完成
    ① AutoRouter 从 PM 收件箱收到转发 "✅ architect 任务完成"
    ② 解析：role=architect, sha=abc1234, round=R88
    ③ chain 中 arch idx=0 → next_idx=1 (developer)
    ④ 派活 Step 3 到 _inbox:dev

Step 3（dev — auto-dispatched by AutoRouter）：
    ⑤ dev 收活 → ACK ✅ → 编码 → 推 dev → ✅ 完成
    ⑥ AutoRouter 检测完成 → chain[1]→chain[2] → 派活 reviewer

Step 4→5→6（自动接力，同上模式）：
    ⑦ 每步完成 → AutoRouter 自动转下步

终局：
    ⑧ Step 6 ops ✅ 完成
    ⑨ AutoRouter 检测 chain 终点 → 发「全部完成」通知 PM
    ⑩ PM 收到 🏁 R88 全线闭环 🎉
```

**PM 全程操作：** 写文档 → `!pipeline_start` → 收 ACK/完成通知 → 收完工通知。

**Bot 全程感知：** 和现在的流程完全一致 — 收消息 → ACK → 干活 → ✅ 完成。消息的 `from_name` 是「系统(管线)」而非「PM」，但 bot 不需要为此做任何改动。

---

## 8. 脱敏检查清单

- [ ] docs/R88/*.md 零内部名残留（frontmatter 的角色 mapping 除外）
- [ ] 使用通用角色名（PM / arch / dev / review / qa / operations）
- [ ] 不包含真实 agent_id / token / URL
- [ ] chain 示例中的 bot 名称用角色名，不使用具体 bot 名
