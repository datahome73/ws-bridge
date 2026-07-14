# R115 管线 Step 产出上下文注入 — 需求文档

> **轮次：** R115
> **类型：** 功能开发轮
> **PM：** 小谷
> **基线：** [R114 协议](https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/R114/R114-inbox-communication-protocol-skill.md) — 8 场景 `##key=value` 完成消息格式

---

## 一、背景

R114 已定义管线全流程中 8 个场景下 bot 向 `_inbox:server` 发送的完成消息格式和 `##key=value` 嵌入规范（见 §二协议引用）。

R115 在 ws-bridge server 端实现对上述格式的**正则解析 + `##` 键值对提取 + 注入 PipelineContext.artifacts**，完成「提取→落盘→注入」链路。

当前 `_try_advance_pipeline()` 已能识别 `已完成 ✅ R{N} Step {N}` 前缀并自动推进 Step，但丢弃了 `##key=value` 部分。R115 补全此链。

---

## 二、R114 协议引用（各场景完成消息格式）

> 以下协议来自 R114 定稿，R115 需按此逐场景实现解析注入。各角色在编码时对照自己的 Step 即可。

### 场景总表

| 场景 | Step | 发送者 | 消息前缀 | `##` keys |
|:-----|:----:|:-------|:---------|:----------|
| A — 创建管线 | — | PM | `##start##R{N}` | `round_title`, `requirements_url` |
| B — 工作计划提交 | 1 | PM | `已完成 ✅ R{N} Step 1` | `work_plan_url` |
| C — 设计方案提交 | 2 | 小开 | `已完成 ✅ R{N} Step 2` | `tech_plan_url`, `design_decision` |
| D — 编码提交 | 3 | 爱泰 | `已完成 ✅ R{N} Step 3` | `commit_sha`, `files_changed`, `commit_description`, `branch_name` |
| E — 代码审查提交 | 4 | 小周 | `已完成 ✅ R{N} Step 4` | `review_report_url`, `review_decision` |
| F — 测试报告提交 | 5 | 泰虾 | `已完成 ✅ R{N} Step 5` | `test_result`, `test_report_url`, `test_commit_sha` |
| G — 合并部署 | 6 | 小爱 | `已完成 ✅ R{N} Step 6` | `merge_commit_sha`, `deploy_version` |
| H — 关闭管线 | — | PM | `##stop##R{N}` | （无） |

### 各 Step 完成消息示例

**Step 1（PM — 工作计划提交）：**
```
已完成 ✅ R115 Step 1##work_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/WORK_PLAN.md
```

**Step 2（小开 — 设计方案提交）：**
```
已完成 ✅ R115 Step 2##tech_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-tech-plan.md##design_decision=重构 handler 为纯函数模式
```

**Step 3（爱泰 — 编码提交）：**
```
已完成 ✅ R115 Step 3##commit_sha=abc1234def5678##files_changed=server/main.py,server/handler.py##commit_description=Add pipeline auto-archive feature##branch_name=dev
```

**Step 4（小周 — 代码审查提交）：**
```
已完成 ✅ R115 Step 4##review_report_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-review-report.md##review_decision=通过
```

**Step 5（泰虾 — 测试报告提交）：**
```
已完成 ✅ R115 Step 5##test_result=PASS##test_report_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-test-report.md##test_commit_sha=def5678
```

**Step 6（小爱 — 合并部署）：**
```
已完成 ✅ R115 Step 6##merge_commit_sha=ghi9012##deploy_version=v2.73
```

---

## 三、功能需求

### 3.1 `##` 键值对提取（通用函数）

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
| 3 | 对 parts[1:] 每段按第一个 `=` 分割为 key 和 value |
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

### 3.2 建议的函数签名

将提取逻辑抽出为独立函数，便于测试和后续维护：

```python
def _extract_artifact_kv(content: str) -> dict[str, str]:
    """从 '已完成 ✅ R{N} Step {N}##key=value##...' 中提取键值对。
    
    Args:
        content: 完整的完成消息文本
    
    Returns:
        提取的键值对 dict（不含 Step/round 信息）
    """
    parts = content.split("##")
    result = {}
    for p in parts[1:]:  # 跳过 parts[0]（前缀段）
        if "=" in p:
            key, value = p.split("=", 1)
            key = key.strip()
            if key:
                result[key] = value
        else:
            logger.warning("[R115] 忽略不含 '=' 的 ## 段: %s", p[:50])
    return result
```

然后在 `_try_advance_pipeline()` 中调用：

