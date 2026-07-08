---
pipeline:
  name: "R78 全局变量迁移补完"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R78/WORK_PLAN.md"

  workspace:
    name: R78-dev
    members:
      - name: 架构师
        role: architect
      - name: 开发工程师
        role: developer
      - name: 审查工程师
        role: reviewer
      - name: 测试工程师
        role: qa
      - name: 项目管理
        role: admin

  steps:
    - step: 2
      role: architect
      task: 技术方案
    - step: 3
      role: developer
      task: 编码实现
    - step: 4
      role: reviewer
      task: 代码审查
    - step: 5
      role: qa
      task: 测试验证
    - step: 6
      role: admin
      task: 合并部署

  timeout_minutes: 60
---

# R78 工作计划 — 全局变量迁移补完：角色映射 + ACK 状态统一管理 📐

> **版本：** v1.0（初稿）
> **状态：** 📝 待审核
> **项目协调人：** 🧐 PM
> **基于需求文档：** [docs/R78/R78-product-requirements.md](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R78/R78-product-requirements.md) v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**严格限定于全局变量迁移，不改任何功能语义，不改 bot 行为。**

| 本轮做 ✅ | 本轮不做 ❌ |
|:----------|:------------|
| `_ROLE_AGENT_MAP` 读写路径迁移到 PipelineContextManager | 修改 Agent Card 数据结构 |
| `_step_ack_states` 写入/读取改为走 Manager 方法 | 修改 WS 协议 |
| `_PIPELINE_CONFIG` 的 steps 部分迁移到 PipelineContext.steps | 修改 shared/protocol.py |
| PipelineContext.role_agent_map 类型修复（单值→多值） | 修改 bot 行为 |
| ACK 状态持久化（加入 JSON → 重启不丢） | 修改前端/Web 端 |
| `!pipeline resume` 新子命令 | 条件分支/多阶段规划（架构扩展） |
| `!pipeline status` ACK 展示增强 | F-3 workspace_admin 角色体系 |

### 0.2 渐进替换策略

```
1. 每个变量迁移前 → PipelineContext 新增对应字段 + to_dict/from_dict
2. Manager 新增操作该字段的方法
3. 旧变量写入点改为走 Manager（先写新、再写旧，双写保险）
4. 旧变量读取点改为走 Manager
5. 旧变量标记 # DEPRECATED — use PipelineContextManager
6. 全部迁移完成后一次性清理旧变量声明
```

### 0.3 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | 架构师 | 开发工程师 | — |
| Step 3 | 💻 编码实现 | 开发工程师 | 架构师 | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 代码审查 | 审查工程师 | 测试工程师 | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试验证 | 测试工程师 | 审查工程师 | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | 项目管理 | 架构师 | — |

---

## 1. 管线总览

### 核心架构

R78 不新增模块，**扩充已有模块**并迁移 handler.py 中的 3 组旧全局变量（58 处引用）：

```
server/pipeline_context.py  (扩展)
  ├── PipelineContext.role_agent_map  类型修复: str→list[str]   ✅
  ├── PipelineContext.ack_states      新增字段                   ✅
  ├── PipelineContext.steps           新增字段                   ✅
  └── PipelineContextManager          新增: set_global_role_map()
                                      新增: get_role_agents()
                                      新增: update_role_agent_map()
                                      新增: set_ack_state() / get_ack_state()
                                      新增: update_steps() / get_step_config()

server/handler.py  (迁移)
  ├── _ROLE_AGENT_MAP  (19处)  → PipelineContextManager  ✅
  ├── _step_ack_states (11处)  → PipelineContext.ack_states  ✅
  └── _PIPELINE_CONFIG (28处)  → PipelineContext.steps (部分) ✅

server/agent_card.py  (适配)
  └── 写 _ROLE_AGENT_MAP (5行) → 走 Manager  ✅
```

