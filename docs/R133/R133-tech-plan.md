# R133 技术方案 — Inbox 发件人颜色扩展 + 收件人颜色显示

| 字段 | 内容 |
|:-----|:------|
| **版本** | v1.0 |
| **作者** | Hermes Agent |
| **轮次** | R133 |
| **类型** | 前端纯 CSS/JS 改动 |
| **涉及文件** | `server/web_ui/templates.py`（仅此一个文件） |

---

## 1. 问题陈述

### 1.1 现状

Web 收件箱目前通过 `colorMap` + CSS class 为 6 个 bot 发件人着色。`系统`和`经理`两个非 bot 发件人 fallback 到 `.s-unknown`（灰色），视觉上无法与 bot 发件人同等区分。

收件人（`to_name`）在两个函数中均硬编码为灰色：

| 函数 | 行号 | 当前实现 |
|:-----|:----:|:---------|
| `createInboxMessageEl` | L421 | `s-unknown` + 内联 `color:#8b949e` |
| `createArchiveMessageEl` | L459-460 | 内联 `color:#8b949e` |

### 1.2 本轮目标

- 为`系统`和`经理`分配 2 种新颜色
- 收件人使用对应 bot 颜色（而非固定灰色）

---

## 2. 代码审计 — 实际行号

### 2.1 `templates.py`（842 行）—— 4 处改动点

| # | 位置 | 行号 | 当前内容 | 操作 |
|:-:|:-----|:----:|:---------|:----:|
| 1 | CSS 区 | L79 后 | 末尾 class 为 `s-unknown` | ✅ 新增 2 行 CSS |
| 2 | JS colorMap | L216 | 仅 6 bot 映射 | 🔧 追加 2 项 |
| 3 | `createInboxMessageEl` | L421 | 收件人固定灰色 | 🔧 改用 colorMap |
| 4 | `createArchiveMessageEl` | L459-460 | 收件人固定灰色 | 🔧 改用 colorMap |

### 2.2 CSS 区（L73-L79）

```css
.msg .sender.s-xiaoai{color:#ffd700;}
.msg .sender.s-xiaogu{color:#ff7b72;}
.msg .sender.s-xiaokai{color:#79c0ff;}
.msg .sender.s-aitai{color:#d2a8ff;}
.msg .sender.s-xiaozhou{color:#7ee787;}
.msg .sender.s-taixia{color:#ffa657;}
.msg .sender.s-unknown{color:#8b949e;}
```

**插入点：** 在 L79（`s-unknown` 行）之后新增 2 行，保持在 `.msg .sender` 规则块内。

### 2.3 JS colorMap（L216）

```js
const colorMap = {'小爱':'xiaoai','小谷':'xiaogu','小开':'xiaokai','爱泰':'aitai','小周':'xiaozhou','泰虾':'taixia'};
```

**修改：** 追加 `'系统':'system','经理':'manager'`。

### 2.4 `createInboxMessageEl`（L410-L425）—— 收件人行 L421

```js
// L421 当前 — 固定灰色
'<span class="sender s-unknown" style="color:#8b949e;font-weight:400;">' + escapeHtml(receiver) + '</span>'
```

**修改：** 在 L414 已有 `const receiver = m.to_name || '?'`，新增 `recvCls` 变量，L421 改用 colorMap 解析 class。

### 2.5 `createArchiveMessageEl`（L450-L466）—— 收件人行 L459-460

```js
// L459-460 当前 — 固定灰色
if (m.to_name) {
  inner += '<span style="color:#8b949e;margin:0 4px;">→</span>' +
    '<span style="color:#8b949e;font-size:0.85rem;">' + escapeHtml(m.to_name) + '</span>';
}
```

**修改：** L459-460 收件人 `<span>` 使用 `colorMap[m.to_name]` 解析 CSS class，保留 `font-size:0.85rem`。

---

## 3. 详细设计

### 3.1 颜色选择

