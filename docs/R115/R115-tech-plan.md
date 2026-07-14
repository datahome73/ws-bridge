# R115 Step 2 — 管线 Step 产出上下文注入技术方案

> **轮次：** R115
> **版本：** v1.0
> **日期：** 2026-07-15
> **设计角色：** 小开（架构师）
> **实现角色：** 爱泰（开发工程师）
>
> **需求文档：** [R115-product-requirements.md](https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/R115/R115-product-requirements.md)
> **协议参考：** [R114-inbox-communication-protocol-skill.md](https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/R114/R114-inbox-communication-protocol-skill.md)

---

## 一、概述

### 1.1 现状

`_try_advance_pipeline()` 已通过正则 `r"已完成 ✅ R(\d+) Step (\d+)"` 识别完成消息并自动推进 Step + 派活下一步，但 **丢弃了 `##key=value` 部分**。

`_render_template()` 已支持读取 `ctx.artifacts`（第 1 优先级变量源），但 artifacts 从未被写入——模板变量机制就绪，管道未接通。

### 1.2 R115 链路

```
Bot 回复 _inbox:server:
  已完成 ✅ R115 Step 2##tech_plan_url=URL##design_decision=xxx
                                ↓
_try_advance_pipeline(content)
  ├─ regex 匹配 round_name / step_num  ✓ (现有)
  ├─ _extract_artifact_kv(content)     ⬅ 新增
  │    └─ split("##") → 解析 key=value
  ├─ ctx.artifacts["step2"] = kv        ⬅ 写入
  ├─ mgr.save()                         ⬅ 持久化
  ├─ mgr.advance_step()                 ✓ (现有)
  └─ _auto_dispatch(ctx, 3)             ✓ (现有)
                                              ↓
                                         下一步派活模板中 {tech_plan_url} 自动填充
```

### 1.3 改动范围

| 文件 | 改动量 | 说明 |
|:-----|:------:|:-----|
| `server/ws_server/main.py` | **+20/-0** | 新增 `_extract_artifact_kv()` + `_try_advance_pipeline()` 中 ~5 行调用 |
| `server/ws_server/pipeline_context.py` | **+0** | 已有 `artifacts: dict = field(default_factory=dict)`，`to_dict()` 已序列化 |
| `tests/test_r115_artifact_inject.py` | 新增 ~60 行 | 10 项验收测试 |

### 1.4 零改动文件

| 文件 | 原因 |
|:-----|:------|
| `_render_template()` | 已支持 `ctx.artifacts` 变量注入，仅验证 |
| `_auto_dispatch()` | 派活逻辑不变 |
| `_handle_server_relay()` | 前缀匹配规则不变 |
| `_handle_hash_cmd()` | `##start` 已有独立 kv 解析逻辑 |
| `command_utils.py` | 无广播需求 |
| `config.py` | 无需新增配置项 |

---

## 二、函数设计

### 2.1 `_extract_artifact_kv(content: str) -> dict[str, str]`

**位置：** `_try_advance_pipeline()` 附近，紧贴其上方

**输入：** 完整的完成消息文本
```
"已完成 ✅ R115 Step 2##tech_plan_url=URL##design_decision=xxx"
```

**输出：** 键值对 dict（不含 Step/round 信息）
```json
{
  "tech_plan_url": "URL",
  "design_decision": "xxx"
}
```

**伪代码：**
```python
def _extract_artifact_kv(content: str) -> dict[str, str]:
    """从 '已完成 ✅ R{N} Step {N}##key=value##...' 中提取键值对。"""
    parts = content.split("##")
    result = {}
    for p in parts[1:]:  # parts[0] 是前缀段，跳过
        if "=" in p:
            key, value = p.split("=", 1)  # 仅第一个 = 做分隔
            key = key.strip()
            if key:
                result[key] = value
        else:
            logger.debug("[R115] 忽略不含 '=' 的 ## 段: %s", p[:50])
    return result
```

### 2.2 `_try_advance_pipeline()` 修改

**改动位置：** 在 `ctx = mgr.get(round_name)` 之后、`mgr.advance_step()` 之前插入：