```python
kv = _extract_artifact_kv(content)
if kv:
    step_key = f"step{completed_step}"
    ctx.artifacts[step_key] = kv
    mgr.save()
```

### 3.3 artifacts 数据结构

`PipelineContext.artifacts` 是 `dict[str, dict]`，key 为 `"step2"`, `"step3"` 等，value 为该步产出的 KV：

```json
{
  "artifacts": {
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
}
```

### 3.4 模板变量注入（验证现有逻辑）

`_render_template()` 中已有 `vars.update(step_artifacts)` 逻辑，R115 **仅验证** 新写入的 artifacts 能正确被后续派活模板消费。

**验证方法：**
1. 构造一个包含 `{tech_plan_url}` 的 step3 派活模板
2. 模拟 Step 2 完成消息写入 `artifacts["step2"]["tech_plan_url"]`
3. 确认自动派活 Step 3 时 `{tech_plan_url}` 被替换为正确 URL

### 3.5 不修改的模块

| 模块 | 原因 |
|:-----|:------|
| `_handle_hash_cmd`（##start） | 已有完整的 kv 解析逻辑 |
| `_auto_dispatch` | 派活逻辑不变，仅消费 artifacts |
| `_handle_server_relay` 前缀匹配规则 | 不变 |
| `_render_template` 渲染逻辑 | 仅验证不变 |

---

## 四、验收标准

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | Step 2 `tech_plan_url` 能正确提取 | 发送 `已完成 ✅ R115 Step 2##tech_plan_url=xxx##design_decision=yyy` → `pipeline_contexts.json` 中 `artifacts.step2.tech_plan_url` = `"xxx"`, `design_decision` = `"yyy"` |
| 2 | Step 3 `commit_sha+files_changed+branch_name` 提取 | 发送 Step 3 完成消息 → artifacts.step3 含全部 4 字段 |
| 3 | Step 4 `review_report_url+review_decision` 提取 | 发送 Step 4 完成消息 → artifacts.step4 含 2 字段 |
| 4 | Step 5 `test_result+test_report_url` 提取 | 发送 Step 5 完成消息 → artifacts.step5 含 test_result=PASS |
| 5 | Step 6 `merge_commit_sha` 提取 | 发送 Step 6 完成消息 → artifacts.step6.merge_commit_sha 正确 |
| 6 | 无 `##` 时正常推进 | 发送 `已完成 ✅ R115 Step 3` 不带 `##` → Step 推进，artifacts 为空 |
| 7 | 含 `=` 的 URL 不被截断 | `##url=https://example.com?a=1&b=2` → value 完整 |
| 8 | 空 value 被接受 | `##key=` → artifacts 中 value 为 `""` |
| 9 | 不合法段被忽略 | `##noequalsign` → 不写入，不报错，Step 正常推进 |
| 10 | 旧数据不丢失 | 先写入 `step2` 数据，再推进 Step 3 写入 `step3` → `step2` 数据仍完整 |

---

## 五、涉及文件

| 文件 | 改动量 | 说明 |
|:-----|:------:|:-----|
| `server/ws_server/main.py` | ~+40/-5 | 增加 `_extract_artifact_kv()` 辅助函数 + `_try_advance_pipeline()` 中调用写入 |
| `server/ws_server/pipeline_context.py` | ~+0 | 确认 `artifacts` 字段序列化正常（已有 `field(default_factory=dict)`），无需改动 |
| `tests/test_r115_artifact_inject.py` | 新增 ~80 行 | 验收测试 10 项 |

---

## 六、风险与注意事项

- **`##` 前缀冲突风险：** `##` 在 `##start##R{N}` 命令中也用作分隔符，但 Step 完成消息以 `已完成 ✅` 开头，命令消息以 `##` 开头，二者处于不同前缀匹配分支，无冲突
- **URL 含 `##` 问题：** GitHub commit URL 片段标识可能包含 `##`，但 Step 完成消息的 `##` 用于分隔键值对。约束：**value 中不应含 `##`**，URL 作为完整值传递即可；如果 URL 需要含 `##`，应使用 URL 编码 `%23`
- **向后兼容：** 旧有 `已完成 ✅` 消息不带 `##` 的部分不受影响，`_extract_artifact_kv()` 返回空 dict，`ctx.artifacts` 不上新数据

---

## 七、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:-----|
| v1.0 | 2026-07-14 | R115 初稿 |
| v1.1 | 2026-07-14 | 补全 R114 协议引用（8 场景全表 + 各 Step 完成消息示例） |
