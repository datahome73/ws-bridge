# R110 — 自动派活：零手工启动管线 🚀

> **版本：** v1.0
> **日期：** 2026-07-13
> **状态：** 📝 需求文档
> **轮次：** R110
> **优先级：** P0（自动派活冲刺）
> **前置条件：** R109 全闭环已上线 ✅

---

## 一、背景

### 1.1 派活层次

当前 ws-bridge 管线派活有四个层次：

| 层次 | 名称 | 说明 | 现状 |
|:----:|:-----|:-----|:----:|
| 1 | TG 中转派活 | PM 通过 Telegram 转发消息到 bot | ❌ 已废弃 |
| 2 | 手工直透派活 | PM 直接向 bot 的 `_inbox` 发 WS 消息 | 🔧 可用但需手动 |
| 3 | Server 中介派活 | PM 发 `_inbox:server`，server 中继转发到目标 bot | ✅ 已实现（R87） |
| **4** | **自动派活** | **无需人工触发，系统自动检测→创建管线→派活** | ⬜ **目标** |

### 1.2 当前瓶颈

R107-R109 已完成 **Step 2→6 的自动链路**（AutoRouter + `_auto_dispatch`），但 **Step 1（管线启动 + PM 审核）仍是手工**：

```
当前流程:
  [PM 写需求文档] → 手动 push dev
    → 手动创建 PipelineContext (scripts/r109_auto.py)
    → 手动发 _admin 命令 (!pipeline_start)
    → 手动发 "已完成 ✅ R{N} Step 1" 信号
    → ✅ **从此自动：** 小开→爱泰→小周→泰虾→小爱
      (AutoRouter 自动派活 Step 2~6)
```

**核心瓶颈：** 从「需求文档推 dev」到「Step 2 自动派活」之间，PM 需 3 次手工操作（创建上下文 + 启动管线 + 确认 Step 1）。

### 1.3 R110 目标

**消灭这 3 次手工操作。** 从「需求文档推 dev」直达「自动派活 Step 2」。

---

## 二、架构方案

### 2.1 总体流程（目标）

```
R110 新流程:
  [PM 写需求文档] → push dev (推完即完)
    ↓
  ① Git Watcher 检测到新 docs/R{N}/WORK_PLAN.md + 需求文档
    ↓
  ② Auto-Create PipelineContext (从 frontmatter 解析)
    ↓
  ③ Auto-Start Pipeline (等效 !pipeline_start)
    ↓
  ④ Auto-Dispatch Step 1 给 PM Bot (小谷)
    ↓
  [PM 审核文档，回复 "✅ 完成"]
    ↓
  ⑤ ✅ **现有 AutoRouter 接管：** 小开→爱泰→小周→泰虾→小爱
```

**PM 唯一的手工操作：** 写需求文档 + push dev。其余全自动。

### 2.2 派活层次演进

| 轮次 | 层次 | 描述 |
|:----:|:----:|:------|
| R87 | Level 3 | `_inbox:server` 中继 |
| R88 | Level 3 | AutoRouter 独立服务 |
| R97 | Level 3 | PipelineContext 驱动自动派活 |
| **R110** | **Level 4** | **Git Watcher 零手工启动 → 全自动派活** |

### 2.3 组件

R110 新增 **一个核心组件** + **修改一个现有组件**：

#### 2.3.1 新增：`PipelineAutoStarter`（`ws-server/pipeline_auto_starter.py`）

Git 感知组件，职责单一：
1. **定期 `git fetch origin dev`**（可配置间隔，默认 60s）
2. **检测 `docs/` 目录**，寻找新出现的 `R{N}/` 子目录
3. **验证**目录包含 `R{N}-product-requirements.md` + `WORK_PLAN.md`
4. **解析 WORK_PLAN.md frontmatter**：轮次名、auto_chain、角色映射、Step 定义
5. **调用 PipelineContextManager.create()** 自动创建上下文
6. **自动启动管线**（内部调用 `_cmd_pipeline_start` 等效逻辑）
7. **自动派活 Step 1 给 PM Bot**
8. **记录已检测轮次**（防重复触发）

#### 2.3.2 修改：`PipelineContextManager.create()` — 支持 frontmatter 驱动

当前 `PipelineContext.create()` 需要调用方传入完整参数。R110 增加：
- `from_work_plan(path: str) -> PipelineContext` **工厂方法**
- 解析 WORK_PLAN.md YAML frontmatter → 自动填充 `round_name`, `steps`, `role_agent_map`, `message_templates`, `references`
- 兼容手工创建（现有调用方不受影响）