```python
# ═══ R115: 提取 ##key=value 并注入 artifacts ═══
_kv = _extract_artifact_kv(content)
if _kv:
    _step_key = f"step{completed_step}"
    if not hasattr(ctx, 'artifacts') or not ctx.artifacts:
        ctx.artifacts = {}
    ctx.artifacts[_step_key] = _kv
    mgr.save()
    logger.info("[R115] %s step%d artifacts: %s", round_name, completed_step, _kv)
# ════════════════════════════════════════════════════════
```

### 2.3 边界处理矩阵

| 场景 | content | parts | 行为 |
|:-----|:--------|:------|:------|
| 无 `##` | `已完成 ✅ R115 Step 3` | `["已完成 ✅ R115 Step 3"]` | `parts[1:]` 为空 → 返回 `{}` → 不写入 |
| 单个键值 | `已完成 ✅ R115 Step 2##url=X` | `["前缀","url=X"]` | 正常提取 `{url: "X"}` |
| 多个键值 | `已完成 ✅ R115 Step 3##a=1##b=2` | `["前缀","a=1","b=2"]` | 正常提取 `{a:"1", b:"2"}` |
| URL 含 `=` | `##url=https://ex.com?a=1` | `["前缀","url=https://ex.com?a=1"]` | `split("=",1)` → 正确截取 `url=https://ex.com?a=1` |
| 空 value | `##key=` | 段 `"key="` | `split("=")` → `("key","")` → `{key: ""}` |
| 无 `=` | `##justtext` | 段 `"justtext"` | 不进入 if → 忽略，log debug |
| 空 key | `##=value` | 段 `"=value"` | `split("=")` → `("","value")` → `key=""` → `if key:` 跳过 |
| URL 含 `##` | `##url=x##y` | `["前缀","url=x","y"]` | 被误分割。约定：**value 不应含裸 `##`**，使用 `%23` 编码 |
| 同 key 重复 | `##key=A##key=B` | `["前缀","key=A","key=B"]` | 后者覆盖前者 |
| 特殊字符 | `##msg=已完成 ✅` | `["前缀","msg=已完成 ✅"]` | `✅` 等 Unicode 正常保留 |

---

## 三、`artifacts` 数据结构

### 3.1 `PipelineContext.artifacts` Schema

```python
# 在 PipelineContext dataclass 中（已有）
artifacts: dict = field(default_factory=dict)
```

**结构（JSON 布局）：**
```json
{
  "step2": {
    "tech_plan_url": "https://raw.githubusercontent.com/.../R115-tech-plan.md",
    "design_decision": "提取为独立函数，注入 artifacts 字典"
  },
  "step3": {
    "commit_sha": "abc1234def5678",
    "files_changed": "server/ws_server/main.py",
    "commit_description": "R115: 上下文注入实现",
    "branch_name": "dev"
  },
  "step4": {
    "review_report_url": "https://raw.githubusercontent.com/.../R115-review-report.md",
    "review_decision": "通过"
  },
  "step5": {
    "test_result": "PASS",
    "test_report_url": "https://raw.githubusercontent.com/.../R115-test-report.md",
    "test_commit_sha": "def5678"
  },
  "step6": {
    "merge_commit_sha": "ghi9012",
    "deploy_version": "v2.73"
  }
}
```

### 3.2 `_render_template()` 变量优先级（已实现）

| 优先级 | 来源 | 变量名 |
|:------:|:-----|:-------|
| 1 (高) | `artifacts[任意step]` | `tech_plan_url`, `commit_sha`, ... |
| 2 | `references` | `requirements_url`, `work_plan_url` |
| 3 (低) | 基础字段 | `round`, `round_title` |

**验证：** `_render_template()` 已有 `vars.update(step_artifacts)` 逻辑，**零改动**，仅需确认。

---

## 四、测试方案（10 项验收）

### 4.1 单元测试策略

使用直接函数调用测试 `_extract_artifact_kv()`（纯函数，无 IO 依赖）：

