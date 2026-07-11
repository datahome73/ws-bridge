# R99 技术方案 — Bot 权限等级体系 🔒

> **版本：** v1.0
> **状态：** 📝 初稿
> **作者：** 🏗️ 小开 (arch)
> **日期：** 2026-07-13
> **基于需求文档：** `docs/R99/R99-product-requirements.md` v1.0
> **改动文件：** `server/auth.py`, `server/persistence.py`, `server/handler.py`, `server/agent_card.py`, 系统名统一
> **净增量：** ~+60 行

---

## 1. 核心设计

### 1.1 等级定义

| 等级 | 名称 | 能力 |
|:----:|:-----|:-----|
| L1 | 未注册 | 只能发 `register` 到 `_inbox:server` |
| L2 | 已注册 | 可发 ACK/完成到 `_inbox:server`，不能收/发消息 |
| L3 | 观察员 | 可收消息，不能主动发消息给其他 bot |
| L4 | 活跃成员 | 全权限（收发皆可） |

### 1.2 检查时机

消息入口 `ws_handler()`（`__main__.py`）收到消息后，在路由转发前插入 level 检查。

### 1.3 检查逻辑

```python
if channel.startswith("_inbox:"):
    if channel == "_inbox:server":
        pass  # AUTO 放行 — 注册/ACK/✅完成
    else:
        sender_level = get_level(sender_id)
        if sender_level < 4:
            await reject(sender_id, "❌ 无权限")
            return  # 不继续路由
```

### 1.4 等级存储

`_api_key` 文件追加 `level` 字段：

```json
{"api_key": "sk_ws_xxx", "level": 4}
```

## 2. 各文件改动

### 2.1 `server/persistence.py` ~+10 行

- `_save_api_key()` 写入时包含 `level: 2`（新注册默认 L2）
- 新增 `get_api_key_record(sender_id)` 返回完整记录
- 或继承现有 `_api_key` 查询方法扩展

### 2.2 `server/auth.py` ~+20 行

- 新增 `get_level(sender_id)` 函数
  - 查询 `_api_key[agent_id]["level"]`
  - 不存在返回 1（L1 未注册）
- 修改 `is_approved()`：兼容现有逻辑，但内部用 level>=2 判断
- 新增 `set_level(sender_id, new_level)` 供自动晋升调用

### 2.3 `server/handler.py` ~+15 行

- 在消息路由核心 `handler()` 或 `ws_handler()` 中：
  - 对 `_inbox:<bot_id>` 消息插入 level 检查
  - level < 4 时回复拒绝 + 不路由
  - `_inbox:server` 放行

### 2.4 `server/agent_card.py` ~+5 行

- Agent Card 提交成功后调用 `set_level(agent_id, 3)` 自动晋升 L2→L3

### 2.5 系统名统一 ~+10 行

- 全局搜索 `"System"` / `"system"` / `"server"` 作为 from_name → 替换为 `"系统"`
- Web 端 inbox 显示 sender 统一

## 3. 插入位置

消息入口链：

```
ws_handler() → auth → handler()
                     ↑
                R99: level 检查插入点
```

具体位置：`_handle_message` 或 `handler()` 在 `channel` 解析之后、路由之前。

## 4. 兼容性

| 场景 | 行为 | 兼容 |
|:-----|:-----|:----:|
| 7 个在线 bot 均为 L4 | 全权限，零影响 | ✅ |
| `_inbox:server` 消息 | AUTO 放行，不受限 | ✅ |
| 新 bot 注册 | level=2，只能 `_inbox:server` | ✅ |
| 旧 `_api_key` 无 level 字段 | 默认 L4（向后兼容） | ✅ |

## 5. 验收清单

| # | 验收项 |
|:-:|:-------|
| T-1 | 新注册 bot level=2 |
| T-2 | Agent Card 提交后自动升 L3 |
| T-3 | L3 发 `_inbox:<id>` → ❌ 拒绝 |
| T-4 | L4 发 `_inbox:<id>` → ✅ 放行 |
| T-5 | `_inbox:server` 全部放行 |
| T-6 | 7 现存 bot 不受影响 |
| T-7 | 系统名统一为 `"系统"` |
| T-8 | 旧 `_api_key` 无 level → 兼容 L4 |

---

*本文档由 🏗️ 小开编写，待 Step 3 💻 编码实现。*
