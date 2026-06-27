# R45 产品需求 — R44 验证 + 测试标签前缀修复

> **版本：** v0.1（草稿，待项目负责人审核）
> **状态：** 📋 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-06-27
> **本轮改动范围：** 🟢 验证（无代码改动）+ 方向 A 仅第①类（服务器代码 `server/handler.py`）

---

## 1. 问题背景

### 1.1 R44 已完成但未经实战验证

R44 修复了两处管线入口断点：

| 断点 | R44 修复 | 测试方法 | 验证结果 |
|:-----|:---------|:---------|:--------:|
| **F-12** — PM 无法直接触发 `!pipeline_start` | `_can_broadcast` _admin 放开 + permission 白名单 + 自动 `--from step2` | 代码级 + 单元测试 | 🟢 16/16 |
| **F-13** — 工作区自动填充开发成员 | `_cmd_pipeline_start` 自动从 `auth.get_users()` 收集角色成员加入工作区 | 代码级 + 单元测试 | 🟢 16/16 |

但**代码测试与生产环境实战之间存在差距**：

1. 代码级测试验证了三处改动（`_can_broadcast`、`_check_command_permission`、`_cmd_pipeline_start`）各自独立正确，但**未验证端到端链路**：TG DM → Gateway → ws-bridge `_admin` 频道 → 管线启动 → 工作区创建 → 成员填充 → 点名成功
2. 网关侧（Hermes Gateway adapter）的路由逻辑在代码测试中未覆盖——PM 从 TG DM 发的 `!pipeline_start R45` 是否能被 adapter 正确拦截并路由到 `_admin` 频道？
3. adapter 侧的 `permission` 白名单实现与 handler.py 中的 `_can_broadcast` / `_check_command_permission` 改动耦合——上层不认识新路由就会拦住

> "实战验证过的才是真的修好了" — 项目负责人过往反馈

### 1.2 测试标签与前缀匹配冲突（F-4）

在 R43/R44 的开发过程中，测试人员按标准流程发送 `[R{N}测试]` 前缀的消息来标记测试流量。但当测试消息需要带前缀指令时（如 `📢` 公告），**两种前缀的冲突暴露**：

```
当前行为（❌）：
  发送：「[R45测试] 📢 全体注意，管线启动验证开始」
  → content 以「[」开头 → startswith("📢") 不匹配
  → 在 lobby 中被判为 'plain' 消息被拒绝 ❌
  → 在 workspace 中正常广播但失去了 📢 语义

期望行为（✅）：
  发送：「[R45测试] 📢 全体注意，管线启动验证开始」
  → 系统识别 📢 前缀（无论测试标签在其前还是后）
  → 正常执行 📢 管理员广播逻辑
```

**对验证轮的影响：** 本轮 R45 的核心目标是验证 R44 管线启动链路，验证过程会产生大量测试消息。如果这些带 `[R45测试]` 标签的测试消息在 lobby 中因前缀不匹配被拒绝，轮次推进效率将大打折扣。

### 1.3 可用基础

| 已有能力 | 状态 | 说明 |
|:---------|:----:|:------|
| `!pipeline_start` 命令（含 F-12+F-13 修复） | ✅ | 已合并 main，生产环境已部署 |
| `_admin` 频道 | ✅ | 常驻，可用于测试命令路由 |
| `_classify_lobby_message()` | ✅ | handler.py 中前缀分类函数 |
| `PREFIX_ANNOUNCE / PREFIX_CHECKIN / PREFIX_HELP` | ✅ | 前缀常量定义 |
| 生产环境 WebSocket 入口 | ✅ | ws://72.62.197.200:8765/ws（开发）/ ws://72.62.197.200/ws（nginx） |
| Web 端聊天室 | ✅ | 可实时观察 `_admin` 频道消息 |

### 1.4 不是问题的情况

- `!pipeline_start` 在 `_admin` 频道由 admin-bot 手动执行 → ✅ 已知可行
- 不带测试标签的普通 `📢` 消息 → ✅ 前缀匹配正常
- 在 workspace 中发送 `[R{N}测试]` 普通文本 → ✅ 正常广播（仅 lobby 分类受影响）

