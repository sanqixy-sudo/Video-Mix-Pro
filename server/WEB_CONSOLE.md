# Web 管理后台 0.3.0

新后台位于 `server/web-admin`（React 19 / TypeScript / Vite / Ant Design 6）。官网使用 FastAPI 模板和独立静态资源；客户端授权、兑换、更新 API 地址不变。

## 本地运行

在 `server/web-admin` 执行 `npm ci`、`npm run build`，再在 `server` 执行 `pip install -r requirements-dev.txt`、`python -m uvicorn app:app --host 127.0.0.1 --port 8000`。启动前配置开发数据库 `DB_PATH`、`ADMIN_USER`、`ADMIN_PASSWORD`，不要使用生产数据。登录 `/admin` 默认进入 `/admin/users`。

调试页面可运行 `npm run dev`；Vite 将管理 API 代理到 8000 端口。正式镜像使用构建产物，不运行 Vite 或 Node。

## 接口与数据

- 列表默认 25，支持稳定排序、日期筛选、分页元数据。`q` 输入完整兑换码时精确定位；其余文本模糊搜索，CSV 与列表共用查询构建器。
- `/admin/api/membership/preview` 接收 `operation_id、user_ids、action、plan/custom_days/expires_at`。预览持久化，30 分钟有效；`/membership/commit` 提交原编号。发生会员/账号变更返回 409，并要求新预览。结果通过 `/operations/{operation_id}` 查询。
- 普通续费累计剩余有效时长；永久会员跳过，封禁保持。单条和批量共用同一事务逻辑。旧后台自动为可重试操作补充编号。
- 生成请求带 `operation_id` 后重复提交返回同一批；批次通过 `/batches` 和 `/batches/{id}` 回访。用户批量上限 100，兑换码上限 500。
- CSV 分块读取，支持 `scope=filtered/selected/batch`，处理公式型单元格。选中范围使用 `codes` 参数，批次范围使用 `batch_id`。
- 数据仅增量扩展：备注、会员版本、操作结果、批次元数据、官网设置及便携版字段。会员版本由数据库触发器维护，因此旧后台和客户端兑换也能触发预览冲突。
- 北京时间展示/日期筛选/今日指标；UTC 存储。管理员会话、CSRF、HttpOnly、限流和单进程约束保留。

## 构建、检查与回退

### GitHub 镜像发布

推送 `web-v<版本号>` 标签会先执行前端构建、依赖审计、后端回归和真实 Docker 验收，通过后发布 `ghcr.io/sanqixy-sudo/video-mix-pro-web:<版本号>`，同时保留 `sha-<完整提交号>` 和 `latest` 标签。标签必须与 `web-admin/package.json` 的版本一致。客户端使用独立的 `v0.2.3` 标签，不会触发 Web 镜像发布。

镜像可用后拉取固定版本：`docker pull ghcr.io/sanqixy-sudo/video-mix-pro-web:0.3.0`。使用 `docker-compose.yml` 时可将 `build: .` 替换为 `image: ghcr.io/sanqixy-sudo/video-mix-pro-web:0.3.0`，保留原有环境变量、端口和数据卷路径。首次创建的 GHCR 包默认可能为私有；此时需有读取权限的账号登录 GHCR，或由仓库所有者在包设置中公开。源码构建不受镜像访问权限影响。

### 升级检查

1. 先对数据库使用 SQLite online backup（`app.backup_database`）生成一致快照，验证 `PRAGMA integrity_check` 与关键记录，再在副本上启动新版本验证迁移。不要复制单独的 WAL 主库文件。
2. 运行 `python -m unittest discover -s tests -v`；前端 `npm run typecheck`、`npm run build`。
3. `python tests/browser_acceptance.py` 使用临时库和隔离 Edge，输出 `.qa-data-web/evidence`。需要 Microsoft Edge 与 Playwright；测试不连接生产站点。`python tests/benchmark_console.py` 生成合成数据性能报告。
4. `python tests/docker_acceptance.py` 必须在有 Docker 的机器上实际运行，涵盖镜像、只读运行、健康检查、路由刷新、旧入口及卷持久化。CI 中配置了同一检查。
5. 在官网设置填入真实联系方式，在版本发布填入实际安装/便携文件与 SHA-256。确认下载、联系开通路径有效后再切换。

`/admin/legacy` 是受同一会话保护的旧入口，基础安全、续费、导出修复同样生效。设置 `ADMIN_USE_LEGACY=true` 后重启可把 `/admin/*` 页面切回旧界面；增量数据保留。镜像回退使用升级前镜像，保留升级后数据卷，不用旧备份覆盖新增记录。多 worker 会导致内存管理员会话不共享，继续使用单个 Uvicorn worker。

## 上线记录与剩余内容

2026-10-10 已在目标服务器实际构建镜像，完成隔离容器、生产数据副本迁移和持久化验收；含服务器位置和备份路径的详细部署记录仅保留在本地。现有安装包地址已验证可下载；实际联系账号、便携版地址与成片示例尚未配置，未配置入口隐藏。当前截图来自本仓库未修改的客户端前端实际渲染，未伪造会员或成功任务，尚不代替原生客户端的处理录屏/真实成片验收。客户端原生授权门禁已在独立的 [客户端 0.2.3](../docs/verification/desktop-0.2.3.md) 中实施与验证。
