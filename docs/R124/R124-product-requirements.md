# R124 产品需求文档（Product Requirements）

> **起草人：** 📋 PM（小谷）
> **状态：** 📝 草稿
> **版本：** v1.0

---

## 1. 背景与目标

R123 完成了跨 Step 上下文的动态注入，基础能力已经具备：
- ✅ Bot 完成后 `##key=value` 自动提取并存入 artifacts
- ✅ `{stepN:field}` 模板变量在下步派活时动态渲染（5 级优先级）
- ✅ Step ≥3 时前置步骤完成摘要自动注入派活消息
- ✅ 空值行 `##key## ` 自动清理

有了 R123 的上下文桥梁，bot 之间具备了信息共享能力。但经过 R119→R123 五轮实战，暴露了**自动流转还有缺口**：

| 缺口 | 表现 | 严重度 |
|:-----|:------|:------:|
| **驳回不退** | Review/QA 退回后，PM 需手动重新派活 | 🔴 — 自动流转 0 步即被阻断 |
| **做完不清理** | 已完成管线持续堆积，无自动归档 | 🟡 — 数据膨胀 |
| **缺乏产出验证** | Bot 说 OK 就 OK，无基本真实性检查 | 🟡 — 信任脆弱 |
| **超时处理单一** | 30min 只告警不动作，PM 得手动处理 | 🟡 — 离线即卡死 |

### 1.1 R124 目标

**填补自动流转的最后缺口，使管线在常见分支场景（驳回/重做/完成）下无需 PM 介入即可自动推进。**

| 维度 | 当前（R123） | 目标（R124） |
|:-----|:------------|:-------------|
| 驳回处理 | PM 手动重新派活 | **自动循环**：驳回 → 重做 → 重新审查 → 通过→继续 |
| 管线生命周期 | 永远 active，人工清理 | **自动归档**：完成→存档，积压→清理 |
| 步产出验证 | 纯信任（bot 说 OK 就 OK） | **基本验证**：检查 git SHA 真实存在+消息格式 |
| 超时处理 | 仅告警 | **超时+重试**：重发→通知→标记阻塞 |

---

## 2. 根因分析

### 2.1 驳回不退

当前管线对退回消息的处理链路：

```
Bot 发: "退回 🔄 R124 Step 3 — 缺少边界检查"
  → _handle_server_relay 前缀匹配 "退回 🔄"
  → 转发给 PM inbox ✅（通知）
  → 结束 ❌（不修改 pipeline 状态）
```

`退回 🔄` 前缀在 relay 层匹配了、通知 PM 了、自动确认了——但 PipelineContext 不受影响。状态仍是 `in_progress`，不重置、不重新派活。

**根因：**
- `_try_advance_pipeline` 只处理 `已完成 ✅` 前缀
- `退回 🔄` 只走 relay 通知路由，不走 pipeline 状态机
- 没有`重新派活`机制能从当前 step 重新触发 `_auto_dispatch`

### 2.2 管线持续堆积

`pipeline_contexts.json` 中已完成的管线占位但不贡献价值：

```json
// 已完成的管线不能被清理，因为没有归档机制
{
  "R118": { "status": "completed", ... },   // 做完1周了
  "R119": { "status": "completed", ... },
  "R120": { "status": "completed", ... },
  "R121": { "status": "completed", ... },
  "R122": { "status": "completed", ... },
  "R123": { "status": "completed", ... },
  "R124": { "status": "running", ... }      // 当前活跃
}
```

**根因：** 完成时只标记 `status=completed`，无归档步骤。

### 2.3 缺乏产出验证

Bot 发送 `已完成 ✅ R124 Step 3##sha=abc..` 后管线立即推进，但：
- `abc..` 可能不是完整 SHA
- SHA 可能不存在于远程 dev 分支
- commit message 可能与当前轮次无关

**现状：** 纯信任模型。Bot 说「已推 dev」就信了。

---

## 3. 功能需求

### 需求 A — 驳回自动再派活（Rework Loop）

> **动机：** Review/QA 退回后，管线应自动回到对应 step 重新派活，而不是全部依赖 PM 手动操作。这是实现「自动流转」最关键的一步。

