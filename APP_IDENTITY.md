# Video Mix Pro 应用身份档案

> 这是安装包升级身份的长期记录。请随源码一起上传 GitHub，并纳入项目备份。以后换电脑、重装系统或由其他人继续开发时，都必须先阅读本文件。

## 永久固定的应用身份

以下字段用于让 Windows 和 Tauri 将新版安装包识别为同一个 Video Mix Pro。除非明确决定发布一个全新的独立应用，否则永久不要修改。

| 配置 | 固定值 | 位置 |
| --- | --- | --- |
| Tauri identifier | `com.videomix.pro` | `desktop/src-tauri/tauri.conf.json` |
| productName | `Video Mix Pro` | `desktop/src-tauri/tauri.conf.json` |
| Rust package name | `video-mix-pro` | `desktop/src-tauri/Cargo.toml` |
| NPM package name | `video-mix-pro` | `desktop/package.json` |
| Windows 安装模式 | `perMachine` | `desktop/src-tauri/tauri.conf.json` |
| 开始菜单目录 | `Video Mix Pro` | `desktop/src-tauri/tauri.conf.json` |
| 主程序名称 | `Video Mix Pro.exe` | 由 productName 生成；快捷方式脚本也使用此名称 |
| 安装器类型 | `nsis` | `desktop/src-tauri/tauri.conf.json` |

当前首次正式延续版本：`0.2.0`。

安装包文件名可以加入日期和版本号，例如 `VideoMixPro_0.3.0_中文安装版.exe`；文件名变化不会改变应用身份。

## 每次发布允许修改的内容

每次客户端升级只递增版本号并修改业务代码、界面和资源。版本号需要同步更新：

1. `desktop/src-tauri/tauri.conf.json` 中的 `version`
2. `desktop/src-tauri/Cargo.toml` 中的 `version`
3. `desktop/package.json` 中的 `version`
4. `desktop/src/App.tsx` 中用于异常情况下显示的备用版本号

服务端的 `SERVER_VERSION` 与客户端版本分开维护。只更新 Docker 官网后台时，不要改客户端版本，也不需要让用户重装客户端。

## 发布前检查

1. 确认永久身份字段与上表完全一致。
2. 确认所有客户端版本号一致，并且高于上一个已发布版本。
3. 先安装上一个正式版，再运行新安装包。
4. Windows“已安装的应用”中应始终只有一个 `Video Mix Pro`。
5. 新版应覆盖原安装目录，桌面和开始菜单不应出现两套快捷方式。
6. 登录状态、用户设置和本地数据应按产品设计保留。

如果新版与旧版并列出现，先停止发布，检查 `identifier`、`productName`、`installMode`、程序名和签名发布者是否发生变化。

## 代码签名长期规则

当前源码中不保存代码签名证书或私钥。以后购买 Windows 代码签名证书后：

- 后续版本尽量一直使用同一发布者身份的证书签名。
- 证书到期时应使用同一主体续签，不要频繁更换发布者。
- 证书文件、私钥和密码不得提交 GitHub，也不得写进本文件。
- 证书应单独加密备份至少两份，并记录恢复方式。

相同签名有助于延续 Windows 的发布者信任和 SmartScreen 声誉。签名变化不一定创建第二个应用，但可能重新触发安全警告。

## 刷机或换电脑后的恢复流程

1. 从 GitHub 克隆完整仓库，或恢复完整项目备份。
2. 打开本文件，核对永久身份字段。
3. 恢复构建工具、FFmpeg/FFprobe 和依赖；不要重新创建一个不同 identifier 的 Tauri 项目。
4. 如已启用代码签名，从加密备份恢复证书，不要把证书提交到仓库。
5. 先做一次测试构建，再执行旧版覆盖安装验证。
6. 验证通过后再上传 GitHub Releases，并在官网后台填写版本、直链、更新说明和 SHA-256。

## 备份清单

至少保存以下内容：

- 完整 Git 仓库和提交历史
- 本文件 `APP_IDENTITY.md`
- `desktop/src-tauri/tauri.conf.json`
- `desktop/src-tauri/Cargo.toml` 与 `Cargo.lock`
- `desktop/package.json` 和前端锁文件
- Logo、图标、FFmpeg/FFprobe 获取方式与打包脚本
- 已发布安装包及其 SHA-256
- 若以后启用签名：单独加密保存的证书、私钥和恢复说明

最后更新：2026-08-07