### 2.4 消息模板自动生成

当前每个 WORK_PLAN.md 需要在 `scripts/r109_auto.py` 硬编码 `message_templates`。
R110 改为 **模板自动生成规则**：

| Step | 角色 | 模板规则 |
|:----:|:-----|:---------|
| 1 | pm | "📋 **R{round} Step 1 — PM 审核**\n\n需求文档已就绪：{requirements_url}\n\n请审核后回复 ✅ 完成" |
| 2 | arch | "🏗️ **R{round} Step 2 — 技术方案**\n\n需求文档：{requirements_url}\nWORK_PLAN：{work_plan_url}\n\n请输出技术方案文档，推 dev 后回复 ✅ 完成" |
| 3 | dev | "💻 **R{round} Step 3 — 编码实现**\n\n技术方案：{tech_plan_url}\n\n按方案实现，推 dev 后回复 ✅ 完成" |
| 4 | review | "🔍 **R{round} Step 4 — 代码审查**\n\n审查 Step 3 改动。通过后回复 ✅ 完成" |
| 5 | qa | "🧪 **R{round} Step 5 — 测试验证**\n\n验证验收标准。全部通过后回复 ✅ 完成" |
| 6 | ops | "🚀 **R{round} Step 6 — 合并部署归档**\n\nPR dev→main，重建镜像，部署。完成后回复 ✅ 完成" |

模板中 `{tech_plan_url}` 自动构造为 `https://github.com/datahome73/ws-bridge/blob/main/docs/R{round}/r{round}-step2-tech-plan.md`。

### 2.5 WORK_PLAN.md frontmatter 格式（兼容现有）

当前 frontmatter 已足够解析，R110 新增可选字段：

```yaml
# 现有字段（保持不变）
> **轮次：** R110
> **auto_chain:** true
> **说明：** 自动派活零手工启动
> **角色映射：** pm=小谷, arch=小开, dev=爱泰, review=小周, qa=泰虾, ops=小爱

# R110 新增 — 自动检测就绪信号（可选）
> **auto_start:** true
> **trigger_on_push:** true
```

- `auto_start: true` — 显式标记此轮次允许自动启动
- `trigger_on_push: true` — 检测到 push 即触发（默认行为）
- 不写 `auto_start` 或设为 `false` → Watcher 忽略此轮次（兼容手工启动场景）

---

## 三、实现方案

### 3.1 PipelineAutoStarter 详细设计

```python
class PipelineAutoStarter:
    """
    Git 感知的管线自动启动器。
    
    职责范围极窄：
    - 定期 git fetch + 检查 docs/ 新目录
    - 发现新轮次 → 调用 PipelineContextManager.create()
    - 启动管线
    - 记录已处理轮次（防重复）
    """

    # ── 配置（可环境变量覆写）──
    POLL_INTERVAL: int = 60          # 秒，检查间隔
    DOCS_DIR: str = "docs"           # 相对于 REPO_PATH
    REMOTE_BRANCH: str = "origin/dev"
    
    def __init__(self, repo_path: str, data_dir: str, pm_agent_id: str):
        self._repo_path = repo_path
        self._data_dir = Path(data_dir)
        self._pm_agent_id = pm_agent_id
        self._processed: set[str] = set()   # 已处理轮次，启动时从已存在 PipelineContext 恢复
        self._running = False
    
    async def start(self):
        """启动轮询循环。"""
        self._running = True
        self._init_processed_from_existing_contexts()
        while self._running:
            try:
                await self._poll()
            except Exception as e:
                logger.warning("[PAS] Poll error: %s", e)
            await asyncio.sleep(self.POLL_INTERVAL)
    
    async def stop(self):
        self._running = False
    
    async def _poll(self):
        """一次轮询周期。"""
        # 1. git fetch 获取远程最新
        await self._git_fetch()
        # 2. 扫描 docs/ 目录
        new_rounds = self._scan_new_rounds()
        for round_name, work_plan_path in new_rounds:
            await self._auto_start_pipeline(round_name, work_plan_path)
    
    def _scan_new_rounds(self) -> list[tuple[str, str]]:
        """扫描 docs/ 中新出现的 R{N}/WORK_PLAN.md。
        
        条件：
        - 目录名匹配 R{数字}
        - 已推送到 origin/dev（通过 git ls-tree 检查）
        - 目录包含 WORK_PLAN.md + {同名}-product-requirements.md
        - 不在 _processed 中
        - WORK_PLAN.md frontmatter 含 auto_start: true（可选）
        """
        pass
    
    async def _auto_start_pipeline(self, round_name: str, work_plan_path: str):
        """为发现的新轮次自动启动管线。
        
        1. 解析 WORK_PLAN.md frontmatter
        2. 从 Agent Card 解析角色→agent_id 映射
        3. 调用 PipelineContextManager.create()
        4. 设置状态为 RUNNING
        5. 生成 message_templates
        6. 派活 Step 1 给 PM bot
        7. 记录到 _processed
        """
        pass
```