| 发件人 | 色值 | CSS class | 选色理由 |
|:-------|:----:|:----------|:---------|
| **系统** | `#58a6ff` | `.s-system` | 蓝色 — 系统默认色，中性不冲突 |
| **经理** | `#bc8cff` | `.s-manager` | 浅紫色 — 权威感，与爱泰 `#d2a8ff` 可区分 |

与现有 6 bot 颜色对照：

| 现有 | 色值 | 色系 |
|:-----|:----:|:-----|
| 小爱 | `#ffd700` | 金色 |
| 小谷 | `#ff7b72` | 珊瑚红 |
| 小开 | `#79c0ff` | 天蓝 |
| 爱泰 | `#d2a8ff` | 浅紫 |
| 小周 | `#7ee787` | 薄荷绿 |
| 泰虾 | `#ffa657` | 橙 |

`#58a6ff`（系统蓝）比小开的 `#79c0ff`（天蓝）更暗，`#bc8cff`（经理紫）比爱泰的 `#d2a8ff`（浅紫）更饱和，均无混淆风险。

### 3.2 修改 1 — CSS 追加（L79 后，+2 行）

```css
.msg .sender.s-system{color:#58a6ff;}
.msg .sender.s-manager{color:#bc8cff;}
```

### 3.3 修改 2 — colorMap 追加（L216，+2 项）

```js
const colorMap = {'小爱':'xiaoai','小谷':'xiaogu','小开':'xiaokai',
                  '爱泰':'aitai','小周':'xiaozhou','泰虾':'taixia',
                  '系统':'system','经理':'manager'};
```

### 3.4 修改 3 — `createInboxMessageEl` 收件人颜色（L421）

```js
// L414 已有: const receiver = m.to_name || '?';
// 在 L415 (const cls = ...) 之后新增:
const recvCls = colorMap[receiver] || 'unknown';

// L421 改为:
'<span class="sender s-' + recvCls + '">' + escapeHtml(receiver) + '</span>' +
```

完整 diff：

```diff
+ const recvCls = colorMap[receiver] || 'unknown';
  div.innerHTML =
    '<div class="meta">' +
      '<span class="ts">' + formatTime(m.ts) + '</span>' +
      '<span class="sender s-' + cls + '">' + escapeHtml(sender) + '</span>' +
      '<span style="color:#8b949e;margin:0 4px;">→</span>' +
-     '<span class="sender s-unknown" style="color:#8b949e;font-weight:400;">' + escapeHtml(receiver) + '</span>' +
+     '<span class="sender s-' + recvCls + '">' + escapeHtml(receiver) + '</span>' +
    '</div>' +
```

### 3.5 修改 4 — `createArchiveMessageEl` 收件人颜色（L459-460）

```diff
  if (m.to_name) {
+   const recvCls = colorMap[m.to_name] || 'unknown';
    inner += '<span style="color:#8b949e;margin:0 4px;">→</span>' +
-     '<span style="color:#8b949e;font-size:0.85rem;">' + escapeHtml(m.to_name) + '</span>';
+     '<span class="sender s-' + recvCls + '" style="font-size:0.85rem;">' + escapeHtml(m.to_name) + '</span>';
  }
```

---

## 4. 设计决策

| 决策 | 选项 | 选择 | 理由 |
|:-----|:-----|:-----|:------|
| 新颜色取值 | 多种蓝色/紫色 | `#58a6ff` + `#bc8cff` | 与现有 6 色不冲突，符合系统/经理角色定位 |
| 收件人集成方式 | 独立 CSS class vs 内联 style | CSS class（`s-{class}`） | 复用已有 `.msg .sender` 规则，与发件人样式一致 |
| fallback 处理 | 特殊颜色 vs 灰色 | `unknown` = 灰色 | 未命名接收者仍按灰色处理，与未知发件人行为一致 |
| `createMessageEl` 影响 | 修改 vs 不动 | **不修改** | 该函数无收件人字段，colorMap 扩展后自动获得系统/经理颜色 |

---

## 5. 数据流