```python
class TestExtractArtifactKv:
    """R115: _extract_artifact_kv 纯函数测试（10 项验收）"""

    def test_v1_c_step2_extract(self):
        """验收1: Step2 tech_plan_url+design_decision 正确提取"""
        content = "已完成 ✅ R115 Step 2##tech_plan_url=xxx##design_decision=yyy"
        result = _extract_artifact_kv(content)
        assert result["tech_plan_url"] == "xxx"
        assert result["design_decision"] == "yyy"

    def test_v2_d_step3_multiple_keys(self):
        """验收2: Step3 全部4字段"""
        content = "已完成 ✅ R115 Step 3##commit_sha=abc##files_changed=a.py,b.py##commit_description=feat: x##branch_name=dev"
        result = _extract_artifact_kv(content)
        assert result["commit_sha"] == "abc"
        assert result["files_changed"] == "a.py,b.py"
        assert result["commit_description"] == "feat: x"
        assert result["branch_name"] == "dev"

    def test_v3_e_step4_two_keys(self):
        """验收3: Step4 review_report_url+review_decision"""
        content = "已完成 ✅ R115 Step 4##review_report_url=https://example.com/report.md##review_decision=通过"
        result = _extract_artifact_kv(content)
        assert result["review_report_url"] == "https://example.com/report.md"
        assert result["review_decision"] == "通过"

    def test_v4_f_step5_test_result(self):
        """验收4: Step5 test_result=PASS"""
        content = "已完成 ✅ R115 Step 5##test_result=PASS##test_report_url=https://example.com/report.md"
        result = _extract_artifact_kv(content)
        assert result["test_result"] == "PASS"

    def test_v5_g_step6_merge_sha(self):
        """验收5: Step6 merge_commit_sha"""
        content = "已完成 ✅ R115 Step 6##merge_commit_sha=ghi9012##deploy_version=v2.73"
        result = _extract_artifact_kv(content)
        assert result["merge_commit_sha"] == "ghi9012"
        assert result["deploy_version"] == "v2.73"

    def test_v6_no_hash_noop(self):
        """验收6: 无 ## 时返回空 dict"""
        content = "已完成 ✅ R115 Step 3"
        result = _extract_artifact_kv(content)
        assert result == {}

    def test_v7_url_with_equals_untouched(self):
        """验收7: URL 含 = 不被截断"""
        content = "已完成 ✅ R115 Step 2##url=https://example.com?a=1&b=2"
        result = _extract_artifact_kv(content)
        assert result["url"] == "https://example.com?a=1&b=2"

    def test_v8_empty_value_accepted(self):
        """验收8: 空 value 被接受"""
        content = "已完成 ✅ R115 Step 2##key="
        result = _extract_artifact_kv(content)
        assert result["key"] == ""

    def test_v9_invalid_segment_ignored(self):
        """验收9: 无 = 段被忽略"""
        content = "已完成 ✅ R115 Step 2##valid=ok##noequalsign"
        result = _extract_artifact_kv(content)
        assert "valid" in result
        assert "noequalsign" not in result
        assert len(result) == 1

    def test_v10_old_data_preserved(self):
        """验收10: 多次写入不覆盖旧 step"""
        # 模拟连续写入
        mgr = ...  # 集成测试场景
        # Step1 写入后 → Step2 写入 → Step1 数据仍在
```

### 4.2 集成测试策略

| 验收 # | 方法 |
|:------:|:------|
| 1-5 | 直接调用 `_extract_artifact_kv()` + 断言返回 dict |
| 6 | 空输入 → 空 dict |
| 7 | 构造含 `=` URL → 完整保留 |
| 8 | 空 value → 接受 |
| 9 | 无效段 → 忽略 |
| 10 | 模拟连续 call → 不丢旧 step |

顶层 `_try_advance_pipeline` 的集成测试：
```python
async def test_full_inject_flow():
    """模拟完整链路：完成消息 → step 推进 + artifacts 写入 + 持久化"""
    round_name = "R115test"
    # 1. 创建管线
    mgr = _ensure_pipeline_manager()
    ctx = create_test_pipeline(round_name)
    mgr.set_context(round_name, ctx)
    
    # 2. 发送完成消息（模拟 _try_advance_pipeline）
    content = f"已完成 ✅ {round_name} Step 1##work_plan_url=https://example.com/WORK_PLAN.md"
    success, name = _try_advance_pipeline(content, "ws_test_agent")
    assert success
    
    # 3. 验证
    ctx = mgr.get(round_name)
    assert ctx.artifacts.get("step1", {}).get("work_plan_url") == "https://example.com/WORK_PLAN.md"
    assert ctx.current_step == 2  # 推进到了 Step 2
```

