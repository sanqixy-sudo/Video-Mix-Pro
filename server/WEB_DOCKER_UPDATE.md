# Web Docker 更新命令

以下命令用于把本更新包部署到服务器上的会员后台 Docker。命令按 Linux 服务器写法；Windows 服务器可参考同名路径替换。

## 1. 上传并解压

```bash
# 在本机上传，按实际服务器和目录替换
scp VideoMixPro_web_docker_update_0.2.3_20260807.zip root@SERVER_IP:/opt/video-mix-member/

# 在服务器执行
cd /opt/video-mix-member
unzip -o VideoMixPro_web_docker_update_0.2.3_20260807.zip -d web_docker_update
cd web_docker_update
```

## 2. 备份旧数据库

```bash
# 如果旧服务还在运行，先确认旧 compose 目录和 data/app.db 路径
mkdir -p data/backups

# 建议先停旧容器，避免数据库写入中备份
docker compose down

# 如果旧库在旧目录，先复制到当前 data/app.db
# cp /old/path/data/app.db ./data/app.db

# 手工备份当前 app.db
cp -av data/app.db "data/backups/app.db.manual-before-update.$(date +%Y%m%d%H%M%S).bak"

# 确认备份文件可读且非 0 字节
ls -lh data/app.db data/backups/*.bak
```

## 3. 迁移 dry-run

```bash
python3 migration_dry_run.py data/app.db

# 如需保存报告
python3 migration_dry_run.py data/app.db --json > data/backups/migration_dry_run.json
```

如果输出 `would create pre-migration backup: True`，正式启动时会在 `data/backups/` 下自动生成 `*.pre_migration.bak`，然后补齐缺失字段。

## 4. 设置生产环境变量

```bash
export ENVIRONMENT=production
export ADMIN_USER='your-admin-user'
export ADMIN_PASSWORD='replace-with-a-strong-password-at-least-12-chars'
export ADMIN_TOKEN='replace-with-long-random-token-at-least-32-chars'
export CORS_ALLOW_ORIGINS='https://tauri.localhost,http://tauri.localhost,tauri://localhost'
export APP_VERSION='0.2.1'
export SERVER_VERSION='0.2.3'
export LEGACY_CLIENT_VERSION='0.2.0'
export DEVICE_REBIND_COOLDOWN_HOURS='6'
```

不要把真实凭据写入代码或文档。历史上使用过或出现在交付包里的凭据应立即轮换；生产启动会要求管理员密码至少 12 位、`ADMIN_TOKEN` 为至少 32 位的固定随机长串。

镜像使用 UID/GID `10001` 的非 root 用户。首次启动或从旧版升级前，请执行：

```bash
mkdir -p data/backups
chown -R 10001:10001 data
```

## 5. 构建并启动

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100
```

## 6. 基础健康检查

```bash
curl -sS http://127.0.0.1:57231/api/health
```

预期返回 `ok=true`、`status=ok`；生产环境不会暴露数据库路径。

## 7. smoke 验证

```bash
python3 smoke_verify.py \
  --base-url http://127.0.0.1:57231 \
  --admin-user "$ADMIN_USER" \
  --admin-password "$ADMIN_PASSWORD"
```

如果已有未使用兑换码，也可以指定：

```bash
python3 smoke_verify.py \
  --base-url http://127.0.0.1:57231 \
  --admin-user "$ADMIN_USER" \
  --admin-password "$ADMIN_PASSWORD" \
  --redeem-code EXISTING_CODE
```

注意：smoke 脚本会创建 `smoke_` 开头测试账号，并会使用或生成一个兑换码。验证后可在后台搜索并清理测试账号。

## 8. 回滚

```bash
# 停新容器
docker compose down

# 保留故障现场
cp -av data/app.db "data/backups/app.db.failed-after-update.$(date +%Y%m%d%H%M%S).bak"

# 恢复更新前备份，按实际备份文件名替换
cp -av data/backups/app.db.manual-before-update.YYYYMMDDHHMMSS.bak data/app.db

# 如果要回旧版本，切回旧代码/旧 compose 目录后启动
docker compose up -d
docker compose ps
docker compose logs --tail=100
curl -sS http://127.0.0.1:57231/api/health
```

## 9. 常见问题

1. `ADMIN_*` 未设置：production 启动会失败。管理员密码至少 12 位，`ADMIN_TOKEN` 必须设置为固定随机长串。
2. 数据库锁：先停旧容器再备份/迁移。
3. 权限错误：确认 `data/` 和 `data/backups/` 归 UID/GID 10001 所有并可写。
4. 端口占用：确认服务器 `57231` 未被旧容器或其他进程占用。
5. HTTPS/域名：应放在 TLS 反向代理后，并保持 `/api/auth/register`、`/api/auth/login`、`/api/auth/verify`、`/api/auth/logout`、`/api/redeem` 路径不变；启用代理 IP 头时再设置 `TRUST_PROXY_HEADERS=true`。
6. 客户端更新：登录管理后台，在“版本发布”填写 `x.y.z` 版本号、最低支持版本与 GitHub Releases 直链。普通更新会在客户端左下角提示；低于最低支持版本时，客户端弹出不可关闭的强更窗口，认证与兑换 API 同时返回 HTTP 426。
7. 设备换绑：首次绑定不冷却，真正换绑后默认冷却 6 小时；管理员可在“用户与设备”中单独解除冷却或解绑设备。
8. 版本区分：`APP_VERSION` 是客户端当前稳定版，`SERVER_VERSION` 是本次官网后台版本；只更新官网时不要改 `APP_VERSION`。`LEGACY_CLIENT_VERSION` 用于没有上报 `app_version` 的老客户端，本次保持 `0.2.0`。
