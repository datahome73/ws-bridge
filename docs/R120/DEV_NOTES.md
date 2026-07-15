# R120 Dev Notes

> **角色:** 爱泰（Dev）
> **字数:** ≤ 10 句

1. 开发环境：Python 3.11+，依赖用 `uv sync` 安装，无需 pip。
2. 本地运行：`cd server && uv run python ws_server/__main__.py`，监听 8765（WSS）和 8766（Web UI）。
3. 分支策略：功能在 `dev` 分支开发，合入条件需通过 Review + QA，由小爱合入 `main`。
4. 容器构建：`docker build -t ws-bridge:<tag> .`，Dockerfile 在项目根目录。
5. 推送文档需 `git add -f`（`docs/R*/` 在 `.gitignore` 中），`.md` 文件无 lint 门槛。
6. 自动派活管线：bot 通过 `##start##R{N}` 创建，`_inbox:server` 接收 `已完成 ✅ R{N} Step N` 完成通知。
7. 日志定位：容器用 `docker logs ws-bridge`，搜索 `[R{N}]` 或 `[ERROR]` 快速定位断面。
8. 本地调试 bot 消息：用小谷凭证连 `wss://wsim.datahome73.cloud/ws`，auth 后发 `_inbox:<bot_id>`。
