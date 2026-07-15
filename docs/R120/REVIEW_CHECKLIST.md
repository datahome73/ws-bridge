# R120 审查清单（Review Checklist）

> **角色：** 小周（Review）
> **字数：** ≤ 10 句

1. **阻塞项优先：** 安全漏洞（SQL注入/敏感信息泄露）、数据丢失风险、死锁/死循环、异常被 except pass 吞掉且无日志。
2. **非阻塞项：** 代码风格/缩进、注释质量、变量命名可读性、性能微优化——标注但不阻塞合并。
3. **审查流程：** `git diff origin/dev...HEAD` 读全量 diff → 逐项对照验收标准 → 标注 inline 评论 → 回复 approval 或 change-request。
4. **自动派活特殊关注：** 消息 type 必须为 `broadcast`（非 `message`），channel 必须是 `_inbox:{agent_id}` 格式，sent=0 必须有 warning 日志。
5. **WebSocket 消息格式：** payload 必须含 `type`、`channel`、`content`、`from_name`、`ts`；`to_agent` 仅定向发送用。
6. **TODO / FIXME / HACK 标记：** `git diff` 中 grep 检查，散落在代码中的标记需说明对应 issue 或轮次。
7. **防御性编程：** list(dict.get(key, []))、json.dumps(ensure_ascii=False)、异常捕获后最少输出 warning 日志。
8. **零改动验证：** R120 纯文档轮，无服务端代码改动——审查重点放在文档内容准确性和格式正确性。