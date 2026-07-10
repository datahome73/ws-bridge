# R97 Step 4 重审 — 角色映射修复 🟢

> **审查人：** 🔍 小周
> **修复提交：** `db58688`
> **修复范围：** `server/auto_router.py` 仅 1 文件
> **原审查报告：** `docs/R97/R97-code-review.md`（🔴 退回）

---

## 重审结论：🟢 通过

修复方案 A（文件直接读取 `config/agent_cards.json`）正确实现，`_role_index` 不再为空。

---

## 修复验证

### 改动内容

| 改动 | 原代码 | 修复后 |
|:-----|:-------|:-------|
| `agent_card_path` | 无 | `__init__` 中设置 → `config/agent_cards.json` |
| `_refresh_role_map()` | 发 `!agent_card list` WS 查询，不读响应 | 直接 `open + json.load` 读取文件 |
| `_role_index` 更新 | 恒空 | `for agent_id, card: role_index.setdefault(role).append(agent_id)` |
| `short_map` | 缺 `operations` → admin 映射 | 补全 `pm` 映射 + 新增 `operations` 映射 |

### 角色解析全量验证（6/6 🟢）

| 默认 Step 角色 | 解析结果 | 匹配方式 | 状态 |
|:--------------|:---------|:---------|:----:|
| `pm` | `pm-bot` | `short_map(pm→product-manager)` | 🟢 |
| `arch` | `arch-bot` | `substring(architect)` | 🟢 |
| `dev` | `dev-bot` | `substring(developer)` | 🟢 |
| `review` | `review-bot` | `substring(reviewer)` | 🟢 |
| `qa` | `qa-bot` | `exact` | 🟢 |
| `operations` | `admin-bot` | `short_map(operations→admin)` | 🟢 |

### 代码走查

```python
# __init__
self.agent_card_path = os.path.join(
    os.path.dirname(__file__), "..", "config", "agent_cards.json"
)  # ✅ 路径正确

# _refresh_role_map()
cards = json.load(f)                             # ✅ 读取文件
role_index: dict[str, list[str]] = {}
for agent_id, card in cards.items():
    roles: list[str] = []
    if "pipeline_roles" in card and isinstance(card["pipeline_roles"], list):
        roles = card["pipeline_roles"]            # ✅ 兼容 array 格式
    elif "role" in card:
        roles = [card["role"]]                    # ✅ 兼容 string 格式
    for role in roles:
        role_index.setdefault(role, []).append(agent_id)
self._role_index = role_index                     # ✅ 正确填充
self._last_role_refresh = now                     # ✅ TTL 更新
```

### 边界检查

| 场景 | 处理 | 状态 |
|:-----|:------|:----:|
| 文件不存在 | `logger.warning` + `return` + TTL 更新（不重复报错） | ✅ |
| JSON 解析失败 | `except json.JSONDecodeError` + `logger.warning` | ✅ |
| 文件 IO 错误 | `except OSError` + `logger.warning` | ✅ |
| 角色名无匹配 | `return None` → PM 通知"未找到对应 bot" | ✅ |
| 60s TTL | `if now - last_refresh < TTL: return` | ✅ |

---

## 确认

| 检查项 | 结果 | 说明 |
|:-------|:----:|:------|
| `_role_index` 恒空问题 | 🟢 已修复 | 文件直接读取，同步填充 |
| 旧 WS 查询代码 | 🟢 已移除 | `!agent_card list` send 代码完全删除 |
| 角色解析可工作 | 🟢 已验证 | 6/6 默认角色成功匹配到 agent |
| 文件路径正确 | 🟢 已验证 | `config/agent_cards.json` 存在且可读 |
| 双格式兼容 | 🟢 已验证 | `pipeline_roles` (array) + `role` (string) 均支持 |
| 向后兼容 | 🟢 | 回退到 R88 的成熟方案，零新风险 |

**结论：修复正确，单文件改动精准对应审查报告的修复建议。🟢 通过。**

---

*重审编写: 🔍 小周 · 2026-07-11*
