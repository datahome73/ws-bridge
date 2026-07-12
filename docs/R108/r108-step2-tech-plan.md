# R108 技术方案 — /api/version 端点

> **编写人：** 🏗️ 小开 (arch)
> **日期：** 2026-07-12
> **需求文档：** [R108-product-requirements.md](R108-product-requirements.md)

---

## 一、改动范围

| 文件 | 改动类型 | 预计行数 |
|:-----|:---------|:--------:|
| `server/web_viewer.py` | 新增 handler + 路由注册 | +10 行 |
| `server/config.py` | **R108 专项：** AUTO_DISPATCH_ENABLED 默认改为 True | +1 行 |

## 二、插入点分析

### 2.1 handler 函数位置

`web_viewer.py` 已有 `_handle_health` 健康检查 handler。新 handler 可放在其旁边。

**插入点：** 在 `_handle_health` 定义之后（~L393），插入 `handle_api_version`。

### 2.2 路由注册位置

`setup_routes()` (~L683) 末尾已有 `/health` 路由。

**插入点：** 在 `app.router.add_get("/health", _handle_health)` 之后（~L691），插入 `/api/version` 路由。

## 三、版本号获取方式

**方案：从 `docs/TODO.md` 首行提取**

```python
async def handle_api_version(request):
    version = "v2.71"  # TODO.md 第 3 行
    return web.json_response({
        "version": version,
        "name": "ws-bridge",
        "build": "R108",
    })
```

## 四、AUTO_DISPATCH_ENABLED 开启方案

```python
# config.py 第 170 行
AUTO_DISPATCH_ENABLED: bool = True  # R108: 永久开启
```

已通过 R107 完整测试，默认关闭。R108 验证通过后永久开启。

## 五、风险

- `/api/version` 无鉴权，但版本信息是公开数据，无风险
- 路由名 `/api/version` 不与任何现有路由冲突
- 不涉及 WSS 核心、不涉及数据库，零回归风险
