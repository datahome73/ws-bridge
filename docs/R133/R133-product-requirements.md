# R133 — Inbox 发件人颜色扩展 + 收件人颜色显示

> **轮次类型：** 主线功能轮
> **编写人：** PM（小谷）
> **版本：** v1.0

---

## §1 背景

### 现状

Web 端收件箱（Inbox Tab）目前通过 `colorMap` + CSS class 为 6 个 bot 的发件人显示不同颜色，以快速区分消息来源：

| bot | from_name | CSS class | 颜色 |
|:---|:----------|:-----------|:-----|
| 小爱 | 小爱 | `.s-xiaoai` | `#ffd700` (金) |
| 小谷 | 小谷 | `.s-xiaogu` | `#ff7b72` (珊瑚红) |
| 小开 | 小开 | `.s-xiaokai` | `#79c0ff` (天蓝) |
| 爱泰 | 爱泰 | `.s-aitai` | `#d2a8ff` (浅紫) |
| 小周 | 小周 | `.s-xiaozhou` | `#7ee787` (薄荷绿) |
| 泰虾 | 泰虾 | `.s-taixia` | `#ffa657` (橙) |

非 bot 发件人（包括`系统`和`经理`）fallback 到 `.s-unknown` → `#8b949e`（灰色），无法与 6 bot 同等级区分。

**收件人（recipient）显示问题：** 当前渲染方式如下：

- **`createInboxMessageEl`**（L410-425）：收件人固定为 `.s-unknown` + 硬编码灰色 `color:#8b949e;font-weight:400;`
- **`createArchiveMessageEl`**（L450-466）：收件人也是固定灰色 `color:#8b949e;`
- 收件人没有使用 bot 颜色

### 痛点

1. **系统和经理无法被颜色区分** — 在消息流中淹没，需要阅读文本才能识别
2. **收件人视觉信息不足** — 收件人应该是哪个 bot，一眼看不出来

### 目标

- 为`系统`和`经理`分配 2 种新增颜色
- 收件人使用对应的 bot 颜色显示（而非一律灰色）

---

## §2 核心设计

### 2.1 颜色方案

选择与现有 6 bot 颜色不冲突的 2 种颜色（排除红/黄/绿已有色系）：

| 发件人 | 色值 | 说明 |
|:------|:----|:-----|
| **系统** | `#58a6ff` | 蓝色 — 系统默认色、中性、与技术底色一致 |
| **经理** | `#bc8cff` | 浅紫色 — 权威、区别于爱泰的 `#d2a8ff` |

### 2.2 CSS 改动

在 `templates.py` CSS 区新增 2 个 class（接 L79 之后）：

```css
.msg .sender.s-system{color:#58a6ff;}
.msg .sender.s-manager{color:#bc8cff;}
```

### 2.3 JavaScript colorMap 扩展

```js
// 原 L216
const colorMap = {'小爱':'xiaoai','小谷':'xiaogu','小开':'xiaokai',
                  '爱泰':'aitai','小周':'xiaozhou','泰虾':'taixia'};
// → 改为
const colorMap = {'小爱':'xiaoai','小谷':'xiaogu','小开':'xiaokai',
                  '爱泰':'aitai','小周':'xiaozhou','泰虾':'taixia',
                  '系统':'system','经理':'manager'};
```

### 2.4 收件人颜色逻辑

#### `createInboxMessageEl`（L410-425）

当前收件人行：
```js
'<span class="sender s-unknown" style="color:#8b949e;font-weight:400;">' + escapeHtml(receiver) + '</span>'
```

改为：
```js
const recvCls = colorMap[receiver] || 'unknown';
'<span class="sender s-' + recvCls + '">' + escapeHtml(receiver) + '</span>'
```

即收件人使用 `colorMap[receiver]` 解析出 CSS class，如果不在 map 中 fallback 到 `unknown`（灰色）。

**效果示例：**
```
09:30  泰虾 → 爱泰
        ^橙     ^浅紫
```

#### `createArchiveMessageEl`（L450-466）

当前收件人行（L458-461）：
```js
if (m.to_name) {
  inner += '<span style="color:#8b949e;margin:0 4px;">→</span>' +
    '<span style="color:#8b949e;font-size:0.85rem;">' + escapeHtml(m.to_name) + '</span>';
}
```

改为：
```js
if (m.to_name) {
  const recvCls = colorMap[m.to_name] || 'unknown';
  inner += '<span style="color:#8b949e;margin:0 4px;">→</span>' +
    '<span class="sender s-' + recvCls + '" style="font-size:0.85rem;">' + escapeHtml(m.to_name) + '</span>';
}
```