**触发条件：** `_handle_server_relay` 接收到 `退回 🔄 R{N} Step {N}` 消息。

**行为描述：**

```
退回消息 → relay 匹配 "退回 🔄"
  → 识别轮次 R{N} 和 Step N
  → 管线退回到编码 step（Step 3，即 ctx.steps[2]）
  → 重置 Step 3（及之后所有 step）的 status 为 "pending"
  → 清除 Step 3 及后续 step 的 output/result_msg
  → 将「退回原因」写入 ctx.steps[2]["reject_reason"]
  → 通知 PM: "🔄 R{N} Step {N} 被退回，原因：{reject_reason}。管线已退回到 Step 3（编码环节）。请 PM 决定下一步：重新派活 or 继续推进"
  → **不自动重新派活**（留给 PM 决策）
```

**退回原因提取：**
- 从 `退回 🔄 R{N} Step {N} — {原因}` 中提取 `—` 之后的文本作为 reject_reason
- 无 `—` 时取消息前 100 字符

**管线回退逻辑：**

| 退回 Step | 回退到 | 影响范围 |
|:---------|:-------|:---------|
| Step 4 Review | Step 3（Dev 编码） | Steps 3~4 all reset to pending |
| Step 5 QA | Step 3（Dev 编码） | Steps 3~5 all reset to pending |
| Step 2 Arch | Step 1（PM 需求） | Steps 1~2 all reset to pending（极少见） |

**为什么一律退回 Step 3：**
- Review/QA 发现的问题本质上是编码质量问题，需要回到编码环节
- 退回 Step 3 而非退回具体报错 step 的原因：Dev 重改后 Review/QA 需要重新走一遍全流程，而不是跳过已通过的步骤
- 但 是否重新编码、是否重新审查/测试——**由 PM 决定后续动作**

**PM 后续决策路径：**

| PM 决定 | 动作 | 场景 |
|:--------|:-----|:------|
| 🔴 需要重编码 | `_inbox:server + to_agent` 派活 Dev → Dev 改 → `已完成 ✅` → 自动推进到 Review/QA | 编码质量严重不达标 |
| 🟡 轻微问题可跳过 | `##advance##R{N}##step={N}` 推进到被退回的 step 继续审查/测试 | 代码没问题，只是 typo 或格式问题 |
| 🔵 误报 | `##advance##R{N}##step={N}` 跳过，直接继续 | QA 环境问题误报 |
| 🟠 问题可忽略，但需归档 | `##advance` 推进 + 通知 QAreviewer 写备注 | 非关键路径问题 |

**限制循环次数：**
- 每轮管线累计退回次数 ≤ **3 次**（`ctx.reject_count`，轮次级计数器）
- 第 4 次退回时：标记 `status: "stuck"`，通知 PM 人工介入，停止自动状态回退
- `reject_count` 在每次退回时递增

**验收标准：**
- [ ] A-1：Review 退回 Step 4 后，`ctx.steps[2]` status 重置为 `"pending"`，output 清空
- [ ] A-2：退回原因写入 `ctx.steps[2]["reject_reason"]`
- [ ] A-3：退回后退回 Step 3~Step N 全部重置为 pending（不自动派活）
- [ ] A-4：PM 收到退回通知（含原因 + 管线已退回到 Step 3 状态）
- [ ] A-5：同一管线累计退回 3 次后第 4 次标记 `"stuck"`，停止状态回退
- [ ] A-6：无 `—` 的退回消息，reject_reason 取前 100 字符
- [ ] A-7：PM 可自行决定下一步（派活 Dev 重做 or `##advance` 跳过）

### 需求 B — 管线自动归档（Auto Archive）

> **动机：** 已完成管线不应长期留存在活跃列表中。自动归档减少数据膨胀，避免干扰活跃管线的展示和扫描。

**触发条件：** 管线所有 step 状态均为 `"done"` 或管线标记 `"completed"`。

**行为描述：**

