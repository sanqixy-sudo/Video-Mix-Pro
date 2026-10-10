Web 0.3.0 更新说明：新的管理后台构建、配置、数据库迁移与回退步骤见 WEB_CONSOLE.md。旧 0.2.3 说明保留作历史参考。

Video Mix Tool 会员后台 Docker

部署地址：
请填写实际域名或服务器 IP（下文统一写作 SERVER_HOST）

端口：
57231

客户端验证地址：
https://SERVER_HOST

部署命令：
先设置环境变量（按指定后台账号密码，并使用固定随机长 token）：
Windows PowerShell 示例：
$env:ADMIN_USER="自定义管理员账号"
$env:ADMIN_PASSWORD="至少 12 位的强密码"
$env:ADMIN_TOKEN="生成的随机 token，至少 32 位"

docker compose up -d --build

后台地址：
https://SERVER_HOST/admin

安全配置：
1. docker-compose.yml 默认按 production 启动，必须通过环境变量设置 ADMIN_USER、ADMIN_PASSWORD、ADMIN_TOKEN。
2. 管理员账号密码不得写入仓库；历史上使用过或出现在文档中的凭据应立即轮换。
3. 生产环境仍会拒绝空 ADMIN_USER、空 ADMIN_PASSWORD、过短或 change-this 类 ADMIN_TOKEN。
4. 本地直接运行 app.py/uvicorn 时 ENVIRONMENT 默认为 development，可使用开发默认值启动；不要用于公网。
5. 管理后台使用随机、短期、HttpOnly、SameSite=Strict 会话 cookie，并对写操作校验 CSRF token。
6. 建议通过 HTTPS 反向代理发布服务；ADMIN_COOKIE_SECURE 默认为 true，直接使用 HTTP 调试时需显式设为 false。
7. production 必须设置明确的 CORS_ALLOW_ORIGINS；桌面客户端默认 origin 已写入 docker-compose.yml。

健康检查：
GET /api/health
生产环境只返回 ok/status/time，不暴露数据库路径和运行环境；Dockerfile 已配置 HEALTHCHECK。

功能：
1. 用户注册、登录、会员验证
2. 每次客户端启动自动联网验证
3. 一个账号只允许一个设备使用；新设备登录会刷新绑定设备
4. 兑换码开通会员
5. 支持月会员、季会员、半年会员、一年会员、永久会员
6. 后台支持用户分页筛选、详情时间线、批量开通/撤销/封禁/解封/解除冷却
7. 兑换码支持固定套餐、自定义天数、批次、失效时间、批量停用/恢复、删除未使用码和 CSV 导出
8. 发布配置自动保留历史，审计日志支持操作类型和关键词筛选

老数据迁移兼容：
1. 启动时会创建 schema_migrations 表，并对 users、sessions、redeem_codes 缺失字段做 ADD COLUMN 补齐。
2. 对已有 data/app.db，启动前会在 data/backups 目录生成 pre_migration 备份。
3. 迁移只做通用检测、备份、补字段和空值回填，不删除、不重建旧数据。
4. 登录保留新 pbkdf2_sha256 校验，并增加 64 位 sha256 十六进制旧哈希兼容入口；未知旧哈希格式仍需人工确认后再扩展。
5. redeem_codes 会自动补齐 custom_days、used_by_username_snapshot、batch_id、expires_at、is_disabled、disabled_at；旧码归入 legacy 批次。
6. 新会话只保存 token 的 SHA-256 摘要；旧库中的明文 token 首次使用时会自动迁移。
7. 新设备登录会注销旧会话；会话同时受绝对有效期和空闲有效期限制。
8. app_release_history 会自动创建，用于保留每次稳定版发布配置。

兑换规则：
1. 固定套餐继续支持月/季/半年/年/永久。
2. 自定义天数兑换码按当前有效到期时间叠加；已过期或未开通会员从当前时间开始。
3. 永久会员兑换非永久码不会消耗兑换码，并返回“已是永久会员，无需兑换非永久会员码”。
4. 永久码仍会开通永久会员。
5. 删除用户会物理删除 users 和该用户 sessions；已使用兑换码保留 used_by_username_snapshot 显示原用户名。

上线/迁移操作流程：
1. 准备备份目录，并让容器内 UID 10001 可写：Linux 可执行 mkdir -p data/backups && sudo chown -R 10001:10001 data。
2. 如果已有旧库，先停旧服务，再复制旧库到新服务数据目录，例如复制为 data\app.db。
3. 手工再做一份外部备份，例如复制 data\app.db 到 data\backups\app.db.manual-before-upgrade.bak。
4. 设置生产环境变量 ADMIN_USER、至少 12 位的 ADMIN_PASSWORD、固定随机长串 ADMIN_TOKEN，以及实际 CORS_ALLOW_ORIGINS。
5. 启动：docker compose up -d --build
6. 查看容器状态：docker ps
7. 查看日志：docker logs video-mix-member
8. 第一次启动会自动检查旧库字段；如需补字段，会先生成 data\backups\app.db.<时间>.pre_migration.bak。

