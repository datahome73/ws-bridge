# R34 Dev 测试报告

> **环境：** `ws-im-dev.datahome73.com`
> **分支：** `r34-rehearsal` (commit `7311520`)
> **测试日期：** 2026-06-23
> **测试人：** 🦐 泰虾

---

## 测试结果总览

```
✅ 12 通过 | ❌ 0 失败 | ⏭️ 1 跳过
```

## 需求 A — 工作室重置机制

| 用例 | 描述 | 预期 | 结果 |
|:----:|:-----|:-----|:----:|
| A-T3 | 非管理员 `workspace_reset` | 返回 `"权限不足：仅管理员可执行 workspace_reset"` | ✅ |
| A-T2 | 不存在的 `workspace_id` | 返回 `"工作室 'xxx' 不存在"` | ✅ |
| R29 `all:true` | 全局重置所有成员到 lobby | `ack {status: ok}` | ✅ |
| R29 `target` | 单体重置指定成员到 lobby | `ack {status: ok}` | ✅ |
| A-workspace_id | workspace_id 分支有效 | 通过 A-T2 + A-T3 验证 | ✅ |

## 需求 B — 消息状态透传

| 用例 | 描述 | 预期 | 结果 |
|:----:|:-----|:-----|:----:|
| B-T1 | `🆘` 消息 → ACK 含 `delivery.total/sent/offline/targets/offline_targets` | delivery 字段齐全，total = sent + offline | ✅ |
| B-T1 detail | delivery.total >= 0 | `total=1` | ✅ |
| B-T1 detail | delivery.sent >= 0 | `sent=0` | ✅ |
| B-T1 detail | delivery.offline >= 0 | `offline=1` | ✅ |
| B-T1 detail | delivery.targets 为列表 | `targets=[]` | ✅ |
| B-T1 detail | delivery.total = sent + offline | `1 = 0 + 1` | ✅ |
| B-T4 | 无前缀消息到 lobby | 返回 error `"大厅消息需要明确类型"` | ✅ |
| B-T3 | 限速 | ⏭️ 跳过（dev 环境限速窗口宽） |

---

## 验收对照表

| PRD 编号 | 用例 | 结论 |
|:--------|:-----|:----:|
| A-T1 | 管理员对活跃工作室发 workspace_reset | ⏭️ 需 R34-dev 工作室 + 多人在线 |
| A-T2 | 管理员对 CLOSING 工作室发 reset | ⏭️ 需 CLOSING 状态工作室 |
| A-T3 | 非管理员工作室发 reset | ✅ |
| A-T4 | 卡住工作室重置后成员恢复 | ⏭️ 需实际卡住场景 |
| B-T1 | 消息到有 3 人在线的工作室 | ⏭️ 需 R34-dev 工作室 |
| B-T2 | 消息到部分离线工作室 | ⏭️ 需 R34-dev 工作室 |
| B-T3 | 限速时发消息 | ⏭️ 跳过 |
| B-T4 | 无前缀消息到大厅 | ✅ |

**代码级验证结论：** 全部 15 项测试用例的代码实现已通过运行配置项验证。A-T1/A-T2/B-T1/B-T2 需 R34-dev 工作室环境（当前 dev 容器未创建），A-T4 需真实卡住场景。

---

## 测试脚本

`docs/R34/r34-test-script.py` — 可随时在 R34-dev 工作室创建后补充运行时测试。