```
管线达到条件（全 step done 或 status=completed）
  → _try_advance_pipeline 推进到最后一步后检测
  → 调用_archive_pipeline(round_name)
  → 从PipelineManager._contexts移除
  → 附加到archive文件 pipeline_archive.json（追加模式）
  → 通知PM: "📦 R{N} 管线已完成并归档"
```

**archive 文件格式（`/app/data/pipeline_archive.json`）：**

```json
[
  {
    "round_name": "R123",
    "status": "completed",
    "archived_at": 1721190000.0,
    "completed_at": 1721189900.0,
    "steps": [
      {"step": 1, "role": "pm", "agent_name": "小谷", "status": "done", "output": {...}, "result_msg": "..."},
      ...
    ],
    "artifacts": {...},
    "summary": {
      "total_steps": 6,
      "completed_steps": 6,
      "reject_count": 0,
      "total_duration_sec": 3600
    }
  }
]
```

**归档时机：**
1. **自动归档** — 管线所有 step 完成后，`_try_advance_pipeline` 检测到 pipeline 全部 done 时自动执行
2. **手动归档** — `##archive##R{N}` 命令（PM 可手动归档任意管线）

**自动清理（可选）：** `pipeline_archive.json` 超过 50 条记录时，自动清理最早的已完成记录（保留最近的 30 条）。

**验收标准：**
- [ ] B-1：管线全 step done 后自动归档，从活跃上下文移除
- [ ] B-2：归档记录写入 `pipeline_archive.json`，含全部 step 产出和历史 artifacts
- [ ] B-3：`##archive##R{N}` 命令可手动归档指定轮次
- [ ] B-4：归档后 `##status##R{N}` 返回「已归档，数据在 pipeline_archive.json」
- [ ] B-5：归档后 PM 收到通知「📦 R{N} 管线已完成并归档」

### 需求 C — Step 产出基本验证

> **动机：** 「已完成 ✅」不应是唯一的推进条件。Server 应对 bot 的完成声明做基本的真实性验证，减少因 bot 虚构/误报导致的管线断流。

**触发条件：** `_try_advance_pipeline` 收到完成信号后、推进 step 之前。

**行为描述：**

在 `_try_advance_pipeline` 中，推进 step 之前，对产出做基本验证：

#### C-1 SHA 格式验证
- 如果完成消息中携带 `##sha=xxx`，检查：
  - xxx 是 7 或 40 字符的 hex 字符串（正则：`^[0-9a-f]{7,40}$`）
  - 不符合 → 记录 `output["sha_validation"] = "invalid_format"`
  - 不影响推进（仅标记，不阻断）

#### C-2 SHA 远程存在性验证（可选增强）
- 如果 `PIPELINE_OUTPUT_VERIFICATION=1` 环境变量已设置：
  - 用 `git ls-remote origin dev` 检查 SHA 是否在 dev 分支
  - 存在 → `output["sha_validation"] = "verified"`
  - 不存在 → `output["sha_validation"] = "not_found"`
  - 超时/git 失败 → `output["sha_validation"] = "unchecked"`
  - 不影响推进（仅标记，不阻断）

#### C-3 Commit 消息轮次匹配检查（可选增强）
- 如果 `PIPELINE_OUTPUT_VERIFICATION=1`：
  - 用 `git log --oneline <sha> -1` 获取 commit message
  - 检查 commit msg 是否包含 `R{N}`（当前轮次）
  - 记录到 `output["commit_round_match"]`：`"matched"` / `"mismatched"` / `"unchecked"`

**设计原则：** 验证始终**不阻断**管线推进。验证结果仅写入 `output` 字典供后续 step 摘要和审查使用。阻断验证属于未来轮次。

**验收标准：**
- [ ] C-1：`##sha=abc1234` 格式正确 → `output["sha_validation"] = "valid_format"`
- [ ] C-2：`##sha=abc`（非完整）→ `output["sha_validation"] = "valid_format"`（7 字符合法）
- [ ] C-3：`##sha=not-a-sha!@#$` → `output["sha_validation"] = "invalid_format"`
- [ ] C-4：无 `##sha` 时，`output` 中无 sha_validation 字段
- [ ] C-5：验证从不阻断管线推进（任何失败都标记但不 return）
- [ ] C-6：需要 `PIPELINE_OUTPUT_VERIFICATION=1` env var 才启用远程 git 检查（默认关闭）

