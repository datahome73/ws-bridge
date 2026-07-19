# R129 Bug 记录

> 发现于 R129 管线运行中（2026-07-19）

## B-5: `{round}` 模板占位符在 PipelineEngine.auto_dispatch 中未替换

**现象：** 派活消息中 `{round}` 字面量原样输出，例如 `💻 {round} Step 3 — 编码实现`，未替换为 `R129`。

**根因：** 新旧两套 `render_template` 占位符不兼容：

| 函数 | 位置 | 占位符 |
|:-----|:-----|:--------|
| `_render_template()` | `main.py:2835`（旧）| `{round}`, `{round_title}` |
| `PipelineEngine.render_template()` | `pipeline_engine.py:211`（新）| `{round_name}`, `{round_title}` |

`!pipeline_start` 创建的模板使用 `{round}`（旧格式），但 Step 1 完成后走 `PipelineEngine.try_advance()` → `PipelineEngine.auto_dispatch()`，后者调用 `self.render_template()`（新）只认 `{round_name}`，`{round}` 被跳过。

**影响范围：** Step 2+ 的派活消息全部缺轮次信息。

**修复方案（二选一）：**
1. `PipelineEngine.render_template()` 增加 `{round}` → `ctx.round_name` 别名
2. 或 `!pipeline_start` 的模板改为 `{round_name}`

## B-6: 派活消息显示 2 遍（B-1 复发）

**现象：** `系统 → 小开` 的派活消息在对话中出现 2 次。

**根因（待确认）：** 疑似 `_sm_handle_complete`（Rule 50）→ `PipelineEngine.try_advance` → `PipelineEngine.auto_dispatch` 与遗留旧路径 `_try_advance_pipeline` 之间存在双重触发。需进一步排查是否两条路径都被调用。

**修复方向：** 确认 `PipelineEngine.try_advance` 是唯一推进路径后，移除或废弃旧的 `_try_advance_pipeline` / `_auto_dispatch`（main.py 中的模块级函数）。

## B-7: `##start`/`##status`/`##advance` 等命令对非 PM 角色静默无响应

**现象：** 临时 bot 发送 `##status##R129`、`##start##R{N}` 到 `_inbox:server` 无任何回复（不报错、不回显）。`##help` 正常工作。

**根因：** `scenario_matcher.py` `handle_hash_cmd()` 中：
```python
from .pipeline_engine import PipelineEngine
_engine: PipelineEngine = None  # type: ignore
```
局部变量 `_engine = None` 覆盖了 `main.py` 注入的模块级 `_engine`（`_sm._engine = _ensure_engine()`），导致所有非 `##help` 命令的 `if _engine else False` 始终为 False。

**影响范围：** `##start`、`##status`、`##stop`、`##advance`、`##archive` 全部不可用。

**修复方案：** 改回 `main` 分支的正确写法——`from . import main as _main; await _main._handle_hash_*(...)`。

> 注意：`main` 分支（`98752f8` R126）的 `scenario_matcher.py` 代码是正确的；R127（`02690c3`）提取 PipelineEngine 模块时引入了此回归。
