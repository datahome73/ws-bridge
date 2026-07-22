# R142 管线稳定性加固轮 — 开发计划

> **仓库：** `datahome73/ws-bridge`（ws-bridge 服务端）
> **来源文档：** `docs/research/L4-auto-pipeline-manager-needs-research.md`
> **状态：** 📝 草稿

---

## 角色分工

| 角色 | 虾虾 | 职责 |
|:----:|:----:|:-----|
| 🧐 PM | 小谷 | 需求调研 → 出需求文档 |
| 🏗️ 架构师 | 小开 | 技术方案设计 |
| 💻 开发工程师 | 爱泰 | 编码实现 |
| 🔍 审查工程师 | 小周 | 代码审查 |
| 🦐 测试工程师 | 泰虾 | Dev 测试 + 上线验证 |
| 🦸 运维 | 小爱 | 部署 + 合并 main |

---

## 开发步骤

### Step 1 — 需求文档 🧐 小谷 ✅（已完成）

产出：`docs/R142/R142-product-requirements.md` + `docs/R142/WORK_PLAN.md`

| 项 | 状态 |
|:---|:-----|
| 需求文档 | ✅ 已写——449 行，7 项改动，26 项验收标准 |
| WORK_PLAN | ✅ 已写——当前文档 |
| 来源文档 | `docs/research/L4-auto-pipeline-manager-needs-research.md` |
| 本地 commit | `2927b59` 在 dev 分支 |
| GitHub push | ⏳ 需配置 GITHUB_TOKEN |

---

### Step 2 — 技术方案 🏗️ 小开

产出：`docs/R142/R142-tech-plan.md`

评估 7 项改动的详细实现方案。以下为需求文档中的实现预分析，供架构师参考：

#### F-1: status_icons 加 `in_progress` 🟢

| 维度 | 值 |
|:-----|:----|
| **目标文件** | `server/ws_server/pipeline_engine.py` |
| **目标函数** | `_handle_hash_status()` — L1561-L1567 |
| **改动** | `status_icons` 字典加一行 `"in_progress": "🔄"` |
| **行数** | +1 行 |
| **风险** | 🟢 零——字典 key 增加，不影响现有 lookup |
| **预检** | grep `status_icons` 确认只有一个字典（`_notify_pm` 和 `_handle_hash_status` 中会用到）|

#### F-2: 完成消息容错匹配 🟢

| 维度 | 值 |
|:-----|:----|
| **目标文件** | `server/ws_server/pipeline_engine.py` |
| **目标函数** | `_try_advance_pipeline()` — L361-L474 |
| **改动** | 新增 `_try_extract_step_completion()` 替代 `re.match(...)` |
| **行数** | ~+50 |
| **风险** | 🟢 低——纯函数 + 降级兼容 |
| **关键点** | `_extract_artifact_kv` 使用 `##key=value` 前缀提取，和新的容错 pattern 无关；新的第 1 条 pattern `r"已完成\s*✅?\s*R(\d+)\s*Step\s*(\d+)"` 覆盖原严格格式 |
| **预检** | 确认 `re.search` 对 `##key=value` 片段无副作用（`re.search` 和 `re.match` 的区别——`re.match` 从开头匹配，`re.search` 全串扫描。用 `re.search` 没问题，因为 R{N} Step{N} 应在消息的靠前位置）|

#### F-3: 管线闭环通知增强 — 统一通知管线协调者 🟢

| 维度 | 值 |
|:-----|:----|
| **目标文件** | `server/ws_server/pipeline_engine.py` |
| **改动** | 增强 `_notify_pm` 的 `"completed"` 分支（L493-L506），增加各 Step 状态表格、产出摘要、SHA 信息 |
| **行数** | ~+20（修改现有函数，不新增函数） |
| **风险** | 🟢 低——纯增量，仅修改 completed 分支的文本内容，不新增配置项、不新增 agent_id |
| **设计原则** | 管线协调者是统一的通知目标角色，复用 `config.PIPELINE_PM_AGENT_ID`。不硬编码任何 agent_id，不新增 env var |
| **预检** | 确认 `_notify_pm` 中 `role_names` 字典已存在；确认 `ctx.steps` 的 output 字段结构（`sha` key 在 Step 6）|

#### F-4: status 证据增强 🟢