---

## 2. 预期体验

### 2.1 验证 Phase

PM 从 TG DM 发送 `!pipeline_start R45`，预期：

```
PM(TG DM) → 发「!pipeline_start R45」
  ↓ (1-2s)
Gateway adapter: 识别命令 → 路由到 ws-bridge _admin 频道
  ↓ (<1s)
handler.py _ADMIN_COMMANDS: 白名单检查通过 → _cmd_pipeline_start 执行
  ↓
创建工作室 R45-dev → 自动收集角色成员 → 点名 arch-bot + 附上下文 → 创建 Step Task
  ↓ (3-5s)
PM 收到成功反馈：「🚀 R45 管线已启动 / Step: step2 → arch / 工作室: __R45_WS / ...」
```

### 2.2 F-4 修复后

```
发送：「[R45测试] 📢 全体注意，管线启动验证开始」
  ↓
_classify_lobby_message()：识别内容中含「📢」→ 类型 'announce' ✅
admin 检查：发送者角色为 admin → 允许
  ↓
正常路由到所有在线 bot + Web 端显示「📢 [R45测试] 全体注意...」
```

测试标签也可以放在前缀之后，两种顺序都支持：

| 发送内容 | 当前行为 | 期望行为 |
|:---------|:---------|:---------|
| `[R45测试] 📢 大家好` | ❌ plain 被拒 | ✅ announce |
| `📢 [R45测试] 大家好` | ✅ announce | ✅ announce（不变） |
| `[R45测试] @arch-bot 开始干活` | ❌ plain 被拒 | ✅ mention |
| `[R45测试] 📋 @all` | ❌ plain 被拒 | ✅ checkin |

> 技术方案（具体前缀匹配逻辑如何调整）由架构师决定。

---

## 3. 需求详述

### 方向 A — 测试标签前缀兼容（F-4 修复） 🟢 P3

修复 `_classify_lobby_message()` 和 `handle_broadcast()` 中的前缀匹配，使消息内容中任意位置出现 `📢` / `📋` / `🆘` 前缀时均能被正确识别。

#### 用户旅程

```
用户发送：「[R45测试] 📢 管线启动验证」
  ↓ 当前行为
content.startswith("📢") → False → 继续检查下一个
content.startswith("📋") → False
content.startswith("🆘") → False
无 @mention → return 'plain', [] → 被拒绝 ❌

  ↓ 期望行为
内容中含「📢」→ 即使前面有 [R{N}测试] 标签
    → 类型 'announce' ✅
    → 后续 admin 角色检查照常
    → 正常推送 + 写入 chat log
```

#### 具体需求

| # | 需求 | 优先级 |
|:-:|:-----|:------:|
| A-1 | 在 `_classify_lobby_message()` 中，如果内容以测试标签（`[R{N}测试]`）开头，在标签之后再次检查 `📢` / `📋` / `🆘` 前缀 | 🟢 P3 |
| A-2 | `handle_broadcast()` 中的 admin 权限检查（`content.startswith("📢")` at line 1539）同样适应测试标签前置的情况 | 🟢 P3 |
| A-3 | 向后兼容：无测试标签的消息不受影响 | 🟢 P3 |
| A-4 | 测试标签放在前缀之后（如 `📢 [R45测试]`）继续正常工作，不退化 | 🟢 P3 |

#### 实现说明

当前 `_classify_lobby_message()` 按固定顺序检查 `startswith`：

```python
def _classify_lobby_message(content: str) -> tuple[str, list[str]]:
    content = content.strip()
    if content.startswith(PREFIX_ANNOUNCE):
        return 'announce', []
    if content.startswith(PREFIX_CHECKIN):
        ...  # 同上
```

方向 A 需要：先 strip 测试标签前缀（`[R{N}测试] `），再检查原始前缀。或改用 `in` 或 `find` 判断内容中是否包含前缀 emoji。

