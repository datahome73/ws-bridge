# R133 技术方案 — Inbox 发件人颜色扩展 + 收件人颜色显示

> **起草人：** 👷 Arch（小开）
> **版本：** v1.0
> **基线：** `origin/dev`
> **参考：** `docs/R133/R133-product-requirements.md` v1.0
> **预估改动：** +4 行 / 修改 ~4 行（纯前端，单文件）

---

## §1 改动文件

| 文件 | 行数 | 改动 | 说明 |
|:-----|:----:|:-----|:------|
| `server/web_ui/templates.py` | ~820 | **+4 / ~4** | CSS + JS colorMap + 2 个函数收件人颜色 |

---

## §2 当前代码审计

### 2.1 CSS 区 — 发件人颜色 class（L72-L79）

```css
.msg .sender{font-size:0.85rem;font-weight:600;color:#58a6ff;}
.msg .sender.s-xiaoai{color:#ffd700;}
.msg .sender.s-xiaogu{color:#ff7b72;}
.msg .sender.s-xiaokai{color:#79c0ff;}
.msg .sender.s-aitai{color:#d2a8ff;}
.msg .sender.s-xiaozhou{color:#7ee787;}
.msg .sender.s-taixia{color:#ffa657;}
.msg .sender.s-unknown{color:#8b949e;}
```

**插入点：** L79（`.s-unknown` 之后），追加 2 行。

### 2.2 JS colorMap（L216）

```js
const colorMap = {'小爱':'xiaoai','小谷':'xiaogu','小开':'xiaokai',
                  '爱泰':'aitai','小周':'xiaozhou','泰虾':'taixia'};
```

**插入点：** L216 行末，在 `taixia'}` 之前追加 2 个 key。

### 2.3 `createInboxMessageEl`（L410-L425）

当前收件人部分（~L421）：
```js
'<span class="sender s-unknown" style="color:#8b949e;font-weight:400;">' + escapeHtml(receiver) + '</span>'
```

**修改点：** 收件人 `<span>` 使用 `colorMap[receiver]` 动态 class。

### 2.4 `createArchiveMessageEl`（L450-L466）

当前收件人部分（~L458-L461）：
```js
if (m.to_name) {
  inner += '<span style="color:#8b949e;margin:0 4px;">→</span>' +
    '<span style="color:#8b949e;font-size:0.85rem;">' + escapeHtml(m.to_name) + '</span>';
}
```

**修改点：** 收件人 `<span>` 使用 `colorMap[m.to_name]` 动态 class。

### 2.5 `createMessageEl`（L218-L231）— 无需改动

工作区消息无 `to_name` 字段，不受影响。发件人颜色已通过 `colorMap[sender] || 'unknown'` 动态解析，新增 `系统`/`经理` 后自动受益。

---

## §3 改动方案

### 3.1 CSS 区（L79 后 +2 行）

```css
.msg .sender.s-system{color:#58a6ff;}
.msg .sender.s-manager{color:#bc8cff;}
```

### 3.2 JS colorMap（L216 +2 项）

```js
const colorMap = {'小爱':'xiaoai','小谷':'xiaogu','小开':'xiaokai',
                  '爱泰':'aitai','小周':'xiaozhou','泰虾':'taixia',
                  '系统':'system','经理':'manager'};
```

### 3.3 `createInboxMessageEl` 收件人颜色（~L421 修改）

```js
// 修改前：
'<span class="sender s-unknown" style="color:#8b949e;font-weight:400;">' + escapeHtml(receiver) + '</span>'

// 修改后：
const recvCls = colorMap[receiver] || 'unknown';
'<span class="sender s-' + recvCls + '">' + escapeHtml(receiver) + '</span>'
```

### 3.4 `createArchiveMessageEl` 收件人颜色（~L458-L461 修改）

```js
// 修改前：
inner += '<span style="color:#8b949e;margin:0 4px;">→</span>' +
  '<span style="color:#8b949e;font-size:0.85rem;">' + escapeHtml(m.to_name) + '</span>';

// 修改后：
const recvCls = colorMap[m.to_name] || 'unknown';
inner += '<span style="color:#8b949e;margin:0 4px;">→</span>' +
  '<span class="sender s-' + recvCls + '" style="font-size:0.85rem;">' + escapeHtml(m.to_name) + '</span>';
```

---

## §4 执行顺序

| 顺序 | 改动 | 行号 | 说明 |
|:----:|:-----|:----:|:------|
| 1 | CSS: 追加 2 个 class | L79 后 | 先定义样式，再使用 |
| 2 | JS colorMap: 追加 2 项 | L216 | 定义映射关系 |
| 3 | `createInboxMessageEl` 收件人 | ~L421 | 使用 colorMap 动态 class |
| 4 | `createArchiveMessageEl` 收件人 | ~L458 | 同上 |

---

## §5 安全边界

| # | 边界 | 说明 | 风险 |
|:-:|:-----|:------|:----:|
| 1 | **`colorMap[receiver]` 未定义时 fallback** | `|| 'unknown'` 确保任何未知收件人显示灰色 | 🟢 |
| 2 | **`createMessageEl` 无收件人字段** | 工作区消息无 `to_name`，不受影响 | 🟢 |
| 3 | **CSS specificity** | `.msg .sender.s-system` 与已有 `.msg .sender` 不冲突 | 🟢 |
| 4 | **JS 无语法错误** | Python raw string 中嵌入的 JS，需注意转义 | 🟡 |

---

## §6 验收标准映射

| # | 验收项 | 代码位置 | 验证 |
|:-:|:-------|:---------|:-----|
| A1 | 系统发件人蓝色 | CSS `.s-system` + colorMap `系统→system` | 浏览器 |
| A2 | 经理发件人浅紫 | CSS `.s-manager` + colorMap `经理→manager` | 浏览器 |
| A3 | 6 bot 颜色不变 | colorMap 原有 6 项未修改 | 浏览器 |
| A4 | 未知发件人灰色 | `colorMap[sender] \|\| 'unknown'` 逻辑未变 | 浏览器 |
| B1 | 收件人显示 bot 颜色 | `createInboxMessageEl` 收件人 class 动态化 | 浏览器 |
| B2 | 未知收件人灰色 | `\|\| 'unknown'` fallback | 浏览器 |
| B3 | 归档页收件人颜色 | `createArchiveMessageEl` 收件人 class 动态化 | 浏览器 |
| B4 | 工作区消息无异常 | `createMessageEl` 未改动 | 浏览器 |
| C1 | 无 JS 报错 | Console 检查 | DevTools |
| C2 | 新消息颜色实时生效 | 发一条新消息 | 浏览器 |
| C3 | 无 CSS 冲突 | 检查 `.s-*` class | 浏览器 |

---

> **审核记录：**
> - v1.0 提交审核
