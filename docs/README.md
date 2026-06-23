# 项目文档目录

按开发轮次归档，每轮独立文件夹。最新轮次：**R32**。

## 目录结构

```
docs/
├── WORKFLOW.md              开发流程（永久文档）
├── WORKSPACE_RULES.md       工作群聊天规则（永久文档）
├── TODO.md                  全局待办
├── product-requirements.md  全局产品需求
├── chat-rules-test-items.md 规则测试项
├── README.md                本文件
├── R32/                     第32轮开发（最新）
│   └── WORK_PLAN.md
└── R{NN}/                   历史轮次（保留参考）
```

## 文档模板

完整开发轮次包含以下文档（参考历史轮次）：

| 文档 | 用途 | 典型文件名 |
|:----|:-----|:----------|
| 📋 工作任务清单 | 任务拆解与进度追踪 | `R{NN}/WORK_PLAN.md` |
| 📝 产品需求 | 需求分析与功能定义 | `R{NN}/product-requirements.md` |
| 📐 技术方案 | 架构设计与实现方案 | `R{NN}/tech-plan.md` |
| 🔍 源码审查 | 代码审查结果与改进点 | `R{NN}/code-review.md` |
| 🧪 测试报告 | 自动化/手动验证结果 | `R{NN}/test-report.md` |
| ✅ 生产验证 | 上线后功能验证清单 | `R{NN}/production-verification.md` |

## 命名规则

- 每轮以 `R{NN}` 格式命名（两位数，如 R01、R15、R32）
- 轮次文件夹内文档前缀统一用 `R{NN}/`
- 根目录文档（WORKFLOW.md 等）为跨轮次全局文档，不放在轮次文件夹内
- WORK_PLAN.md 为当前轮次首要入口文档
