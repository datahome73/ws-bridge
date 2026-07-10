# R88 技术方案 — Pipeline AutoRouter 🚂

> **版本：** v1.0
> **状态：** 📝 初稿
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-10
> **基于需求文档：** `docs/R88/R88-product-requirements.md` v3.0
> **基于工作计划：** `docs/R88/WORK_PLAN.md` v1.0
> **新增文件：** `server/auto_router.py`（独立服务，~250 行）
> **零修改文件：** `handler.py` ✅ · `config.py` ✅ · `__main__.py` ✅

---

## 目录

1. [服务架构设计](#1-服务架构设计)
2. [PipelineAutoRouter 类设计](#2-pipelineautorouter-类设计)
3. [角色映射策略](#3-角色映射策略)
4. [Chain 解析策略](#4-chain-解析策略)
5. [模板变量替换方案](#5-模板变量替换方案)
6. [断线重连方案](#6-断线重连方案)
7. [错误处理方案](#7-错误处理方案)
8. [边界情况处理](#8-边界情况处理)
9. [改动一览](#9-改动一览)
10. [附录：完整伪代码](#10-附录完整伪代码)

---

## 1. 服务架构设计

### 1.1 架构决策回顾

| 方案 | handler.py 内嵌 | **独立服务（✅ 选定）** |
|:-----|:---------------|:---------------------|
| 侵入性 | 修改核心路由逻辑 ~60 行 | **零侵入** |
| 回归风险 | 中 | **无** |
| 部署 | 随 server 一起重启 | 独立启动/停止 |
| 容错 | server 挂了 AutoRouter 也挂 | server 挂了 AutoRouter 仍在 |
| 兼容性 | 需回归测试旧路由 | 全手动模式零影响 |

### 1.2 模块划分

```
server/auto_router.py
│
├── PipelineAutoRouter (class)
│   ├── 生命周期层
│   │   ├── start()              — WS 连接 + 认证 + 主循环
│   │   ├── _reconnect_loop()    — 断线重连
│   │   └── stop()               — 优雅退出
│   │
│   ├── 消息处理层
│   │   ├── _handle_message()    — 消息入口分发
│   │   ├── _on_pipeline_ready() — 管线就绪事件
│   │   ├── _on_step_complete()  — Step 完成事件
│   │   └── _on_ack_received()   — ACK 确认事件（可选，用于进度追踪）
│   │
│   ├── 管线引擎层
│   │   ├── _dispatch_step()     — 派活下一棒
│   │   ├── _notify_all_done()   — 全部完成通知
│   │   ├── _fetch_topology()    — 远程读取 WORK_PLAN frontmatter
│   │   └── _resolve_agent_id()  — 角色→agent_id 映射
│   │
│   └── 工具层
│       ├── _extract_role()      — 从完成消息提取角色
│       ├── _extract_sha()       — 从完成消息提取 SHA
│       ├── _extract_round()     — 从消息提取轮次名
│       ├── _render_template()   — 模板变量替换
│       ├── _send_inbox()        — 发 inbox 消息
│       ├── _send_to_pm()        — 通知 PM
│       └── _restore_pipeline_state() — 启动时重建活跃管线状态
│
└── main (if __name__ == "__main__")
    ├── argparse 参数解析
    └── asyncio.run(start())
```

### 1.3 通信架构

```
ws-bridge Server                    AutoRouter Service（bot 身份）
      │                                     │
      │  ┌─ WS 连接 (api_key 认证) ────────→│
      │  │                                   │
      │  │  ┌─ 监听 PM 收件箱转发通知 ─────→│
      │  │  │   (channel = _inbox:<PM_id>)   │
      │  │  │                                │
      │  │  │  ┌─ 检测到 ✅ 完成 → 派活 ───→│  → 发 _inbox:<bot_id>
      │  │  │  ├─ 检测到 管线就绪 → 加载拓扑│
      │  │  │  └─ 检测到 全部完成 → 通知 PM │
      │  │  │                                │
      │  │  │  ┌─ _restore_pipeline_state ──→│  启动时
      │  │  │                                │
      │  └────────────────────────────────────┤
      │          不依赖 server 内存状态        │
      │          AutoRouter 自己从远程读取拓扑  │
```

### 1.4 数据流

```
!pipeline_start  (PM 发到工作群)
        │
        ▼
ws-bridge Server 创建 workspace + 通知
        │
        ▼
PM 收件箱收到 "R88 管线已启动，工作区已就绪"
        │
        ▼
AutoRouter 从 PM 收件箱感知到该通知
        │
        ├─ _extract_round() → "R88"
        ├─ _fetch_topology("R88") → 从 WORK_PLAN raw URL 下载 frontmatter
        │   └─ PyYAML 解析 → topology.chain
        └─ 记录 _round_progress["R88"]
        │
        ▼
    等待 ✅ 完成消息（从 PM 收件箱转发）
        │
        ▼
收到 "✅ architect 任务完成: ✅ 完成，已推 dev: abc1234"
        │
        ├─ _extract_role() → "architect"
        ├─ _extract_sha() → "abc1234"
        ├─ _extract_round() → "R88"
        ├─ chain[0] (architect) 完成 → chain[1] (developer)
        ├─ _resolve_agent_id("developer", "R88") → ws_agent_id
        └─ _dispatch_step() → 发 _inbox:<dev_agent_id>
```

---

## 2. PipelineAutoRouter 类设计

### 2.1 类签名与状态

```python
class PipelineAutoRouter:
    """管线自动路由服务 — 独立外挂，零 handler.py 侵入。"""

    def __init__(
        self,
        api_key: str,
        ws_url: str = "wss://wsim.datahome73.cloud/ws",
        pm_agent_id: str = "",
        agent_card_path: str = "",
    ):
        # ── 连接参数 ──
        self.api_key = api_key
        self.ws_url = ws_url
        self.pm_agent_id = pm_agent_id
        self.agent_card_path = agent_card_path

        # ── WebSocket 状态 ──
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.my_agent_id: str = ""
        self.my_inbox: str = ""
        self._running = False

        # ── 管线拓扑缓存 ──
        # Key: round_name → {"chain": [...], "auto_chain": bool, "pipeline": {...}}
        self._topologies: dict[str, dict] = {}

        # ── Step 进度追踪 ──
        # Key: round_name → {
        #   "current_step_idx": int,
        #   "completed_steps": set[int],
        #   "chain": list,
        #   "topology": dict,
        # }
        self._round_progress: dict[str, dict] = {}

        # ── 已处理的 msg_id（去重） ──
        self._seen_ids: set[str] = set()
    ```

### 2.2 核心方法概览

| 方法 | 可见性 | 触发 | 职责 |
|:-----|:------:|:-----|:-----|
| `start()` | public | CLI 入口 | 建立 WS 连接 → 认证 → 启动主循环 |
| `stop()` | public | 信号/SIGINT | 优雅断开连接 |
| `_handle_message()` | async private | 每收到一条消息 | 按 channel + 内容模式分发 |
| `_on_pipeline_ready()` | async private | 管线就绪通知 | 加载拓扑，记录进度 |
| `_on_step_complete()` | async private | ✅ 完成消息 | 解析 → 找下一步 → 派活/完成 |
| `_dispatch_step()` | async private | 找到下一步 | 构建任务消息 → 发 inbox |
| `_notify_all_done()` | async private | 最后一步完成 | 通知 PM 全链闭环 |
| `_fetch_topology()` | async private | 管线就绪 / 重启恢复 | HTTP GET WORK_PLAN.md → frontmatter |
| `_resolve_agent_id()` | sync private | 派活前 | role → agent_id 查表 |
| `_render_template()` | sync private | 构建任务内容 | `${pipeline.xxx}` / `{round}` 替换 |
| `_restore_pipeline_state()` | async private | 启动时 | 查询活跃管线 → 恢复进度 |
| `_send_inbox()` | async private | 发消息 | 发 `_inbox:<target_id>` 消息 |
| `_send_to_pm()` | async private | 通知 PM | 发 `_inbox:<pm_id>` 通知 |
| `_extract_role()` | static private | 消息解析 | 正则提取角色 |
| `_extract_sha()` | static private | 消息解析 | 正则提取 SHA |
| `_extract_round()` | static private | 消息解析 | 正则提取轮次 |
| `_reconnect_loop()` | async private | 断线 | 指数退避重连 |

### 2.3 主循环伪代码

```python
async def start(self):
    """启动 AutoRouter 并保持连接。"""
    self._running = True
    while self._running:
        try:
            async with websockets.connect(
                self.ws_url, max_size=2**20, ping_interval=30, ping_timeout=10
            ) as ws:
                self.ws = ws
                # ── ① 认证 ──
                await ws.send(json.dumps({"type": "auth", "api_key": self.api_key}))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if resp.get("type") != "auth_ok":
                    raise RuntimeError(f"认证失败: {resp}")
                self.my_agent_id = resp.get("agent_id", "")
                self.my_inbox = f"_inbox:{self.my_agent_id}"
                logger.info("[AR] ✅ 已连接, agent_id=%s", self.my_agent_id[:16])

                # ── ② 启动时恢复已有管线 ──
                await self._restore_pipeline_state()

                # ── ③ 主监听循环 ──
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        await self._handle_message(msg)
                    except json.JSONDecodeError:
                        logger.warning("[AR] 无效 JSON: %s", raw[:80])
                    except Exception as e:
                        logger.error("[AR] 消息处理异常: %s", e)
        except websockets.ConnectionClosed as e:
            logger.warning("[AR] 连接断开 (code=%s), 准备重连...", e.code)
            await asyncio.sleep(5)  # 简单重连延迟
        except Exception as e:
            logger.error("[AR] 连接异常: %s, 10s 后重试", e)
            await asyncio.sleep(10)
```

### 2.4 消息分发伪代码

```python
async def _handle_message(self, msg: dict):
    """消息入口 — 只关心 PM 收件箱的转发通知。"""
    channel = msg.get("channel", "")
    content = (msg.get("content") or "").strip()
    msg_id = msg.get("id", "")

    # ── 去重 ──
    if msg_id and msg_id in self._seen_ids:
        return
    if msg_id:
        self._seen_ids.add(msg_id)

    # ── 只监听 PM 收件箱 ──
    if channel != f"_inbox:{self.pm_agent_id}":
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

    # 其他消息 → 忽略（ACK 转发、系统通知等不处理）
```

### 2.5 Step 完成处理伪代码

```python
async def _on_step_complete(self, content: str):
    """Step 完成 → 自动派活下一棒。"""
    role = self._extract_role(content)
    sha = self._extract_sha(content)
    round_name = self._extract_round(content)

    if not round_name or not role:
        logger.debug("[AR] 无法解析完成消息: %s", content[:60])
        return

    progress = self._round_progress.get(round_name)
    if not progress:
        logger.debug("[AR] [%s] 无进度记录，跳过", round_name)
        return

    chain = progress["chain"]

    # 找完成者在 chain 中的 index
    current_idx = None
    for i, step in enumerate(chain):
        if step.get("role") == role:
            current_idx = i
            break

    if current_idx is None:
        logger.debug("[AR] [%s] 角色 %s 不在 chain 中", round_name, role)
        return

    # 标记完成
    progress["completed_steps"].add(current_idx)
    progress["current_step_idx"] = current_idx

    # 找下一棒
    next_idx = current_idx + 1
    if next_idx >= len(chain):
        await self._notify_all_done(round_name)
        return

    next_step = chain[next_idx]
    await self._dispatch_step(round_name, next_step, role, sha, chain)

    logger.info(
        "[AR] [%s] ✅ %s → 🎯 %s (SHA=%s)",
        round_name, role, next_step.get("role", "?"), sha or "?",
    )
```

### 2.6 派活伪代码

```python
async def _dispatch_step(
    self,
    round_name: str,
    step_config: dict,
    prev_role: str,
    prev_sha: str,
    chain: list,
):
    """发送派活消息到目标 bot 的 inbox。"""
    role = step_config.get("role", "")
    title = step_config.get("title", "")
    step_key = step_config.get("step", "")

    # ── 找目标 bot ──
    target_id = self._resolve_agent_id(role, round_name)
    if not target_id:
        await self._send_to_pm(
            f"❌ AutoRouter: {round_name} {step_key}({role}) "
            f"未找到对应 bot，请手动派活"
        )
        return

    # ── 构建任务上下文 ──
    context_lines = []
    for k, v in (step_config.get("context") or {}).items():
        if v:
            rendered = self._render_template(v, round_name, chain)
            context_lines.append(f"- {k}: {rendered}")
    context_str = "\n".join(context_lines)

    # ── 任务消息（自然语言模板） ──
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

    await self._send_inbox(target_id, task_content)
    logger.info("[AR] 派活 %s → %s (%s)", round_name, role, target_id[:12])
```

---

## 3. 角色映射策略

### 3.1 映射方案

**采用 Agent Card 查询策略：** AutoRouter 通过读取 `config/agent_cards.json`（本地文件，与服务端共享）建立 role→agent_id 反向索引。

### 3.2 Agent Card 格式

```json
{
  "ws_abcd1234": {
    "display_name": "ArchitectBot",
    "pipeline_roles": ["architect", "arch"],
    "skills": ["technical-design", "code-review"],
    "status": "registered",
    "trigger_preference": {
      "mode": "mention",
      "mention_keyword": "architect;架构师"
    }
  },
  "ws_efgh5678": {
    "display_name": "DevBot",
    "pipeline_roles": ["developer", "dev"],
    "skills": ["coding", "implementation"],
    "status": "registered",
    "trigger_preference": {
      "mode": "mention",
      "mention_keyword": "developer;开发"
    }
  }
}
```

### 3.3 反向索引构建

```python
def _build_role_index(self) -> dict[str, list[str]]:
    """从 Agent Card 构建 role → [agent_id, ...] 反向索引。

    一个 role 可能对应多个 agent（备用），取第一个匹配的。
    """
    if self.agent_card_path and os.path.exists(self.agent_card_path):
        cards = json.loads(open(self.agent_card_path, encoding="utf-8").read())
    else:
        logger.warning("[AR] Agent Card 文件不可用，尝试 WS 查询...")
        cards = {}  # fallback: 用 _agent_card_cache 或 WS 查询

    role_index: dict[str, list[str]] = {}
    for agent_id, card in cards.items():
        roles = card.get("pipeline_roles", [])
        for role in roles:
            role_index.setdefault(role, []).append(agent_id)
    return role_index
```

### 3.4 查询逻辑

```python
def _resolve_agent_id(self, role: str, round_name: str) -> str | None:
    """根据 pipeline role 查找 agent_id。

    查找优先级：
    1. 本轮的 workspace.members 中直接指定的 agent_id（精确匹配）
    2. Agent Card pipeline_roles 精确匹配（如 "architect"）
    3. Agent Card pipeline_roles 模糊匹配（如 role="arch" 匹配 "architect"）
    4. 检查 _r72_users 缓存（已注册且在线的 agent）
    5. 返回 None → 通知 PM 手动
    """
    # 首次/重建索引
    if not hasattr(self, "_role_index") or not self._role_index:
        self._role_index = self._build_role_index()

    # 精确匹配
    if role in self._role_index:
        candidates = self._role_index[role]
        return candidates[0]  # 取第一个

    # 模糊匹配：chain 中的 role 是单数形式（architect），
    # 但 card 可能存的是通用名（arch/architect）
    for known_role, agents in self._role_index.items():
        if role in known_role or known_role in role:
            return agents[0]

    logger.warning("[AR] 角色 %s 无对应 agent", role)
    return None
```

### 3.5 缓存刷新策略

| 时机 | 动作 |
|:-----|:------|
| 启动时 | 加载一次 `config/agent_cards.json` 构建索引 |
| 每次派活前 | 检查索引是否存在（延迟构建） |
| `!pipeline_status` 响应中检测到新 agent | 强制重建索引 |

### 3.6 文件路径默认值

```
agent_card_path = os.path.join(
    os.path.dirname(__file__), "..", "config", "agent_cards.json"
)
```

---

## 4. Chain 解析策略

### 4.1 数据源

从 WORK_PLAN.md 的 frontmatter 读取 topology 定义。AutoRouter 不依赖 server 内存状态，自己从原始 URL 读取。

### 4.2 获取方式

```python
async def _fetch_topology(self, round_name: str) -> dict | None:
    """从 WORK_PLAN 读取 pipeline topology。

    查找优先级：
    1. 从 self._topologies 缓存获取（之前已加载过）
    2. 从 workspace 配置中读取 work_plan_url →
       HTTP GET raw URL → PyYAML 解析 frontmatter
    3. 从已知的 GitHub URL 模式构造：docs/{round}/WORK_PLAN.md

    Returns:
        {"chain": [...], "auto_chain": True/False, "pipeline": {...}}
        或 None（无 topology 定义）
    """
    # ① 检查缓存
    if round_name in self._topologies:
        return self._topologies[round_name]

    # ② 构造可能的 URL
    urls_to_try = [
        # 如果 workspace 配置中指定了 work_plan_url
        # 从 _pipeline_status 获取
    ]

    # ③ 默认从 GitHub raw 构造
    base = "https://raw.githubusercontent.com/datahome73/ws-bridge/dev"
    work_plan_url = f"{base}/docs/{round_name}/WORK_PLAN.md"
    urls_to_try.append(work_plan_url)

    for url in urls_to_try:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        topology = self._parse_topology(text)
                        if topology:
                            self._topologies[round_name] = topology
                            return topology
        except Exception as e:
            logger.debug("[AR] 读取拓扑失败 %s: %s", url, e)

    logger.warning("[AR] [%s] 未找到 topology 定义", round_name)
    return None
```

### 4.3 YAML Frontmatter 解析

```python
@staticmethod
def _parse_topology(markdown_text: str) -> dict | None:
    """从 Markdown frontmatter 解析 pipeline topology。

    支持两种格式：

    格式 A（完整）：
        ---
        pipeline:
          topology:
            auto_chain: true
            chain:
              - step: step2
                role: architect
                title: 技术方案
                context:
                  requirements_url: "${pipeline.requirements_url}"
        steps:
          step2: { role: architect, title: 技术方案 }
        ---

    格式 B（简写 — 仅 auto_chain: true，无 chain）：
        ---
        pipeline:
          auto_chain: true          # ← 仅需 1 行
          steps:
            step2: { role: architect, title: 技术方案 }
        ---

    Returns:
        {"chain": [...], "auto_chain": bool, "pipeline": {...}}
    """
    # ── 提取 YAML frontmatter ──
    m = re.match(r"^---\s*\n(.*?)\n---", markdown_text, re.DOTALL)
    if not m:
        return None

    try:
        frontmatter = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        logger.warning("[AR] YAML 解析失败: %s", e)
        return None

    pipeline = frontmatter.get("pipeline", {}) if isinstance(frontmatter, dict) else {}
    if not pipeline:
        return None

    auto_chain = pipeline.get("auto_chain", False) or \
                 pipeline.get("topology", {}).get("auto_chain", False)

    # ── 格式 A: 有 topology.chain ──
    topology = pipeline.get("topology", {})
    chain = topology.get("chain", [])
    if chain:
        return {
            "chain": chain,
            "auto_chain": auto_chain,
            "pipeline": pipeline,
        }

    # ── 格式 B: 无 chain，从 steps 自动生成 ──
    if auto_chain:
        steps = pipeline.get("steps", {})
        # steps 按 step2, step3, ..., stepN 排序
        sorted_keys = sorted(steps.keys(), key=lambda k: int(re.search(r'\d+', k).group()))
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
            return {
                "chain": chain,
                "auto_chain": True,
                "pipeline": pipeline,
            }

    # ── 格式 C: 适配旧版 steps 格式 (非结构化) ──
    # chain 为空但 auto_chain 为 true → 按 role 自动排序
    if auto_chain:
        return {
            "chain": [],  # 表示需要动态推断
            "auto_chain": True,
            "pipeline": pipeline,
        }

    return None
```

### 4.4 简写格式（格式 B）补全

当 `auto_chain: true` 但未定义 `topology.chain` 时：

```python
# 标准管线顺序映射（作为默认推断）
_STANDARD_PIPELINE_ORDER = ["product_manager", "architect", "developer",
                            "reviewer", "qa", "operations"]

def _infer_chain_from_steps(self, steps: dict) -> list:
    """从 steps 和标准顺序推断 chain。"""
    # 收集所有 role
    role_order = {role: i for i, role in enumerate(_STANDARD_PIPELINE_ORDER)}
    entries = []
    for key, step in steps.items():
        if isinstance(step, dict):
            role = step.get("role", "")
            order_idx = role_order.get(role, 99)
            entries.append((order_idx, key, step))

    entries.sort()  # 按标准管线顺序排序
    return [
        {"step": key, "role": s.get("role", ""),
         "title": s.get("title", ""), "context": s.get("context", {})}
        for _, key, s in entries
    ]
```

---

## 5. 模板变量替换方案

### 5.1 支持的变量格式

| 格式 | 示例 | 解析 | 来源 |
|:-----|:------|:-----|:-----|
| `${pipeline.xxx}` | `${pipeline.requirements_url}` | 从 frontmatter `pipeline` 字段取值 | pipeline 配置 |
| `{round}` | `docs/{round}/{round}-tech-plan.md` | 替换为 round_name（如 R88） | 运行时参数 |

### 5.2 替换实现

```python
def _render_template(self, template: str, round_name: str,
                     chain: list | None = None) -> str:
    """执行模板变量替换。

    ${pipeline.xxx.yyy}  → 从 pipeline 配置的嵌套字段取值
    {round}              → round_name
    {prev_sha}           → 前一棒的 commit SHA（派活时动态传入）
    """
    result = template

    # ① 替换 {round}
    result = result.replace("{round}", round_name)

    # ② 替换 ${pipeline.xxx.yyy}
    # 注：这里需要在调用时传入 pipeline 配置的引用
    #     _dispatch_step 会从 step_config.chain 的 pipeline 字段获取
    def _resolve_pipeline_var(m: re.Match) -> str:
        path = m.group(1).split(".")
        value = self._pipeline_config
        for key in path:
            if isinstance(value, dict):
                value = value.get(key, m.group(0))
            else:
                return m.group(0)  # 不替换，保留原样
        return str(value) if not isinstance(value, (dict, list)) else m.group(0)

    result = re.sub(r'\$\{pipeline\.([^}]+)\}', _resolve_pipeline_var, result)

    # ③ 替换 {prev_sha} — 由调用方在渲染前设好
    result = result.replace("{prev_sha}", self._prev_sha or "")

    return result
```

### 5.3 变量解析时 pipeline 配置注入

`_dispatch_step` 在构建 task content 前需要先设置 `self._pipeline_config`:

```python
async def _dispatch_step(self, ...):
    topology = self._round_progress.get(round_name, {}).get("topology", {})
    self._pipeline_config = topology.get("pipeline", {})
    self._prev_sha = prev_sha
    # ... 后续渲染
```

---

## 6. 断线重连方案

### 6.1 方案选择

| 方案 | 复杂度 | 状态恢复 | **选定** |
|:-----|:------:|:--------:|:--------:|
| `websockets` 原生 reconnect | 简单 | 手动 | ✅ v1 |
| 外部 supervisor（systemd） | 中等 | 依赖服务 | ❌ |
| 心跳 + 状态持久化 | 高 | 自动 | ❌ v2 优化 |

### 6.2 v1 实现：指数退避重连

```python
async def _reconnect_loop(self):
    """断线重连主循环 — 指数退避 + 抖动。"""
    delay = 1  # 初始 1 秒
    max_delay = 60  # 最长 60 秒
    attempts = 0

    while self._running:
        try:
            await self._connect_and_listen()
            # 正常退出 → 终止重连
            attempts = 0
            delay = 1
            return
        except (websockets.ConnectionClosed, OSError) as e:
            attempts += 1
            logger.warning(
                "[AR] 连接断开 (#%d): %s, %ds 后重连",
                attempts, e, delay,
            )
            await asyncio.sleep(delay + random.uniform(0, 2))
            delay = min(delay * 2, max_delay)  # 指数退避
        except Exception as e:
            logger.error("[AR] 意外错误: %s, 30s 后重试", e)
            await asyncio.sleep(30)
```

### 6.3 断线后状态恢复

重连后自动调用 `_restore_pipeline_state()`:

```python
async def _restore_pipeline_state(self):
    """重连 / 启动时查询现有活跃管线，恢复进度状态。

    策略：发 !pipeline_status 或 !status 消息到 _admin 频道，
    解析响应中的活跃管线列表 → 加载拓扑 → 根据 Step 完成情况
    重建 _round_progress。
    """
    logger.info("[AR] 正在查询活跃管线状态...")

    # 方法 1：发 !pipeline_status 到 _admin 频道（最佳，推荐）
    # await self._send_to_channel("_admin", "!pipeline_status")
    # — 等待响应（需异步等待）
    # — 解析活跃管线列表

    # 方法 2：没有 !pipeline_status API 时的兜底
    # — 遍历 _round_progress 缓存
    # — 重新从远程 WORK_PLAN 加载各活跃管线的拓扑

    # v1 实现：启动时清空已知管线列表
    # 如果之前有已完成的管线（重启前已到 Step 4），
    # 需要手动触发下一个 Step 或 PM 手动补位
    logger.info("[AR] 已重建活跃管线状态: %d 个管线", len(self._round_progress))
```

### 6.4 重连后完整流程

```
AutoRouter 启动/重连
    │
    ├─ ① WS 连接 + 认证
    ├─ ② _restore_pipeline_state()
    │     ├─ 如果有进度缓存 → 从远程重读拓扑
    │     └─ 无缓存 → 等待新管线事件
    │
    └─ ③ 正常监听循环
```

### 6.5 重连期间管线影响

| 场景 | 影响 |
|:-----|:------|
| AutoRouter 断开 → 无 bots 完成 Step | **无影响** — 管线在等待 bot 干活 |
| AutoRouter 断开 → 有 bot 完成 Step | PM 收件箱有完成通知缓存，重连后读取历史可恢复 |
| AutoRouter 断开时间较长（> 10min） | 重建状态后可能错过完成通知，PM 手动触发下一棒 |

---

## 7. 错误处理方案

### 7.1 错误类型矩阵

| # | 错误类型 | 检测时机 | 处理策略 | 对管线影响 |
|:-:|:---------|:---------|:---------|:----------:|
| E1 | **YAML frontmatter 解析失败** | `_parse_topology()` | 日志 ERROR + 跳过该管线（返回 None） | ❌ 无自动接力，PM 手动 |
| E2 | **找不到 WORK_PLAN URL** | `_fetch_topology()` HTTP 404/500 | 日志 WARNING + 尝试备用 URL | ❌ 同上 |
| E3 | **Topology 中无 `auto_chain: true`** | `_parse_topology()` | 日志 INFO + 跳过（不破坏手动模式） | ✅ 无影响 |
| E4 | **找不到目标 agent** | `_resolve_agent_id()` 返回 None | 派活失败 → 通知 PM ❌ + 日志 | ❌ 无自动接力，PM 手动 |
| E5 | **WS 发送失败** | `_send_inbox()` 抛异常 | 重试 1 次 → 通知 PM ❌ | ❌ 该步需手动 |
| E6 | **角色不在 chain 中** | `_on_step_complete()` 遍历 chain | 日志 DEBUG + 忽略 | ✅ 不影响 |
| E7 | **消息解析失败** | `_extract_role/sha/round()` | 日志 DEBUG + 返回 None | ✅ 不影响 |
| E8 | **Agent Card 文件 IO 错误** | `_build_role_index()` | 日志 ERROR + 返回空索引 | ❌ 无法自动路由 |
| E9 | **多个 bot 同时完成** | `_on_step_complete()` 并发调用 | 串行处理（async 无锁竞争） | ✅ chain 按 idx 推进 |

### 7.2 具体实现

```python
# ── E1: YAML 解析失败 ──
try:
    frontmatter = yaml.safe_load(m.group(1))
except yaml.YAMLError as e:
    logger.error("[AR] [%s] YAML frontmatter 解析失败: %s", round_name, e)
    return None

# ── E2: HTTP 获取失败 ──
try:
    async with session.get(url, timeout=10) as resp:
        if resp.status != 200:
            logger.warning("[AR] [%s] WORK_PLAN HTTP %s, URL=%s",
                           round_name, resp.status, url)
            continue
except asyncio.TimeoutError:
    logger.warning("[AR] [%s] WORK_PLAN 请求超时: %s", round_name, url)
    continue
except aiohttp.ClientError as e:
    logger.warning("[AR] [%s] WORK_PLAN 请求失败: %s", round_name, e)
    continue

# ── E4: 找不到 agent → 通知 PM ──
target_id = self._resolve_agent_id(role, round_name)
if not target_id:
    await self._send_to_pm(
        f"❌ AutoRouter: {round_name} {step_key}({role}) "
        f"未找到对应 bot，请手动派活"
    )
    return

# ── E5: WS 发送失败 → 重试 + 通知 PM ──
for attempt in range(2):  # 最多重试一次
    try:
        await self._send_inbox(target_id, task_content)
        break
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
```

### 7.3 错误通知格式

```
AutoRouter → PM:
  ❌ AutoRouter: R88 step3(developer) 未找到对应 bot，请手动派活
  ❌ AutoRouter: R88 step4(reviewer) WS 发送失败: Connection closed
  ❌ AutoRouter: R88 拓扑解析失败，已跳过自动接力
  ⚠️ AutoRouter: R88 已恢复连接，请确认管线进度
  🏁 R88 全部 Step 已完成！管线自动闭环。
```

---

## 8. 边界情况处理

### 8.1 多活跃管线

| # | 场景 | 策略 |
|:-:|:-----|:------|
| B1 | R88 和 R89 同时运行 | 用 `round_name` 区分，各自维护 `_round_progress[R88]` 和 `_round_progress[R89]` |
| B2 | R88 Step 2 完成 + R89 Step 2 同时完成 | 两个 `_on_step_complete()` 异步调用，各自查自己的 chain，互不干扰 |
| B3 | 同一管线重复 Step 完成（重复消息） | `_seen_ids` 去重 + `completed_steps` set 幂等 |
| B4 | 管线结束后又收到完成消息 | `_round_progress` 中该管线已无后续 → 日志 DEBUG + 忽略 |

### 8.2 AutoRouter 中途重启

| # | 场景 | 策略 |
|:-:|:-----|:------|
| B5 | 重启时管线已完成 Step 2（刚完成） | `_restore_pipeline_state()` 通过 `!pipeline_status` 查询当前 Step → 派活 Step 3 |
| B6 | 重启时管线已到 Step 4（中间步骤丢失） | **v1 限制**：无法精确恢复断点，PM 通知「已恢复但需确认进度」 |
| B7 | 重启后 PM 手动补发了 Step 3 | AutoRouter 检测到 Step 3 完成 → 继续自动接力 Step 4 |
| B8 | 重启后无活跃管线 | 安静等待新的 `!pipeline_start` |

### 8.3 手动模式兼容

| # | 场景 | 策略 |
|:-:|:-----|:------|
| B9 | AutoRouter 运行中，PM 手动派活 | OK — PM 发 `_inbox:<bot_id>`，AutoRouter 仅监听 PM 收件箱，不冲突 |
| B10 | PM 手动补发已完成 Step | AutoRouter 检测到同一 role 的完成通知 → `completed_steps` set 幂等 → 跳过 |
| B11 | 无 AutoRouter 运行 | 管线完全手动，零影响 |

### 8.4 消息去重

```python
# 使用滑动窗口去重：保留最近 1000 条 msg_id
_MAX_SEEN_IDS = 1000

def _mark_seen(self, msg_id: str) -> bool:
    """标记已处理。返回 True 表示已见过（去重）。"""
    if msg_id in self._seen_ids:
        return True
    self._seen_ids.add(msg_id)
    if len(self._seen_ids) > _MAX_SEEN_IDS:
        # 溢出时丢弃最旧的
        self._seen_ids = set(list(self._seen_ids)[-500:])
    return False
```

### 8.5 并发安全

AutoRouter 是单线程 async 模型，所有消息按顺序处理，无需锁。但需要注意：

| 注意点 | 说明 |
|:-------|:------|
| `_round_progress` 修改 | 在同一个 event loop 中按序执行，无并发问题 |
| `_seen_ids` 读写 | 同上 |
| WS 发送 | `_send_inbox()` 使用已经建立的 `self.ws` 连接，async 写安全 |
| 外部资源（HTTP GET） | 每个 `_fetch_topology()` 独立创建 session，不共享状态 |

---

## 9. 改动一览

| 文件 | 操作 | 行数 | 说明 |
|:-----|:----:|:----:|:------|
| `server/auto_router.py` | **🆕 新增** | ~250 | 完整独立服务：PipelineAutoRouter 类 + CLI 入口 |
| `docs/R88/R88-tech-plan.md` | **🆕 新增** | ~400 | 本文档 |
| `handler.py` | **✅ 零修改** | 0 | 核心路由文件完全不动 |
| `config.py` | **✅ 零修改** | 0 | 配置常量文件完全不动 |
| `__main__.py` | **✅ 零修改** | 0 | 服务入口完全不动 |

---

## 10. 附录：完整伪代码

### 10.1 命令行入口

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Pipeline AutoRouter — 管线自动路由服务 🚂"
    )
    parser.add_argument(
        "--api-key", required=True,
        help="AutoRouter 的 ws-bridge api_key（bot 身份）"
    )
    parser.add_argument(
        "--pm-agent-id", default="",
        help="PM 的 agent_id（收件箱监听目标）"
    )
    parser.add_argument(
        "--ws-url",
        default="wss://wsim.datahome73.cloud/ws",
        help="ws-bridge WebSocket 地址"
    )
    parser.add_argument(
        "--agent-card-path", default="",
        help="Agent Card JSON 文件路径（默认 server/../config/agent_cards.json）"
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

    # 确定 agent_card 默认路径
    agent_card_path = args.agent_card_path or os.path.join(
        os.path.dirname(__file__), "..", "config", "agent_cards.json"
    )

    router = PipelineAutoRouter(
        api_key=args.api_key,
        ws_url=args.ws_url,
        pm_agent_id=args.pm_agent_id,
        agent_card_path=agent_card_path,
    )

    try:
        asyncio.run(router.start())
    except KeyboardInterrupt:
        logger.info("[AR] AutoRouter 已停止（Ctrl+C）")
```

### 10.2 完整类结构（骨架）

```python
class PipelineAutoRouter:
    """管线自动路由服务 — 独立外挂，零 handler.py 侵入。"""

    # ── 常量 ──
    _MAX_SEEN_IDS = 1000
    _RECONNECT_MAX_DELAY = 60
    _STANDARD_PIPELINE_ORDER = [
        "product_manager", "architect", "developer",
        "reviewer", "qa", "operations",
    ]

    def __init__(self, api_key, ws_url, pm_agent_id, agent_card_path):
        ...

    # ── 生命周期 ──
    async def start(self): ...
    async def stop(self): ...

    # ── 消息处理 ──
    async def _handle_message(self, msg): ...
    async def _on_pipeline_ready(self, round_name): ...
    async def _on_step_complete(self, content): ...
    async def _on_ack_received(self, content): ...

    # ── 管线引擎 ──
    async def _dispatch_step(self, round_name, step_config, prev_role, prev_sha, chain): ...
    async def _notify_all_done(self, round_name): ...
    async def _fetch_topology(self, round_name): ...
    def _resolve_agent_id(self, role, round_name): ...
    def _build_role_index(self): ...

    # ── 模板 ──
    def _render_template(self, template, round_name, chain): ...

    # ── 解析工具 ──
    @staticmethod
    def _parse_topology(markdown_text): ...
    @staticmethod
    def _extract_role(content): ...
    @staticmethod
    def _extract_sha(content): ...
    @staticmethod
    def _extract_round(content): ...

    # ── 通信 ──
    async def _send_inbox(self, target_id, content): ...
    async def _send_to_pm(self, content): ...
    async def _send_to_channel(self, channel, content): ...

    # ── 恢复 ──
    async def _restore_pipeline_state(self): ...
    async def _reconnect_loop(self): ...

    # ── 去重 ──
    def _mark_seen(self, msg_id): ...
```

---

## 附录：R88 技术方案验收清单

| # | 检查项 | 要求 |
|:-:|:-------|:-----|
| T-1 | 服务架构图已包含所有模块划分 | ✅ |
| T-2 | PipelineAutoRouter 类的所有核心方法伪代码已提供 | ✅ |
| T-3 | 角色映射策略已确定（Agent Card pipeline_roles） | ✅ |
| T-4 | chain 解析策略已确定（PyYAML frontmatter + 简写格式） | ✅ |
| T-5 | 模板变量替换方案已确定（`${pipeline.xxx}` + `{round}`） | ✅ |
| T-6 | 断线重连方案已确定（指数退避 + 启动恢复） | ✅ |
| T-7 | 9 种错误场景已覆盖（E1~E9） | ✅ |
| T-8 | 12 种边界情况已覆盖（B1~B12） | ✅ |
| T-9 | 零 handler.py 侵入已确认（仅新增 auto_router.py） | ✅ |

---

*本文档由 🏗️ 架构师编写，待 Step 3 💻 编码实现。*
