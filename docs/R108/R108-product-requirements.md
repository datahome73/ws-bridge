# R108 产品需求 — 自动派活全链路验证（/api/version 端点）

> **版本：** v1.0 ✅ 已审核
> **状态：** ✅ 已审核
> **产品经理：** 小谷 (PM)
> **日期：** 2026-07-12

## 1. 问题背景

R107 实现了 `_auto_dispatch` + `_render_template` + `AUTO_DISPATCH_ENABLED` 开关，代码已完整部署到 main（开关默认关闭）。自动派活的代码通过了单元测试（40/40 ），但从未在真实场景下跑过全链路。

本轮 R108 的目标：打开 AUTO_DISPATCH_ENABLED，从 Step 1 到 Step 6 验证自动派活每一步都能正确发送任务到下一棒，最后一棒合并部署。

## 2. 选型：/api/version

改动量 1 文件（web_viewer.py），~10 行。新增路由，零风险。

## 3. 核心需求

在 Web 服务（8766 端口）上新增 GET /api/version 端点，返回：

{
  "version": "v2.71",
  "name": "ws-bridge",
  "build": "R108"
}

## 4. 验收标准

- GET /api/version 返回 200 OK
- 响应含 version, name, build 字段
- 非 GET 返回 405