### 改动范围

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:-----|:----:|
| 1 | A | 修复 PipelineContext.role_agent_map 类型（str→list[str]） | `server/pipeline_context.py` | ~10 行 |
| 2 | A | Manager 新增 set_global_role_map() + get_role_agents() + update_role_agent_map() | `server/pipeline_context.py` | ~30 行 |
| 3 | A | agent_card.py 写入改走 Manager | `server/agent_card.py` | ~5 行 |
| 4 | A | handler.py `_get_agents_by_role()` + 其他读取点迁移 | `server/handler.py` | ~20 行 |
| 5 | A | `!agent_role_map` 命令展示走 Manager 全局快照 | `server/handler.py` | ~5 行 |
| 6 | B | PipelineContext 新增 ack_states 字段 + 序列化 | `server/pipeline_context.py` | ~10 行 |
| 7 | B | Manager 新增 set_ack_state() / get_ack_state() | `server/pipeline_context.py` | ~15 行 |
| 8 | B | handler.py `_step_ack_states` 写入/读取迁移 | `server/handler.py` | ~20 行 |
| 9 | C | PipelineContext 新增 steps 字段 + 序列化 | `server/pipeline_context.py` | ~10 行 |
| 10 | C | Manager 新增 update_steps() / get_step_config() | `server/pipeline_context.py` | ~20 行 |
| 11 | C | _cmd_pipeline_start 中 steps 写入 | `server/handler.py` | ~10 行 |
| 12 | C | 替换部分高频 _PIPELINE_CONFIG 读取点 | `server/handler.py` | ~20 行 |
| 13 | D | `!pipeline resume` 子命令 | `server/handler.py` | ~25 行 |
| 14 | D | `!pipeline status` ACK 展示增强 | `server/handler.py` | ~15 行 |
| 15 | — | 旧变量标记 DEPRECATED | `server/handler.py` | ~5 行 |

**总估算：** ~220 行净改（含~100 行新增 + ~120 行替换迁移，最终净增约 +80 行）

---

## 2. 分步计划

---

### Step 2 🏗️ 技术方案

**角色：** 架构师
**输入：** [需求文档 v1.0 ✅](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R78/R78-product-requirements.md)
**产出：** 技术方案文档 + 代码实现计划

**要点：**
- 评估 `_ROLE_AGENT_MAP` 19 处引用的迁移优先级（先写后读）
- 评估 `_step_ack_states` 11 处引用的迁移顺序
- 评估 `_PIPELINE_CONFIG` 中哪些 Step 级配置可以优先迁移（至少 10 处高频点）
- 确认 `PipelineContextManager` 新增方法的签名和类型标注
- 确认双写保险期间的兼容守卫细节
- 特别关注：`agent_card.py` 中 `handler._ROLE_AGENT_MAP` 的 5 处引用——需要避免循环 import

**验收：**
| # | 检查项 | 预期 |
|:-:|:-------|:------|
| 1 | 技术方案文档推 dev | SHA 确认 |
| 2 | 代码改动点精确到函数/行号 | read_file 引用的行号有效 |
| 3 | 兼容性分析覆盖旧命令回归 | 41 个旧命令不受影响 |

---

### Step 3 💻 编码实现

**角色：** 开发工程师
**输入：** 需求文档 + 技术方案
**产出：** 代码改动推 dev

**编码顺序（建议）：**

1. **方向 A 第一步** → 修复 `PipelineContext.role_agent_map` 类型并更新序列化
2. **方向 A Manager 方法** → 新增 `set_global_role_map()` / `get_role_agents()` / `update_role_agent_map()`
3. **方向 A agent_card.py 适配** → 5 行改为走 Manager（注意循环 import）
4. **方向 A handler.py 读取迁移** → `_get_agents_by_role()` 等 3 个消费点
5. **方向 B 第一步** → PipelineContext 新增 `ack_states` 字段 + 序列化
6. **方向 B Manager + handler 迁移** → 11 处引用迁移
7. **方向 C 第一步** → PipelineContext 新增 `steps` 字段 + Manager 方法
8. **方向 C handler 集成** → `_cmd_pipeline_start` 写入 + 替换部分读取点
9. **方向 D** → `!pipeline resume` + ACK 展示增强
10. **收尾** → 旧变量标记 DEPRECATED，验证一次推 dev

**关键注意事项：**
- ⚠️ 方向 A+B 中 handler.py 的旧变量写入点要「先写新、再写旧」的双写保险
- ⚠️ `agent_card.py` 中 `import handler` 可能引起循环 import——用 `_handler_mod = sys.modules.get('server.handler')` 模式
- ⚠️ 每改一个方向后先 `!pipeline status` 验证旧命令不崩溃
- ⚠️ 不要一次改完所有 58 处再推——每个方向推一次 dev，方便 review

---

### Step 4 🔍 代码审查

**角色：** 审查工程师
**输入：** 需求文档 + 技术方案 + 编码 commit
**产出：** 审查报告