### 3.2 PipelineContextManager 兼容性

```python
# 新增工厂方法
@classmethod
def from_work_plan(
    cls,
    work_plan_path: str,
    repo_path: str,
    pm_agent_id: str,
) -> "PipelineContext":
    """从 WORK_PLAN.md 文件创建 PipelineContext。
    
    解析 frontmatter：
      - 轮次名 → round_name
      - 角色映射 → role_agent_map
      - Step 定义 → steps / total_steps
      - auto_chain → R107 行为启用
    
    自动生成：
      - message_templates（见 §2.4 模板规则）
      - references（需求文档 / WORK_PLAN URL）
      - task_dir（workspace_dir / pipeline_tasks / {round_name}）
    """
    ...
```

### 3.3 WORK_PLAN 文件结构约定

```
docs/
├── R110/
│   ├── R110-product-requirements.md     ← 需求文档（必须）
│   ├── WORK_PLAN.md                     ← 管线定义（必须）
│   ├── r110-step2-tech-plan.md          ← 技术方案（Step 2 产出）
│   ├── r110-step3-code-review.md        ← 审查报告（Step 4 产出）
│   └── r110-step5-test-report.md        ← 测试报告（Step 5 产出）
```

**自动检测条件：**
- 目录名 `R{N}` 匹配
- 同时存在 `R{N}-product-requirements.md` + `WORK_PLAN.md`
- 都已在 `origin/dev` 分支存在（通过 `git ls-tree` 验证）
- 前端 frontmatter 中 `auto_start: true`（或前台默认允许）

### 3.4 与现有 AutoRouter 的关系

```
PipelineAutoStarter (R110 新增)
    │
    │  检测新轮次 → 创建 PipelineContext → 启动管线 → 派活 Step 1
    │
    ▼
Bot 回复 "✅ 完成" (Step 1)
    │
    ▼
_handle_server_relay → _try_advance_pipeline → _auto_dispatch (已有)
    │
    ▼
Step 2~6 自动推进 (已有，R107)
```

**`PipelineAutoStarter` 和 `AutoRouter`（`auto_router.py`）职责分离：**

| 组件 | 职责 | 激活条件 |
|:-----|:------|:---------|
| `PipelineAutoStarter` | 发现新轮次 → 创建管线 | Git 有新的 R{N}/WORK_PLAN.md |
| `_auto_dispatch`（main.py 内联） | Step N 完成后派活 Step N+1 | Bot 回复 "✅ 完成" |
| `auto_router.py` | 可选：独立外挂，超时检测 | 如需独立超时检测功能 |

**R110 不依赖 `auto_router.py`（已禁用），完全复用 `_auto_dispatch` 内联逻辑。**

### 3.5 防重复与安全

| 机制 | 说明 |
|:-----|:------|
| `_processed` 集 | 已处理的轮次不入第二次 |
| 从已有 PipelineContext 恢复 | 重启时扫描已有上下文，跳过已存在的轮次 |
| `auto_start` 标记 | WORK_PLAN.md 可选字段，不标记的不自动启动 |
| `git ls-tree` 验证 | 文件必须在 `origin/dev`，防止半推的文件触发 |
| 同一轮次只启动一次 | PipelineContextManager.create() 对重复轮次抛出 `ValueError` |

---

## 四、执行计划

### Step 1 — 实现 `PipelineAutoStarter`

1. 新建 `ws-server/pipeline_auto_starter.py`
2. 实现 `PipelineAutoStarter` 类（~200 行）
   - `_git_fetch()` — 执行 `git fetch origin dev`
   - `_scan_new_rounds()` — 扫描 `docs/` 新目录
   - `_parse_work_plan()` — 解析 frontmatter
   - `_auto_start_pipeline()` — 创建上下文 + 启动管线 + 派活 Step 1
3. 在 `ws-server/__main__.py` 中注册：作为 asyncio task 启动

### Step 2 — 实现 `from_work_plan` 工厂方法

