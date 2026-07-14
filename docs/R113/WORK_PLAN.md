# R113 — 管线自动派活修复轮 🔧

> **轮次：** R113
> **auto_chain:** true
> **状态：** ⏳ 需求文档待审核
> **说明：** 修复管线状态机转换链路断裂（`INIT→RUNNING` 非法）+ 数据序列化脆弱性（`from_dict` 硬索引），使 `##start` 能真正自动派活
> **需求文档：** [R113-product-requirements.md](https://github.com/datahome73/ws-bridge/blob/main/docs/R113/R113-product-requirements.md)
> **审核记录：** v1.0 — 待审核

---

## 需求文档状态 ⏳ 待审核

- R113 需求文档 v1.0 已提交，等待项目负责人审核
- **审核期间不推 dev / 不 inbox 派活**

---

## 分工

| 角色 | 虾虾 | 职责 |
|:----:|:----:|:-----|
| 🏗️ 架构师 | 小开 | 技术方案确认（~8 行改动无需长篇方案，确认修复方向） |
| 💻 开发工程师 | 爱泰 | 编码实现（2 文件 ~8 行） |
| 🔍 审查工程师 | 小周 | 代码审查（重点：状态机完整性、向后兼容） |
| 🦐 测试工程师 | 泰虾 | Dev 测试 + **生产环境 ##start 全链路验证** |
| 🦸 项目管理 | 小爱 | 部署 + 合并维护 |

---

## 开发步骤

### Step 1 — 需求文档 ⏳ 待审核

> 产出：`docs/R113/R113-product-requirements.md`
> 状态：⏳ 等待项目负责人审核

### Step 2 — 技术方案 🏗️ 架构师（小开）

改动极小，在需求文档基础上确认 4 个修复方向即可：

| # | 确认项 | 方案 A | 方案 B |
|:-:|:-------|:-------|:-------|
| 1 | `INIT→RUNNING` 状态转换 | INIT 加 RUNNING（1 行） | 两步过渡 PLANNING→RUNNING |
| 2 | `from_dict` 后备值 | `.get()` 后备（5 行） | 同上 |
| 3 | `_load()` catch 类型 | 精确 +KeyError/ValueError | Exception 全覆盖 |
| 4 | `_auto_dispatch` step 搜索 | 优先 step_key 回退 name | 仅用 step_key |

### Step 3 — 方向审查 🧐 PM（小谷）

确认方案可行后转开发。

### Step 4 — 编码 💻 开发工程师（爱泰）

**改动清单（2 文件 ~8 行）：**

#### 4.1 `server/ws_server/pipeline_context.py`

**Bug 1:** `_VALID_TRANSITIONS[INIT]` 增加 `RUNNING`

```python
PipelineStatus.INIT: {PipelineStatus.PLANNING, PipelineStatus.RUNNING, PipelineStatus.CANCELLED},
```

**Bug 2:** `from_dict()` 5 处 `d["key"]` 改 `.get("key", default)`

| 行 | 当前 | 改为 |
|:--:|:-----|:-----|
| 223 | `d["round_name"]` | `d.get("round_name", "")` |
| 224 | `PipelineTaskKind(d["task_kind"])` | `PipelineTaskKind(d.get("task_kind", "dev"))` |
| 225 | `Path(d["workspace_dir"])` | `d.get("workspace_dir", "")` — Path 构造前判空 |
| 226 | `Path(d["task_dir"])` | `d.get("task_dir", "")` — Path 构造前判空 |
| 229 | `PipelineStatus(d["status"])` | `PipelineStatus(d.get("status", "init"))` |

**Bug 3:** `_load()` except 增加 `KeyError, ValueError`

```python
except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
```

#### 4.2 `server/ws_server/main.py`

**Bug 4:** `_auto_dispatch()` step 搜索优先 `step_key` 回退 `name`

```python
# 修改前
s.get("name") == next_step_key
# 修改后
s.get("step_key") or s.get("name") == next_step_key
```

> 注意：OR 优先级问题，实际应为 `(s.get("step_key") or s.get("name")) == next_step_key`

### Step 5 — 代码审查 🔍 审查工程师（小周）

**审查清单：**

| # | 审查项 | 严重度 |
|:-:|:-------|:------:|
| 1 | `_VALID_TRANSITIONS` 改动是否破坏其他合法路径 | 🔴 P0 |
| 2 | `from_dict` 后备值不掩盖真正数据异常 | 🔴 P0 |
| 3 | `_load()` catch 覆盖所有预期异常 | 🟡 P2 |
| 4 | `_auto_dispatch` step 搜索修改向后兼容 | 🟡 P2 |
| 5 | 4 个 Bug 全修，无遗漏 | 🔴 P0 |

### Step 6 — Dev 测试 🦐 测试工程师（泰虾）

**单元验证（代码改动后）：**

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 1 | `_VALID_TRANSITIONS[INIT]` 含 `RUNNING` | 读代码 |
| 2 | `from_dict` 无残留 `d["round_name"/"task_kind"/"workspace_dir"/"task_dir"/"status"]` | grep |
| 3 | `_load()` except 含 `KeyError, ValueError` | 读代码 |
| 4 | `_auto_dispatch` step 搜索优先 `step_key` | 读代码 |

**全链路验证（生产环境）：**

| # | 验收项 | 预期 |
|:-:|:-------|:------|
| 5 | `##start##R113` → 派活 Step 1 | 收到「✅ 已启动」，Step 1 bot 收到 |
| 6 | Step 1 完成后自动派活 Step 2 | 推进后下一 bot 收到 |
| 7 | `##stop##R113` | 状态变为 CANCELLED |

### Step 7 — 上线验证 🦸 项目管理（小爱）

| # | 验证项 |
|:-:|:-------|
| 1 | 生产环境 `##start##R113` Step 1 自动派活 |
| 2 | 全 6 步自动流转 |
| 3 | 测试管线停止归档 |

### Step 8 — 合并 main + 部署 🦸 项目管理（小爱）

1. 审查 + 测试通过 → 合并 dev → main
2. 重建 Docker 镜像 `ws-bridge:r113`
3. 重启生产容器
4. 健康检查通过 ✅

### Step 9 — 关闭工作室 🦸 项目管理（小爱）

全员 ACK → 归档轮次文档 → 各成员切回大厅待命。

---

## 注意事项

1. **改动虽小，验证必须彻底** — 必须在生产环境实测 `##start##R113` 全 6 步自动流转
2. **确认 `AUTO_DISPATCH_ENABLED` 生产值** — 默认为 True，但需确认未被环境变量覆盖
3. **旧数据已清空** — `pipeline_contexts.json` = `{}`，纯绿色启动

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-14 | 初稿 — R113 工作计划 |