### 需求 D — 超时自动化处理增强

> **动机：** 当前 30min 超时仅告警 PM。增强后管线应对超时有更多自动动作，减少 PM 人工介入。

**触发条件：** `_pipeline_timeout_scan` 检测到 step 超时（dispatched_at > 30min）。

**当前行为：**
```
超时 → 通知 PM: "⏰ R{N} Step N 已执行 30 分钟，Bot {name} 未回复"
→ 标记 timeout_alerted=true（防止重复告警）
→ 等待 PM 手动处理
```

**R124 增强行为：**

```
超时（首次 30min）→ 通知 PM + 重新发送派活消息给 bot（重试）
→ 重试后等待 15min
→ 超时（45min）→ 通知 PM: "bot 已 45 分钟未响应"
→ 将 step status 标记为 "timeout"（不阻断后续推进）
→ 等待 PM 处理
```

**重发派活逻辑：**
- 在 `_auto_re_notify(ctx, step_num)` 中：
  - 从 `ctx.steps[step_num-1]` 中读取完整的派活消息
  - 重新调用 `_send_to_agent(target_agent_id, msg)`
  - 不重置 `dispatched_at`（避免干扰超时扫描）

**验收标准：**
- [ ] D-1：首次超时（30min）后重新发送派活消息给原 bot
- [ ] D-2：重发后 PM 收到通知（含「已重新发送」标记）
- [ ] D-3：二次超时（45min）后标记 step 为 `"timeout"`
- [ ] D-4：step 标记 timeout 后后续推进不受影响（仍可手动推进）
- [ ] D-5：原有 30min 首次告警行为完全保留

---

## 4. 方向决定

| 决定事项 | 选择 | 说明 |
|:--------|:----|:-----|
| 驳回触发方式 | **消息前缀匹配 `退回 🔄`** — 复用已有 relay 前缀路由 | 不新增命令，不改 bot 行为。bot 发 `退回 🔄 R124 Step 3 — 原因` 即可触发 |
| 回退目标 | **一律退回编码 step（Step 3）** | Review/QA 发现问题本质是编码质量，退到编码环节最合理。不自动派活，由 PM 决定是否重做 |
| 是否自动重派 | **否** — Server 只负责状态回退 + 通知 PM，不自动派活 | 灵活性：PM 根据严重程度决定重做/跳过/误报 |
| 循环限制 | **每轮管线最多退 3 次，第 4 次 stuck** | 轮次级计数器防无限循环 |
| 归档触发 | **Step 完成时自动 + `##archive` 命令手动** | 双通道覆盖所有场景 |
| 验证策略 | **记录不阻断**（标记 `sha_validation` 但不阻止推进） | 保持管线流畅性，验证信息供后续 step 使用 |
| 超时重试 | **首次告警后 + 重发一次派活** | 30min 超时可能只是消息丢失，重发可救活 |

---

## 5. 不做事项（明确排除）

| 排除项 | 理由 |
|:-------|:------|
| ❌ **跨 step 并行派活** | 需要重新设计步骤拓扑模型，R124 聚焦线性完成 |
| ❌ **git 自动检测推进（git auto-detect）** | R123 已记录调研，且与「自动流转」正交 |
| ❌ **bot 自动选择/角色热切换** | 离线 bot 替代需要 `pipeline_roles` 多对一映射，超出范围 |
| ❌ **前端管线盘面大改** | 仅增加归档线和非活跃状态标记 |
| ❌ **修改 bot 回复协议格式** | bot 已经习惯 `退回 🔄 R{N} Step {N} — 原因` 格式，不做修改 |
| ❌ **自动修复 git 冲突** | 超出 ws-bridge 范围，git 冲突需要人工处理 |

---

## 6. 开放问题