| 维度 | 值 |
|:-----|:----|
| **目标文件** | `server/ws_server/pipeline_engine.py` |
| **目标函数** | `_handle_hash_status()` — L1577-L1591 |
| **改动** | step_lines 构造后追加完成时间/进行时长/消息片段 |
| **行数** | ~+20 |
| **风险** | 🟢 低——纯展示层增加；`_fmt_ts` 检查是否在模块内可用 |
| **预检** | `_fmt_ts` 用法：搜索 `_fmt_ts` 确认存在 |

#### F-5: 审查回退 Step 3 🟡

| 维度 | 值 |
|:-----|:----|
| **目标文件** | `server/ws_server/pipeline_engine.py` |
| **目标方法** | `PipelineEngine.handle_reject()` 或模块级异步函数 |
| **改动** | 解析 `content` 取 R{N} → 检查 `current_step == 4` → 回退 Step 3&Step 4→pending → ctx.current_step=3 → mgr.save() → 通知 PM |
| **行数** | ~+30 |
| **风险** | 🟡 中——涉及状态机写入；必须 try/except 包裹 |
| **关键设计选择** | 回退后不自动派活（由管线协调者/后续完成消息触发）→ 已写入需求文档 |
| **预检** | 确认 `PipelineEngine.handle_reject` 当前是否有实现。grep 搜 `async def handle_reject` 确认是 stub 还是已有逻辑 |

#### F-6: completed_at 记录 🟢

| 维度 | 值 |
|:-----|:----|
| **目标文件** | `server/ws_server/pipeline_engine.py` |
| **目标位置** | L404-406 `_step_info["status"] = "done"` 处 |
| **改动** | 追加 `_step_info["completed_at"] = time.time()` |
| **行数** | +1 行 |
| **风险** | 🟢 零——新字段写入，不改变现有字段读取 |

#### F-7: 格式自动提示 🟢

| 维度 | 值 |
|:-----|:----|
| **目标文件** | `server/ws_server/pipeline_engine.py` |
| **目标位置** | `_try_advance_pipeline()` L367-369 匹配失败分支 |
| **改动** | 匹配失败 + 含"完成"关键词时 `asyncio.ensure_future(_send_format_hint(agent_id))` |
| **行数** | ~+20 |
| **风险** | 🟢 低——纯增量，不影响正常匹配路径 |

---

### Step 3 — 编码 💻 爱泰

#### 前置条件

```bash
cd /opt/data/ws-bridge
git checkout dev
git pull --rebase origin dev          # 同步最新
```

#### 提交 1/2：🟢 低风险改动（F-1/F-3/F-4/F-6/F-7）

```bash
# 1. F-1: status_icons 加 in_progress
# 文件：pipeline_engine.py L1561-L1567
# 在 status_icons dict 中加 "in_progress": "🔄"

# 2. F-6: completed_at 记录
# 文件：pipeline_engine.py L404-406
# 在 _step_info["status"] = "done" 后加 _step_info["completed_at"] = time.time()

# 3. F-4: status 证据增强
# 文件：pipeline_engine.py _handle_hash_status()
# 在 L1577-L1591 step_lines 构造后追加时间戳/时长/消息片段

# 4. F-3: 管线闭环通知增强
# 文件：pipeline_engine.py _notify_pm() L493-L506
# 增强 completed 分支：增加 Step 状态表格、产出摘要、SHA 信息

git add -p server/ws_server/pipeline_engine.py
git commit -m "R142 F-1/F-3/F-4/F-6/F-7: status增强+闭环通知增强+格式提示

- F-1: status_icons 加 'in_progress': '🔄'（1行）
- F-3: 增强 _notify_pm completed 分支——管线协调者统一收到含Step摘要的闭环通知（20行）
- F-4: ##status 显示完成时间/时长/消息片段（20行）
- F-6: done 时记录 completed_at 时间戳（1行）
- F-7: 格式错误完成消息自动提示正确格式（20行）"
```

#### 提交 2/2：🟡 中风险改动（F-2/F-5）

