# R64 Technical Plan — Gateway `mention_keyword` 多触发词支持

> **版本：** v1.0
> **状态：** ✅ 已提交
> **架构师：** 👷 arch
> **日期：** 2026-07-02
> **对应需求：** docs/R64/R64-product-requirements.md v1.0
> **代码基线：** dev branch (gateway-plugin/__init__.py, 499 lines)

---

## 1. 改动总览

### 1.1 文件范围

| 文件 | 改动类型 | 行数 | 说明 |
|:-----|:---------|:----:|:------|
| `gateway-plugin/__init__.py` | 修改（4处消费点 + 2处日志顺手修复） | ~22行净增 | 纯 Gateway 层，零 server 侧 |
| `docs/R64/R64-tech-plan.md` | 新增 | — | 本文档 |

### 1.2 4处消费点一览

| # | 名称 | 行号 | 当前代码 | 改造后 | 行数 |
|:-:|:-----|:----:|:---------|:-------|:----:|
| A1 | 初始化 | L133 | `self._mention_keyword = extra.get(...) or _env(...) or "admin-bot"` | 分号 `split(";")` → `_mention_keywords: list[str]` + 保留 `_mention_keyword = _mention_keywords[0]` | ~5行 |
| A2 | 触发检查 | L359 | `if self._mention_keyword not in content:` | `if not any(kw in content for kw in self._mention_keywords):` | ~5行 |
| A3 | 前缀剥离 | L367 | `if text.startswith(self._mention_keyword):` | 长词优先遍历 `_mention_keywords` 匹配 `startswith` | ~6行 |
| A4 | 频道路由 | L434 | `if "@admin" in content or f"@{self._mention_keyword}" in content:` | 先检查 `@admin`，再遍历 `_mention_keywords` | ~4行 |
| C | 日志顺手修复 | L144, L361 | 打印 `self._mention_keyword` 单值 | 改为打印 `self._mention_keywords` 列表 | ~2行 |

---

## 2. 技术细节

### 2.1 A1 — 初始化解析（L133）

```python
# 当前（1行）
self._mention_keyword = extra.get("mention_keyword") or _env("MENTION_KEYWORD") or "admin-bot"

# 改造后（3行）
_raw = extra.get("mention_keyword") or _env("MENTION_KEYWORD") or "admin-bot"
self._mention_keywords = [k.strip() for k in _raw.split(";") if k.strip()]
self._mention_keyword = self._mention_keywords[0]  # 向后兼容
```

**设计决策：**
- `_raw` 保持原 `_env()` 调用链不变（`extra` > 环境变量 > 默认值）
- `split(";")` 后 `strip()` 去除前后空格 → `" 小开 ; arch "` → `["小开", "arch"]`
- `if k.strip()` 过滤空字符串 → `"小开;;arch"` → `["小开", "arch"]`（中间空值被过滤）
- `_mention_keyword` 保留为 `_mention_keywords[0]`，单值场景下行为零变化
- 不引入新依赖，纯标准库

**边缘情况分析：**
| 输入 | `_mention_keywords` | `_mention_keyword` |
|:-----|:--------------------|:-------------------|
| `"小开"` | `["小开"]` | `"小开"` |
| `" 小开 "` | `["小开"]` | `"小开"` |
| `"小开;arch"` | `["小开", "arch"]` | `"小开"` |
| `"小开;"` | `["小开"]` | `"小开"` |
| `";arch"` | `["arch"]` | `"arch"` |
| `""` | `["admin-bot"]` | `"admin-bot"` |
| `None` | `["admin-bot"]` | `"admin-bot"` |

### 2.2 A2 — 触发检查（L359）

```python
# 当前
if self._mention_keyword not in content:
    logger.warning("[WSBridge] Silent: no mention keyword '%s'", self._mention_keyword)
    return

# 改造后
if not any(kw in content for kw in self._mention_keywords):
    logger.warning("[WSBridge] Silent: no mention keyword in '%s'", self._mention_keywords)
    return
```

**说明：**
- `any(kw in content for kw in list)` 短路求值：第一个匹配项命中即停止
- 当前各 bot 各配 2 个词 → 列表长度 ≤ 5，性能无影响
- 日志改为打印整个列表（C3 顺手修复）

**正确性分析：**
```
content = "小开 到你了"
any(kw in content for kw in ["小开", "arch"]) → True ✅（"小开" 匹配）
any(kw in content for kw in ["arch"]) → False ✅（静默）
```

### 2.3 A3 — 前缀剥离（L367）

```python
# 改造后
text = content
for kw in sorted(self._mention_keywords, key=len, reverse=True):
    if text.startswith(kw):
        text = text[len(kw):].strip()
        break
```

**长词优先排序原理：**
```
_mention_keywords = ["小开", "arch"]
sorted(["小开", "arch"], key=len, reverse=True) → ["小开", "arch"]
# 如果 ["小", "小开"]:
sorted(["小", "小开"], key=len, reverse=True) → ["小开", "小"]  ← 长词优先
```

