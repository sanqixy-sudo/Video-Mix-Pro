# 仓库协作

- `desktop/` 是 Tauri 桌面客户端，`server/` 是 FastAPI 授权服务和官网，`server/web-admin/` 是管理前端。客户端与 Web 分开管理版本。
- Web 变更运行 Node.js 24 的管理前端构建和 Python 3.11 的 `python -m unittest discover -s tests -v`。Docker 变更在 `server/` 执行 `python tests/docker_acceptance.py`，用独立卷验证重启和持久化。
- 客户端改动运行 `npm run typecheck`。Windows 便携包验证使用独立的测试配置和用户数据目录。
- Web 版本来自 `server/web-admin/package.json`，使用 `web-vX.Y.Z` 发版。Windows 客户端沿用其独立的版本和发布方式。