```bash
# 1. F-2: 完成消息容错匹配
# 文件：pipeline_engine.py _try_advance_pipeline() L361
# 新增 _try_extract_step_completion() 纯函数（~30行）
# 替换 L367 re.match(...) 为调用新函数

# 2. F-5: 审查回退 Step 3
# 文件：pipeline_engine.py handle_reject() 方法
# 解析 R{N} → 检查 current_step==4 → 回退 Step 3&4 → save → 通知 PM

git add -p server/ws_server/pipeline_engine.py
git commit -m "R142 F-2/F-5: 完成消息容错匹配+审查回退

- F-2: 新增 _try_extract_step_completion() 多模式容错匹配（50行）
  支持: 已完成✅R{N}Step{N} / ✅完成R{N}Step{N} / R{N}Step{N}已完成
- F-5: handle_reject 审查退回→自动回退 Step 4→Step 3（30行）
  仅 current_step==4 时触发，try/except 保护"
```

#### 编码检查清单

| # | 检查项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | Python 语法正确 | `python3 -c "compile(open('server/ws_server/pipeline_engine.py').read(), 'pipeline_engine.py', 'exec'); print('Syntax OK')"` |
| 2 | import 路径无断裂 | `python3 -c "from server.ws_server import pipeline_engine; print('Import OK')"` |
| 3 | F-2 原始格式仍然匹配 | 编写测试脚本：传入 `"已完成 ✅ R142 Step 3##sha=abc"` → 确认返回 (142, 3, ...) |
| 4 | F-2 新格式正确匹配 | 传入 `"✅ 完成，R142 Step 3 已推 dev"` → 确认返回 (142, 3, ...) |
| 5 | F-5 回退边界安全 | 模拟 current_step=5 → 发退回消息 → 确认 current_step 不变 |
| 6 | 无 debug print 残留 | `grep -n 'print(' server/ws_server/pipeline_engine.py` |
| 7 | 无新硬编码 agent_id | `grep -n 'ws_e9007a4cf802' server/ws_server/pipeline_engine.py` — 确认新增代码中无硬编码 agent_id |

---

### Step 4 — 代码审查 🔍 小周

产出：`docs/R142/R142-code-review.md`

逐 commit 审查，审查内容：

#### commit 1/2 审查（F-1/F-3/F-4/F-6/F-7）

| # | 检查项 | 说明 |
|:-:|:-------|:-----|
| 1 | 🔍 F-1: `status_icons["in_progress"] = "🔄"` 是否只有 1 处 | 确保字典无重复 key |
| 2 | 🔍 F-3: `_notify_pm` completed 分支增强后内容完整 | 确认表格格式正确、Step 6 的 SHA 信息能正确提取 |
| 3 | 🔍 F-4: `_fmt_ts` 是否存在于模块作用域 | 检查函数名拼写错误 |
| 4 | 🔍 F-6: `completed_at` 写入后没有其他地方需要同步读取 | 确认只有 `##status##` 用到 |
| 5 | 🔍 F-7: 格式提示不阻塞主流程 | `asyncio.ensure_future` → 确认不 `await` |

#### commit 2/2 审查（F-2/F-5）

| # | 检查项 | 说明 |
|:-:|:-------|:-----|
| 6 | 🔍 F-2: 新 patterns 不会误匹配无关消息 | 测试 "Refactored Step 3 for R142" 不应匹配 |
| 7 | 🔍 F-2: `##key=value` 提取未破坏 | `_extract_artifact_kv` 在容错路径中是否仍被调用 |
| 8 | 🔍 F-5: 回退前 `current_step == 4` 断言 | 确保不会错误回退其他 Step |
| 9 | 🔍 F-5: `mgr.save()` 在 try 内 | 异常时状态机不损坏 |
| 10 | 🔍 全局 import 无循环依赖 | `pipeline_engine.py` 对 `scenario_rules.py` 无反向引用 |

---

### Step 5 — Dev 测试 🦐 泰虾

产出：`docs/R142/R142-test-report.md`

验证 26 项验收标准（§5）全部通过。以下是**核心验证脚本**：

```python
# 测试前准备
from server.ws_server import pipeline_engine as pe
from server.ws_server.pipeline_engine import _try_extract_step_completion

# ── 容错匹配测试 (CP-1~5) ──
test_cases = [
    ("已完成 ✅ R142 Step 3##sha=abc",     (142, 3, {"sha": "abc"})),
    ("✅ 完成，R142 Step 3 已推 dev",         (142, 3, {})),
    ("R142 Step 3 已完成",                    (142, 3, {})),
    ("已完成 R142 Step 3##sha=xyz##branch=main", (142, 3, {"sha": "xyz", "branch": "main"})),
    ("✅ 完成，R145 Step 2 方案已推",         (145, 2, {})),
    ("完成了，push 到 dev",                   (None, None, {})),  # 缺 R{N}
    ("无关的消息",                             (None, None, {})),  # 不匹配
]
for msg, expected in test_cases:
    result = _try_extract_step_completion(msg)
    assert result == expected, f"FAIL: {msg[:30]} → {result}"

# ── 格式提示测试 (HT-1~3) ──
# 在 _try_advance_pipeline 中匹配失败分支验证
# 含"完成"关键词但不含 R{N} → _send_format_hint 被调用
# 含"完成"且格式正确 → 不触发提示
# 无关消息 → 不触发提示
```