上线后验证：
1. 健康检查：GET https://SERVER_HOST/api/health，应返回 ok=true、status=ok。
2. 管理后台：打开 https://SERVER_HOST/admin，使用 ADMIN_USER / ADMIN_PASSWORD 登录。
3. 注册兼容：POST /api/auth/register，确认返回 {"ok": true}。
4. 登录兼容：POST /api/auth/login，确认返回 token、active、username、plan、plan_label、expires_at、device_id、session_expires_at。
5. 验证兼容：POST /api/auth/verify，使用登录 token 和 device_id；未开通会员会按旧逻辑返回 403，已开通会员返回会员信息。
6. 兑换兼容：先在后台生成兑换码，再 POST /api/redeem，确认返回会员信息且后台兑换记录标记已使用。

自动 smoke 验证脚本：
1. 脚本位置：server/smoke_verify.py，仅使用 Python 标准库。
2. 验证范围：/api/health、/admin 登录、/api/auth/register、/api/auth/login、后台生成兑换码、/api/redeem、/api/auth/verify。
3. Windows PowerShell 示例：
python .\smoke_verify.py --base-url https://SERVER_HOST --admin-user $env:ADMIN_USER --admin-password $env:ADMIN_PASSWORD
4. Linux/macOS 示例：
python3 ./smoke_verify.py --base-url https://SERVER_HOST --admin-user "$ADMIN_USER" --admin-password "$ADMIN_PASSWORD"
5. 如果已有可用兑换码，也可以避免后台生成新码：
python .\smoke_verify.py --base-url https://SERVER_HOST --admin-user $env:ADMIN_USER --admin-password $env:ADMIN_PASSWORD --redeem-code EXISTING_CODE
6. 脚本会注册一个 smoke_ 开头的新测试账号，并使用月会员兑换码完成 redeem/verify；生产执行后可在后台搜索 smoke_ 清理测试账号。
7. 该脚本会写入测试用户、会话和兑换码使用记录；只应在确认要做上线验证时运行。

本地自动化测试：
1. 创建虚拟环境后安装：python -m pip install -r requirements-dev.txt
2. 运行：python -m unittest discover -s tests -v
3. 覆盖会话 token 摘要、旧 token 迁移、单设备登录、过期与注销、兑换码状态/批次操作、用户分页/详情/批量操作、发布历史、管理后台 CSRF/注销、限流、生产健康信息脱敏和容器加固配置。

旧库迁移 dry-run 工具：
1. 脚本位置：server/migration_dry_run.py，仅使用 Python 标准库，默认只读打开 SQLite。
2. 验证范围：输出表名、字段、行数、关键字段缺失情况、密码哈希格式样例统计、是否会触发 schema 补字段/备份。
3. Windows PowerShell 示例：
python .\migration_dry_run.py .\data\app.db
4. Linux/macOS 示例：
python3 ./migration_dry_run.py ./data/app.db
5. JSON 输出示例：
python .\migration_dry_run.py .\data\app.db --json
6. dry-run 不会修改数据库；如果输出 would create pre-migration backup: True，表示正式启动时会先生成 data/backups/*.pre_migration.bak 再补字段。
7. 建议在停旧容器后、正式启动新容器前，对复制出来的旧 app.db 先运行 dry-run。

回滚方案：
1. 停新容器：docker compose down
2. 保留故障现场：复制当前 data\app.db 到 data\backups\app.db.failed-after-upgrade.bak。
3. 恢复启动前备份：用 data\backups 中的 manual-before-upgrade 或 pre_migration 备份覆盖 data\app.db。
4. 启动旧服务或重新启动当前服务：docker compose up -d
5. 再次验证 /api/health、/admin、/api/auth/login、/api/auth/verify、/api/redeem。

注意事项：
1. schema 迁移是向前补字段，不会自动删除字段、重建索引或合并未知旧表。
2. 如果旧库密码哈希不是 pbkdf2_sha256 或 64 位 sha256 hex，需要先提供样例再扩展兼容逻辑。
3. 如果旧库文件名不是 app.db，请先改名或设置 DB_PATH，并确保容器内路径和挂载路径一致。
4. 生产环境必须固定 ADMIN_TOKEN；它用于配置校验和部署身份，不再直接作为浏览器 cookie。
5. 常见问题：ADMIN_* 未配置会导致 production 启动失败；数据库锁通常需要先停旧容器；权限错误需确认 data 目录归 UID 10001 可写；端口冲突需检查 57231；HTTPS/CORS 应由反向代理和显式 origin 配置共同处理。


后台 UI 已升级为 0.2.3 运营控制台：八项指标、服务端分页筛选、用户批量管理和详情、Key 批次/过期/导出、发布历史、审计日志，并适配桌面与手机端。

客户端更新策略：
1. APP_VERSION 表示当前稳定客户端版本；SERVER_VERSION 表示官网后台代码版本，两者独立递增。
2. LEGACY_CLIENT_VERSION 表示没有上报 app_version 的旧客户端版本，本次默认 0.2.0。
3. 客户端版本低于后台“最低支持版本”时，登录、会话验证与兑换接口返回 HTTP 426 / CLIENT_UPDATE_REQUIRED。
4. 当前生产最低支持版本继续保持 0.2.0，不会立即锁定现有用户；需要强制升级时由管理员在“版本发布”中手动提高。