### 2.5 不影响 `createMessageEl`（工作区消息）

L218-231 的 `createMessageEl` 用于工作区/大厅消息，当前没有显示收件人字段，无需改动。发件人颜色已通过 `colorMap[sender] || 'unknown'` 正确工作，系统和经理进入 map 后会自动获得颜色。

### 集成方式

纯前端改动，仅修改 `server/web_ui/templates.py` 一个文件。不涉及后端 API 或 DB schema 变更。

---

## §3 改动范围

| 文件 | 改动类型 | 新增 | 修改 | 说明 |
|:----|:---------|:----|:----|:------|
| `server/web_ui/templates.py` | CSS | +2 行 | — | 新增 `.s-system`、`.s-manager` 样式 |
| `server/web_ui/templates.py` | JS colorMap | +2 项 | — | 追加 `系统`、`经理` 映射 |
| `server/web_ui/templates.py` | JS createInboxMessageEl | — | ~2 行 | 收件人改用 bot 颜色 |
| `server/web_ui/templates.py` | JS createArchiveMessageEl | — | ~2 行 | 收件人改用 bot 颜色 |

**统计：+4 行（CSS/colorMap），修改 ~4 行（2 个函数各 2 行）**

---

## §4 验收标准

### A 组 — 发件人颜色

| # | 验收项 | 验证方法 |
|:--|:-------|:---------|
| A1 | 系统发消息时收件箱显示蓝色 `#58a6ff` | 打开 Web 收件箱，找到 `from_name=系统` 的消息，查看蓝色标签 |
| A2 | 经理发消息时收件箱显示浅紫色 `#bc8cff` | 打开 Web 收件箱，找到 `from_name=经理` 的消息，查看紫色标签 |
| A3 | 6 个 bot 发件人颜色不受影响 | 逐一检查 6 bot 颜色不变 |
| A4 | 未知发件人仍 fallback 灰色 `#8b949e` | 模拟未知 sender 显示灰色 |

### B 组 — 收件人颜色

| # | 验收项 | 验证方法 |
|:--|:-------|:---------|
| B1 | 收件箱消息收件人显示对应 bot 颜色 | 找一条 `to_name=小开` 的消息，收件人应为天蓝 `#79c0ff` |
| B2 | 未知收件人 fallback 灰色 | 找一条 `to_name` 不在 colorMap 的消息，显示灰色 |
| B3 | 归档历史页收件人同样显示 bot 颜色 | 切换到 Archive Tab，查看 `to_name` 颜色 |
| B4 | 工作区/大厅消息不受影响（无收件人字段） | 切换到 Lobby/Workspace Tab，确认无异常 |

### C 组 — 回归验证

| # | 验收项 | 验证方法 |
|:--|:-------|:---------|
| C1 | 页面无 JS 报错 | 浏览器 Console 检查 |
| C2 | 新消息实时插入后颜色正确 | 发一条新的 inbox 消息，确认颜色立即生效 |
| C3 | 无 CSS 冲突或覆盖其他 class | 检查其他 `.s-*` class 样式未受影响 |

---

## §5 不做事项

| ❌ 不做 | 理由 |
|:--------|:-----|
| 后端数据库存储颜色配置 | 纯前端固定颜色，无需动态配置 |
| 用户自定义颜色 | 需求不涉及，轮次范围外 |
| 工作区/大厅消息收件人显示 | 工作区消息无 `to_name` 字段 |
| inbox 消息以外页面的颜色扩展 | 仅收件箱和归档页涉及收件人 |
| 修改 6 bot 现有颜色 | 保留现有配色，只做增量 |

---

## §6 验收检查表

### 文件改动清单

| 文件 | 改动描述 | 验收 ✅ |
|:----|:---------|:-------|
| `server/web_ui/templates.py` | CSS: +`.s-system` +`.s-manager` | ⬜ |
| `server/web_ui/templates.py` | JS: colorMap +`'系统':'system'` +`'经理':'manager'` | ⬜ |
| `server/web_ui/templates.py` | JS: `createInboxMessageEl` 收件人颜色 | ⬜ |
| `server/web_ui/templates.py` | JS: `createArchiveMessageEl` 收件人颜色 | ⬜ |

### 验收计数

| 分组 | 验收项数 | 通过 |
|:----|:--------|:----|
| A 发件人颜色 | 4 | 🟢/🔴 |
| B 收件人颜色 | 4 | 🟢/🔴 |
| C 回归验证 | 3 | 🟢/🔴 |
| **合计** | **11** | **/11** |