```
createInboxMessageEl(m)
  ├─ sender = m.from_name
  ├─ cls = colorMap[sender] || 'unknown'  →  发件人着色
  ├─ receiver = m.to_name
  ├─ recvCls = colorMap[receiver] || 'unknown'  ← NEW
  ├─ → 收件人 <span class="sender s-{recvCls}">  ← NEW
  └─ div.innerHTML = ...

createArchiveMessageEl(m)
  ├─ sender = m.from_name
  ├─ cls = colorMap[sender] || 'unknown'  →  发件人着色
  ├─ m.to_name 存在?
  │   → recvCls = colorMap[m.to_name] || 'unknown'  ← NEW
  │   → <span class="sender s-{recvCls}">  ← NEW
  └─ div.innerHTML = ...

createMessageEl(m)  ← 工作区消息，无收件人字段，不受影响
  └─ sender 着色 → colorMap 自动包含 '系统'/'经理' ← 副作用受益
```

---

## 6. 侧效应分析

### 6.1 `createMessageEl`（L218，工作区消息）

`createMessageEl` 没有收件人字段，不受收件人颜色修改影响。但它的发件人着色使用 `colorMap[sender]`（隐式调用，当前已有逻辑），colorMap 扩展后，工作区消息中`系统`和`经理`发件人会自动获得颜色。**这是期望效果，不是副作用。**

### 6.2 未知 recvCls fallback

如果 `receiver` / `m.to_name` 不在 colorMap 中（如自定义 agent），`recvCls` 为 `'unknown'`，渲染为灰色 `#8b949e` —— 与旧版行为一致，无退化。

### 6.3 CSS 优先级

`.msg .sender.s-system` 和 `.msg .sender.s-manager` 优先级与现有 6 bot 相同，style 属性中的 `color` 会覆盖 CSS class（如有冲突）。收件人使用 class 而非内联 style，遵从 CSS 层叠规则无问题。

---

## 7. 修改位置汇总

| # | 位置(L) | 操作 | 内容 |
|:-:|:--------|:----:|:------|
| 1 | L80-81 | ✅ 新增 | 2 行 CSS：`.s-system` + `.s-manager` |
| 2 | L216 | 🔧 修改 | colorMap 追加 2 项 |
| 3 | L415-421 | 🔧 修改 | 新增 `recvCls` 变量 + 收件人改用 class |
| 4 | L459-461 | 🔧 修改 | 收件人改用 class（保留 font-size） |

**净变更：+4 行（CSS 2 + colorMap 2），修改 ~4 行（2 个函数各 2 行）。**

---

## 8. 验证验收标准

### A 组 — 发件人颜色

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| A1 | `系统`→`#58a6ff`(蓝) | 打开 inbox，找 from_name=系统 的消息 |
| A2 | `经理`→`#bc8cff`(浅紫) | 打开 inbox，找 from_name=经理 的消息 |
| A3 | 6 bot 颜色不受影响 | 逐一检查 6 bot 颜色不变 |
| A4 | 未知发件人仍灰色 | 模拟未知 sender |

### B 组 — 收件人颜色

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| B1 | inbox 收件人显示 bot 颜色 | 找 to_name=小开，应为天蓝 |
| B2 | 未知收件人灰色 | 找 to_name 不在 map 中的 |
| B3 | 归档页收件人同样色 | Archive Tab 确认 |
| B4 | 工作区消息无异常 | Lobby Tab 确认 |

### C 组 — 回归

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| C1 | 无 JS 报错 | Console 检查 |
| C2 | 新消息实时插入颜色正确 | 在线测试 |
| C3 | 无 CSS 冲突 | 检查 `.s-*` class |

---

## 9. 不做事项

| 事项 | 说明 |
|:-----|:------|
| 后端 API/DB 变更 | 纯前端改动，不动后端 |
| 用户自定义颜色 | 需求不涉及 |
| 工作区消息收件人 | 无 `to_name` 字段 |
| 6 bot 现有颜色修改 | 只做增量 |
| 其他页面颜色扩展 | 仅 inbox + archive |

---

*技术方案结束*