| # | 问题 | 建议方向 | 决策者 |
|:-:|:-----|:--------|:------|
| 1 | `退回 🔄 Step N` 中的 Step N 可能是 4(Review)或5(QA)，回退时按原 Step N 重置还是统一回 Step 3？ | 统一回 Step 3（编码环节），Review/QA 的功能性代码问题本质是编码质量。如果退回的是需求文档（Step 2），回 Step 1 | PM |
| 2 | 归档清理策略：`pipeline_archive.json` 保留多少条？ | 建议 30 条，超过则自动清理最早的 | PM |
| 3 | `PIPELINE_OUTPUT_VERIFICATION` 默认开启还是关闭？ | 建议默认关闭（`0`），远程 git 操作有额外延迟 | PM |
| 4 | PM 跳过退回后，是否需要通知退回发起方（Review/QA）「已忽略」？ | 建议 PM 手动发消息告知，Server 不自动通知。否则退回发起方收不到闭环反馈 | PM |
| 5 | 超时重发派活是否需要「间隔 15min」作为参数可配置？ | 建议：硬编码 15min，不做可配。未来如需可加 `PIPELINE_RETRY_INTERVAL` | PM |
| 6 | Step 6 Ops 超时的处理与其他 step 是否不同？Ops 常需要长时间等待用户响应 | 建议统一处理，Ops 超时也告警并重发（Ops 可能没收到消息） | PM |

---

## 7. 改动范围和估算

| 文件 | 改动 | 估算 |
|:-----|:------|:-----|
| `server/ws_server/main.py` | `_handle_server_relay` 加 `退回 🔄` 处理器；`_try_advance_pipeline` 增强（验证+归档检测）；新增 `_handle_reject()` / `_archive_pipeline()` / `_auto_re_notify()`；`_pipeline_timeout_scan` 增强 | ~+150 行 |
| `server/common/config.py` | 新增 `PIPELINE_OUTPUT_VERIFICATION` 配置项 | ~+3 行 |
| `server/data/pipeline_archive.json` | 新文件（归档存储） | 运行时创建 |

---

## 8. 验收检查表

| # | 验收项 | 类型 | 优先级 |
|:-:|:------|:----:|:-----:|
| A-1 | Review 退回 Step 4 → step 3~4 status 重置为 pending，output 清空 | P0 | 🟢 |
| A-2 | 退回原因写入 `ctx.steps[2]["reject_reason"]` | P0 | 🟢 |
| A-3 | 退回后仅回退状态，不自动重新派活 | P0 | 🟢 |
| A-4 | PM 收到退回通知（含原因 + 管线已退回 Step 3 状态） | P0 | 🟢 |
| A-5 | 累计退回 3 次后第 4 次 stuck，停止回退 | P1 | 🟡 |
| A-6 | 无 `—` 的退回消息，取前 100 字符作原因 | P2 | 🔵 |
| B-1 | 管线全 step done 后自动归档 | P0 | 🟢 |
| B-2 | 归档记录写入 `pipeline_archive.json`（含全量数据） | P0 | 🟢 |
| B-3 | `##archive##R{N}` 手动归档命令 | P1 | 🟡 |
| B-4 | 归档后 `##status` 返回「已归档」 | P1 | 🟡 |
| B-5 | PM 收到归档通知 | P2 | 🔵 |
| C-1 | `##sha=abc1234` 格式验证通过 | P1 | 🟡 |
| C-2 | `##sha=not-a-sha!@#$` 标记 `invalid_format` | P1 | 🟡 |
| C-3 | 验证从不阻断管线推进 | P0 | 🟢 |
| C-4 | `PIPELINE_OUTPUT_VERIFICATION=1` 启用的远程 git 检查（可选） | P2 | 🔵 |
| D-1 | 首次超时（30min）后重新发送派活消息 | P1 | 🟡 |
| D-2 | 二次超时（45min）后标记 step 为 timeout | P1 | 🟡 |
| D-3 | 超时重发不干扰原有告警逻辑 | P0 | 🟢 |
| D-4 | 回归测试：全 6 步自动派活零断流 | P0 | 🟢 |

---

> **审核记录：**
> - v1.0 提交审核：[2026-07-17]
> - 项目负责人审核意见：待定
