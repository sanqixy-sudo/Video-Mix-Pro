# 客户端 0.2.2 交付说明

本次基于现有桌面功能，新增便携模式独立数据目录和内置 WebView2 启动支持。Web 后台重构不改变桌面界面；原生授权门禁仍是独立待办。

## 构建与打包

在 `desktop` 执行 `npm.cmd run tauri -- build -- --locked`。应用身份保持 `com.videomix.pro`，安装模式保持 perMachine，中文 NSIS、Windows x64。

从微软官方下载并完整解压固定版 x64 WebView2，然后在仓库根目录执行：

```powershell
python scripts/package_desktop.py --runtime-dir .packaging/webview2-extracted/Microsoft.WebView2.FixedVersionRuntime.155.0.4283.45.x64
```

输出到 `release/0.2.2`，拒绝覆盖已有目录。生成安装版、便携 ZIP、SHA-256 和文件清单。便携包仅携带程序资源，不携带用户账号、测试数据、源代码或开发依赖。

## 便携行为

`portable.flag` 使主程序使用相邻 `data` 文件夹保存账号及 WebView 配置；安装版没有此标记，继续使用原配置位置。安装版和便携版设备标识独立，首次切换登录可能触发已有的设备换绑冷却。

便携版内置 FFmpeg、FFprobe、DLL 和完整固定版 WebView2；安装版使用系统 Evergreen WebView2，由 NSIS 在缺少时引导安装。Windows 10 所需的沙箱读取权限仅赋予随包的 `WebView2` 文件夹，不修改系统运行时。

- [微软 WebView2 分发说明](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)
- [Tauri Windows 安装器说明](https://v2.tauri.app/distribute/windows-installer/)

## 验证范围

类型检查、原生 release 编译、安装器生成、PE/DLL 依赖、安装包完整性、内置视频工具和便携模式实际启动分别检查。`desktop/scripts/smoke_portable.py` 仅接受新建的测试目录，检查真实主界面、版本、诊断、独立数据位置及线上只读接口。

此机器不执行全局覆盖安装，避免改动已有安装注册项；全新 Windows 虚拟机与旧版覆盖安装未验证。未提供代码签名证书，安装包不宣称已签名。Windows Defender cmdlet 不可用，不能把病毒扫描记为通过。

## 已执行

- React/TypeScript 与 Vite 正式构建通过；Rust MSVC release 编译通过。
- 真实桌面 WebView 启动与接口检查通过，版本 0.2.2；随包 WebView2 155.0.4283.45 的微软 Authenticode 签名有效。
- FFmpeg/FFprobe 识别正常；使用内置工具生成 2 秒测试素材并转码，输出 H.264 240×136 与 AAC 音轨，时长 2.02 秒。
- 独立便携账号存储、原生版本命令和线上授权服务 0.3.0 的只读请求通过，页面脚本错误 0。
- PE 导入检查：主程序依赖 Windows 系统 DLL/UCRT，无额外 VCRUNTIME/MSVCP 动态依赖。

- 最终 NSIS 安装器完整性检查通过，解包后的主程序、FFmpeg、FFprobe 和两项运行 DLL 与构建文件 SHA-256 一致。
- 最终便携 ZIP 完整解压后，使用解压目录内的程序和 WebView2 再次实际启动；独立账号数据、视频工具诊断、服务健康及更新查询通过，脚本错误 0。

原始证据：[原生启动](desktop-0.2.2-native.json)、[启动画面](desktop-0.2.2-native.png)、[视频转码](desktop-0.2.2-media.json)、[安装包检查](desktop-0.2.2-installer.json)、[最终 ZIP 启动](desktop-0.2.2-zip.json)。

| 交付文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| VideoMixPro_0.2.2_Setup.exe | 94778988 | `0a28c5c8c56a9ba3b36393ebf253f492c807a81e0c24afee5910c54b4aac51e4` |
| VideoMixPro_0.2.2_Portable.zip | 460849076 | `e7550be4392d783bb7cd9450343e41192e90bbc49f7540326b6eb7f0181687f7` |

本次文件交付输出目录为外层工作区 `release/0.2.2`；线上下载与最新客户端版本暂时保持原配置，未自动发布 GitHub Release。