1. 在 `pipeline_context.py` 中新增 `@classmethod`
2. 实现 frontmatter 解析（YAML/regex）
3. 实现模板自动生成
4. 实现角色映射（从 Agent Card 或 frontmatter）

### Step 3 — `WORK_PLAN.md` frontmatter 扩展

1. 支持 `auto_start: true/false`
2. 兼容现有 frontmatter 格式

### Step 4 — 测试

### Step 5 — 部署

---

## 五、验收标准

### 5.1 自动检测与启动

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 1 | 推 `docs/Rxxx/WORK_PLAN.md` + 需求文档到 dev 后，60s 内自动创建 PipelineContext | 检查 `pipeline_contexts.json` 有 Rxxx 条目 |
| 2 | PipelineContext 的 step/role 正确解析自前 frontmatter | `round_name=Rxxx, total_steps=6` |
| 3 | 自动启动管线（状态 `RUNNING`） | `ctx.status == running` |
| 4 | 重复 push 同一轮次不重复创建 | 第二次 push → 无新上下文 |
| 5 | 重启服务后不重新处理已有轮次 | 重启后 `_processed` 从已有上下文恢复 |
| 6 | 缺少 `auto_start` 标记的轮次不自动启动 | WORK_PLAN.md 无 `auto_start` → 跳过 |
| 7 | `git ls-tree` 验证失败（文件不在 remote）不触发 | 本地半推文件 → 静默跳过 |

### 5.2 自动派活

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 8 | Step 1 自动派活到 PM bot（小谷） | 小谷 inbox 收到 Step 1 审核消息 |
| 9 | Step 1 消息内容包含需求文档链接 + 审核指引 | 消息含 `{requirements_url}` |
| 10 | PM 回复 "✅ 完成" → 自动推进 Step 2 | Step 2 派活到小开 |
| 11 | Steps 2→6 全链路自动（与 R107 一致） | 管线自动执行至部署 |

### 5.3 安全与稳定性

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 12 | `git fetch` 超时/失败不阻塞 | 网络断开时静默跳过本轮 poll |
| 13 | WORK_PLAN.md 格式异常 → 跳过并日志告警 | 非法 frontmatter → log warning |
| 14 | 与现有 `!pipeline_start` 命令共存 | 手工启动仍可用 |

---

## 六、风险与缓解

| 风险 | 缓解 |
|:-----|:------|
| Git poll 间隔太长（60s）导致派活延迟 | 可配置 `PAS_POLL_INTERVAL` 环境变量 |
| `git fetch` 与手动 git 操作冲突 | 只读 fetch，不 push，不 merge |
| WORK_PLAN.md frontmatter 解析不稳定 | 严格解析 + 异常跳过 + 日志告警 |
| 自动启动后 PM 未及时回复 Step 1 | 现有 Step 超时检测（`_STEP_TIMEOUT`）自动告警 |
| 与 `auto_router.py` 独立服务冲突 | R110 不依赖 `auto_router.py`，`_auto_dispatch` 内联足够 |

---

## 七、关于「自动派活」的范围定义

R110 的自动派活范围：

| 步骤 | 组件 | 自动程度 | 说明 |
|:----:|:-----|:--------:|:-----|
| 检测新需求 | `PipelineAutoStarter` | ✅ 全自动 | Git poll 检测 |
| 创建上下文 | `PipelineContextManager` | ✅ 全自动 | Frontmatter → Context |
| 启动管线 | `_cmd_pipeline_start` 等效 | ✅ 全自动 | 无命令需要 |
| Step 1 派活 | `_auto_dispatch` | ✅ 全自动 | 派到 PM bot inbox |
| Step 1 审核 | PM（人） | ❌ 需人工 | PM 审核需求文档 |
| Step 1 ✅ 完成 | PM（人） | ❌ 需人工 | 发 "✅ 完成" |
| Step 2~6 | `_auto_dispatch` | ✅ 全自动 | 已有逻辑 |

> ⚡ **为什么 Step 1 审核保留人工？** 需求文档审核是 PM 的核心职责，涉及对开发范围的判断、优先级确认，无法完全自动化。R110 将其从 3 次手工操作降为 **1 次（审核回复）**，已是量级飞跃。

**后续 R111+ 可以考虑：**
- Step 1 自动化（需求质量自动检查 + 自动通过）
- 异常自动恢复（超时自动重派、失败自动跳步）
- 多轮并行管线

---

## 八、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-13 | 初稿 — 自动派活 R110 需求文档 🚀 |
