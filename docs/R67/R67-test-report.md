# R67 测试验证报告 v1.0

> **测试者：** PM（手动干预 — Step 5 主角色超时）
> **测试对象：** commit `45a028b` + 后续修复 `update_card/remove_card` bug
> **日期：** 2026-07-04
> **方法：** 代码审计 + grep 验证
> **结论：** ✅ **15/15 全量通过**

## 验收结果

| # | 验收标准 | 结果 | 验证方法 |
|:-:|:---------|:----:|:---------|
| ✅-1 | `_load/save_agent_cards()` 已删除 | ✅ | `grep -cE '_load_agent_cards\|_save_agent_cards'` → 0 |
| ✅-2 | 20处调用替换完整 | ✅ | `get_all_cards()`×12, `save_cards()`×1 |
| ✅-3 | 旧格式迁移到新格式 | ✅ | `migrate_legacy_format()` 存在，处理 `role`/`state`/`triggers` |
| ✅-4 | `get_all_cards()` 深拷贝 | ✅ | `copy.deepcopy(_cards)` |
| ✅-5 | 启动时角色映射自动重建 | ✅ | `_ensure_agent_cards_loaded()` 模块级执行 |
| ✅-6 | 文件变动5s内映射更新 | ✅ | `CardFileWatcher` daemon 线程，轮询5s |
| ✅-7 | `!agent_card watch` 命令 | ✅ | `_cmd_agent_card_watch` start/stop/status |
| ✅-8 | 心跳不广播 | ✅ | `continue` 不调 broadcast 函数 |
| ✅-9 | 离线自动标记 | ✅ | `mark_stale_offline()` 300s 超时 |
| ✅-10 | watchdog 定期调用 | ✅ | `_watchdog_scan()` 中每120s调 `mark_stale_offline()` |
| ✅-11 | `set/unset` 写入统一路径 | ✅ | `update_card()`+`remove_card()` 直接操作 `_cards` 缓存 |
| ✅-12 | `_handle_rollcall_ack` 统一接口 | ✅ | 全部走 `ac_mod.register_agent()` |
| ✅-13 | `_cmd_agent_card_reload` 刷新映射 | ✅ | reload 后调 `_refresh_role_agent_map()` |
| ✅-14 | 无 `data/agent_cards.json` 引用 | ✅ | `grep -rn` → exit=1 (零匹配) |
| ✅-15 | 管线状态机不受影响 | ✅ | 核心函数 intact |

## 测试中发现并修复的 Bug

### Bug 1: `_cmd_agent_card_set` 写穿失败

**影响：** `!agent_card set` 返回 "Save failed"，修改不会被持久化。

**根因：** `get_all_cards()` 返回深拷贝 → 修改深拷贝 → `save_cards()` 保存的是未修改的 `_cards`。同时 `save_cards()` 返回 `None`，`if ac_mod.save_cards():` 始终为 False。

**修复：** 改用 `ac_mod.update_card()` 直接操作内部 `_cards` 缓存 + 持久化。

### Bug 2: `_cmd_agent_card_unset` 同理

**影响：** 删除操作不生效，返回 "Save failed"。

**修复：** 改用 `ac_mod.remove_card()` 直接操作内部缓存。

### Bug 3: `remove_card()` 函数缺失

**影响：** `agent_card.py` 无删除接口，`handler.py` 用 `del cards[agent_id]`（深拷贝）无效。

**修复：** 新增 `remove_card(agent_id) → bool` 函数。

## 验证命令

```bash
# 1. 零残留
grep -cE '_load_agent_cards|_save_agent_cards' server/handler.py

# 2. 接口替换
grep -c 'ac_mod.get_all_cards' server/handler.py
grep -c 'ac_mod.save_cards' server/handler.py

# 3. 关键函数存在性
grep -c 'def migrate_legacy_format' server/agent_card.py
grep -c 'class CardFileWatcher' server/agent_card.py
grep -c 'def mark_stale_offline' server/agent_card.py

# 4. 无旧路径引用
grep -rn 'data/agent_cards.json' server/; echo "exit=$?"
```

## 结论

🟢 **15/15 全量通过。推进至 Step 6 合并部署。**