**测试检查清单：**

| # | 测试项 | 标准 | 类型 |
|:-:|:-------|:-----|:----:|
| 1 | ST-1: status in_progress 图标 | `##status##R142` 已派活 step 显示 🔄 | P0 |
| 2 | ST-2: status 完成时间 | ✅ step 显示 `完成于: 07-22 14:30` | P0 |
| 3 | ST-3: status 进行时长 | 🔄 step 显示 `已进行: 5分23秒` | P0 |
| 4 | ST-4: result_msg 展示 | 有 result_msg 的 step 显示 `消息: ...` | P0 |
| 5 | CP-1: 原始严格格式 | `已完成 ✅ R142 Step 3##sha=abc` → 推进 | P0 |
| 6 | CP-2: ✅ 完成变体 | `✅ 完成，R142 Step 3 已推 dev` → 推进 | P0 |
| 7 | CP-3: 无表情变体 | `R142 Step 3 已完成` → 推进 | P0 |
| 8 | CP-4: 缺 R{N} | `完成了，push 到 dev` → 不推进不报错 | P0 |
| 9 | CP-5: ##key=value 保留 | 容错路径下 `##sha=abc` 仍能提取 | P0 |
| 10 | NT-1: 闭环通知管线协调者 | 全管线完成 → 管线协调者收到含 Step 摘要的通知 | P0 |
| 11 | NT-2: 通知含摘要 | 通知含各 Step 状态/角色/产出 | P0 |
| 12 | NT-3: 其他 status 分支不变 | dispatched/failed/rejected 等通知不受影响 | P0 |
| 13 | RJ-1: Step 4→3 回退 | `退回 🔄 R142 Step 4` → current_step=3 | P1 |
| 14 | RJ-2: 非 Step4 不回退 | Step=3 发退回 → 只日志 | P1 |
| 15 | RJ-3: 回退通知管线协调者 | 回退后 `_notify_pm` 被调用 | P1 |
| 16 | RJ-4: 回退不自动派活 | 回退后 state 停在 Step 3 pending | P1 |
| 17 | RJ-5: 异常安全 | 回退中异常 → 状态机不损坏 | P1 |
| 18 | HT-1: 格式错误提示 | 含"完成"但格式错 → 回复格式提示 | P2 |
| 19 | HT-2: 格式正确不提示 | 格式正确 → 不回复提示 | P2 |
| 20 | HT-3: 无关消息不提示 | 无"完成"关键词 → 不提示 | P2 |

---

### Step 6 — 合并 main + 部署 🦸 小爱

```bash
# Step 6a: 合并 dev → main
git checkout main
git merge dev
git push origin main           # 或 ssh-origin main

# Step 6b: 部署到 VPS Docker 容器
# (仅小爱可操作，PM 不写 SSH 命令)
# 部署后需验证：
# 1. 容器启动正常（health check）
# 2. ##start##R143 → 自动推进 Step 2
# 3. 发完成消息 → 推进 → 管线协调者收到闭环通知

# Step 6c: 标记 R142 完成
git checkout dev
# TODO: 更新 TODO.md 将 B-3/B-4 标记为 ✅ 已完成
```

---

## 注意事项

1. `docs/R*/` 被 `.gitignore` 忽略，需 `git add -f` 强制提交
2. **安全优先**——7 项改动中有 6 项是低风险增量改动，F-5（审查回退）是唯一的新状态变更逻辑，需重点验证
3. **回归防护**——F-2 新匹配函数第 1 条 pattern 与原正则等价，不存在格式降级风险
4. **部署顺序**——先部署到 dev 环境 → QA 验证通过 → 合 main → 部署生产
5. **外部依赖**——不依赖 bot 端修改，纯 server 端改动
6. 编码时 `git pull --rebase origin dev` 拉取最新后再推送，避免覆盖他人提交