**边缘情况验证：**
| content | `_mention_keywords` | 匹配 | 剥离后 |
|:--------|:--------------------|:-----|:-------|
| `"小开 到你了"` | `["小开"]` | `startswith("小开")` | `"到你了"` |
| `"arch 方案"` | `["小开", "arch"]` | `startswith("arch")` | `"方案"` |
| `"小 到你了"` | `["小", "小开"]` | 长词 `"小开"` 不匹配 → 短词 `"小"` 匹配 | `"到你了"` |
| `"小开你好"` | `["小开"]` | `startswith("小开")` | `"你好"` |
| `"收到"` | `["小开"]` | 无匹配 | `"收到"`（原样） |

### 2.4 A4 — 频道路由（L434）

```python
# 改造后
if "@admin" in content:
    return "lobby"
for kw in self._mention_keywords:
    if f"@{kw}" in content:
        return "lobby"
return self._active_channel or "lobby"
```

**行为说明：**
- `@admin` 硬编码优先检查（与改造前一致）
- 遍历 `_mention_keywords` 检查 `@kw`，任一匹配即路由到 lobby
- 均不匹配 → 返回 `_active_channel`

### 2.5 C — 日志顺手修复

| 位置 | 当前 | 改造后 |
|:-----|:-----|:-------|
| L144 | `"mention=%s", self._mention_mode` | 不变（mention_mode 布尔值与多值无关） |
| L361 | `"'%s'", self._mention_keyword` | `"'%s'", self._mention_keywords` |

注意 L144 打印的 `self._mention_mode` 是布尔值，不打印触发词本身——不需要改。

---

## 3. 向下兼容验证

| 场景 | 旧代码行为 | 新代码行为 | 是否一致 |
|:-----|:-----------|:-----------|:--------:|
| `mention_keyword: "小开"` | `_mention_keyword = "小开"` | `_mention_keywords = ["小开"]`; `_mention_keyword = "小开"` | ✅ |
| `@小开 收到` | `"小开" in content` → True | `any(kw in content ...)` → True | ✅ |
| `小开 收到` → 剥离 | `startswith("小开")` → `"收到"` | 遍历 `["小开"]` → `startswith` → `"收到"` | ✅ |
| `@小开 内容` → 路由 | `f"@{"小开"}" in content` → lobby | 遍历 `["小开"]` → `f"@{"小开"}"` → lobby | ✅ |
| 普通消息 | `"小开" not in "普通"` → 静默 | `any(...)` → False → 静默 | ✅ |

---

## 4. 安全性分析

| 方面 | 风险等级 | 说明 |
|:-----|:--------:|:------|
| 触发绕过 | 🟢 无 | 多触发词不降低安全性——bot 名仍然是触发词之一 |
| 前缀碰撞 | 🟢 无 | 长词优先排序避免短词误剥 |
| 路由 hijack | 🟢 无 | `@admin` 仍硬编码优先级最高 |
| 异常输入 | 🟢 低 | `split(";")` + `strip()` + `if k.strip()` 三级防御 |

---

## 5. 测试建议

| 测试类型 | 场景 | 方法 |
|:---------|:-----|:------|
| 单元测试 | 单值 parse | 传入 `"小开"` → 断言 `["小开"]` |
| 单元测试 | 双值 parse | 传入 `"小开;arch"` → 断言 `["小开", "arch"]` |
| 单元测试 | 空格 trim | 传入 `" 小开 ; arch "` → 断言 `["小开", "arch"]` |
| 单元测试 | 空值过滤 | 传入 `"小开;;arch"` → 断言 `["小开", "arch"]` |
| 单元测试 | 长词优先排序 | `["小", "小开"]` sorted → `["小开", "小"]` |
| 集成测试 | `@角色英文名` 触发 | 实测工作室发送 `@arch 到你了` |
| 集成测试 | `@不同角色名` 路由 | 实测 `@dev` 触发 dev bot |
| 集成测试 | 无触发词静默 | 实测普通消息不触发 |

---

## 6. 实施顺序

| 顺序 | 改动 | 行号 | 前后文 |
|:----:|:-----|:----:|:-------|
| 1️⃣ | A1 初始化 | L133 | 替换单行赋值，改为 3 行 |
| 2️⃣ | C2 日志修复 | L144 | 不改（L144 打印 `_mention_mode` 布尔值，不涉及触发词字段） |
| 3️⃣ | A2 触发检查 | L359-362 | 替换 if 条件 + 日志 |
| 4️⃣ | A3 前缀剥离 | L367-368 | 替换为 6 行遍历 |
| 5️⃣ | A4 频道路由 | L434-436 | 替换为 7 行遍历 |
| 6️⃣ | C3 日志修复 | L360-361 | 日志单值 → 列表 |

---

## 7. 回退方案

**零回滚回退：** 将配置从 `"小开;arch"` 改回 `"小开"` → 重启容器 → 行为与改造前完全一致。无需回滚代码。

---

## 8. 脱敏检查

- [x] 文档无内部 bot 名（使用占位符 `"小开"`、`"arch"`、`"dev"` 等）
- [x] 无内部 URL 泄露
- [x] 无 token/key/AGENT_ID 泄露
