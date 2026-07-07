# 项目文档目录

按开发轮次归档，每轮独立文件夹。最新轮次：**R73**。

> ⚠️ 脱敏提醒：所有 WORK_PLAN.md 已使用通用角色名
> （需求分析师 / 项目管理 / 架构师 / 开发工程师 / 审查工程师 / 测试工程师 / 项目负责人）。
> 新建轮次请参考 `docs/templates/` 模板，继续使用通用角色名。

## 目录结构

```
docs/
├── WORKFLOW.md              开发流程（永久文档）
├── WORKSPACE_RULES.md       工作群聊天规则（永久文档）
├── TODO.md                  全局待办
├── product-requirements.md  全局产品需求
├── chat-rules-test-items.md 规则测试项
├── README.md                本文件
├── templates/               开发文档模板（新建轮次时参考，使用通用角色名）
│   └── ...
├── R32/ ... R74/            历史轮次（已归档，详见各轮次文件夹）
```

## 开发文档模板

新建轮次时，从 `templates/` 复制对应模板，`R{NN}` 替换为实际轮次号。

| 步骤 | 文档（`templates/`） | 用途 | 产出角色 |
|:----|:--------------------|:-----|:--------|
| Step 3 | `R-product-requirements.md` | 📝 产品需求文档 | 🧐 需求分析师 |
| Step 4 | `R-tech-plan.md` | 📐 技术方案 | 🏗️ 架构师 |
| Step 5 | `R-direction-review.md` | 🔍 方向审查报告 | 🧐 需求分析师 |
| Step 6 | R{NN} 编码 | 💻 编码实现 | 开发工程师 |
| Step 7 | `R-code-review.md` | 🔍 代码审查报告 | 审查工程师 |
| Step 8 | R{NN} Dev 部署 | ⚙️ 部署到 dev 环境 | 🦸 项目管理 |
| Step 9 | `R-test-report.md` | 🧪 Dev 测试报告 | 🦐 测试工程师 |
| Step 10 | `R-release-verification.md` | ✅ 上线验证报告 | 🦸 项目管理+全员 |
| Step 11 | 合并 main + 更新容器 | 🚀 生产发布 | 🦸 项目管理 |
| Step 12 | 关闭工作室 | 📦 归档轮次 | 🦸 项目管理 |

## 命名规则

- 每轮以 `R{NN}` 格式命名（两位数，如 R01、R15、R32）
- 轮次文件夹内文档统一以 `R{NN}-` 前缀开头
- 根目录文档（WORKFLOW.md 等）为跨轮次全局文档，不放在轮次文件夹内
- `WORK_PLAN.md` 为当前轮次首要入口文档