**审查重点：**
1. `PipelineContext` 新增字段的 `to_dict()` / `from_dict()` 完备性——尤其 role_agent_map 类型从 str→list[str] 的向后兼容
2. `PipelineContextManager` 新增方法的锁保护——所有写入方法需 `async with self._lock`
3. `agent_card.py` 的循环 import 处理——确认 `sys.modules` 模式不会在模块加载时触发死锁
4. 双写保险——旧变量和新路径是否都写入了（期间万一切换以新为准）
5. 不做 scope creep——没有引入不该改的功能
6. 所有的 `DEPRECATED` 标记是否到位

---

### Step 5 🦐 测试验证

**角色：** 测试工程师
**输入：** 需求文档 + 技术方案 + 编码结果
**产出：** 测试报告

**验收标准：**

| # | 验收项 | 测试方法 |
|:-:|:-------|:---------|
| 1 | `_ROLE_AGENT_MAP` 不再被新代码直接读写 | grep 结果仅出现在旧变量声明行 + `# DEPRECATED` 注释附近 |
| 2 | Agent Card 注册后 PipelineContext.role_agent_map 同步更新 | `!agent_card list` → `!pipeline list` 确认活跃管线的角色映射正确 |
| 3 | `_get_agents_by_role()` 通过 Manager 读取 | grep 无 `_ROLE_AGENT_MAP.get(role)` 调用 |
| 4 | `_step_ack_states` 不再被新代码直接读写 | grep 结果仅出现在旧变量声明 + DEPRECATED 注释 |
| 5 | ACK 状态持久化 | 新建管线 → 推进到 step2 → 重启 server → `!pipeline status` 显示 step2 ACK 状态 |
| 6 | PipelineContext 新增字段序列化完整 | `to_dict()` → `from_dict()` 往返不丢数据 |
| 7 | `!pipeline status` 展示 ACK 状态 | 至少展示每个 step 的 ACK 状态 ✅⏳❌+角色名 |
| 8 | `!pipeline resume` 恢复归档管线 | 已归档管线恢复到活跃，step 和 ACK 状态正确 |
| 9 | 旧 `!pipeline_start` 命令行为不变 | 管线启动正常，`_PIPELINE_CONFIG` 解析兼容 |
| 10 | 所有旧命令回归正常 | 41 个现有命令 + 7 个 pipeline 子命令全部可用 |

---

### Step 6 🦸 合并部署归档

**角色：** 项目管理
**输入：** 测试报告 ✅
**产出：** main 合并部署 + TODO.md 更新

**操作：**
1. `git checkout main && git merge dev`
2. `git push origin main`
3. `docker build -t ws-bridge:r78 .`
4. 部署生产容器（注意先 pull 后 build，不是 restart）
5. 检查容器日志确认启动正常
6. `!pipeline_status` 验证 ACK 持久化
7. 关闭工作室
8. TODO.md v2.44 → v2.45（移入 R78 完成项 + 更新版本号）

---

## 3. 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| `agent_card.py` 循环 import 导致启动失败 | server 无法启动 | 用 `sys.modules` 惰性引用模式，加防御性 `None` 检查 |
| 旧变量标记 DEPRECATED 后仍有遗漏引用 | 新代码读到过期数据 | 每迁移一个变量后执行 `grep` 确认旧引用已迁移 |
| `!_PIPELINE_CONFIG` 迁移不完整导致 Step 配置读不到 | bot 任务配置异常 | 保持 `_PIPELINE_CONFIG` 作为 fallback 读取源，steps 迁移后优先读 ctx.steps，读不到则回退 |
| `role_agent_map` 类型从 str→list[str] 时旧 JSON 无法反序列化 | 重启后现有管线的角色映射丢失 | `from_dict` 中做类型兼容：如果值是 str 则包装为 `[d["role_agent_map"]]` |

---

## 4. 脱敏检查清单

- [ ] docs/R78/*.md 零内部名残留
- [ ] `grep -nE '内部名模式' docs/R78/*.md` 零匹配
- [ ] WORK_PLAN frontmatter 用角色名（非真实 bot 名）
- [ ] 使用通用角色名（PM / arch / dev / review / QA / admin）
- [ ] 不包含真实 agent_id / token / URL

---

## 5. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-09 | 初稿 — R78 WORK_PLAN 定稿（待审核） |
