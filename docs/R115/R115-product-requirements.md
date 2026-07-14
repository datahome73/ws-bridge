# R115 管线 Step 产出上下文注入 — 需求文档

> **轮次：** R115
> **类型：** 功能开发轮
> **PM：** 小谷
> **基线：** R114 协议定稿（8 场景 `##key=value` 完成消息格式）

---

## 一、背景

R114 已定义完成 8 个场景下 bot 向 `_inbox:server` 发送的完成消息格式（`已完成 ✅ R{N} Step {N}##key=value`），R115 在 ws-bridge server 端实现对上述格式的正则解析 + `##` 键值对提取 + 注入 PipelineContext.artifacts。

当前 `_try_advance_pipeline()` 已能识别 `已完成 ✅ R{N} Step {N}` 前缀并自动推进 Step，但丢弃了 `##key=value` 部分。R115 补全这个「**提取→落盘→注入**」链路。

---

## 二、功能需求

### 2.1 `##` 键值对提取

**触发入口：** `_handle_server_relay()` 中规则 2（`已完成 ✅` / `✅ 完成` 前缀）→ `_try_advance_pipeline()`

**输入示例：**
```
已完成 ✅ R115 Step 2##tech_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-tech-plan.md##design_decision=重构 handler 为纯函数模式
```

**处理逻辑：**

| 步骤 | 操作 |
|:-----|:------|
| 1 | 用正则提取 round_name 和 step_num（已有 `r"已完成 ✅ R(\d+) Step (\d+)"`） |
| 2 | 将 content 按 `##` 分割，跳过第 0 段（前缀段） |
| 3 | 对 parts[1:] 每段按 `=` 分割为 key 和 value |
| 4 | 构建 dict: `artifacts["step{N}"] = {key1: value1, key2: value2, ...}` |
| 5 | 写入 `ctx.artifacts` |
| 6 | 调用 `mgr.save()` 持久化 |

**边界情况：**

| 场景 | 处理 |
|:-----|:------|
| content 没有 `##` | 无 artifacts，仅推进 Step |
| `##` 段不含 `=` | 忽略该段（log warning） |
| key 为空 | 忽略 |
| value 为空 | 接受（插入空字符串） |
| 同 key 重复 | 后者覆盖前者（log debug） |
| 特殊字符（URL 中的 `&`、`=`） | value 中允许，仅第一个 `=` 做分隔符 |

### 2.2 artifacts 数据结构

`PipelineContext.artifacts` 是 `dict[str, dict]`，key 为 `"step2"`, `"step3"` 等，value 为该步产出的 KV：

```json
{
  "step2": {
    "tech_plan_url": "https://raw.githubusercontent.com/.../R115-tech-plan.md",
    "design_decision": "重构 handler 为纯函数模式"
  },
  "step3": {
    "commit_sha": "abc1234def5678",
    "files_changed": "server/main.py,server/handler.py",
    "commit_description": "Add pipeline auto-archive feature",
    "branch_name": "dev"
  }
}
```

### 2.3 模板变量注入（验证现有逻辑）

`_render_template()` 中已有 `vars.update(step_artifacts)` 逻辑，R115 **仅验证** 新写入的 artifacts 能正确被后续派活模板消费。

**验证方法：**
1. 构造一个包含 `{tech_plan_url}` 的 step3 派活模板
2. 模拟 Step 2 完成消息写入 `artifacts["step2"]["tech_plan_url"]`
3. 确认自动派活 Step 3 时 `{tech_plan_url}` 被替换为正确 URL

### 2.4 不修改的模块

| 模块 | 原因 |
|:-----|:------|
| `_handle_hash_cmd`（##start） | 已有完整的 kv 解析逻辑 |
| `_auto_dispatch` | 派活逻辑不变，仅消费 artifacts |
| `_handle_server_relay` 前缀匹配规则 | 不变 |
| `_render_template` 渲染逻辑 | 仅验证不变 |

---

## 三、验收标准

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `##key=value` 能正确提取 | 发送 `已完成 ✅ R115 Step 2##tech_plan_url=xxx` → 检查 `pipeline_contexts.json` 中 `artifacts["step2"]["tech_plan_url"]` 为 `"xxx"` |
| 2 | 无 `##` 时正常推进 | 发送 `已完成 ✅ R115 Step 3` → Step 推进，artifacts 为空 |
| 3 | 含 `=` 的 URL 不被截断 | `##url=https://example.com?a=1&b=2` → value 完整 |
| 4 | 多段 `##` 全部提取 | 4 段 kv 全部出现在 artifacts 中 |
| 5 | 上一步 artifacts 注入下一步模板 | Step 2 产出的 tech_plan_url 出现在 Step 3 派活消息中 |
| 6 | 空 value 被接受 | `##key=` → artifacts 中 value 为 `""` |
| 7 | 不合法段被忽略 | `##noequalsign` → 不写入，不报错 |
| 8 | 旧数据不丢失 | 已有 artifacts 字段（如 `step2`）追加新轮次数据时保持原数据 |

---

## 四、涉及文件

| 文件 | 改动量 | 说明 |
|:-----|:------:|:-----|
| `server/ws_server/main.py` | ~+40/-5 | `_try_advance_pipeline()` 中增加 `##` 键值对提取逻辑，增加辅助函数 `_extract_artifact_kv(content)` |
| `server/ws_server/pipeline_context.py` | ~+5 | 确认 `artifacts` 字段序列化正常（已有），可能无需改动 |
| `tests/test_r115_artifact_inject.py` | 新增 | 验收测试 8 项 |

---

## 五、风险与注意事项

- `##` 在消息模板中已用作 `##start##R{N}` 的分隔符，但 Step 完成消息中的 `##` 和命令消息中的 `##` 处于不同前缀分支（`已完成 ✅` vs `##`），无冲突
- URL 中可能含 `##`（GitHub commit URL 片段标识），但 Step 完成消息的 `##` 用于嵌入 `key=value`，URL 如果是 `##key=value` 格式会被误解析——约束：**value 中不应含 `##`**，URL 作为完整值传递即可

---

## 六、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:-----|
| v1.0 | 2026-07-14 | R115 初稿 — `##` 键值对提取 + artifacts 落盘 |