**设计约束：** 不应改变现有的 lobby 消息类型枚举（`'announce' / 'checkin' / 'help' / 'mention' / 'plain'`），只扩展匹配逻辑。

> 技术方案（具体实现——strip 标签再 match / 改用 find / 或其他方案）由架构师决定。

---

## 4. 架构原则

### 4.1 验证与开发解耦

本轮包含两个独立环节：

| 阶段 | 性质 | 代码改动 | 前置条件 |
|:-----|:-----|:---------|:---------|
| **Phase V — 验证** | 🟡 条件性验证 | 无代码改动，仅实战测试 | 生产环境可达 |
| **Phase F — 修复 F-4** | 🟢 确定性开发 | 仅 `handler.py` 中 `_classify_lobby_message()` + 相关路由 | Phase V 验证通过（可选） |

两个阶段可并行，无依赖关系。

### 4.2 纯服务端系统层

方向 A（F-4 修复）涉及的前缀匹配逻辑全部在服务端系统层（`handler.py`）完成，不涉及 AI/LLM 判断，不占用 token。

### 4.3 向后兼容

- 无测试标签的消息：行为不变
- 测试标签在后（`📢 [R45测试] xxx`）：行为不变
- admin `📢` 权限检查逻辑不变
- 非 lobby 频道（workspace / _admin / registration）：不受影响

---

## 5. 验收标准

### Phase V — R44 实战验证

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| V-1 | PM 从 TG DM 发送 `!pipeline_start R45` 后，在 <10s 内收到 `🚀 R45 管线已启动` 反馈 | 🔴 P1 |
| V-2 | 管线启动输出显示工作室名（`R45-dev`）、Step 2（技术方案）、目标角色（arch） | 🟡 P2 |
| V-3 | `auth.get_users()` 中所有开发角色（arch/dev/review/qa/admin）均被自动加入工作区 | 🟡 P2 |
| V-4 | `!pipeline_status` 显示 R45 管线为活跃状态，当前 Step = step2 | 🟡 P2 |
| V-5 | 非 `pipeline_start` 的 `!` 命令（如 `!create_workspace`）不被错误路由到 `_admin` 频道 | 🟡 P2 |
| V-6 | 测试完成后，PM 可关闭管线 (`!step_complete Step6`) 或清理工作区 | 🟢 P3 |

### 方向 A — 测试标签前缀兼容

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| A-1 | `[R45测试] 📢 xxx` 在 lobby 中被标记为 'announce' 类型（不走 plain 拒绝） | 🟢 P3 |
| A-2 | `[R45测试] 📋 @xxx` 在 lobby 中被标记为 'checkin' 类型 | 🟢 P3 |
| A-3 | `[R45测试] 🆘 xxx` 在 lobby 中被标记为 'help' 类型 | 🟢 P3 |
| A-4 | `[R45测试] @arch-bot xxx` 在 lobby 中被标记为 'mention' 类型 | 🟢 P3 |
| A-5 | `📢 [R45测试] xxx` 继续正常工作（测试标签在后的场景不退化） | 🟢 P3 |
| A-6 | 无测试标签的消息分类不受影响，回归通过 | 🟢 P3 |

---

## 6. 不纳入本轮需求

| 事项 | 原因 |
|:-----|:------|
| F-3 P3 角色体系 | 独立功能轮，本轮专注验证 + F-4 小修复 |
| F-9 Web 端 Tab 加载空白 | 🔴 P0 但待定位，需独立调查轮 |
| F-5/F-6 工作室管理能力/面板 | 独立方向，非验证轮范畴 |
| R36-B/C 注册流程 | 较大功能方向，需独立调研和决策 |
| L-4/D-3/D-4 文档清理 | 文档类工作，可独立排入后续轮次 |
| Web 端 Android APK 封装 | 第④类，本轮只改第①类 |

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v0.1 | 2026-06-27 | 初稿 — R45 验证轮：R44 实战验证 + F-4 测试标签前缀兼容修复 |
