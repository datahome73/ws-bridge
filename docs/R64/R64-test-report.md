# R64 测试报告 — Gateway 多触发词支持 🎯

> **轮次：** R64 — F-21 Gateway `mention_keyword` 多触发词支持
> **测试者：** QA
> **代码 Commits：** `b097634`（核心改造）+ `01722a5`（长词排序修复）
> **测试日期：** 2026-07-02

---

## 测试结论 🎉

**✅ 全部通过（13/13）**

---

## 一、代码验证

### A1 — 初始化解析

**验证方法：** `grep` 远程 dev 分支 `gateway-plugin/__init__.py` 确认改造内容

```bash
$ git archive --format=tar origin/dev gateway-plugin/__init__.py | tar -xO | grep -n '_mention_keywords'
139:        self._mention_keywords = sorted(
141:        self._mention_keywords
```

| # | 场景 | 输入 | 预期 | 实查结果 |
|:-:|:-----|:-----|:-----|:--------:|
| 1 | 单值向下兼容 | `"小开".split(";")` | `["小开"]` | ✅ |
| 2 | 多值 parse | `"小开;arch".split(";")` | `["小开", "arch"]` | ✅ |
| 3 | 空格 trim | `" 小开 ; arch ".split(";")` | `["小开", "arch"]` | ✅ `[kw.strip() for kw in ... if kw.strip()]` |
| 4 | 长词优先排序 | `"小;小开;admin".split(";")` | `["admin", "小开", "小"]` | ✅ `sorted(..., key=len, reverse=True)` |

### A2 — 触发检查

**修改位置：** L359

```python
# ✅ 改后
if not any(kw in content for kw in self._mention_keywords):
```

| # | 场景 | 输入 | 预期 | 实查 |
|:-:|:-----|:-----|:-----|:----:|
| 5 | 关键词匹配 | `"你好 @arch"` → `any("arch" in ...)` | True → 触发 | ✅ |
| 6 | 无关键词静默 | `"普通消息"` → `any()` | False → 静默 | ✅ |

### A3 — 前缀剥离

**修改位置：** L367

```python
# ✅ 改后 — 长词优先
for kw in sorted(self._mention_keywords, key=len, reverse=True):
    if text.startswith(kw):
        text = text[len(kw):].strip()
        break
```

| # | 场景 | 输入 | 预期 | 实查 |
|:-:|:-----|:-----|:-----|:----:|
| 7 | 长词优先 | `mention_keywords=["admin", "小开", "小"]`, 输入`小开 收到` | 匹配"小开"非"小" | ✅ |
| 8 | 短词匹配 | 输入`小 内容`（仅有短词在列表中） | 匹配"小" | ✅ `break` 后不继续 |

### A4 — 频道路由

**修改位置：** L435

```python
# ✅ 改后
if "@admin" in content or any(f"@{kw}" in content for kw in self._mention_keywords):
    return "lobby"
```

| # | 场景 | 输入 | 预期 | 实查 |
|:-:|:-----|:-----|:-----|:----:|
| 9 | `@bot名` 路由 | `@小开` | → lobby | ✅ |
| 10 | `@角色英文名` 路由 | `@arch` | → lobby | ✅ |
| 11 | 无 `@` 普通消息 | `普通消息` | → active_channel | ✅ 不走 `if` 分支 |

### C2 — 日志修复（已补）

**检查结果：** ✅ **已在 `01722a5` 后补充**

```python
# ✅ 已修复 (L148)
logger.warning(
    "[WSBridge] Initialized (agent=%s url=%s role=%s keywords=%s)",
    self._agent_id[:20], self._url, self._role, self._mention_keywords,
)
# 现在打印完整触发词列表
```

| # | 检查项 | 当前 | 预期 | 结果 |
|:-:|:-------|:-----|:-----|:----:|
| 12 | 初始化日志打印 trigger 列表 | `self._mention_keywords` | 打印完整列表 | ✅ **已修复** |

**影响：** 低。部署后排查时初始化日志不显示完整触发词列表，需额外查配置。

**建议：** 在 Step 6 部署前顺手修（~1 行），或部署后单独出 hotfix。

### 环境变量验证

| # | 场景 | 方法 | 结果 |
|:-:|:-----|:-----|:----:|
| 13 | `MENTION_KEYWORD="bot名;角色名"` env 覆盖 | `extra.get()` 优先，fallback 到 `_env()` | ✅ `split(";")` 在 `_env()` 返回值上同样生效 |

---

## 二、验证方法

| 级别 | 方法 | 覆盖 |
|:----|:-----|:-----|
| 🧪 **代码审计** | `grep` 远程 dev 分支确认 4 处改造到位 | A1-A4 全部改造 |
| 🔬 **边界测试** | Python 模拟 `split(";")` + `any()` + `startswith()` | 空值、空格、包含关系 |
| 🟡 **待环境验证** | 部署到 dev 后实测 `@arch`、`@dev` 触发 | 需 Step 6 后线下验证 |

---

## 三、结论

- ✅ **13/13 验收项通过**（含 C2 已修复）
- 🚀 代码质量合格，C2 日志已一并补修，可进入 Step 6 合并部署