---

## 五、风险分析

### 5.1 `##` 前缀冲突

| 场景 | 前缀 | 路由分支 | 风险 |
|:-----|:------|:----------|:-----|
| `##start##R{N}` | `##` | `_handle_hash_cmd`（规则前插，PM 守卫前） | ❌ 无冲突，不同分支 |
| `已完成 ✅ R{N} Step N##k=v` | `已完成 ✅` | `_try_advance_pipeline`（规则 2） | ❌ 无冲突，不同分支 |
| `##help` | `##` | `_handle_hash_cmd` | ❌ 无冲突 |

**结论：** `##` 在 `_handle_hash_cmd` 中是**命令 delimiter**，在完成消息中是 **键值分隔符**。二者处于不同的前缀匹配分支（`content.startswith("##")` vs `content.startswith("已完成 ✅")`），**零冲突**。

### 5.2 URL 含裸 `##`

GitHub URL 片段标识符使用 `#`（如 `#L42`）。如果 URL 含 `#`，不被 `##` 匹配器影响。但如果 value 中含裸 `##`：

| value | split("##") 结果 | 问题 |
|:------|:----------------|:------|
| `https://ex.com/doc.md#section` | `["前缀","url=https://ex.com/doc.md","section"]` | ✅ `#` 不是 `##`，无影响 |
| `https://ex.com/doc.md##section` | `["前缀","url=https://ex.com/doc.md","section"]` | ❌ 被误分割 |

**约定：value 中不应含裸 `##`**。如果 URL 片段需用 `#`，自然单个 `#` 安全。如果真需传递 `##`，使用 URL 编码 `%23%23`。

### 5.3 向后兼容

| 场景 | 行为 |
|:-----|:------|
| 旧完成消息无 `##` | `_extract_artifact_kv()` 返回 `{}` → `ctx.artifacts` 不更新 → 推进正常 |
| 已完成管线的 artifacts | 旧管线 artifacts 为 `{}` 或部分数据 → 不受影响 |
| 重复 `##start` | 已由 `mgr.exists()` 拦截，不涉及 |

### 5.4 数据写入时机

当前 `_try_advance_pipeline()` 使用 `asyncio.ensure_future(mgr.advance_step(...))` **异步推进**。R115 的 artifacts 写入应在 `ensure_future` **之前**同步完成，确保推进前数据已持久化：

```python
# ✅ 正确的插入顺序（同步→异步）
_kv = _extract_artifact_kv(content)       # 同步：提取
if _kv:
    ctx.artifacts[step_key] = _kv         # 同步：写入内存
    mgr.save()                            # 同步：持久化
asyncio.ensure_future(mgr.advance_step()) # 异步：推进
```

---

## 六、验收与验证

| # | 验收项 | 测试方法 | 通过条件 |
|:-:|:-------|:---------|:---------|
| V-1 | Step2 KV 提取 | 调用 `_extract_artifact_kv()` | 返回 `{tech_plan_url:xxx, design_decision:yyy}` |
| V-2 | Step3 多字段 | 同上 | 返回 4 字段 |
| V-3 | Step4 两字段 | 同上 | 返回 2 字段 |
| V-4 | Step5 test_result | 同上 | `test_result` = `PASS` |
| V-5 | Step6 merge_sha | 同上 | `merge_commit_sha` 正确 |
| V-6 | 无 `##` 不报错 | 同上 | 返回 `{}` |
| V-7 | URL 含 `=` 完整 | 同上 | value 完整 |
| V-8 | 空 value | 同上 | value 为 `""` |
| V-9 | 无 `=` 被忽略 | 同上 | 仅有效 key 在结果中 |
| V-10 | 旧数据不覆盖 | 模拟多步写入 | Step2 写入后 Step3 写入不丢 Step2 |

---

## 七、部署步骤

1. 推 dev: 新增 `_extract_artifact_kv()` + `_try_advance_pipeline` 修改
2. 推测试文件: `tests/test_r115_artifact_inject.py`
3. 运行验收项 V-1 ~ V-10
4. 部署到生产：仅需重启容器（纯 Python 代码变更）

---

## 八、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-15 | 初稿 |
